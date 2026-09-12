from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import BusinessProfile
from catalogue.models import MAX_PRICE, MAX_QUANTITY, QUOTE_UNITS, Accessory, CableSize

# Cable type names that are just catalogue buckets, so the size label alone describes the item
# (e.g. "RG6 Coaxial" rather than "RG6 Coaxial Other").
GENERIC_TYPE_NAMES = {"other", "others", "misc", "miscellaneous"}


def money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Quote(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="quotes")
    reference_number = models.CharField(max_length=32, editable=False)
    customer_name = models.CharField(max_length=200)
    date = models.DateField(default=timezone.localdate)
    staff_name = models.CharField(max_length=200)
    staff_phone = models.CharField(max_length=50, blank=True)
    product_manufacturer = models.CharField(max_length=200, blank=True)
    transport_cost = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0"),
        validators=[MinValueValidator(0), MaxValueValidator(MAX_PRICE)],
    )
    vat_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"), validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    revision_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="revisions",
        help_text="The sent quote this one was raised to replace.",
    )
    # Copied from the business profile when the quote is written, so editing the profile later can never
    # change the account a customer was told to pay into.
    payment_bank_name = models.CharField(max_length=100, blank=True)
    payment_account_name = models.CharField(max_length=200, blank=True)
    payment_account_number = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["business", "reference_number"], name="unique_quote_reference_per_business"),
        ]

    def __str__(self):
        return f"{self.reference_number} — {self.customer_name}"

    @classmethod
    def next_reference_number(cls, business, date):
        """QT-YYYYMMDD-NNN, numbered per business per day. Callers should hold a lock on the business row."""
        prefix = f"QT-{date:%Y%m%d}-"
        existing = cls.objects.filter(business=business, reference_number__startswith=prefix).values_list(
            "reference_number", flat=True
        )
        last = max((int(ref.removeprefix(prefix)) for ref in existing), default=0)
        return f"{prefix}{last + 1:03d}"

    @property
    def is_locked(self):
        """A sent quote is the record of what the customer received, so it stops being editable."""
        return self.status == self.Status.SENT

    def create_revision(self):
        """Copy this quote into a fresh draft, leaving the sent one exactly as it went out."""
        business = self.business
        revision = Quote.objects.create(
            business=business,
            reference_number=Quote.next_reference_number(business, timezone.localdate()),
            customer_name=self.customer_name,
            date=timezone.localdate(),
            staff_name=self.staff_name,
            staff_phone=self.staff_phone,
            product_manufacturer=self.product_manufacturer,
            transport_cost=self.transport_cost,
            vat_percentage=self.vat_percentage,
            notes=self.notes,
            payment_bank_name=business.bank_name,
            payment_account_name=business.account_name or business.business_name,
            payment_account_number=business.account_number,
            revision_of=self,
        )
        for item in self.line_items.all():
            copy = QuoteLineItem.objects.create(
                quote=revision, kind=item.kind, cable_size=item.cable_size, accessory=item.accessory,
                cable_type_name=item.cable_type_name, size_label=item.size_label, item_name=item.item_name,
                unit=item.unit, unit_price=item.unit_price, order=item.order,
            )
            QuoteLineItemColour.objects.bulk_create(
                QuoteLineItemColour(line_item=copy, colour=entry.colour, quantity=entry.quantity)
                for entry in item.colours.all()
            )
        return revision

    @property
    def payment_details(self):
        """Where to pay, as recorded on this quote. Quotes written before snapshots fall back to the profile."""
        if self.payment_bank_name or self.payment_account_number:
            return {
                "bank_name": self.payment_bank_name,
                "account_name": self.payment_account_name or self.business.business_name,
                "account_number": self.payment_account_number,
            }
        business = self.business
        return {
            "bank_name": business.bank_name,
            "account_name": business.account_name or business.business_name,
            "account_number": business.account_number,
        }

    # Totals are computed from line items on the fly; prefetch "line_items__colours" to avoid extra queries.
    @property
    def subtotal(self):
        return money(sum((item.amount for item in self.line_items.all()), Decimal("0")))

    @property
    def vat_amount(self):
        return money(self.subtotal * self.vat_percentage / Decimal("100"))

    @property
    def grand_total(self):
        return self.subtotal + self.vat_amount + self.transport_cost


class QuoteLineItem(models.Model):
    """One product on a quote. Names, unit and price are copied from the catalogue so the quote never changes."""

    class Kind(models.TextChoices):
        CABLE = "cable", "Cable"
        ACCESSORY = "accessory", "Accessory"

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name="line_items")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CABLE)
    # Catalogue entries this line came from, kept for future cost and stock tracking. Display uses the snapshot fields.
    cable_size = models.ForeignKey(
        CableSize, on_delete=models.SET_NULL, null=True, blank=True, related_name="quote_line_items"
    )
    accessory = models.ForeignKey(
        Accessory, on_delete=models.SET_NULL, null=True, blank=True, related_name="quote_line_items"
    )
    cable_type_name = models.CharField(max_length=100, blank=True)
    size_label = models.CharField(max_length=100, blank=True)
    item_name = models.CharField(max_length=150, blank=True, help_text="Accessory name. Cables use type and size.")
    unit = models.CharField(max_length=10, choices=list(QUOTE_UNITS.items()))
    unit_price = models.DecimalField(
        max_digits=15, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(MAX_PRICE)]
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.description

    @property
    def description(self):
        if self.kind == self.Kind.ACCESSORY:
            return self.item_name
        if self.cable_type_name.strip().lower() in GENERIC_TYPE_NAMES:
            return self.size_label
        return f"{self.size_label} {self.cable_type_name}".strip()

    @property
    def has_colours(self):
        return any(entry.colour for entry in self.colours.all())

    @property
    def total_quantity(self):
        return sum((entry.quantity for entry in self.colours.all()), Decimal("0"))

    @property
    def amount(self):
        return money(self.total_quantity * self.unit_price)


class QuoteLineItemColour(models.Model):
    """Quantity of one colour on a line item. Items without colour variants have a single row with colour ""."""

    line_item = models.ForeignKey(QuoteLineItem, on_delete=models.CASCADE, related_name="colours")
    colour = models.CharField(max_length=50, blank=True)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(MAX_QUANTITY)]
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.colour or 'Qty'}: {self.quantity}"
