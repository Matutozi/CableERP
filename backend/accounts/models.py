import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

DEFAULT_DISCLAIMER = "Prices are subject to variations in market conditions"

# The store every business starts with. Migration 0009 keeps its own copy of these, as a data
# migration must reproduce the state at the time it ran rather than follow later edits.
DEFAULT_STORE_NAME = "Main"
DEFAULT_STORE_CODE = "MAIN"


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
    # Distributors who compete on being cheaper than the factory turn this on; others never would.
    # It only sets the default for new quotes — each quote carries its own copy (Q28).
    show_factory_price = models.BooleanField(
        default=False,
        help_text="Show the manufacturer's direct price on quotes, so customers see what they save.",
    )
    # How many active stores this business may run. Set by a platform operator in the Django
    # admin, never through the API — see SYSTEM_DESIGN.md Q21. When plans arrive this becomes the
    # per-customer override of the plan's default rather than the only source.
    store_limit = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Maximum active stores. Operator-set; the business cannot change it.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.business_name

    @property
    def phone_list(self):
        return [phone.strip() for phone in self.phone_numbers.split(",") if phone.strip()]

    @property
    def active_store_count(self):
        return self.stores.filter(is_active=True).count()

    @property
    def is_over_store_limit(self):
        """Over the allowance, and therefore restricted until the owner deactivates stores (Q22)."""
        return self.active_store_count > self.store_limit


class Store(models.Model):
    """A branch a business trades from. The third level of tenancy: user → business → store.

    Every business has at least one (PRD P6-F21). Quotes, waybills, purchases and per-store cost
    hang off this rather than off the business directly, so the branches of a business that buy
    independently can carry different landed costs.
    """

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="stores")
    name = models.CharField(max_length=120)
    # Goes into reference numbers — QT-IKJ-20260923-001 (PRD P6-F25) — so it is short, uppercase
    # and fixed once documents carry it.
    code = models.CharField(max_length=8, help_text="Short branch code used in reference numbers, e.g. IKJ.")
    address = models.TextField(blank=True)
    # Deactivated rather than deleted: a closed branch's quotes and waybills must keep resolving.
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "code"], name="one_store_code_per_business")]
        ordering = ["business_id", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        return super().save(*args, **kwargs)


class Feature(models.TextChoices):
    """The units access is granted in — one per major piece of functionality (PRD P6-F2a).

    These strings are stored on every membership row, so renaming one is a data migration, not a
    rename. Add new features at the end; never reuse a retired value.
    """

    # Reading the catalogue and repricing it are separate: anyone who sells needs the first, and
    # PRD P6-F6 restricts the second. One flag cannot say both.
    CATALOGUE = "catalogue", "See the catalogue"
    CATALOGUE_EDIT = "catalogue_edit", "Add items and change selling prices"
    PURCHASES = "purchases", "Record purchases"
    VIEW_COSTS = "view_costs", "See cost and margin"
    QUOTES = "quotes", "Quotes"
    WAYBILLS = "waybills", "Waybills"
    BANK_DETAILS = "bank_details", "Change bank details"
    MANAGE_MEMBERS = "manage_members", "Invite and remove members"
    REPORTS = "reports", "Reports"


# The templates every business starts with. They are seed data, not the authority: a business may
# rename them, edit them, and add its own — "Cashier", "Storekeeper", whatever its org chart
# actually is (SYSTEM_DESIGN.md Q26). Editing a template never changes an existing member's access.
SYSTEM_ROLE_TEMPLATES = {
    "Owner": frozenset(Feature.values),
    # Everything except the two an employee should never hold: the bank account money is paid
    # into, and the power to grant themselves more access (PRD P6-F2).
    "Manager": frozenset(Feature.values) - {Feature.BANK_DETAILS, Feature.MANAGE_MEMBERS},
    # Sells and delivers. Reads the catalogue because you cannot quote without it; cannot reprice
    # it, and never sees what the business paid (PRD P6-F5).
    "Sales": frozenset({Feature.CATALOGUE, Feature.QUOTES, Feature.WAYBILLS}),
}
OWNER_TEMPLATE_NAME = "Owner"


class RoleTemplate(models.Model):
    """A named starting set of permissions, owned by one business.

    Picking a template at invite time *copies* its permissions onto the membership. The template is
    never consulted afterwards, so editing "Cashier" next month cannot change what existing
    cashiers may do — the Q19 property, now per business.
    """

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="role_templates")
    name = models.CharField(max_length=50)
    permissions = models.JSONField(default=list, blank=True)
    # Seeded at onboarding. Editable and renameable, but not deletable: a business that deleted
    # every template would have nothing to invite anyone with.
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "name"], name="one_template_name_per_business")]
        ordering = ["business_id", "name"]

    def __str__(self):
        return f"{self.name} ({self.business.business_name})"

    @classmethod
    def seed_for(cls, business):
        """Give a new business the default templates. Idempotent."""
        existing = set(business.role_templates.values_list("name", flat=True))
        return cls.objects.bulk_create(
            [
                cls(business=business, name=name, permissions=sorted(perms), is_system=True)
                for name, perms in SYSTEM_ROLE_TEMPLATES.items()
                if name not in existing
            ]
        )

    def set_permissions(self, features):
        valid = {f for f in features if f in Feature.values}
        # The owner template is how a business administers itself. Editing it down to nothing is
        # the one change that cannot be undone from inside the product.
        if self.name == OWNER_TEMPLATE_NAME and Feature.MANAGE_MEMBERS not in valid:
            raise ValueError("The Owner template must keep the ability to manage members.")
        self.permissions = sorted(valid)
        return self.permissions


class Membership(models.Model):
    """One person's access to one business.

    Replaces `BusinessProfile.user` as the link between a user and a business, which was a
    one-to-one and therefore allowed neither employees nor a second owner (SYSTEM_DESIGN.md Q1).

    `permissions` is the authority. `role_template` and `role_label` are descriptive only: the
    template records which starting set was applied so the UI can offer to reapply it, and the
    label is a snapshot of its name so renaming or deleting a template never rewrites history.
    Every access check reads `permissions`.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        # Suspended rather than deleted, so their history keeps naming them (PRD P6-F4).
        SUSPENDED = "suspended", "Suspended"

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role_template = models.ForeignKey(
        RoleTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="memberships"
    )
    # A snapshot of the template's name at assignment. Descriptive, never consulted for access.
    role_label = models.CharField(max_length=50, blank=True)
    # Whether this person administers the business. Stored rather than derived from the role name,
    # because role names are now the business's to choose and "Owner" may not be one of them.
    is_owner = models.BooleanField(default=False)
    permissions = models.JSONField(default=list, blank=True)
    # Store access, per SYSTEM_DESIGN.md Q23. `all_stores` covers branches opened later; `stores`
    # is the explicit subset when it does not. The two are not interchangeable — see the entry.
    all_stores = models.BooleanField(default=False)
    stores = models.ManyToManyField("Store", blank=True, related_name="members")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["business", "user"], name="one_membership_per_user_per_business")
        ]
        ordering = ["business_id", "id"]

    def __str__(self):
        return f"{self.user} — {self.role_label or 'member'} at {self.business.business_name}"

    @classmethod
    def create_from_template(cls, business, user, template, invited_by=None, all_stores=None, stores=()):
        """Create a membership by copying a template's permissions onto it.

        The copy is the point: see SYSTEM_DESIGN.md Q19. After this the template can be renamed,
        edited or deleted without touching what this person may do.
        """
        owner = template.name == OWNER_TEMPLATE_NAME
        membership = cls.objects.create(
            business=business,
            user=user,
            role_template=template,
            role_label=template.name,
            is_owner=owner,
            permissions=list(template.permissions),
            # An owner sees branches opened after they joined; everyone else sees what they were given.
            all_stores=owner if all_stores is None else all_stores,
            invited_by=invited_by,
        )
        if stores:
            membership.stores.set(stores)
        return membership

    def has(self, feature):
        """Whether this member may use `feature` right now."""
        # A suspended member keeps their permission list — it is what they get back on
        # reinstatement — but it grants nothing while they are suspended.
        if self.status != self.Status.ACTIVE:
            return False
        return feature in self.permissions

    def set_permissions(self, features):
        """Replace the granted set, dropping anything that is not a real feature."""
        valid = {f for f in features if f in Feature.values}
        self.permissions = sorted(valid)
        return self.permissions

    def visible_stores(self):
        """The stores this member may see. Everything store-scoped filters through this."""
        if self.all_stores:
            return self.business.stores.filter(is_active=True)
        return self.stores.filter(is_active=True)

    def can_see_store(self, store):
        return (self.all_stores and store.business_id == self.business_id) or self.stores.filter(pk=store.pk).exists()


class Invitation(models.Model):
    """A pending staff member: the access an owner chose, waiting for a person to claim it.

    The membership is created on acceptance, not here — see SYSTEM_DESIGN.md Q25. Until then this
    row is what the owner's staff list shows as "pending".
    """

    # Long enough that guessing is hopeless, short enough to paste into WhatsApp.
    TOKEN_BYTES = 32
    DEFAULT_VALIDITY_DAYS = 7

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(blank=True)
    # Nigerian staff are far likelier to have WhatsApp than email (PRD P6-F3).
    phone = models.CharField(max_length=32, blank=True)
    full_name = models.CharField(max_length=150, blank=True)
    role_template = models.ForeignKey(
        RoleTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="invitations"
    )
    role_label = models.CharField(max_length=50, blank=True)
    # Copied from the template at invite time, then editable per person: the owner can tick or
    # untick individual features for this one invitation without touching the template.
    permissions = models.JSONField(default=list, blank=True)
    all_stores = models.BooleanField(default=False)
    stores = models.ManyToManyField("Store", blank=True, related_name="invitations")
    # Hashed, not stored raw: a leaked table should not be a set of working keys (Q25).
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invitation for {self.email or self.phone or 'unnamed'} to {self.business.business_name}"

    @staticmethod
    def hash_token(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, business, template, invited_by=None, validity_days=None, stores=(), **fields):
        """Create an invitation and return it with the one-time raw token.

        The raw token is returned, never stored. Losing it means reissuing, which is the intended
        trade: a link recoverable from the database is a link an attacker can recover too.
        """
        raw = secrets.token_urlsafe(cls.TOKEN_BYTES)
        days = cls.DEFAULT_VALIDITY_DAYS if validity_days is None else validity_days
        permissions = fields.pop("permissions", None)
        invitation = cls.objects.create(
            business=business,
            role_template=template,
            role_label=template.name,
            permissions=sorted(permissions) if permissions is not None else list(template.permissions),
            all_stores=fields.pop("all_stores", template.name == OWNER_TEMPLATE_NAME),
            token_hash=cls.hash_token(raw),
            expires_at=timezone.now() + timedelta(days=days),
            invited_by=invited_by,
            **fields,
        )
        if stores:
            invitation.stores.set(stores)
        return invitation, raw

    @classmethod
    def claim(cls, raw_token):
        """Find a usable invitation for this token, or None.

        Looks up by hash, so a token that is expired or already accepted is indistinguishable from
        one that never existed — an attacker probing links learns nothing either way.
        """
        invitation = cls.objects.filter(token_hash=cls.hash_token(raw_token)).first()
        return invitation if invitation and invitation.is_pending else None

    def accept(self, user):
        """Turn a pending invitation into a real membership."""
        membership = Membership.create_from_template(
            business=self.business,
            user=user,
            template=self.role_template,
            invited_by=self.invited_by,
            all_stores=self.all_stores,
            stores=list(self.stores.all()),
        )
        # The owner's per-person edits win over the template's defaults.
        membership.permissions = list(self.permissions)
        membership.role_label = self.role_label
        membership.save(update_fields=["permissions", "role_label"])
        self.accepted_at = timezone.now()
        self.save(update_fields=["accepted_at"])
        return membership

    @property
    def is_pending(self):
        return self.accepted_at is None and timezone.now() < self.expires_at

    @property
    def status(self):
        if self.accepted_at is not None:
            return "accepted"
        return "pending" if timezone.now() < self.expires_at else "expired"


def provision_business(business, owner_user, invited_by=None):
    """Everything a new business needs before anyone can use it.

    One function because there are three callers — registration, `seed_data`, and operator-led
    onboarding — and a business missing any of these pieces fails in a different confusing way:
    no templates means nobody can be invited, no membership means `get_business()` falls back to
    the legacy one-to-one, no store means quotes have nowhere to belong. Idempotent.
    """
    RoleTemplate.seed_for(business)
    owner_template = business.role_templates.get(name=OWNER_TEMPLATE_NAME)
    membership = Membership.objects.filter(business=business, user=owner_user).first()
    if membership is None:
        membership = Membership.create_from_template(business, owner_user, owner_template, invited_by=invited_by)
    store, _ = Store.objects.get_or_create(
        business=business, code=DEFAULT_STORE_CODE, defaults={"name": DEFAULT_STORE_NAME}
    )
    return membership, store


class AuditLog(models.Model):
    """Who changed what, in business terms. Phase 6 gives each person their own login; this is what it will fill."""

    class Action(models.TextChoices):
        PRICE_CHANGED = "price_changed", "Price changed"
        BANK_CHANGED = "bank_changed", "Bank details changed"
        # A quote sent with a different account than the profile's. Logged because the permission
        # prevents the obvious abuse and this catches the rest (SYSTEM_DESIGN.md Q31).
        QUOTE_PAYMENT_OVERRIDE = "quote_payment_override", "Quote payment account overridden"
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
    # 32 rather than 20: action names are descriptive, and the PRD already plans to widen this.
    action = models.CharField(max_length=32, choices=Action.choices)
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
