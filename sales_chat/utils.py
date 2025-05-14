# sales_chat/utils.py
import os
from openai import OpenAI


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
