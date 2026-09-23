from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.models import AuditLog, BusinessProfile, Feature, record
from accounts.permissions import HidesRestrictedFields, member_can
from catalogue.models import FRACTIONAL_UNITS, MAX_PRICE, MAX_QUANTITY
from catalogue.serializers import BusinessAccessoryField, BusinessCableSizeField

from .models import Quote, QuoteLineItem, QuoteLineItemColour, snapshot_costs, snapshot_factory_prices

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
# The factory comparison, listed apart from the cost fields because it is shown to the customer
# while those must never be (SYSTEM_DESIGN.md Q27).
LINE_FACTORY_FIELDS = ["factory_price", "factory_amount", "factory_saving"]
QUOTE_FACTORY_FIELDS = ["show_factory_price", "factory_subtotal", "total_factory_saving"]


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


class QuoteLineItemSerializer(HidesRestrictedFields, serializers.ModelSerializer):
    cable_size = BusinessCableSizeField(required=False, allow_null=True)
    accessory = BusinessAccessoryField(required=False, allow_null=True)
    unit_price = serializers.DecimalField(**PRICE_FIELD)
    colours = QuoteLineItemColourSerializer(many=True)
    description = serializers.CharField(read_only=True)
    total_quantity = serializers.DecimalField(**TOTAL_FIELD)
    amount = serializers.DecimalField(**TOTAL_FIELD)
    factory_price = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    unit_cost = serializers.DecimalField(**COST_FIELD)
    restricted_fields = {Feature.VIEW_COSTS: LINE_COST_FIELDS}
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
            *LINE_FACTORY_FIELDS,
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
            raise serializers.ValidationError(
                {"colours": f"{attrs['unit'].capitalize()} quantities must be whole numbers."}
            )
        return attrs


# Redirecting where a customer pays is the sharpest edge in the product, so the fields that do it
# are writable only by members who may change bank details at all (SYSTEM_DESIGN.md Q31).
QUOTE_PAYMENT_FIELDS = ["payment_bank_name", "payment_account_name", "payment_account_number"]


class QuoteSerializer(HidesRestrictedFields, serializers.ModelSerializer):
    line_items = QuoteLineItemSerializer(many=True)
    transport_cost = serializers.DecimalField(required=False, **PRICE_FIELD)
    vat_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"), required=False
    )
    revision_of_reference = serializers.CharField(source="revision_of.reference_number", read_only=True, default=None)
    subtotal = serializers.DecimalField(**TOTAL_FIELD)
    vat_amount = serializers.DecimalField(**TOTAL_FIELD)
    grand_total = serializers.DecimalField(**TOTAL_FIELD)
    total_cost = serializers.DecimalField(**TOTAL_FIELD)
    costed_subtotal = serializers.DecimalField(**TOTAL_FIELD)
    total_margin = serializers.DecimalField(**TOTAL_FIELD)
    margin_percentage = serializers.DecimalField(**PERCENTAGE_FIELD)
    margin_coverage = serializers.JSONField(read_only=True)
    restricted_fields = {Feature.VIEW_COSTS: QUOTE_COST_FIELDS}

    def get_fields(self):
        fields = super().get_fields()
        # Visible to everyone — the customer is told where to pay — but settable only by those who
        # may change bank details. Read-only rather than hidden, or the quote would print no
        # payment box for a salesperson.
        if not member_can(self.context.get("request"), Feature.BANK_DETAILS):
            for name in QUOTE_PAYMENT_FIELDS:
                if name in fields:
                    fields[name].read_only = True
        return fields

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
            *QUOTE_FACTORY_FIELDS,
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "reference_number",
            "sent_at",
            "revision_of",
            "created_at",
            "updated_at",
        ]

    def _log_payment_override(self, quote, business):
        """Record a quote whose payment account differs from the business's own.

        The permission stops a salesperson doing this at all; the log is what makes an override by
        someone who *may* do it attributable afterwards.
        """
        profile_details = (
            business.bank_name,
            business.account_name or business.business_name,
            business.account_number,
        )
        quote_details = (quote.payment_bank_name, quote.payment_account_name, quote.payment_account_number)
        if quote_details == profile_details:
            return
        request = self.context.get("request")
        record(
            business,
            getattr(request, "user", None),
            AuditLog.Action.QUOTE_PAYMENT_OVERRIDE,
            f"Payment account set to {quote.payment_account_number or '—'} "
            f"({quote.payment_bank_name or 'no bank'}) instead of the business account",
            reference=quote.reference_number,
        )

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
        # Defaults first, then whatever was posted, so an explicit payment override or factory
        # toggle wins while everything unspecified falls back to the profile. Both are frozen onto
        # the quote either way: a later profile edit must not rewrite a quote already sent (Q6).
        defaults = {
            "payment_bank_name": business.bank_name,
            "payment_account_name": business.account_name or business.business_name,
            "payment_account_number": business.account_number,
            "show_factory_price": business.show_factory_price,
        }
        quote = Quote.objects.create(
            business=business,
            reference_number=Quote.next_reference_number(business, validated_data["date"]),
            **{**defaults, **validated_data},
        )
        self._save_line_items(quote, items)
        snapshot_costs(quote)
        snapshot_factory_prices(quote)
        self._log_payment_override(quote, business)
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
        snapshot_factory_prices(instance)
        self._log_payment_override(instance, instance.business)
        return instance

    def _save_line_items(self, quote, items):
        for position, item in enumerate(items):
            colours = item.pop("colours")
            line_item = QuoteLineItem.objects.create(quote=quote, order=position, **item)
            QuoteLineItemColour.objects.bulk_create(
                QuoteLineItemColour(line_item=line_item, **colour) for colour in colours
            )


class QuoteListSerializer(HidesRestrictedFields, serializers.ModelSerializer):
    grand_total = serializers.DecimalField(**TOTAL_FIELD)
    total_margin = serializers.DecimalField(**TOTAL_FIELD)
    restricted_fields = {Feature.VIEW_COSTS: ["total_margin"]}

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
