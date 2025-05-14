import csv
import json
import time
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Conversation
from .utils import get_openai_client
from .utils_prompt import get_prompt


# -------------------------------------------------------------------
# constants & helpers
# -------------------------------------------------------------------
CSV_HEADER = (
    "timestamp,sales person,AI customer,AI assistant coach,clicked\n"
)


def _now():
    """Return local time HH:MM:SS (sufficient granularity for the log)."""
    return timezone.localtime().strftime("%H:%M:%S")


def _append_row(log_path: str, *, sales="", customer="", coach="", clicked=""):
    """Append one row to the on-disk CSV file."""
    if not log_path:
        return                            # should never happen
    try:
        with open(Path(log_path), "a", newline="", encoding="utf-8") as fp:
            csv.writer(fp).writerow([_now(), sales, customer, coach, clicked])
    except Exception as e:
        # Don’t crash the UX; just log the error
        print("CSV append error:", e)


# -------------------------------------------------------------------
# fall-back prompts
# -------------------------------------------------------------------
DEFAULT_CUSTOMER_PROMPT = """
You are playing the role of a potential customer.
- Act like a real person evaluating a product or service the salesperson proposes.
- Ask questions, raise objections, or show interest naturally.
- Keep replies around 1-3 short paragraphs so the chat flows quickly.
"""

DEFAULT_COACH_PROMPT = """
You are a silent sales coach observing the whole dialogue between a salesperson (the USER)
and a customer (the ASSISTANT). Give concise, actionable advice ONLY IF it will materially
improve the next sales move. If the salesperson is doing well, answer exactly:  NO_ADVICE
"""


# -------------------------------------------------------------------
# ensure Conversation + CSV
# -------------------------------------------------------------------
def _ensure_conversation(request):
    """
    Make sure the current browser session is linked to exactly one
    Conversation row **and** on-disk CSV file. Return the Conversation.
    """
    conv_id = request.session.get("conversation_id")

    if conv_id:
        try:
            return Conversation.objects.get(id=conv_id)
        except Conversation.DoesNotExist:
            pass  # stale → fall through to create fresh one

    now = timezone.localtime()
    filename = f"{request.user.username}_{now:%Y-%m-%d_%H-%M-%S}.csv"

    conv = Conversation.objects.create(user=request.user)
    conv.log_file.save(filename, ContentFile(CSV_HEADER))
    conv.save()

    request.session["conversation_id"] = conv.id
    request.session["chat_log_path"] = conv.log_file.path
    request.session.save()
    return conv


# -------------------------------------------------------------------
# UI page
# -------------------------------------------------------------------
@login_required
def chat_room(request):
    return render(request, "sales_chat/chat.html")


# -------------------------------------------------------------------
# customer endpoint (non-stream)
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def chat_stream(request):
    user_text = request.POST.get("query", "").strip()
    if not user_text:
        return JsonResponse({"error": "empty"}, status=400)

    _ensure_conversation(request)
    log_path = request.session["chat_log_path"]

    # ---- record salesperson message immediately -----------------
    _append_row(log_path, sales=user_text)

    # ---- build / extend chat history ----------------------------
    history = request.session.get("sales_chat_history", [])
    if not history:
        system_prompt = get_prompt("CUSTOMER_PROMPT", DEFAULT_CUSTOMER_PROMPT)
        history.append({"role": "system", "content": system_prompt})

    history.append({"role": "user", "content": user_text})

    # ---- OpenAI call (non-stream) -------------------------------
    client = get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=history,
        temperature=0.7,
        stream=False,
    )
    full = response.choices[0].message.content

    # ---- “human” typing delay -----------------------------------
    delay = min(max(len(full.split()) * 0.2, 0.5), 8.0)
    time.sleep(delay)

    # ---- update history & CSV -----------------------------------
    history.append({"role": "assistant", "content": full})
    request.session["sales_chat_history"] = history
    request.session.save()

    _append_row(log_path, customer=full)

    return JsonResponse({"answer": full}, json_dumps_params={"ensure_ascii": False})


# -------------------------------------------------------------------
# coach endpoint
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def coach_advice(request):
    """
    Generate (or skip) coach advice and log it.
    """
    history: list[dict] = request.session.get("sales_chat_history", [])

    if len(history) < 3:  # system + first user turn
        return JsonResponse(
            {"advice": "🕒 Say hello to the customer and I'll jump in!"}
        )

    trimmed_history = history[-12:]
    coach_prompt = get_prompt("COACH_PROMPT", DEFAULT_COACH_PROMPT)

    # ---- LLM call ----------------------------------------------
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4.1",
            temperature=0.35,
            max_tokens=180,
            messages=[
                {"role": "system", "content": coach_prompt},
                {
                    "role": "user",
                    "content": (
                        "Conversation transcript:\n"
                        f"{json.dumps(trimmed_history, ensure_ascii=False)}"
                    ),
                },
            ],
        )
        advice_text = response.choices[0].message.content.strip()
    except Exception as err:
        print("Coach-LLM error:", err)
        advice_text = "⚠️ Coach temporarily unavailable – please continue."

    # ---- decide if we show & log advice ------------------------
    advice_visible = ""
    if advice_text and not advice_text.upper().startswith("NO_ADVICE"):
        advice_visible = advice_text
        _append_row(
            request.session.get("chat_log_path"),
            coach=advice_text,
            clicked="false",      # default until the UI reports otherwise
        )

    # (nothing is written if NO_ADVICE)

    return JsonResponse({"advice": advice_visible})


# -------------------------------------------------------------------
# coach: mark advice as "clicked"
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def coach_clicked(request):
    """
    The front-end calls this exactly once when the user opens
    the advice tab. We rewrite the last CSV row and set clicked=true.
    """
    log_path = request.session.get("chat_log_path")
    if not log_path:
        return JsonResponse({"status": "no-log"}, status=400)

    try:
        path = Path(log_path)
        rows = list(csv.reader(path.open(newline="", encoding="utf-8")))

        if len(rows) <= 1:                      # header only
            return JsonResponse({"status": "no-data"}, status=400)

        last = rows[-1]
        # clicked is column index 4
        last[4] = "true"
        rows[-1] = last

        csv.writer(path.open("w", newline="", encoding="utf-8")).writerows(rows)
        return JsonResponse({"status": "ok"})
    except Exception as err:
        print("CSV rewrite error:", err)
        return JsonResponse({"status": "error"}, status=500)

