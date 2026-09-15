from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from catalogue.models import FRACTIONAL_UNITS, MAX_QUANTITY
from catalogue.serializers import BusinessAccessoryField, BusinessCableSizeField
from quotes.models import Quote, QuoteLineItem

from .models import Waybill, WaybillItem, WaybillItemColour

MAX_WAYBILL_ITEMS = 200  # same ceiling as a quote
QUANTITY_FIELD = {"max_digits": 12, "decimal_places": 2, "read_only": True}


class BusinessQuoteField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Quote.objects.filter(business=self.context["business"]).prefetch_related("line_items__colours")


class WaybillItemColourSerializer(serializers.ModelSerializer):
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, max_value=MAX_QUANTITY)

    class Meta:
        model = WaybillItemColour
        fields = ["id", "colour", "quantity"]
        read_only_fields = ["id"]

    def validate_colour(self, value):
        return value.strip()

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value


class WaybillItemSerializer(serializers.ModelSerializer):
    cable_size = BusinessCableSizeField(required=False, allow_null=True)
    accessory = BusinessAccessoryField(required=False, allow_null=True)
    colours = WaybillItemColourSerializer(many=True)
    model_label = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    total_quantity = serializers.DecimalField(**QUANTITY_FIELD)

    class Meta:
        model = WaybillItem
        fields = [
            "id", "kind", "cable_size", "accessory", "cable_type_name", "size_label", "item_name",
            "unit", "order", "colours", "model_label", "description", "total_quantity",
        ]
        read_only_fields = ["id", "order"]

    def validate(self, attrs):
        if attrs.get("kind", QuoteLineItem.Kind.CABLE) == QuoteLineItem.Kind.ACCESSORY:
            if not attrs.get("item_name", "").strip():
                raise serializers.ValidationError({"item_name": "Enter the item name."})
        elif not attrs.get("cable_type_name", "").strip():
            raise serializers.ValidationError({"cable_type_name": "Enter the cable type."})

        colours = attrs["colours"]
        if not colours:
            raise serializers.ValidationError({"colours": "Enter a quantity for this item, or remove it."})
        names = [entry["colour"].lower() for entry in colours]
        if len(names) != len(set(names)):
            raise serializers.ValidationError({"colours": "Each colour can only be listed once."})
        if attrs["unit"] not in FRACTIONAL_UNITS and any(entry["quantity"] % 1 for entry in colours):
            raise serializers.ValidationError({"colours": f"{attrs['unit'].capitalize()} quantities must be whole numbers."})
        return attrs


class WaybillSerializer(serializers.ModelSerializer):
    items = WaybillItemSerializer(many=True)
    quote_reference = serializers.CharField(source="quote.reference_number", read_only=True, default=None)
    colour_columns = serializers.ListField(child=serializers.CharField(), read_only=True)
    totals = serializers.ListField(read_only=True)

    class Meta:
        model = Waybill
        fields = [
            "id", "reference_number", "quote", "quote_reference", "date", "customer_name", "invoice_number",
            "branch", "vehicle_number", "product_manufacturer", "notes", "items", "colour_columns", "totals",
            "created_at", "updated_at",
        ]
        read_only_fields = ["reference_number", "quote", "created_at", "updated_at"]

    def validate_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("A waybill can't be dated in the future. Check the date.")
        return value

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("A waybill needs at least one item.")
        if len(value) > MAX_WAYBILL_ITEMS:
            raise serializers.ValidationError(f"A waybill can hold up to {MAX_WAYBILL_ITEMS} items.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if items is not None:
            # Lines are copies with no identity worth keeping; an edit — usually a part delivery — replaces them.
            instance.items.all().delete()
            for position, item in enumerate(items):
                colours = item.pop("colours")
                line = WaybillItem.objects.create(waybill=instance, order=position, **item)
                WaybillItemColour.objects.bulk_create(WaybillItemColour(item=line, **colour) for colour in colours)
        return instance


class WaybillCreateSerializer(serializers.Serializer):
    """A waybill is only ever made from a quotation; this is the whole of the create request."""

    quote = BusinessQuoteField()


class WaybillListSerializer(serializers.ModelSerializer):
    quote_reference = serializers.CharField(source="quote.reference_number", read_only=True, default=None)
    item_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Waybill
        fields = ["id", "reference_number", "date", "customer_name", "quote", "quote_reference", "item_count", "created_at"]
