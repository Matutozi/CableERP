from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import generics, mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import AuditLog, Feature, Invitation, Membership, RoleTemplate, Store, record
from .permissions import NotRestricted, member_can, requires
from .serializers import (
    AuditLogSerializer,
    BusinessProfileSerializer,
    InvitationAcceptSerializer,
    InvitationSerializer,
    LoginSerializer,
    MemberSerializer,
    RegisterSerializer,
    RoleTemplateSerializer,
    StoreSerializer,
    UserSerializer,
    image_upload_serializer,
)
from .throttling import LoginUsernameThrottle
from .utils import (
    CURRENT_STORE_SESSION_KEY,
    current_store,
    get_business,
    get_membership,
    scope_to_current_store,
    scope_to_stores,
)


class MeView(APIView):
    """Report who is signed in. Also plants the CSRF cookie the frontend echoes back on writes."""

    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        user = request.user if request.user.is_authenticated else None
        return Response({"user": UserSerializer(user).data if user else None})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    """CSRF-protected so another site can't sign a visitor into an account of its choosing."""

    permission_classes = [AllowAny]
    # Two limits, because they stop different attacks: ScopedRateThrottle caps one
    # address guessing quickly, LoginUsernameThrottle caps one account being guessed
    # at from many addresses.
    throttle_classes = [ScopedRateThrottle, LoginUsernameThrottle]
    throttle_scope = "auth"

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        login(request, user)
        # Without "keep me signed in" the session ends with the browser — safer on a shared shop computer.
        request.session.set_expiry(settings.SESSION_COOKIE_AGE if serializer.validated_data["remember"] else 0)
        return Response({"user": UserSerializer(user).data})


@method_decorator(csrf_protect, name="dispatch")
class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        login(request, user)
        return Response({"user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutEverywhereView(APIView):
    """Drop every session this account has, including this one. Django keeps no per-user index, so we scan."""

    def post(self, request):
        user_id = str(request.user.pk)
        for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
            if session.get_decoded().get("_auth_user_id") == user_id:
                session.delete()
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = BusinessProfileSerializer

    def get_object(self):
        return get_business(self.request)


class ActivityView(generics.ListAPIView):
    """The business's own change history, newest first."""

    serializer_class = AuditLogSerializer

    def get_queryset(self):
        entries = get_business(self.request).audit_log.select_related("user")
        # A bank-change entry spells out the account number in its summary, so the history is a
        # back door to the one field the product guards hardest. Hidden rather than the whole log
        # blocked: quote and price history is exactly what a manager should be able to review.
        if not member_can(self.request, Feature.BANK_DETAILS):
            entries = entries.exclude(action=AuditLog.Action.BANK_CHANGED)
        # A branch's staff see their branch's history and no other's.
        scoped = scope_to_current_store(scope_to_stores(entries, self.request), self.request)
        return scoped.order_by("-created_at", "-id")[:50]


class ProfileLogoView(APIView):
    """Upload or remove one of the profile's images. `field` picks which: the business logo by default."""

    parser_classes = [MultiPartParser, FormParser]
    field = "logo"

    def post(self, request):
        profile = get_business(request)
        image = getattr(profile, self.field)
        old_name = image.name
        serializer = image_upload_serializer(self.field)(profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        image = getattr(profile, self.field)
        if old_name and old_name != image.name:
            image.storage.delete(old_name)
        return Response(BusinessProfileSerializer(profile, context={"request": request}).data)

    def delete(self, request):
        profile = get_business(request)
        image = getattr(profile, self.field)
        if image:
            image.delete(save=True)
        return Response(BusinessProfileSerializer(profile, context={"request": request}).data)


class ProfileBrandLogoView(ProfileLogoView):
    field = "brand_logo"


class StaffViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """The people who work in this business, and what each may do.

    No create: a person joins by accepting an invitation, never by an owner conjuring an account
    (SYSTEM_DESIGN.md Q25). No delete either — a member is suspended so their history keeps naming
    them (PRD P6-F4).
    """

    serializer_class = MemberSerializer
    permission_classes = [IsAuthenticated, NotRestricted, requires(Feature.MANAGE_MEMBERS)]

    def get_queryset(self):
        return (
            Membership.objects.filter(business=get_business(self.request))
            .select_related("user")
            .prefetch_related("stores")
        )

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "business": get_business(self.request)}

    def perform_update(self, serializer):
        membership = serializer.save()
        record(
            get_business(self.request),
            self.request.user,
            AuditLog.Action.MEMBER_CHANGED,
            f"{membership.user.username}: {membership.role_label or 'member'}, "
            f"{len(membership.permissions)} permissions, {membership.status}",
        )


class InvitationViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """Invitations this business has sent. Creating one returns the link exactly once."""

    serializer_class = InvitationSerializer
    permission_classes = [IsAuthenticated, NotRestricted, requires(Feature.MANAGE_MEMBERS)]

    def get_queryset(self):
        return Invitation.objects.filter(business=get_business(self.request)).prefetch_related("stores")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "business": get_business(self.request)}

    def create(self, request, *args, **kwargs):
        business = get_business(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        invitation, raw = Invitation.issue(
            business,
            data["role_template"],
            invited_by=request.user,
            stores=data.get("stores", ()),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            full_name=data.get("full_name", ""),
            permissions=data.get("permissions"),
            all_stores=data.get("all_stores", False),
        )
        # Carried on the instance for this response only; it is hashed at rest and unrecoverable
        # afterwards, so an owner who loses the link reissues rather than looks it up (Q25).
        invitation.raw_token = raw
        record(
            business,
            request.user,
            AuditLog.Action.MEMBER_INVITED,
            f"Invited {data.get('email') or data.get('phone')} as {invitation.role_label}",
        )
        return Response(self.get_serializer(invitation).data, status=status.HTTP_201_CREATED)


class RoleTemplateViewSet(viewsets.ModelViewSet):
    """The role presets this business invites people with — its own, not the platform's (Q26)."""

    serializer_class = RoleTemplateSerializer
    permission_classes = [IsAuthenticated, NotRestricted, requires(Feature.MANAGE_MEMBERS)]

    def get_queryset(self):
        return RoleTemplate.objects.filter(business=get_business(self.request))

    def perform_create(self, serializer):
        serializer.save(business=get_business(self.request))

    def perform_destroy(self, instance):
        # The seeded templates are what a business invites with; deleting them all would leave it
        # unable to add anyone.
        if instance.is_system:
            raise ValidationError("The built-in roles cannot be deleted. Rename or edit them instead.")
        instance.delete()


class AcceptInvitationView(APIView):
    """Claim an invitation and set a password. Reachable without signing in, by design."""

    permission_classes = [AllowAny]
    throttle_scope = "register"
    throttle_classes = [ScopedRateThrottle]

    def post(self, request):
        serializer = InvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        login(request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class FeatureListView(APIView):
    """Every permission a business can grant, with its label.

    Served rather than hard-coded in the app, because a list kept in two places drifts: a feature
    added on the server but missing from the UI is not merely ungrantable, it is *silently revoked*
    the next time anyone saves that member, since the picker submits only what it knows to tick.
    """

    def get(self, request):
        return Response([{"value": value, "label": label} for value, label in Feature.choices])


class CurrentStoreView(APIView):
    """Which branch the member is working in, and the branches they may choose from.

    A preference, not a permission (SYSTEM_DESIGN.md Q33): the choices come from the membership,
    and setting anything outside them is refused.
    """

    def get(self, request):
        membership = get_membership(request)
        available = membership.visible_stores() if membership else Store.objects.none()
        chosen = current_store(request)
        return Response(
            {
                "current": StoreSerializer(chosen).data if chosen else None,
                "available": StoreSerializer(available, many=True).data,
                # Below two branches there is nothing to choose between, so the app hides the picker.
                "selectable": available.count() > 1,
            }
        )

    def put(self, request):
        store_id = request.data.get("store")
        if store_id in (None, "", "all"):
            request.session.pop(CURRENT_STORE_SESSION_KEY, None)
            return self.get(request)

        membership = get_membership(request)
        allowed = membership.visible_stores().filter(pk=store_id).exists() if membership else False
        if not allowed:
            raise ValidationError({"store": "That branch is not one of yours."})
        request.session[CURRENT_STORE_SESSION_KEY] = int(store_id)
        return self.get(request)


class StoreViewSet(viewsets.ModelViewSet):
    """The branches this business trades from."""

    serializer_class = StoreSerializer
    permission_classes = [IsAuthenticated, NotRestricted, requires(Feature.MANAGE_MEMBERS)]

    def get_queryset(self):
        return Store.objects.filter(business=get_business(self.request))

    def perform_create(self, serializer):
        business = get_business(self.request)
        # The allowance is the operator's lever; a business cannot grant itself another branch
        # by creating one (SYSTEM_DESIGN.md Q21).
        if business.active_store_count >= business.store_limit:
            raise ValidationError(
                f"Your plan allows {business.store_limit} store(s). Deactivate one, or ask for the limit to be raised."
            )
        serializer.save(business=business)
