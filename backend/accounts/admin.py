from django.contrib import admin

from .models import AuditLog, BusinessProfile


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ["business_name", "user", "phone_numbers", "vat_rate"]
    search_fields = ["business_name", "user__username"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "business", "user", "action", "summary"]
    list_filter = ["business", "action"]
    readonly_fields = ["business", "user", "action", "summary", "reference", "created_at"]
