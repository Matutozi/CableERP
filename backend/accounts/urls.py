from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("staff", views.StaffViewSet, basename="staff")
router.register("invitations", views.InvitationViewSet, basename="invitation")
router.register("roles", views.RoleTemplateViewSet, basename="role-template")
router.register("stores", views.StoreViewSet, basename="store")

urlpatterns = [
    path("auth/me/", views.MeView.as_view(), name="auth-me"),
    path("auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("auth/register/", views.RegisterView.as_view(), name="auth-register"),
    path("auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/logout-everywhere/", views.LogoutEverywhereView.as_view(), name="auth-logout-everywhere"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("profile/logo/", views.ProfileLogoView.as_view(), name="profile-logo"),
    path("profile/brand-logo/", views.ProfileBrandLogoView.as_view(), name="profile-brand-logo"),
    path("activity/", views.ActivityView.as_view(), name="activity"),
    path("features/", views.FeatureListView.as_view(), name="features"),
    path("current-store/", views.CurrentStoreView.as_view(), name="current-store"),
    # Reachable without a session: the invited person has no account yet.
    path("auth/accept-invite/", views.AcceptInvitationView.as_view(), name="auth-accept-invite"),
    path("", include(router.urls)),
]
