from rest_framework.exceptions import PermissionDenied


def get_business(request):
    """Return the signed-in user's BusinessProfile — the tenant every query is scoped to."""
    profile = getattr(request.user, "business_profile", None)
    if profile is None:
        raise PermissionDenied("This account has no business profile.")
    return profile
