from django.db import models
from django.conf import settings
from django.utils import timezone


class Prompt(models.Model):

    class Keys(models.TextChoices):
        CUSTOMER = "CUSTOMER_PROMPT", "Customer prompt"
        COACH = "COACH_PROMPT", "Coach prompt"

    key = models.CharField(
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
        return self.get_key_display()


# -------------------------------------------------------------------
# Conversations – exactly ONE per user (→ one lifetime session)
# -------------------------------------------------------------------

def _chat_log_upload_to(instance, filename):
    """MEDIA_ROOT/chat_logs/<username>/<filename>"""
    return f"chat_logs/{instance.user.username}/{filename}"


class Conversation(models.Model):
    """One CSV file per user. After the first session this row blocks all further sessions."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sales_conversation",
    )
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    log_file = models.FileField(upload_to=_chat_log_upload_to)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self) -> str:  # pragma: no cover
        ts = self.started_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.user.username} – {ts}"


# -------------------------------------------------------------------
# Global configuration (unchanged)
# -------------------------------------------------------------------

class ChatSetting(models.Model):
    session_duration = models.PositiveIntegerField(
        default=20 * 60,  # 20 min in seconds
        help_text="Length of one training session in **seconds**",
    )

    class Meta:
        verbose_name = "Chat setting"
        verbose_name_plural = "Chat settings"

    def __str__(self) -> str:  # pragma: no cover
        return f"Session length: {self.session_duration}s"