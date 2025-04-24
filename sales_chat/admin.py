from django.contrib import admin
from django.http import HttpResponse
import csv
from .models import Conversation, Prompt
from django.utils.html import format_html 


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display   = ("user", "started_at", "log_link")
    date_hierarchy = "started_at"
    list_filter    = ("user",)

    @admin.display(description="Transcript")
    def log_link(self, obj):
        """
        Renders a safe HTML link if the CSV exists.
        """
        if obj.log_file:
            return format_html(
                "<a href='{}' download>Download CSV</a>",
                obj.log_file.url,
            )
        return "–"


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display  = ("key", "short_content")
    search_fields = ("key", "content")

    # neat one-liner to keep the list view tidy
    def short_content(self, obj):
        return (obj.content[:60] + "…") if len(obj.content) > 60 else obj.content
