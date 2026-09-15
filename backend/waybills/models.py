"""Waybills: the document that travels with the goods.

A waybill is made from a quotation but is its own record, not a restyled quote. It carries no
prices — the driver and the person signing for the delivery don't need them — and its quantities
can be less than the quote's, because a delivery is often only part of an order. So it copies the
quote's lines at the moment it is created and never reads the quote again.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from accounts.models import BusinessProfile
from accounts.numbering import next_reference_number
from catalogue.models import MAX_QUANTITY, QUOTE_UNITS, Accessory, CableSize
from quotes.models import GENERIC_TYPE_NAMES, Quote, QuoteLineItem


class Waybill(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="waybills")
    # Kept if the quote is deleted: the goods were still dispatched.
    quote = models.ForeignKey(Quote, on_delete=models.SET_NULL, null=True, blank=True, related_name="waybills")
    reference_number = models.CharField(max_length=32, editable=False)
    date = models.DateField(default=timezone.localdate)
    customer_name = models.CharField(max_length=200, help_text='Printed as "M/S".')
    invoice_number = models.CharField(max_length=50, blank=True)
    branch = models.CharField(max_length=100, blank=True)
    vehicle_number = models.CharField(max_length=30, blank=True)
    product_manufacturer = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["business", "reference_number"], name="unique_waybill_reference_per_business"),
        ]

    def __str__(self):
        return f"{self.reference_number} — {self.customer_name}"

    @classmethod
    def next_reference_number(cls, business, date):
        """WB-YYYYMMDD-NNN, numbered per business per day, independently of quotes."""
        return next_reference_number(cls.objects.filter(business=business), "WB", date)

    @classmethod
    def from_quote(cls, quote, user=None):
        """Copy a quotation's lines into a new waybill, dated today, with every quantity in full.

        Quantities can be reduced afterwards for a part delivery. The invoice number starts as the
        quote's reference so the two documents can be matched up; it is editable.
        """
        with transaction.atomic():
            business = BusinessProfile.objects.select_for_update().get(pk=quote.business_id)
            today = timezone.localdate()
            waybill = cls.objects.create(
                business=business,
                quote=quote,
                reference_number=cls.next_reference_number(business, today),
                date=today,
                customer_name=quote.customer_name,
                invoice_number=quote.reference_number,
                product_manufacturer=quote.product_manufacturer,
                created_by=user if getattr(user, "is_authenticated", False) else None,
            )
            for line in quote.line_items.all():
                item = WaybillItem.objects.create(
                    waybill=waybill, kind=line.kind, cable_size=line.cable_size, accessory=line.accessory,
                    cable_type_name=line.cable_type_name, size_label=line.size_label, item_name=line.item_name,
                    unit=line.unit, order=line.order,
                )
                WaybillItemColour.objects.bulk_create(
                    WaybillItemColour(item=item, colour=entry.colour, quantity=entry.quantity)
                    for entry in line.colours.all()
                )
        return waybill

    @property
    def colour_columns(self):
        """Every colour on this waybill, in the order first met. Empty when nothing is sold by colour."""
        seen = []
        for item in self.items.all():
            for entry in item.colours.all():
                if entry.colour and entry.colour not in seen:
                    seen.append(entry.colour)
        return seen

    @property
    def totals(self):
        """Quantity totals per unit — "69 coils" and "9 metres" can't be added into one number."""
        sums = {}
        for item in self.items.all():
            sums[item.unit] = sums.get(item.unit, Decimal("0")) + item.total_quantity
        return [{"unit": unit, "quantity": quantity} for unit, quantity in sums.items()]


class WaybillItem(models.Model):
    waybill = models.ForeignKey(Waybill, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=10, choices=QuoteLineItem.Kind.choices, default=QuoteLineItem.Kind.CABLE)
    cable_size = models.ForeignKey(
        CableSize, on_delete=models.SET_NULL, null=True, blank=True, related_name="waybill_items"
    )
    accessory = models.ForeignKey(
        Accessory, on_delete=models.SET_NULL, null=True, blank=True, related_name="waybill_items"
    )
    cable_type_name = models.CharField(max_length=100, blank=True)
    size_label = models.CharField(max_length=100, blank=True)
    item_name = models.CharField(max_length=150, blank=True)
    unit = models.CharField(max_length=10, choices=list(QUOTE_UNITS.items()))
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.model_label} {self.description}".strip()

    @property
    def model_label(self):
        """The waybill's MODEL column: the cable type, unless it's a catch-all like "Other"."""
        if self.kind == QuoteLineItem.Kind.ACCESSORY:
            return ""
        return "" if self.cable_type_name.strip().lower() in GENERIC_TYPE_NAMES else self.cable_type_name

    @property
    def description(self):
        return self.item_name if self.kind == QuoteLineItem.Kind.ACCESSORY else self.size_label

    @property
    def total_quantity(self):
        return sum((entry.quantity for entry in self.colours.all()), Decimal("0"))

    def quantity_for(self, colour):
        """Quantity in one colour column, or None when this item isn't sold by colour at all ("NA")."""
        if not any(entry.colour for entry in self.colours.all()):
            return None
        return next((entry.quantity for entry in self.colours.all() if entry.colour == colour), Decimal("0"))


class WaybillItemColour(models.Model):
    item = models.ForeignKey(WaybillItem, on_delete=models.CASCADE, related_name="colours")
    colour = models.CharField(max_length=50, blank=True)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(MAX_QUANTITY)]
    )

    class Meta:
        ordering = ["id"]
