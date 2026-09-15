"""The purchase ledger: what the seller paid for the stock they quote.

This is the source of truth for cost. The `last_unit_cost` / `average_unit_cost` columns on
catalogue rows are a cache of what these rows say, kept so the quote builder can read a cost
without aggregating the ledger on every keystroke — see purchasing/costing.py.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import BusinessProfile
from catalogue.models import (
    COST_DECIMAL_PLACES,
    MAX_PRICE,
    MAX_QUANTITY,
    QUOTE_UNITS,
    Accessory,
    CableSize,
)

MAX_PURCHASE_ITEMS = 200  # same ceiling as a quote, for the same reason


class Purchase(models.Model):
    """One delivery: what arrived, from whom, and what it cost to get it here."""

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="purchases")
    supplier_name = models.CharField(max_length=200, blank=True)
    date = models.DateField(default=timezone.localdate)
    # Transport, clearing, loading: spread across the items by value, because leaving it out
    # overstates margin on every line by the same silent percentage.
    additional_cost = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0), MaxValueValidator(MAX_PRICE)],
        help_text="Transport, clearing and loading for this delivery.",
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date} — {self.supplier_name or 'purchase'}"

    @property
    def goods_total(self):
        """What the items themselves cost, before transport."""
        return sum((item.line_cost for item in self.items.all()), Decimal("0"))

    @property
    def total_cost(self):
        return self.goods_total + self.additional_cost


class PurchaseItem(models.Model):
    """One product on a delivery.

    Quantities are recorded in whatever unit the goods were bought in ("3 coils", "2 boxes")
    and normalised to the catalogue row's sale unit when the landed cost is worked out, so a
    coil bought for ₦76,500 and sold by the metre costs ₦765 a metre and not ₦76,500.
    """

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    # The catalogue row this stock belongs to. Nullable and SET_NULL for the same reason
    # QuoteLineItem's links are: deleting a catalogue entry must not delete the history.
    cable_size = models.ForeignKey(
        CableSize, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_items"
    )
    accessory = models.ForeignKey(
        Accessory, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_items"
    )
    # Long enough by construction: a cable reads as size_label (100) + " " + type name (100),
    # so 200 was one character short of what the catalogue can produce.
    item_name = models.CharField(max_length=255, help_text="What was bought, as it read at the time.")
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(MAX_QUANTITY)],
        help_text="How many of entry_unit arrived.",
    )
    entry_unit = models.CharField(max_length=10, choices=list(QUOTE_UNITS.items()))
    units_per_entry = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(MAX_QUANTITY)],
        help_text="Sale units in one entry unit: 100 when a coil is sold by the metre.",
    )
    unit_cost = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(MAX_PRICE)],
        help_text="Paid per entry_unit, before transport.",
    )
    # Per sale unit, with this delivery's transport allocated in. Computed by purchasing.costing.
    landed_unit_cost = models.DecimalField(
        max_digits=17, decimal_places=COST_DECIMAL_PLACES, null=True, blank=True, editable=False
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.quantity} × {self.item_name}"

    @property
    def catalogue_row(self):
        """The CableSize or Accessory this line restocked, or None if it has since been deleted."""
        return self.cable_size or self.accessory

    @property
    def line_cost(self):
        """What this line cost, goods only."""
        return self.quantity * self.unit_cost

    @property
    def sale_quantity(self):
        """How much arrived, counted in the unit the item is sold in."""
        return self.quantity * self.units_per_entry
