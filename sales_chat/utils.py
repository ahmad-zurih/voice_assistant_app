# sales_chat/utils.py
import os
from openai import OpenAI
from django.core.cache import cache
from .models import ChatSetting


def get_openai_client() -> OpenAI:
    """
    Return a configured OpenAI client, relying on settings.py
    (which loads the .env file via django‑environ).

    Accepted variable names in .env:
        OPENAI_KEY          (preferred)
        OPENAI_API_KEY      (fallback for legacy)
    """
    api_key = (
        os.environ.get("openai_key")
    )

    if not api_key:
        raise RuntimeError(
            "OPENAI_KEY not found in environment. "
            "Add it to your .env file."
        )

    return OpenAI(api_key=api_key)


def get_session_duration() -> int:
    """
    Returns the current duration (in seconds).  
    Cached for 1 minute to avoid a DB hit on every request.
    """
    cached = cache.get("chat_session_duration")
    if cached is not None:
        return cached

    try:
        duration = ChatSetting.objects.values_list(
            "session_duration", flat=True
        ).first()
    except Exception:
        duration = 20 * 60          # sane fallback

    cache.set("chat_session_duration", duration, 60)
    return duration