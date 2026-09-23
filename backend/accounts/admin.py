from django.contrib import admin

from .models import AuditLog, BusinessProfile, Membership, Store


class StoreInline(admin.TabularInline):
    model = Store
    extra = 0
    fields = ["name", "code", "is_active"]


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    # store_limit is editable here and nowhere else: this admin is the operator's, and the API
    # exposes the field read-only (SYSTEM_DESIGN.md Q21).
    list_display = ["business_name", "user", "phone_numbers", "vat_rate", "store_limit", "stores_in_use"]
    list_editable = ["store_limit"]
    search_fields = ["business_name", "user__username"]
    inlines = [StoreInline]

    @admin.display(description="Stores in use")
    def stores_in_use(self, profile):
        used = profile.active_store_count
        # Lowering the allowance below what is in use is allowed and restricts the business until
        # the owner deactivates one (Q22). Say so here, or the operator cannot see what they did.
        return f"{used} / {profile.store_limit}" + (" — OVER LIMIT" if used > profile.store_limit else "")


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "business", "is_active"]
    list_filter = ["is_active", "business"]
    search_fields = ["name", "code", "business__business_name"]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "business", "role", "status", "created_at"]
    list_filter = ["role", "status"]
    search_fields = ["user__username", "business__business_name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "business", "user", "action", "summary"]
    list_filter = ["business", "action"]
    readonly_fields = ["business", "user", "action", "summary", "reference", "created_at"]
