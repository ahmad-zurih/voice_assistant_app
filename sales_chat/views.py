import csv
import io
import json
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Conversation
from .utils import get_openai_client
from .utils_prompt import get_prompt  

# -------------------------------------------------------------------
# default fall-backs (used only if the Prompt rows don’t exist yet)
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
# helper: fetch or create Conversation + CSV
# -------------------------------------------------------------------
def _ensure_conversation(request):
    """
    Makes sure the current browser session is linked to exactly one
    Conversation row and on-disk CSV file.
    Returns the Conversation instance.
    """
    conv_id = request.session.get("conversation_id")

    if conv_id:
        try:
            return Conversation.objects.get(id=conv_id)
        except Conversation.DoesNotExist:
            # Stale ID in session → fall through to create a fresh one
            pass

    now = timezone.now()
    filename = f"{request.user.username}_{now:%Y-%m-%d_%H-%M-%S}.csv"

    # CSV header row
    header = "Human message,AI respond,AI assistant respond\n"
    conv   = Conversation.objects.create(user=request.user)
    conv.log_file.save(filename, ContentFile(header))  # writes to MEDIA_ROOT/chat_logs/...
    conv.save()

    # store pointers in the browser session
    request.session["conversation_id"] = conv.id
    request.session["chat_log_path"]   = conv.log_file.path
    request.session.save()

    return conv


# -------------------------------------------------------------------
# UI page
# -------------------------------------------------------------------
@login_required
def chat_room(request):
    return render(request, "sales_chat/chat.html")


# -------------------------------------------------------------------
# streaming endpoint: Customer messages
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def chat_stream(request):
    user_text = request.POST.get("query", "").strip()
    if not user_text:
        return JsonResponse({"error": "empty"}, status=400)

    # 0️⃣  guarantee a Conversation + CSV for this browser session
    _ensure_conversation(request)

    # 1️⃣  recover or start the chat history held in the session
    history = request.session.get("sales_chat_history", [])
    if not history:
        customer_prompt = get_prompt("CUSTOMER_PROMPT", DEFAULT_CUSTOMER_PROMPT)
        history.append({"role": "system", "content": customer_prompt})

    history.append({"role": "user", "content": user_text})

    # 2️⃣  call OpenAI & stream the assistant reply
    client = get_openai_client()
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=history,
        temperature=0.7,
        stream=True,
    )

    # 3️⃣  SSE generator — builds the assistant reply incrementally
    def sse():
        full = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            full += delta
            yield delta

        # assistant turn finished → update session history
        history.append({"role": "assistant", "content": full})
        request.session["sales_chat_history"] = history

        # stash human + assistant texts for coach to finalise the CSV row
        request.session["pending_row"] = [user_text, full]
        request.session.save()          # ✨ force-save ✨

    return StreamingHttpResponse(sse(), content_type="text/plain")


# -------------------------------------------------------------------
# coach endpoint: just-in-time advice
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def coach_advice(request):
    """
    Generates coaching feedback and appends the complete row
    (Human, AI customer, AI coach) to the CSV file.
    """
    history: list[dict] = request.session.get("sales_chat_history", [])

    # not enough context yet
    if len(history) < 3:  # system + first user turn
        return JsonResponse(
            {"advice": "🕒 Say hello to the customer and I'll jump in!"}
        )

    trimmed_history = history[-12:]
    coach_prompt    = get_prompt("COACH_PROMPT", DEFAULT_COACH_PROMPT)

    # ----- call LLM ------------------------------------------------------
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
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

    # ----- normalise -----------------------------------------------------
    if not advice_text or advice_text.upper().startswith("NO_ADVICE"):
        advice_text = "✅ Great job! No advice needed."

    # --------------------------------------------------------------------
    # append Human / AI-customer / AI-coach to CSV (if we have all parts)
    # --------------------------------------------------------------------
    log_path = request.session.get("chat_log_path")
    pending  = request.session.pop("pending_row", None)

    if log_path and pending:
        pending.append(advice_text)  # → [human, customer, coach]
        try:
            with open(Path(log_path), "a", newline="", encoding="utf-8") as fp:
                csv.writer(fp).writerow(pending)
        except Exception as e:
            # Don’t crash the UX; just log the error
            print("CSV append error:", e)

    return JsonResponse({"advice": advice_text})
