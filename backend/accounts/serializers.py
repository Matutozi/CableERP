import logging

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from .models import AuditLog, BusinessProfile, naira, record

User = get_user_model()
logger = logging.getLogger(__name__)

MAX_LOGO_BYTES = 2 * 1024 * 1024
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
            raise serializers.ValidationError({"password": list(error.messages)})
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
        BusinessProfile.objects.create(user=user, business_name=validated_data["business_name"].strip())
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


class BusinessProfileSerializer(serializers.ModelSerializer):
    # A path, never an absolute URL: the app and the API share an origin, and an absolute one built from
    # Django's own socket (http://127.0.0.1:8000/...) points a phone at itself.
    logo = serializers.SerializerMethodField()
    current_password = serializers.CharField(write_only=True, required=False, allow_blank=True,
                                             style={"input_type": "password"})

    class Meta:
        model = BusinessProfile
        fields = [
            "id",
            "business_name",
            "address",
            "phone_numbers",
            "email",
            "logo",
            "bank_name",
            "account_name",
            "account_number",
            "disclaimer",
            "payment_terms",
            "quote_validity",
            "vat_rate",
            "current_password",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]

    def get_logo(self, profile):
        return profile.logo.url if profile.logo else None

    def _changed_bank_fields(self, attrs):
        return [name for name in BANK_FIELDS if name in attrs and attrs[name] != getattr(self.instance, name)]

    def validate(self, attrs):
        """Bank details decide where customers send money, so re-check the password before they move."""
        password = attrs.pop("current_password", "")
        if self.instance and self._changed_bank_fields(attrs):
            if not password:
                raise serializers.ValidationError(
                    {"current_password": "Enter your password to change bank details."}
                )
            if not self.instance.user.check_password(password):
                raise serializers.ValidationError({"current_password": "That password is not correct."})
        return attrs

    def update(self, instance, validated_data):
        changed = {name: (getattr(instance, name), validated_data[name]) for name in self._changed_bank_fields(validated_data)}
        profile = super().update(instance, validated_data)
        if changed:
            logger.warning("Bank details changed on business %s by user %s: %s",
                           instance.pk, instance.user_id, ", ".join(changed))
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


class LogoSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessProfile
        fields = ["logo"]
        extra_kwargs = {"logo": {"required": True, "allow_null": False}}

    def validate_logo(self, value):
        if value.size > MAX_LOGO_BYTES:
            raise serializers.ValidationError("Logo must be 2 MB or smaller.")
        return value
