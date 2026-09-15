from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from catalogue.models import FRACTIONAL_UNITS, MAX_PRICE, MAX_QUANTITY, QUOTE_UNITS
from catalogue.serializers import BusinessAccessoryField, BusinessCableSizeField

from .costing import landed_unit_costs, out_of_range
from .models import MAX_PURCHASE_ITEMS, Purchase, PurchaseItem

COST_FIELD = {"max_digits": 15, "decimal_places": 2, "min_value": Decimal("0"), "max_value": MAX_PRICE}
TOTAL_FIELD = {"max_digits": 20, "decimal_places": 2, "read_only": True}


class PurchaseItemSerializer(serializers.ModelSerializer):
    cable_size = BusinessCableSizeField(required=False, allow_null=True)
    accessory = BusinessAccessoryField(required=False, allow_null=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, max_value=MAX_QUANTITY)
    # Both units default to however this item was bought last time, so a repeat delivery is
    # just a quantity and a price.
    entry_unit = serializers.CharField(required=False)
    units_per_entry = serializers.DecimalField(
        max_digits=12, decimal_places=2, max_value=MAX_QUANTITY, required=False
    )
    unit_cost = serializers.DecimalField(**COST_FIELD)
    landed_unit_cost = serializers.DecimalField(max_digits=17, decimal_places=4, read_only=True)
    sale_quantity = serializers.DecimalField(**TOTAL_FIELD)
    line_cost = serializers.DecimalField(**TOTAL_FIELD)

    class Meta:
        model = PurchaseItem
        fields = [
            "id",
            "cable_size",
            "accessory",
            "item_name",
            "quantity",
            "entry_unit",
            "units_per_entry",
            "unit_cost",
            "landed_unit_cost",
            "sale_quantity",
            "line_cost",
            "order",
        ]
        read_only_fields = ["id", "item_name", "order"]

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value

    def validate(self, attrs):
        # Unlike a quote, a purchase must point at a catalogue entry: cost has nowhere to live
        # otherwise, and the whole point of recording it is to price that entry against it.
        row = attrs.get("cable_size") or attrs.get("accessory")
        if not row:
            raise serializers.ValidationError(
                {"cable_size": "Pick the catalogue item this stock is for. Add it to your catalogue first if it is new."}
            )
        if attrs.get("cable_size") and attrs.get("accessory"):
            raise serializers.ValidationError({"accessory": "A line is either a cable or an accessory, not both."})

        attrs["item_name"] = str(row)
        # Default the units to however this item was bought last time, remembered on the catalogue row.
        attrs.setdefault("entry_unit", row.purchase_unit or row.sale_unit)
        attrs.setdefault("units_per_entry", row.units_per_purchase if row.purchase_unit else Decimal("1"))

        if attrs["entry_unit"] not in QUOTE_UNITS:
            raise serializers.ValidationError({"entry_unit": "Not a unit this catalogue uses."})
        if attrs["entry_unit"] not in FRACTIONAL_UNITS and attrs["quantity"] % 1:
            raise serializers.ValidationError(
                {"quantity": f"{attrs['entry_unit'].capitalize()} quantities must be whole numbers."}
            )
        if attrs["units_per_entry"] <= 0:
            raise serializers.ValidationError({"units_per_entry": "Enter how many are in one unit bought."})
        if attrs["entry_unit"] == row.sale_unit and attrs["units_per_entry"] != 1:
            raise serializers.ValidationError(
                {"units_per_entry": f"Bought and sold by the {row.sale_unit}, so one is one."}
            )
        return attrs


class PurchaseSerializer(serializers.ModelSerializer):
    items = PurchaseItemSerializer(many=True)
    additional_cost = serializers.DecimalField(required=False, **COST_FIELD)
    goods_total = serializers.DecimalField(**TOTAL_FIELD)
    total_cost = serializers.DecimalField(**TOTAL_FIELD)
    recorded_by = serializers.CharField(source="created_by.username", read_only=True, default=None)

    class Meta:
        model = Purchase
        fields = [
            "id",
            "supplier_name",
            "date",
            "additional_cost",
            "note",
            "items",
            "goods_total",
            "total_cost",
            "recorded_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one item to this delivery.")
        if len(value) > MAX_PURCHASE_ITEMS:
            raise serializers.ValidationError(f"A delivery can hold up to {MAX_PURCHASE_ITEMS} items.")
        return value

    def validate_date(self, value):
        """A delivery cannot have arrived yet if it is dated in the future.

        This matters more than a tidy-up: `recalculate` picks replacement cost by date, so a
        mistyped year would win "most recent" forever and silently set the cost every future
        quote is priced against.
        """
        if value > timezone.localdate():
            raise serializers.ValidationError("A delivery can't be dated in the future. Check the date.")
        return value

    def validate(self, attrs):
        """Run the delivery's arithmetic before saving any of it.

        Bounding each field is not enough, because landed cost is derived from all of them
        together: a small enough sale quantity — nearly always a mistyped conversion — turns an
        ordinary delivery into a cost per unit that will not fit the column. Better to say which
        line is wrong than to fail on the way back out of the database.
        """
        items = attrs.get("items")
        if items is None:
            return attrs

        lines = [(item["quantity"] * item["unit_cost"], item["quantity"] * item["units_per_entry"]) for item in items]
        landed = landed_unit_costs(lines, attrs.get("additional_cost", Decimal("0")))
        for item, value in zip(items, landed):
            if out_of_range(value):
                # Raised without a field name so the app shows the sentence as written, the way
                # the locked-quote message does.
                raise serializers.ValidationError(
                    f"{item['item_name']} works out to ₦{value:,.2f} per unit sold, which can't be right. "
                    f"Check the quantity, the price, and how many are in one {item['entry_unit']}."
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        purchase = Purchase.objects.create(
            business=self.context["business"],
            created_by=self.context["request"].user,
            **validated_data,
        )
        self._save_items(purchase, items)
        return purchase

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if items is not None:
            # Items carry no identity worth keeping, so an edit replaces them wholesale — the
            # view recomputes cost for the rows that were here before as well as the ones now.
            instance.items.all().delete()
            self._save_items(instance, items)
        return instance

    def _save_items(self, purchase, items):
        PurchaseItem.objects.bulk_create(
            PurchaseItem(purchase=purchase, order=position, **item) for position, item in enumerate(items)
        )
        # Remember how this item is bought, so the next delivery pre-fills the conversion.
        for item in items:
            row = item.get("cable_size") or item.get("accessory")
            if row and (row.purchase_unit != item["entry_unit"] or row.units_per_purchase != item["units_per_entry"]):
                row.purchase_unit = "" if item["entry_unit"] == row.sale_unit else item["entry_unit"]
                row.units_per_purchase = item["units_per_entry"]
                row.save(update_fields=["purchase_unit", "units_per_purchase"])


class PurchaseListSerializer(serializers.ModelSerializer):
    total_cost = serializers.DecimalField(**TOTAL_FIELD)
    item_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Purchase
        fields = ["id", "supplier_name", "date", "additional_cost", "total_cost", "item_count", "created_at"]
