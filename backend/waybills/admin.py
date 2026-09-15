from django.contrib import admin

from .models import Waybill, WaybillItem


class WaybillItemInline(admin.TabularInline):
    model = WaybillItem
    extra = 0


@admin.register(Waybill)
class WaybillAdmin(admin.ModelAdmin):
    list_display = ["reference_number", "customer_name", "date", "business"]
    list_filter = ["business", "date"]
    search_fields = ["reference_number", "customer_name", "invoice_number"]
    inlines = [WaybillItemInline]
