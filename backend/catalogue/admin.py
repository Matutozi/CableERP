from django.contrib import admin

from .models import Accessory, CableSize, CableType


class CableSizeInline(admin.TabularInline):
    model = CableSize
    extra = 0


@admin.register(CableType)
class CableTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "business", "unit", "has_colour_variants", "order"]
    list_filter = ["business", "unit"]
    inlines = [CableSizeInline]


@admin.register(Accessory)
class AccessoryAdmin(admin.ModelAdmin):
    list_display = ["name", "business", "unit", "default_price", "order"]
    list_filter = ["business", "unit"]
    search_fields = ["name"]
