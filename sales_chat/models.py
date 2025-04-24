from django.db import models

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