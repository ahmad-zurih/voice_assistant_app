import json
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import StreamingHttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required

from .utils import get_openai_client
from .utils_prompt import get_prompt   # ← helper that pulls & caches prompts

# -------------------------------------------------------------------
# default fall-backs; used only if the Prompt rows don’t exist yet
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
# UI page
# -------------------------------------------------------------------
@login_required
def chat_room(request):
    return render(request, "sales_chat/chat.html")


# -------------------------------------------------------------------
# streaming endpoint: customer messages
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def chat_stream(request):
    user_text = request.POST.get("query", "").strip()
    if not user_text:
        return JsonResponse({"error": "empty"}, status=400)

    # 1️⃣  recover or start the session history
    history = request.session.get("sales_chat_history", [])
    if not history:
        customer_prompt = get_prompt("CUSTOMER_PROMPT", DEFAULT_CUSTOMER_PROMPT)
        history.append({"role": "system", "content": customer_prompt})

    history.append({"role": "user", "content": user_text})

    # 2️⃣  call OpenAI and stream
    client = get_openai_client()
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=history,
        temperature=0.7,
        stream=True,
    )

    # generator that yields Server-Sent Events
    def sse():
        full = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            full += delta
            yield delta

        # assistant turn complete → persist session
        history.append({"role": "assistant", "content": full})
        request.session["sales_chat_history"] = history
        request.session.save()        # ✨ force-save ✨

    return StreamingHttpResponse(sse(), content_type="text/plain")


# -------------------------------------------------------------------
# coach endpoint: just-in-time advice
# -------------------------------------------------------------------
@csrf_exempt
@require_POST
@login_required
def coach_advice(request):
    """
    Generates coaching feedback on the running conversation.

    • Reads the dialogue from the session.
    • If there is at least one user + customer exchange, calls the LLM.
    • Returns a non-empty 'advice' string so the front-end always shows something.
    """
    history: list[dict] = request.session.get("sales_chat_history", [])

    # not enough context yet
    if len(history) < 3:     # system + first user turn = 2
        return JsonResponse(
            {"advice": "🕒 Say hello to the customer and I'll jump in!"}
        )

    # keep the last 12 messages to stay within context window
    trimmed_history = history[-12:]

    coach_prompt = get_prompt("COACH_PROMPT", DEFAULT_COACH_PROMPT)

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
        # log server error, but avoid breaking UX
        print("Coach-LLM error:", err)
        advice_text = "⚠️ Coach temporarily unavailable – please continue."

    # normalise output
    if not advice_text or advice_text.upper().startswith("NO_ADVICE"):
        advice_text = "✅ Great job! No advice needed."

    return JsonResponse({"advice": advice_text})
