from django.utils import timezone
from rest_framework import serializers

from accounts.models import Feature
from accounts.permissions import HidesRestrictedFields

from .models import Accessory, CableSize, CableType

# Filled in from the purchase ledger, never posted directly. Listed once so Phase 6 can hide
# cost from staff who aren't the owner in a single place.
COST_FIELDS = ["purchase_unit", "units_per_purchase", "last_unit_cost", "average_unit_cost", "margin_percentage"]
# The factory comparison. Listed separately from COST_FIELDS on purpose: these are *shown to
# customers*, the cost fields must never be (SYSTEM_DESIGN.md Q27).
FACTORY_FIELDS = ["factory_price", "factory_saving", "factory_price_updated_at"]
COST_FIELD = {"max_digits": 17, "decimal_places": 4, "read_only": True}


def _priced_in_the_old_unit(row_filter):
    """Whether any recorded delivery would be left describing a cost in a unit no longer used."""
    from purchasing.models import PurchaseItem  # purchasing depends on catalogue, not the reverse

    return PurchaseItem.objects.filter(**row_filter).exclude(landed_unit_cost__isnull=True).exists()


UNIT_CHANGE_REFUSED = (
    "You have recorded deliveries for this, and their cost is held per {old}. Selling it per {new} "
    "would leave those costs describing something else, and there is no way to convert them. "
    "Add a separate catalogue entry for the {new} version instead."
)


class BusinessCableSizeField(serializers.PrimaryKeyRelatedField):
    """Only accepts catalogue sizes belonging to the signed-in business."""

    def get_queryset(self):
        return CableSize.objects.filter(cable_type__business=self.context["business"])


class BusinessAccessoryField(serializers.PrimaryKeyRelatedField):
    """Only accepts accessories belonging to the signed-in business."""

    def get_queryset(self):
        return Accessory.objects.filter(business=self.context["business"])


# Declared on each serializer rather than on the mixin below: DRF's SerializerMetaclass collects
# `_declared_fields` only from Serializer bases, so fields written on a plain mixin are silently
# dropped and fall back to an auto-generated ReadOnlyField with the wrong output type.
FACTORY_READ_ONLY = {
    "factory_saving": serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True),
    "factory_price_updated_at": serializers.DateTimeField(read_only=True),
}


class FactoryPriceMixin:
    """Validates and timestamps the factory price on a catalogue row.

    Shared by cable sizes and accessories so the rule cannot hold in one and not the other. Carries
    behaviour only — see FACTORY_READ_ONLY for why the fields are not declared here.
    """

    def _validate_factory_price(self, attrs):
        if "factory_price" not in attrs:
            return attrs
        factory = attrs["factory_price"]
        if factory is None:
            return attrs
        price = attrs.get("default_price", getattr(self.instance, "default_price", None))
        # The whole feature is "buying from me beats going direct". A factory price at or below the
        # selling price is a stale figure or the purchase cost typed into the wrong box — and the
        # second would print what the distributor paid onto a customer's quote.
        if price is not None and factory <= price:
            raise serializers.ValidationError(
                {
                    "factory_price": (
                        f"The factory price must be above your own price of {price}. "
                        "It is what the manufacturer would charge your customer buying direct, "
                        "not what you paid for the stock."
                    )
                }
            )
        return attrs

    def _touch_factory_timestamp(self, validated_data):
        """Record when the figure was last confirmed, so a seller can spot a stale one."""
        if "factory_price" in validated_data:
            previous = getattr(self.instance, "factory_price", None)
            if validated_data["factory_price"] != previous:
                validated_data["factory_price_updated_at"] = timezone.now()
        return validated_data

    def validate(self, attrs):
        return self._validate_factory_price(super().validate(attrs))

    def create(self, validated_data):
        return super().create(self._touch_factory_timestamp(validated_data))

    def update(self, instance, validated_data):
        return super().update(instance, self._touch_factory_timestamp(validated_data))


class CableSizeSerializer(HidesRestrictedFields, FactoryPriceMixin, serializers.ModelSerializer):
    factory_saving = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    factory_price_updated_at = serializers.DateTimeField(read_only=True)
    restricted_fields = {Feature.VIEW_COSTS: COST_FIELDS}
    last_unit_cost = serializers.DecimalField(**COST_FIELD)
    average_unit_cost = serializers.DecimalField(**COST_FIELD)
    margin_percentage = serializers.DecimalField(max_digits=7, decimal_places=2, read_only=True)
    purchase_unit = serializers.CharField(read_only=True)
    units_per_purchase = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = CableSize
        fields = ["id", "cable_type", "size_label", "default_price", "order", *COST_FIELDS, *FACTORY_FIELDS]
        read_only_fields = ["cable_type"]
        validators = []  # uniqueness is checked (case-insensitively) in validate_size_label

    def validate_size_label(self, value):
        value = value.strip()
        cable_type = self.instance.cable_type if self.instance else self.context["cable_type"]
        clash = cable_type.sizes.filter(size_label__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f'"{value}" already exists under {cable_type.name}.')
        return value


class CableTypeSerializer(serializers.ModelSerializer):
    sizes = CableSizeSerializer(many=True, read_only=True)

    class Meta:
        model = CableType
        fields = ["id", "name", "unit", "has_colour_variants", "colour_options", "order", "sizes"]
        validators = []  # uniqueness per business is checked in validate_name

    def validate_name(self, value):
        value = value.strip()
        clash = CableType.objects.filter(business=self.context["business"], name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f'You already have a cable type called "{value}".')
        return value

    def validate_unit(self, value):
        """A type's unit is the unit its costs are held in, so it cannot move under them."""
        if (
            self.instance
            and value != self.instance.unit
            and _priced_in_the_old_unit({"cable_size__cable_type": self.instance})
        ):
            raise serializers.ValidationError(UNIT_CHANGE_REFUSED.format(old=self.instance.unit, new=value))
        return value

    def validate_colour_options(self, value):
        if not isinstance(value, list) or not all(isinstance(colour, str) for colour in value):
            raise serializers.ValidationError("Colour options must be a list of colour names.")
        colours = []
        for colour in (c.strip() for c in value):
            if colour and colour.lower() not in {c.lower() for c in colours}:
                colours.append(colour)
        return colours

    def validate(self, attrs):
        has_variants = attrs.get("has_colour_variants", getattr(self.instance, "has_colour_variants", False))
        colours = attrs.get("colour_options", getattr(self.instance, "colour_options", []))
        if has_variants and not colours:
            raise serializers.ValidationError(
                {"colour_options": "Add at least one colour, or turn off colour variants."}
            )
        return attrs


class AccessorySerializer(HidesRestrictedFields, FactoryPriceMixin, serializers.ModelSerializer):
    factory_saving = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    factory_price_updated_at = serializers.DateTimeField(read_only=True)
    restricted_fields = {Feature.VIEW_COSTS: COST_FIELDS}
    last_unit_cost = serializers.DecimalField(**COST_FIELD)
    average_unit_cost = serializers.DecimalField(**COST_FIELD)
    margin_percentage = serializers.DecimalField(max_digits=7, decimal_places=2, read_only=True)
    purchase_unit = serializers.CharField(read_only=True)
    units_per_purchase = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Accessory
        fields = ["id", "name", "unit", "default_price", "order", *COST_FIELDS, *FACTORY_FIELDS]
        validators = []  # uniqueness per business is checked in validate_name

    def validate_name(self, value):
        value = value.strip()
        clash = Accessory.objects.filter(business=self.context["business"], name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f'"{value}" is already in your accessories.')
        return value

    def validate_unit(self, value):
        """As for cable types: recorded costs are held per unit and cannot be reinterpreted."""
        if self.instance and value != self.instance.unit and _priced_in_the_old_unit({"accessory": self.instance}):
            raise serializers.ValidationError(UNIT_CHANGE_REFUSED.format(old=self.instance.unit, new=value))
        return value


class PricePointSerializer(serializers.Serializer):
    date = serializers.DateField()
    value = serializers.DecimalField(max_digits=15, decimal_places=2)


class CostPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    value = serializers.DecimalField(max_digits=17, decimal_places=4)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=2)
    supplier = serializers.CharField(allow_blank=True)


class ItemHistorySerializer(HidesRestrictedFields, serializers.Serializer):
    """One catalogue item's two money series: what it has sold for, and what it has cost."""

    price = PricePointSerializer(many=True)
    cost = CostPointSerializer(many=True)
    # The cost series is the same disclosure as the cost figure, spread over time.
    restricted_fields = {Feature.VIEW_COSTS: ["cost"]}


class PriceMovementSerializer(HidesRestrictedFields, serializers.Serializer):
    """One catalogue item on the dashboard's "what has moved" panel, with its series attached."""

    kind = serializers.CharField()
    id = serializers.IntegerField()
    name = serializers.CharField()
    unit = serializers.CharField()
    price = serializers.DecimalField(max_digits=15, decimal_places=2)
    last_unit_cost = serializers.DecimalField(**COST_FIELD)
    margin_percentage = serializers.DecimalField(max_digits=7, decimal_places=2, allow_null=True)
    last_moved = serializers.DateField()
    history = ItemHistorySerializer()
    restricted_fields = {Feature.VIEW_COSTS: ["last_unit_cost", "margin_percentage"]}
