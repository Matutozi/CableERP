from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.models import BusinessProfile
from catalogue.models import FRACTIONAL_UNITS, MAX_PRICE, MAX_QUANTITY
from catalogue.serializers import BusinessAccessoryField, BusinessCableSizeField

from .models import Quote, QuoteLineItem, QuoteLineItemColour, snapshot_costs

TOTAL_FIELD = {"max_digits": 20, "decimal_places": 2, "read_only": True}
# Bounds so a line can never hold a number the totals cannot represent (see MAX_PRICE / MAX_QUANTITY).
PRICE_FIELD = {"max_digits": 15, "decimal_places": 2, "min_value": Decimal("0"), "max_value": MAX_PRICE}
# Generous for a quotation, and it keeps one request from asking for an unbounded PDF.
MAX_LINE_ITEMS = 200
# Cost carries four decimal places because it is derived from purchases, not charged.
COST_FIELD = {"max_digits": 17, "decimal_places": 4, "read_only": True}
PERCENTAGE_FIELD = {"max_digits": 7, "decimal_places": 2, "read_only": True}

# What the seller paid, and what they stand to make. Never shown to a customer: these must
# not reach quote_pdf.html, and Phase 6 hides them from staff who aren't the owner — keeping
# them listed here means that is one edit rather than an audit of every endpoint.
LINE_COST_FIELDS = ["unit_cost", "cost_amount", "margin_amount", "margin_percentage"]
QUOTE_COST_FIELDS = ["total_cost", "costed_subtotal", "total_margin", "margin_percentage", "margin_coverage"]


class QuoteLineItemColourSerializer(serializers.ModelSerializer):
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, max_value=MAX_QUANTITY)

    class Meta:
        model = QuoteLineItemColour
        fields = ["id", "colour", "quantity"]
        read_only_fields = ["id"]

    def validate_colour(self, value):
        return value.strip()

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value


class QuoteLineItemSerializer(serializers.ModelSerializer):
    cable_size = BusinessCableSizeField(required=False, allow_null=True)
    accessory = BusinessAccessoryField(required=False, allow_null=True)
    unit_price = serializers.DecimalField(**PRICE_FIELD)
    colours = QuoteLineItemColourSerializer(many=True)
    description = serializers.CharField(read_only=True)
    total_quantity = serializers.DecimalField(**TOTAL_FIELD)
    amount = serializers.DecimalField(**TOTAL_FIELD)
    unit_cost = serializers.DecimalField(**COST_FIELD)
    cost_amount = serializers.DecimalField(**TOTAL_FIELD)
    margin_amount = serializers.DecimalField(**TOTAL_FIELD)
    margin_percentage = serializers.DecimalField(**PERCENTAGE_FIELD)

    class Meta:
        model = QuoteLineItem
        fields = [
            "id",
            "kind",
            "cable_size",
            "accessory",
            "cable_type_name",
            "size_label",
            "item_name",
            "unit",
            "unit_price",
            "order",
            "colours",
            "description",
            "total_quantity",
            "amount",
            *LINE_COST_FIELDS,
        ]
        read_only_fields = ["id", "order"]

    def validate(self, attrs):
        # Keep only the fields that belong to this kind of line, so a stale catalogue link can't linger.
        if attrs.get("kind", QuoteLineItem.Kind.CABLE) == QuoteLineItem.Kind.ACCESSORY:
            attrs["item_name"] = attrs.get("item_name", "").strip()
            if not attrs["item_name"]:
                raise serializers.ValidationError({"item_name": "Enter the accessory name."})
            attrs.update(cable_size=None, cable_type_name="", size_label="")
        else:
            attrs["cable_type_name"] = attrs.get("cable_type_name", "").strip()
            attrs["size_label"] = attrs.get("size_label", "").strip()
            if not attrs["cable_type_name"]:
                raise serializers.ValidationError({"cable_type_name": "Enter the cable type."})
            attrs.update(accessory=None, item_name="")

        colours = attrs["colours"]
        if not colours:
            raise serializers.ValidationError({"colours": "Enter a quantity for this item."})
        names = [entry["colour"].lower() for entry in colours]
        if len(names) != len(set(names)):
            raise serializers.ValidationError({"colours": "Each colour can only be listed once."})
        if attrs["unit"] not in FRACTIONAL_UNITS and any(entry["quantity"] % 1 for entry in colours):
            raise serializers.ValidationError({"colours": f"{attrs['unit'].capitalize()} quantities must be whole numbers."})
        return attrs


class QuoteSerializer(serializers.ModelSerializer):
    line_items = QuoteLineItemSerializer(many=True)
    transport_cost = serializers.DecimalField(required=False, **PRICE_FIELD)
    vat_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"),
                                              max_value=Decimal("100"), required=False)
    revision_of_reference = serializers.CharField(source="revision_of.reference_number", read_only=True, default=None)
    subtotal = serializers.DecimalField(**TOTAL_FIELD)
    vat_amount = serializers.DecimalField(**TOTAL_FIELD)
    grand_total = serializers.DecimalField(**TOTAL_FIELD)
    total_cost = serializers.DecimalField(**TOTAL_FIELD)
    costed_subtotal = serializers.DecimalField(**TOTAL_FIELD)
    total_margin = serializers.DecimalField(**TOTAL_FIELD)
    margin_percentage = serializers.DecimalField(**PERCENTAGE_FIELD)
    margin_coverage = serializers.JSONField(read_only=True)

    class Meta:
        model = Quote
        fields = [
            "id",
            "reference_number",
            "customer_name",
            "date",
            "staff_name",
            "staff_phone",
            "product_manufacturer",
            "transport_cost",
            "vat_percentage",
            "notes",
            "status",
            "sent_at",
            "revision_of",
            "revision_of_reference",
            "payment_bank_name",
            "payment_account_name",
            "payment_account_number",
            "line_items",
            "subtotal",
            "vat_amount",
            "grand_total",
            *QUOTE_COST_FIELDS,
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "reference_number",
            "sent_at",
            "revision_of",
            "payment_bank_name",
            "payment_account_name",
            "payment_account_number",
            "created_at",
            "updated_at",
        ]

    def validate_date(self, value):
        """The quote date drives the reference number, so a future one misfiles the quote too."""
        if value > timezone.localdate():
            raise serializers.ValidationError("A quote can't be dated in the future. Check the date.")
        return value

    def validate_line_items(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one item.")
        if len(value) > MAX_LINE_ITEMS:
            raise serializers.ValidationError(f"A quote can hold up to {MAX_LINE_ITEMS} items.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("line_items")
        # Lock the business row so two quotes saved at once can't be given the same reference number.
        business = BusinessProfile.objects.select_for_update().get(pk=self.context["business"].pk)
        validated_data.setdefault("vat_percentage", business.vat_rate)
        validated_data.setdefault("date", timezone.localdate())
        quote = Quote.objects.create(
            business=business,
            reference_number=Quote.next_reference_number(business, validated_data["date"]),
            # Freeze where the customer should pay, so a later profile edit cannot rewrite it.
            payment_bank_name=business.bank_name,
            payment_account_name=business.account_name or business.business_name,
            payment_account_number=business.account_number,
            **validated_data,
        )
        self._save_line_items(quote, items)
        snapshot_costs(quote)
        return quote

    @transaction.atomic
    def update(self, instance, validated_data):
        if instance.is_locked:
            raise serializers.ValidationError(
                "This quote has been sent, so it can no longer be changed. Create a revision instead."
            )
        if validated_data.get("status") == Quote.Status.SENT:
            validated_data["sent_at"] = timezone.now()
        items = validated_data.pop("line_items", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if items is not None:
            # Line items are snapshots with no identity worth preserving, so an edit replaces them wholesale.
            instance.line_items.all().delete()
            self._save_line_items(instance, items)
        # Re-costed on every save while the quote is a draft; the save that marks it sent is the
        # last one this method allows, so that is where the figures freeze.
        snapshot_costs(instance)
        return instance

    def _save_line_items(self, quote, items):
        for position, item in enumerate(items):
            colours = item.pop("colours")
            line_item = QuoteLineItem.objects.create(quote=quote, order=position, **item)
            QuoteLineItemColour.objects.bulk_create(
                QuoteLineItemColour(line_item=line_item, **colour) for colour in colours
            )


class QuoteListSerializer(serializers.ModelSerializer):
    grand_total = serializers.DecimalField(**TOTAL_FIELD)
    total_margin = serializers.DecimalField(**TOTAL_FIELD)

    class Meta:
        model = Quote
        fields = [
            "id",
            "reference_number",
            "customer_name",
            "staff_name",
            "date",
            "status",
            "grand_total",
            "total_margin",
            "created_at",
        ]
