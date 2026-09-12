from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import BusinessProfile

# Ceilings that stop a typo (or an attacker) writing a number the quote totals cannot represent.
MAX_PRICE = Decimal("1000000000")  # ₦1bn per unit
MAX_QUANTITY = Decimal("100000")  # coils, metres or pieces on one line


class CableType(models.Model):
    class Unit(models.TextChoices):
        COIL = "coil", "Coil (100m)"
        METRE = "metre", "Metre"

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="cable_types")
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.COIL)
    has_colour_variants = models.BooleanField(default=False)
    colour_options = models.JSONField(default=list, blank=True, help_text='e.g. ["Red", "Black", "Yellow/Green"]')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["business", "name"], name="unique_cable_type_name_per_business"),
        ]

    def __str__(self):
        return self.name


class CableSize(models.Model):
    cable_type = models.ForeignKey(CableType, on_delete=models.CASCADE, related_name="sizes")
    size_label = models.CharField(max_length=100)
    default_price = models.DecimalField(
        max_digits=15, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(MAX_PRICE)]
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["cable_type", "size_label"], name="unique_size_label_per_cable_type"),
        ]

    def __str__(self):
        return f"{self.size_label} {self.cable_type.name}"


class Accessory(models.Model):
    """A non-cable product the seller also quotes: sockets, switches, breakers, conduit, tape…"""

    class Unit(models.TextChoices):
        PIECE = "piece", "Piece"
        PACK = "pack", "Pack"
        BOX = "box", "Box"
        ROLL = "roll", "Roll"
        LENGTH = "length", "Length"
        SET = "set", "Set"
        METRE = "metre", "Metre"

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="accessories")
    name = models.CharField(max_length=150)
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.PIECE)
    default_price = models.DecimalField(
        max_digits=15, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(MAX_PRICE)]
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name_plural = "accessories"
        constraints = [
            models.UniqueConstraint(fields=["business", "name"], name="unique_accessory_name_per_business"),
        ]

    def __str__(self):
        return self.name


# Every unit a quote line can be sold in. Only metres may be fractional; everything else is counted whole.
QUOTE_UNITS = {**dict(CableType.Unit.choices), **dict(Accessory.Unit.choices)}
FRACTIONAL_UNITS = {"metre"}
