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
from .utils import get_openai_client, get_session_duration
from .utils_prompt import get_prompt

# -------------------------------------------------------------------
# constants & helpers
# -------------------------------------------------------------------
CSV_HEADER = "timestamp,sales person,AI customer,AI assistant coach,clicked\n"


def _now():
    """Return local time HH:MM:SS (good enough for this log)."""
    return timezone.localtime().strftime("%H:%M:%S")


def _buffer_row(request, *, sales="", customer="", coach="", clicked=""):
    """Store one CSV row in the session until we flush at session end."""
    rows = request.session.get("csv_buffer", [])
    rows.append([_now(), sales, customer, coach, clicked])
    request.session["csv_buffer"] = rows
    request.session.modified = True


def _write_row(request, *, sales="", customer="", coach="", clicked=""):
    path = request.session.get("chat_log_path")
    if not path:
        return
    try:
        with open(Path(path), "a", newline="", encoding="utf-8") as fp:
            csv.writer(fp).writerow([_now(), sales, customer, coach, clicked])
    except Exception as err:
        print("CSV write error:", err)


# -------------------------------------------------------------------
# session status helpers
# -------------------------------------------------------------------

def _session_active(request) -> bool:
    """True if user pressed “Start session” and timer not expired."""
    if not request.session.get("session_active"):
        return False

    started_at = request.session.get("session_start")
    if not started_at:
        return False

    if time.time() - started_at > get_session_duration():
        request.session["session_active"] = False
        request.session["session_finished"] = True
        request.session.save()
        return False

    return True


def _session_finished(request) -> bool:
    return request.session.get("session_finished", False)


# -------------------------------------------------------------------
# CSV / conversation initialisation
# -------------------------------------------------------------------

def _ensure_conversation(request):
    """Guarantee exactly one Conversation + CSV file per browser session."""
    conv_id = request.session.get("conversation_id")

    if conv_id:
        try:
            return Conversation.objects.get(id=conv_id)
        except Conversation.DoesNotExist:
            pass  # stale ID → create fresh conversation

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
# start / end session endpoints
# -------------------------------------------------------------------

@csrf_exempt
@require_POST
@login_required
def start_session(request):
    if _session_finished(request):
        return JsonResponse({"error": "already-finished"}, status=403)

    # wipe everything from previous run
    for key in (
        "conversation_id",
        "chat_log_path",
        "csv_buffer",
        "sales_chat_history",
    ):
        request.session.pop(key, None)

    _ensure_conversation(request)

    request.session["session_active"] = True
    request.session["session_start"] = int(time.time())
    request.session.save()

    return JsonResponse({"status": "started", "duration": get_session_duration()})


@csrf_exempt
@require_POST
@login_required
def end_session(request):
    rows = request.session.pop("csv_buffer", [])
    path = request.session.get("chat_log_path")

    if rows and path:
        with open(Path(path), "a", newline="", encoding="utf-8") as fp:
            csv.writer(fp).writerows(rows)

    request.session["session_active"] = False
    request.session["session_finished"] = True
    request.session.modified = True
    request.session.save()
    return JsonResponse({"status": "ended"})


# -------------------------------------------------------------------
# customer endpoint – sales person ↔︎ AI customer
# -------------------------------------------------------------------

@csrf_exempt
@require_POST
@login_required
def chat_stream(request):
    if not _session_active(request):
        return JsonResponse({"error": "inactive"}, status=403)

    user_text = request.POST.get("query", "").strip()
    if not user_text:
        return JsonResponse({"error": "empty"}, status=400)

    _ensure_conversation(request)

    _write_row(request, sales=user_text)

    # build chat history (system prompt only once)
    history = request.session.get("sales_chat_history", [])
    if not history:
        system_prompt = get_prompt("CUSTOMER_PROMPT", DEFAULT_CUSTOMER_PROMPT)
        history.append({"role": "system", "content": system_prompt})

    history.append({"role": "user", "content": user_text})

    client = get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=history,
        temperature=0.7,
        stream=False,
    )
    full_reply = response.choices[0].message.content

    time.sleep(min(max(len(full_reply.split()) * 0.2, 0.5), 8.0))

    history.append({"role": "assistant", "content": full_reply})
    request.session["sales_chat_history"] = history
    request.session.save()

    _write_row(request, customer=full_reply)

    return JsonResponse({"answer": full_reply}, json_dumps_params={"ensure_ascii": False})


# -------------------------------------------------------------------
# coach advice (AI assistant coach) – now WITHOUT seeing the system prompt
# -------------------------------------------------------------------

@csrf_exempt
@require_POST
@login_required
def coach_advice(request):
    if not _session_active(request):
        return JsonResponse({"error": "inactive"}, status=403)

    full_history: list[dict] = request.session.get("sales_chat_history", [])

    # Strip system‑level messages so the coach only sees the real dialogue
    dialogue_only = [m for m in full_history if m["role"] != "system"]

    if len(dialogue_only) < 2:
        return JsonResponse({"advice": "🕒 Say hello to the customer and I'll jump in!"})

    trimmed_history = dialogue_only[-12:]
    coach_prompt = get_prompt("COACH_PROMPT", DEFAULT_COACH_PROMPT)

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
                        "Conversation transcript:\n" +
                        json.dumps(trimmed_history, ensure_ascii=False)
                    ),
                },
            ],
        )
        advice_text = response.choices[0].message.content.strip()
    except Exception as err:
        print("Coach‑LLM error:", err)
        advice_text = "⚠️ Coach temporarily unavailable – please continue."

    advice_visible = ""
    if advice_text and not advice_text.upper().startswith("NO_ADVICE"):
        advice_visible = advice_text
        _buffer_row(request, coach=advice_text, clicked="false")

    return JsonResponse({"advice": advice_visible})


# -------------------------------------------------------------------
# mark advice as clicked
# -------------------------------------------------------------------

@csrf_exempt
@require_POST
@login_required
def coach_clicked(request):
    if not _session_active(request):
        return JsonResponse({"error": "inactive"}, status=403)

    rows = request.session.get("csv_buffer", [])
    if not rows:
        return JsonResponse({"status": "no-data"}, status=400)

    rows[-1][4] = "true"  # clicked column
    request.session["csv_buffer"] = rows
    request.session.modified = True

    return JsonResponse({"status": "ok"})


# -------------------------------------------------------------------
# default prompts
# -------------------------------------------------------------------

DEFAULT_CUSTOMER_PROMPT = """
You are playing the role of a potential customer.
- Act like a real person evaluating a product or service the salesperson proposes.
- Ask questions, raise objections, or show interest naturally.
- Keep replies around 1‑3 short paragraphs so the chat flows quickly.
"""

DEFAULT_COACH_PROMPT = """
You are a silent sales coach observing the whole dialogue between a salesperson (the USER)
and a customer (the ASSISTANT). Give concise, actionable advice ONLY IF it will materially
improve the next sales move. If the salesperson is doing well, answer exactly:  NO_ADVICE
"""
