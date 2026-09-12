from django.contrib import admin

from .models import Quote, QuoteLineItem, QuoteLineItemColour


class QuoteLineItemInline(admin.TabularInline):
    model = QuoteLineItem
    extra = 0
    show_change_link = True


class QuoteLineItemColourInline(admin.TabularInline):
    model = QuoteLineItemColour
    extra = 0


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ["reference_number", "customer_name", "business", "date", "status"]
    list_filter = ["business", "status", "date"]
    search_fields = ["reference_number", "customer_name"]
    inlines = [QuoteLineItemInline]


@admin.register(QuoteLineItem)
class QuoteLineItemAdmin(admin.ModelAdmin):
    list_display = ["quote", "cable_type_name", "size_label", "unit_price"]
    inlines = [QuoteLineItemColourInline]
