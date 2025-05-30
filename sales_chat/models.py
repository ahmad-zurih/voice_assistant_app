from django.db import models
from django.conf import settings
from django.utils import timezone

class Prompt(models.Model):

    class Keys(models.TextChoices):
        CUSTOMER = "CUSTOMER_PROMPT", "Customer prompt"
        COACH    = "COACH_PROMPT",    "Coach prompt"

    key     = models.CharField(
        max_length=50,
        choices=Keys.choices,     
        unique=True,
        help_text="System prompt this row represents",
    )
    content = models.TextField()

    class Meta:
        verbose_name = "AI prompt"
        verbose_name_plural = "AI prompts"

    def __str__(self):
        # shows human-friendly label in lists
        return self.get_key_display()



def _chat_log_upload_to(instance, filename):
    """MEDIA_ROOT/chat_logs/<username>/<filename>"""
    return f"chat_logs/{instance.user.username}/{filename}"


class Conversation(models.Model):
    """
    One CSV file per conversation (= one front-end session).
    The file grows row-by-row while the chat is happening.
    """
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    log_file   = models.FileField(upload_to=_chat_log_upload_to)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self) -> str:
        ts = self.started_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.user.username} – {ts}"



class ChatSetting(models.Model):
    """
    Global config for the sales-chat app.
    Only one row is expected, but using a normal model keeps things simple.
    """
    session_duration = models.PositiveIntegerField(
        default=20 * 60,                # 20 min in seconds
        help_text="Length of one training session in **seconds**",
    )

    class Meta:
        verbose_name = "Chat setting"
        verbose_name_plural = "Chat settings"

    def __str__(self) -> str:
        return f"Session length: {self.session_duration}s"