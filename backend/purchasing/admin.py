from django.contrib import admin

from .models import Purchase, PurchaseItem


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0
    readonly_fields = ["landed_unit_cost"]


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["date", "supplier_name", "business", "additional_cost"]
    list_filter = ["business", "date"]
    search_fields = ["supplier_name", "note"]
    inlines = [PurchaseItemInline]
