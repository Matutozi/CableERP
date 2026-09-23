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
    # Distributors print the maker's mark beside their own ("Product of COLEMAN WIRES AND CABLES"),
    # on quotations and waybills alike: it is the brand the customer is actually buying.
    brand_logo = models.ImageField(
        upload_to="logos/",
        blank=True,
        help_text="Logo of the manufacturer whose cables you distribute, shown beside your own.",
    )
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


class Feature(models.TextChoices):
    """The units access is granted in — one per major piece of functionality (PRD P6-F2a).

    These strings are stored on every membership row, so renaming one is a data migration, not a
    rename. Add new features at the end; never reuse a retired value.
    """

    CATALOGUE = "catalogue", "Catalogue and selling prices"
    PURCHASES = "purchases", "Record purchases"
    VIEW_COSTS = "view_costs", "See cost and margin"
    QUOTES = "quotes", "Quotes"
    WAYBILLS = "waybills", "Waybills"
    BANK_DETAILS = "bank_details", "Change bank details"
    MANAGE_MEMBERS = "manage_members", "Invite and remove members"
    REPORTS = "reports", "Reports"


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    MANAGER = "manager", "Manager"
    SALES = "sales", "Sales"


# A preset is a starting point, copied into the membership when it is created. It is deliberately
# *not* consulted afterwards — see SYSTEM_DESIGN.md Q19. Widening a preset here must never widen
# what an existing member can already do.
ROLE_PRESETS = {
    Role.OWNER: frozenset(Feature.values),
    # Everything except the two an employee should never hold: the bank account money is paid
    # into, and the power to grant themselves more access (PRD P6-F2).
    Role.MANAGER: frozenset(Feature.values) - {Feature.BANK_DETAILS, Feature.MANAGE_MEMBERS},
    # Sells, but never sees what the business paid (PRD P6-F5).
    Role.SALES: frozenset({Feature.QUOTES, Feature.WAYBILLS}),
}


class Membership(models.Model):
    """One person's access to one business.

    Replaces `BusinessProfile.user` as the link between a user and a business, which was a
    one-to-one and therefore allowed neither employees nor a second owner (SYSTEM_DESIGN.md Q1).

    `permissions` is the authority, not `role`. The role records which preset was applied so the
    UI can say "Manager" and offer to reapply it; every access check reads `permissions`.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        # Suspended rather than deleted, so their history keeps naming them (PRD P6-F4).
        SUSPENDED = "suspended", "Suspended"

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SALES)
    # A flat list of Feature values. Stores add a second dimension to this later (PRD P6-F26);
    # that migration has to run over every row anyway to give each business its one store, so it
    # can reshape this at the same time. A flat list until then keeps the checks honest.
    permissions = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "user"], name="one_membership_per_user_per_business")]
        ordering = ["business_id", "id"]

    def __str__(self):
        return f"{self.user} — {self.get_role_display()} at {self.business.business_name}"

    @classmethod
    def create_with_role(cls, business, user, role, invited_by=None):
        """Create a membership with the preset's permissions copied onto it."""
        return cls.objects.create(
            business=business,
            user=user,
            role=role,
            permissions=sorted(ROLE_PRESETS[role]),
            invited_by=invited_by,
        )

    def has(self, feature):
        """Whether this member may use `feature` right now."""
        # A suspended member keeps their permission list — it is what they get back on
        # reinstatement — but it grants nothing while they are suspended.
        if self.status != self.Status.ACTIVE:
            return False
        return feature in self.permissions

    @property
    def is_owner(self):
        return self.role == Role.OWNER

    def set_permissions(self, features):
        """Replace the granted set, dropping anything that is not a real feature."""
        valid = {f for f in features if f in Feature.values}
        self.permissions = sorted(valid)
        return self.permissions


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
        WAYBILL_CREATED = "waybill_created", "Waybill created"
        WAYBILL_UPDATED = "waybill_updated", "Waybill edited"
        WAYBILL_DELETED = "waybill_deleted", "Waybill deleted"

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
