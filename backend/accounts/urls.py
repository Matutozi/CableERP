from django.urls import path

from . import views

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
]
