from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "document_name", "document_type", "created_at")
    list_filter = ("status", "document_type")
    readonly_fields = ("id", "created_at", "updated_at")
    search_fields = ("document_name", "id")
