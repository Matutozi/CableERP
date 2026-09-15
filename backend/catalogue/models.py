from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import BusinessProfile

# Ceilings that stop a typo (or an attacker) writing a number the quote totals cannot represent.
MAX_PRICE = Decimal("1000000000")  # ₦1bn per unit
MAX_QUANTITY = Decimal("100000")  # coils, metres or pieces on one line

# Cost is derived, not charged, so it carries two more decimal places than money on a quote:
# a box of 12 sockets bought for ₦5,000 costs ₦416.6667 each, and rounding that to kobo
# would drift the margin on every line that uses it.
COST_DECIMAL_PLACES = 4


class CostedItem(models.Model):
    """Purchase cost carried by a catalogue row.

    Both figures are per *sale* unit and include allocated transport and clearing.
    `last_unit_cost` is what a refill costs today — the figure to price against when
    the naira is moving. `average_unit_cost` is what the stock bought so far averaged out at,
    which is the honest basis for reporting profit later.

    Written only by purchasing.costing, from the purchase ledger; never edited by hand,
    and always rebuildable with `manage.py rebuild_costs`.
    """

    purchase_unit = models.CharField(
        max_length=10,
        blank=True,
        help_text="What this is bought in, when that differs from how it is sold (bought by coil, sold by metre).",
    )
    units_per_purchase = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(MAX_QUANTITY)],
        help_text="Sale units in one purchase unit: 100 for a 100 m coil sold by the metre.",
    )
    last_unit_cost = models.DecimalField(
        max_digits=17, decimal_places=COST_DECIMAL_PLACES, null=True, blank=True, editable=False
    )
    average_unit_cost = models.DecimalField(
        max_digits=17, decimal_places=COST_DECIMAL_PLACES, null=True, blank=True, editable=False
    )

    class Meta:
        abstract = True

    @property
    def margin_percentage(self):
        """Margin of the catalogue price over replacement cost, or None when cost was never recorded.

        None matters: treating an unknown cost as zero would report 100% margin on every
        item nobody has costed yet, which is worse than saying nothing.
        """
        if self.last_unit_cost is None or not self.default_price:
            return None
        margin = (self.default_price - self.last_unit_cost) / self.default_price * 100
        return margin.quantize(Decimal("0.01"))


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


class CableSize(CostedItem):
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

    @property
    def sale_unit(self):
        """Cables are sold in the unit their type is sold in; costing normalises to this."""
        return self.cable_type.unit


class Accessory(CostedItem):
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

    @property
    def sale_unit(self):
        return self.unit


# Every unit a quote line can be sold in. Only metres may be fractional; everything else is counted whole.
QUOTE_UNITS = {**dict(CableType.Unit.choices), **dict(Accessory.Unit.choices)}
FRACTIONAL_UNITS = {"metre"}


class PriceChange(models.Model):
    """What a catalogue item was priced at, and when it changed.

    Kept as real rows rather than read back out of the audit log's prose, so the price trend
    is data the app can chart and Phase 4 can report on. Deleted with the item it belongs to:
    the selling price of something no longer sold has nothing to say.
    """

    cable_size = models.ForeignKey(
        "CableSize", on_delete=models.CASCADE, null=True, blank=True, related_name="price_changes"
    )
    accessory = models.ForeignKey(
        "Accessory", on_delete=models.CASCADE, null=True, blank=True, related_name="price_changes"
    )
    price = models.DecimalField(
        max_digits=15, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(MAX_PRICE)]
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["changed_at", "id"]

    def __str__(self):
        return f"{self.cable_size or self.accessory}: {self.price}"


def record_price(row, user=None):
    """Add a point to an item's price history, unless the price has not actually moved."""
    field = "cable_size" if isinstance(row, CableSize) else "accessory"
    latest = PriceChange.objects.filter(**{field: row}).order_by("-changed_at", "-id").first()
    if latest and latest.price == row.default_price:
        return None
    return PriceChange.objects.create(
        price=row.default_price,
        changed_by=user if getattr(user, "is_authenticated", False) else None,
        **{field: row},
    )
