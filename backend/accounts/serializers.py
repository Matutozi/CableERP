import logging

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from PIL import Image
from rest_framework import serializers

from .models import (
    OWNER_TEMPLATE_NAME,
    AuditLog,
    BusinessProfile,
    Feature,
    Invitation,
    Membership,
    RoleTemplate,
    Store,
    provision_business,
    record,
)
from .permissions import HidesRestrictedFields

User = get_user_model()
logger = logging.getLogger(__name__)

MAX_LOGO_BYTES = 2 * 1024 * 1024
# A 2 MB file says nothing about how much memory it becomes once decoded: a mostly
# blank PNG can compress 30000x30000 into a few hundred kilobytes. WeasyPrint decodes
# the logo in full on every uncached PDF render, so the pixel count is the figure that
# actually sizes the box. 3000 a side is far more than any letterhead needs.
MAX_LOGO_DIMENSION = 3000
# Where customers are told to send money. Changing these is the one profile edit that needs the password.
BANK_FIELDS = ("bank_name", "account_name", "account_number")


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    business_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "full_name", "business_name"]

    def get_full_name(self, user):
        return user.get_full_name()

    def get_business_name(self, user):
        profile = getattr(user, "business_profile", None)
        return profile.business_name if profile else None


class RegisterSerializer(serializers.Serializer):
    business_name = serializers.CharField(max_length=200)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    username = serializers.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate(self, attrs):
        candidate = User(username=attrs["username"], email=attrs.get("email", ""))
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": list(error.messages)}) from error
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        first_name, _, last_name = validated_data.get("full_name", "").strip().partition(" ")
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email", ""),
            password=validated_data["password"],
            first_name=first_name,
            last_name=last_name.strip(),
        )
        business = BusinessProfile.objects.create(user=user, business_name=validated_data["business_name"].strip())
        # Role templates, an owner membership and the first store. Without them a new business
        # falls through to the legacy one-to-one in get_business() and has nothing to invite
        # anyone with.
        provision_business(business, user)
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    remember = serializers.BooleanField(default=False)

    def validate(self, attrs):
        user = authenticate(self.context.get("request"), username=attrs["username"], password=attrs["password"])
        if user is None:
            raise serializers.ValidationError("Invalid username or password.")
        attrs["user"] = user
        return attrs


class BusinessProfileSerializer(HidesRestrictedFields, serializers.ModelSerializer):
    # Where customers send money. Dropping the fields also blocks writing them, which is what
    # PRD P6-F7 asks for: only the owner changes bank details.
    restricted_fields = {Feature.BANK_DETAILS: list(BANK_FIELDS)}
    # A path, never an absolute URL: the app and the API share an origin, and an absolute one built from
    # Django's own socket (http://127.0.0.1:8000/...) points a phone at itself.
    logo = serializers.SerializerMethodField()
    brand_logo = serializers.SerializerMethodField()
    current_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={"input_type": "password"}
    )

    class Meta:
        model = BusinessProfile
        fields = [
            "id",
            "business_name",
            "address",
            "phone_numbers",
            "email",
            "logo",
            "brand_logo",
            "bank_name",
            "account_name",
            "account_number",
            "disclaimer",
            "payment_terms",
            "quote_validity",
            "vat_rate",
            # Writable: this one is the business's own preference, unlike the allowance below.
            "show_factory_price",
            # Visible so the app can show "2 of 3 stores used", but never writable here: the
            # allowance is the operator's lever, not the customer's (SYSTEM_DESIGN.md Q21).
            "store_limit",
            "active_store_count",
            "is_over_store_limit",
            "current_password",
            "updated_at",
        ]
        read_only_fields = ["updated_at", "store_limit", "active_store_count", "is_over_store_limit"]

    def get_logo(self, profile):
        return profile.logo.url if profile.logo else None

    def get_brand_logo(self, profile):
        return profile.brand_logo.url if profile.brand_logo else None

    def _changed_bank_fields(self, attrs):
        return [name for name in BANK_FIELDS if name in attrs and attrs[name] != getattr(self.instance, name)]

    def validate(self, attrs):
        """Bank details decide where customers send money, so re-check the password before they move."""
        password = attrs.pop("current_password", "")
        if self.instance and self._changed_bank_fields(attrs):
            if not password:
                raise serializers.ValidationError({"current_password": "Enter your password to change bank details."})
            if not self.instance.user.check_password(password):
                raise serializers.ValidationError({"current_password": "That password is not correct."})
        return attrs

    def update(self, instance, validated_data):
        changed = {
            name: (getattr(instance, name), validated_data[name]) for name in self._changed_bank_fields(validated_data)
        }
        profile = super().update(instance, validated_data)
        if changed:
            logger.warning(
                "Bank details changed on business %s by user %s: %s", instance.pk, instance.user_id, ", ".join(changed)
            )
            summary = "; ".join(
                f"{name.replace('_', ' ')} {old or '—'} → {new}" for name, (old, new) in sorted(changed.items())
            )
            request = self.context.get("request")
            record(profile, getattr(request, "user", None), AuditLog.Action.BANK_CHANGED, summary)
        return profile


class AuditLogSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source="get_action_display", read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["id", "action", "action_label", "summary", "reference", "user_name", "created_at"]

    def get_user_name(self, entry):
        if not entry.user:
            return "Removed user"
        return entry.user.get_full_name() or entry.user.username


def image_upload_serializer(field):
    """An upload serializer for one image field on the business profile (the logo, or the brand logo)."""

    class ImageUploadSerializer(serializers.ModelSerializer):
        class Meta:
            model = BusinessProfile
            fields = [field]
            extra_kwargs = {field: {"required": True, "allow_null": False}}

        def validate(self, attrs):
            upload = attrs[field]
            if upload.size > MAX_LOGO_BYTES:
                raise serializers.ValidationError({field: "Logo must be 2 MB or smaller."})
            # Image.open reads the header only; it does not decode the pixels, so probing
            # the dimensions of a decompression bomb is itself cheap.
            try:
                with Image.open(upload) as probe:
                    width, height = probe.size
            except (OSError, ValueError) as error:
                raise serializers.ValidationError({field: "That file is not an image we can read."}) from error
            finally:
                upload.seek(0)
            if max(width, height) > MAX_LOGO_DIMENSION:
                raise serializers.ValidationError(
                    {field: f"Logo must be {MAX_LOGO_DIMENSION} pixels or smaller on each side."}
                )
            return attrs

    return ImageUploadSerializer


LogoSerializer = image_upload_serializer("logo")


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["id", "name", "code", "address", "is_active"]


class RoleTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleTemplate
        fields = ["id", "name", "permissions", "is_system"]
        read_only_fields = ["is_system"]

    def validate_permissions(self, value):
        unknown = sorted(set(value) - set(Feature.values))
        if unknown:
            raise serializers.ValidationError(f"Not a feature: {', '.join(unknown)}.")
        return sorted(set(value))

    def validate(self, attrs):
        """Guard the one edit a business cannot undo from inside the product."""
        name = attrs.get("name", getattr(self.instance, "name", ""))
        permissions = attrs.get("permissions", getattr(self.instance, "permissions", []))
        if name == OWNER_TEMPLATE_NAME and Feature.MANAGE_MEMBERS not in permissions:
            raise serializers.ValidationError(
                {"permissions": "The Owner role must keep the ability to manage members."}
            )
        return attrs


class MemberSerializer(serializers.ModelSerializer):
    """A person on the staff list. Their access is editable; who they are is not."""

    username = serializers.CharField(source="user.username", read_only=True)
    full_name = serializers.SerializerMethodField()
    stores = serializers.PrimaryKeyRelatedField(many=True, queryset=Store.objects.none(), required=False)
    store_names = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = [
            "id",
            "username",
            "full_name",
            "role_label",
            "is_owner",
            "permissions",
            "all_stores",
            "stores",
            "store_names",
            "status",
            "created_at",
        ]
        read_only_fields = ["is_owner", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only this business's branches may be assigned — the field is a write surface, so its
        # queryset is a tenant boundary, not a convenience.
        business = self.context.get("business")
        if business is not None:
            self.fields["stores"].child_relation.queryset = business.stores.all()

    def get_full_name(self, membership):
        return membership.user.get_full_name() or membership.user.username

    def get_store_names(self, membership):
        if membership.all_stores:
            return ["All stores"]
        return [store.name for store in membership.stores.all()]

    def validate_permissions(self, value):
        unknown = sorted(set(value) - set(Feature.values))
        if unknown:
            raise serializers.ValidationError(f"Not a feature: {', '.join(unknown)}.")
        return sorted(set(value))

    def validate(self, attrs):
        """A business must never be left with nobody who can administer it."""
        if self.instance and self.instance.is_owner:
            losing_access = attrs.get("status") == Membership.Status.SUSPENDED
            losing_rights = Feature.MANAGE_MEMBERS not in attrs.get("permissions", self.instance.permissions)
            if losing_access or losing_rights:
                others = Membership.objects.filter(
                    business=self.instance.business, is_owner=True, status=Membership.Status.ACTIVE
                ).exclude(pk=self.instance.pk)
                if not others.exists():
                    raise serializers.ValidationError(
                        "This is the only active owner. Make someone else an owner first."
                    )
        return attrs


class InvitationSerializer(serializers.ModelSerializer):
    """A pending staff member. The raw token is returned once, on creation, and never again."""

    role_template = serializers.PrimaryKeyRelatedField(queryset=RoleTemplate.objects.none())
    stores = serializers.PrimaryKeyRelatedField(many=True, queryset=Store.objects.none(), required=False)
    status = serializers.CharField(read_only=True)
    invite_url = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "phone",
            "full_name",
            "role_template",
            "role_label",
            "permissions",
            "all_stores",
            "stores",
            "status",
            "expires_at",
            "accepted_at",
            "invite_url",
            "created_at",
        ]
        read_only_fields = ["role_label", "expires_at", "accepted_at", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        business = self.context.get("business")
        if business is not None:
            self.fields["role_template"].queryset = business.role_templates.all()
            self.fields["stores"].child_relation.queryset = business.stores.all()

    def get_invite_url(self, invitation):
        """Only ever populated on the response to creating it — the token is hashed at rest."""
        raw = getattr(invitation, "raw_token", None)
        return f"/invite/{raw}" if raw else None

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError("Give an email address or a phone number to send the invite to.")
        return attrs


class InvitationAcceptSerializer(serializers.Serializer):
    """Claiming an invitation: the person sets their own password (PRD P6-F3)."""

    token = serializers.CharField()
    username = serializers.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate(self, attrs):
        invitation = Invitation.claim(attrs["token"])
        if invitation is None:
            # Expired, used and never-existed are deliberately indistinguishable.
            raise serializers.ValidationError({"token": "This invitation link is not valid any more."})
        candidate = User(username=attrs["username"])
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": list(error.messages)}) from error
        attrs["invitation"] = invitation
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        first_name, _, last_name = validated_data.get("full_name", "").strip().partition(" ")
        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            first_name=first_name,
            last_name=last_name.strip(),
        )
        validated_data["invitation"].accept(user)
        return user
