from rest_framework import serializers

from .models import Accessory, CableSize, CableType

# Filled in from the purchase ledger, never posted directly. Listed once so Phase 6 can hide
# cost from staff who aren't the owner in a single place.
COST_FIELDS = ["purchase_unit", "units_per_purchase", "last_unit_cost", "average_unit_cost", "margin_percentage"]
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


class CableSizeSerializer(serializers.ModelSerializer):
    last_unit_cost = serializers.DecimalField(**COST_FIELD)
    average_unit_cost = serializers.DecimalField(**COST_FIELD)
    margin_percentage = serializers.DecimalField(max_digits=7, decimal_places=2, read_only=True)
    purchase_unit = serializers.CharField(read_only=True)
    units_per_purchase = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = CableSize
        fields = ["id", "cable_type", "size_label", "default_price", "order", *COST_FIELDS]
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
        if self.instance and value != self.instance.unit and _priced_in_the_old_unit(
            {"cable_size__cable_type": self.instance}
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


class AccessorySerializer(serializers.ModelSerializer):
    last_unit_cost = serializers.DecimalField(**COST_FIELD)
    average_unit_cost = serializers.DecimalField(**COST_FIELD)
    margin_percentage = serializers.DecimalField(max_digits=7, decimal_places=2, read_only=True)
    purchase_unit = serializers.CharField(read_only=True)
    units_per_purchase = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Accessory
        fields = ["id", "name", "unit", "default_price", "order", *COST_FIELDS]
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


class ItemHistorySerializer(serializers.Serializer):
    """One catalogue item's two money series: what it has sold for, and what it has cost."""

    price = PricePointSerializer(many=True)
    cost = CostPointSerializer(many=True)


class PriceMovementSerializer(serializers.Serializer):
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
