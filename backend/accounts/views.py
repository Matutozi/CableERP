from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .serializers import (
    AuditLogSerializer,
    BusinessProfileSerializer,
    LoginSerializer,
    image_upload_serializer,
    RegisterSerializer,
    UserSerializer,
)
from .utils import get_business


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
    throttle_classes = [ScopedRateThrottle]
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
        return get_business(self.request).audit_log.select_related("user")[:50]


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
