from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

DEFAULT_DISCLAIMER = "Prices are subject to variations in market conditions"


def naira(value):
    return f"₦{value:,.2f}"


class BusinessProfile(models.Model):
    """The seller's business details. Every catalogue entry and quote belongs to one of these."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="business_profile")
    business_name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    phone_numbers = models.CharField(max_length=255, blank=True, help_text="Comma-separated")
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_name = models.CharField(max_length=200, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    disclaimer = models.TextField(blank=True, default=DEFAULT_DISCLAIMER)
    payment_terms = models.TextField(blank=True)
    quote_validity = models.CharField(max_length=255, blank=True)
    vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("7.50"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentage. Set to 0 if VAT does not apply.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.business_name

    @property
    def phone_list(self):
        return [phone.strip() for phone in self.phone_numbers.split(",") if phone.strip()]


class AuditLog(models.Model):
    """Who changed what, in business terms. Phase 6 gives each person their own login; this is what it will fill."""

    class Action(models.TextChoices):
        PRICE_CHANGED = "price_changed", "Price changed"
        BANK_CHANGED = "bank_changed", "Bank details changed"
        QUOTE_CREATED = "quote_created", "Quote created"
        QUOTE_UPDATED = "quote_updated", "Quote edited"
        QUOTE_SENT = "quote_sent", "Quote sent"
        QUOTE_REVISED = "quote_revised", "Quote revised"
        QUOTE_DELETED = "quote_deleted", "Quote deleted"
        PURCHASE_RECORDED = "purchase_recorded", "Purchase recorded"
        PURCHASE_DELETED = "purchase_deleted", "Purchase deleted"

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="audit_log")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    action = models.CharField(max_length=20, choices=Action.choices)
    summary = models.CharField(max_length=255)
    reference = models.CharField(max_length=100, blank=True, help_text="Quote reference or catalogue entry.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_action_display()}: {self.summary}"


def record(business, user, action, summary, reference=""):
    """Add one line of history. Called from the views that change money, bank details or quotes."""
    return AuditLog.objects.create(
        business=business,
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        summary=summary[:255],
        reference=reference[:100],
    )
