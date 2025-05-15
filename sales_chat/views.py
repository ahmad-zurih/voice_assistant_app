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
CSV_HEADER = "timestamp,sales person,AI customer,AI assistant coach,clicked\n"
SESSION_DURATION = 20 * 60           # 20 minutes  → 1 200 seconds


def _now():
    """Return local time HH:MM:SS (good enough for this log)."""
    return timezone.localtime().strftime("%H:%M:%S")


def _append_row(log_path: str, *, sales="", customer="", coach="", clicked=""):
    """Append one row to the on-disk CSV file."""
    if not log_path:
        return
    try:
        with open(Path(log_path), "a", newline="", encoding="utf-8") as fp:
            csv.writer(fp).writerow([_now(), sales, customer, coach, clicked])
    except Exception as e:
        print("CSV append error:", e)


def _buffer_row(request, *, sales="", customer="", coach="", clicked=""):
    """Store one CSV row in the session until we flush at session end."""
    rows = request.session.get("csv_buffer", [])
    rows.append([_now(), sales, customer, coach, clicked])
    request.session["csv_buffer"] = rows
    request.session.modified = True


# views.py
# -------------------------------------------------------------------
# write-through CSV helper
# -------------------------------------------------------------------
def _log_row(request, *, sales="", customer="", coach="", clicked=""):
    """
    • immediately append ONE row to the on-disk CSV  
    • also keep a copy in the session so we can later update the
      *clicked* column or flush anything that might still be pending
    """
    row = [_now(), sales, customer, coach, clicked]

    # --- write to disk right away ----------------------------------
    path = request.session.get("chat_log_path")
    if path:
        try:
            with open(Path(path), "a", newline="", encoding="utf-8") as fp:
                csv.writer(fp).writerow(row)
        except Exception as err:
            print("CSV write-through error:", err)

    # --- mirror into the session buffer ----------------------------
    buf = request.session.get("csv_buffer", [])
    buf.append(row)
    request.session["csv_buffer"] = buf
    request.session.modified = True



# -------------------------------------------------------------------
# session status helpers
# -------------------------------------------------------------------
def _session_active(request) -> bool:
    """
    Returns True if the user has pressed “Start session” AND the
    20-minute window is still running.
    """
    if not request.session.get("session_active"):
        return False

    started_at = request.session.get("session_start")
    if not started_at:
        return False

    if time.time() - started_at > SESSION_DURATION:
        # auto-expire
        request.session["session_active"] = False
        request.session.save()
        return False

    return True


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
    """Start a brand-new 20-min exercise and a brand-new CSV file."""
    # ------------------------------------------------------------
    # 1. wipe anything that ties us to the previous conversation
    # ------------------------------------------------------------
    for key in (
        "conversation_id",      # ← makes _ensure_conversation create a new Conversation
        "chat_log_path",        # path to the previous CSV
        "csv_buffer",           # rows still in memory
        "sales_chat_history",   # old chat transcript
    ):
        request.session.pop(key, None)

    # ------------------------------------------------------------
    # 2. create new Conversation + CSV
    # ------------------------------------------------------------
    _ensure_conversation(request)            # ⇒ new file, new filename

    # ------------------------------------------------------------
    # 3. mark the session “active” and start the timer
    # ------------------------------------------------------------
    request.session["session_active"] = True
    request.session["session_start"]  = int(time.time())
    request.session.save()

    return JsonResponse(
        {"status": "started", "duration": SESSION_DURATION}
    )


@csrf_exempt
@require_POST
@login_required
def end_session(request):
    """Flush anything still buffered, then close the session."""
    rows   = request.session.pop("csv_buffer", [])
    path   = request.session.get("chat_log_path")

    if rows and path:                       # unlikely, but be safe
        with open(Path(path), "a", newline="", encoding="utf-8") as fp:
            csv.writer(fp).writerows(rows)

    request.session["session_active"] = False
    request.session.modified = True
    request.session.save()
    return JsonResponse({"status": "ended"})



# -------------------------------------------------------------------
# customer endpoint
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
    log_path = request.session["chat_log_path"]

    _log_row(request, sales=user_text)

    # ---- build chat history
    history = request.session.get("sales_chat_history", [])
    if not history:
        system_prompt = get_prompt("CUSTOMER_PROMPT", DEFAULT_CUSTOMER_PROMPT)
        history.append({"role": "system", "content": system_prompt})

    history.append({"role": "user", "content": user_text})

    # ---- OpenAI call
    client = get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=history,
        temperature=0.7,
        stream=False,
    )
    full = response.choices[0].message.content

    # ---- “human” delay
    delay = min(max(len(full.split()) * 0.2, 0.5), 8.0)
    time.sleep(delay)

    # ---- update state & CSV
    history.append({"role": "assistant", "content": full})
    request.session["sales_chat_history"] = history
    request.session.save()

    _log_row(request, customer=full)

    return JsonResponse({"answer": full}, json_dumps_params={"ensure_ascii": False})


# -------------------------------------------------------------------
# coach advice
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def coach_advice(request):
    if not _session_active(request):
        return JsonResponse({"error": "inactive"}, status=403)

    history: list[dict] = request.session.get("sales_chat_history", [])

    if len(history) < 3:
        return JsonResponse({"advice": "🕒 Say hello to the customer and I'll jump in!"})

    trimmed_history = history[-12:]
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

    advice_visible = ""
    if advice_text and not advice_text.upper().startswith("NO_ADVICE"):
        advice_visible = advice_text
        _log_row(
            request,
            coach=advice_text,
            clicked="false",
        )

    return JsonResponse({"advice": advice_visible})


# -------------------------------------------------------------------
# mark advice as clicked
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def coach_clicked(request):
    """
    Called exactly once when the user opens the coach-advice tab.
    We flip the *clicked* column from "false" to "true" — but now
    we do it in the session-buffer, NOT on disk.
    """
    if not _session_active(request):
        return JsonResponse({"error": "inactive"}, status=403)

    rows = request.session.get("csv_buffer", [])
    if not rows:
        return JsonResponse({"status": "no-data"}, status=400)

    # last row is always the most recent coach advice
    rows[-1][4] = "true"            # column index 4 == clicked
    request.session["csv_buffer"] = rows
    request.session.modified = True   # make sure Django saves the session

    return JsonResponse({"status": "ok"})



# -------------------------------------------------------------------
# default prompts (kept at bottom for readability)
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
