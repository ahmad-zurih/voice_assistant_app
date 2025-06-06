from django.contrib import admin
from django.http import HttpResponse
import csv
from .models import Conversation, Prompt, ChatSetting
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

    def get_readonly_fields(self, request, obj=None):
        # Only make 'key' read-only if editing, not when adding
        if obj:  # Editing existing prompt
            return ("key",)
        return ()

    def has_add_permission(self, request):
        # Only allow adding prompts if there are less than 2
        return Prompt.objects.count() < 2

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions

    def short_content(self, obj):
        return (obj.content[:60] + "…") if len(obj.content) > 60 else obj.content




@admin.register(ChatSetting)
class ChatSettingAdmin(admin.ModelAdmin):
    # there will normally be just one row, so hide the “Add” button
    def has_add_permission(self, request):
        return not ChatSetting.objects.exists()
