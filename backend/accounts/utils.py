from rest_framework.exceptions import PermissionDenied

from accounts.models import Membership

# The session key holding the business a user with several memberships is currently working in
# (PRD P6-F9). Absent for the overwhelming majority, who belong to exactly one.
CURRENT_BUSINESS_SESSION_KEY = "current_business_id"


def get_membership(request):
    """The signed-in user's membership of the business they are working in, or None.

    Resolution order, and why:

    1. The business named in the session, if the user still has an active membership of it. A
       stale id — revoked access, deleted business — falls through rather than raising, so a
       suspended member sees their other businesses instead of a dead end.
    2. Their single active membership, when there is exactly one. This is everybody today.
    3. None when they have several and have chosen none. The caller decides whether that is an
       error or a prompt to choose.
    """
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return None

    active = Membership.objects.select_related("business").filter(user=user, status=Membership.Status.ACTIVE)

    chosen_id = request.session.get(CURRENT_BUSINESS_SESSION_KEY) if hasattr(request, "session") else None
    if chosen_id:
        membership = active.filter(business_id=chosen_id).first()
        if membership:
            return membership

    memberships = list(active[:2])
    return memberships[0] if len(memberships) == 1 else None


def get_business(request):
    """Return the BusinessProfile every query is scoped to.

    While the membership migration is in flight this falls back to the legacy one-to-one, so a
    user whose Membership row has not been backfilled is not locked out of their own data. See
    SYSTEM_DESIGN.md Q20; the fallback goes when `BusinessProfile.user` does.
    """
    membership = get_membership(request)
    if membership is not None:
        return membership.business

    profile = getattr(request.user, "business_profile", None)
    if profile is None:
        raise PermissionDenied("This account has no business profile.")
    return profile


def require(request, feature):
    """Raise unless the signed-in user holds `feature` in the business they are working in.

    Users still on the legacy one-to-one hold everything: they are the sole owner of their own
    business, and there is no membership row yet to say so.
    """
    membership = get_membership(request)
    if membership is None:
        if getattr(request.user, "business_profile", None) is not None:
            return
        raise PermissionDenied("This account has no business profile.")
    if not membership.has(feature):
        raise PermissionDenied("Your access does not include this.")
