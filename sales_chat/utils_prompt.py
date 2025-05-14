from django.core.cache import cache
from .models import Prompt

def get_prompt(key: str, fallback: str, ttl_sec: int = 60) -> str:
    cache_key = f"prompt::{key}"
    text = cache.get(cache_key)
    if text is None:
        try:
            text = Prompt.objects.get(key=key).content
        except Prompt.DoesNotExist:
            text = fallback
        cache.set(cache_key, text, ttl_sec)
    return text
