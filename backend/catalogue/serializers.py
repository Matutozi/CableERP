from rest_framework import serializers

from .models import Accessory, CableSize, CableType


class CableSizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CableSize
        fields = ["id", "cable_type", "size_label", "default_price", "order"]
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
    class Meta:
        model = Accessory
        fields = ["id", "name", "unit", "default_price", "order"]
        validators = []  # uniqueness per business is checked in validate_name

    def validate_name(self, value):
        value = value.strip()
        clash = Accessory.objects.filter(business=self.context["business"], name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f'"{value}" is already in your accessories.')
        return value
