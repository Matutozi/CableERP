from rest_framework.exceptions import PermissionDenied

from accounts.models import Membership

# The session key holding the business a user with several memberships is currently working in
# (PRD P6-F9). Absent for the overwhelming majority, who belong to exactly one.
CURRENT_BUSINESS_SESSION_KEY = "current_business_id"
# The branch a member is currently working in. A preference, not a permission — see Q33. Held in
# the session so it is per-device: checking Aba from a phone must not change the laptop's view.
CURRENT_STORE_SESSION_KEY = "current_store_id"


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


def scope_to_stores(queryset, request, field="store"):
    """Narrow a queryset to the branches the signed-in member may see.

    Every store-scoped queryset goes through here rather than filtering per view, for the reason
    `get_business()` exists: one chokepoint is auditable, and a view that forgets to filter looks
    exactly like a view with nothing to hide (SYSTEM_DESIGN.md Q32).

    Records with no store are kept. They predate stores or belong to the business as a whole — a
    bank change is not a branch's doing — and hiding them would blank the history of every existing
    business the day this ships.
    """
    membership = get_membership(request)
    # A user still on the legacy one-to-one is the sole owner of their own business (Q20).
    if membership is None or membership.all_stores:
        return queryset
    return queryset.filter(**{f"{field}__in": membership.visible_stores()}) | queryset.filter(
        **{f"{field}__isnull": True}
    )


def current_store(request):
    """The branch the member has chosen to work in, or None for "all mine".

    Selected from `visible_stores()` and nowhere else, so a stale or crafted session value can only
    ever show less than the membership already allows (SYSTEM_DESIGN.md Q33). A value that no longer
    resolves falls through to None rather than erroring: a member whose branches changed should find
    the app working, not broken.
    """
    membership = get_membership(request)
    if membership is None or not hasattr(request, "session"):
        return None
    chosen_id = request.session.get(CURRENT_STORE_SESSION_KEY)
    if not chosen_id:
        return None
    return membership.visible_stores().filter(pk=chosen_id).first()


def scope_to_current_store(queryset, request, field="store"):
    """Narrow to the chosen branch, on top of what the member is allowed to see.

    Applied *after* `scope_to_stores`, never instead of it. The order is the safety property: the
    worst a bad selection can do is show too little.
    """
    chosen = current_store(request)
    if chosen is None:
        return queryset
    return queryset.filter(**{f"{field}__in": [chosen]}) | queryset.filter(**{f"{field}__isnull": True})


def default_store(request):
    """The branch a new record belongs to, or None when it cannot be decided.

    The chosen branch wins. Failing that, a member scoped to exactly one branch is plainly working
    in it. A member who sees several and has chosen none has not said which, so the record stays
    business-wide rather than being filed under a branch nobody picked.
    """
    chosen = current_store(request)
    if chosen is not None:
        return chosen
    membership = get_membership(request)
    if membership is None:
        return None
    stores = list(membership.visible_stores()[:2])
    return stores[0] if len(stores) == 1 and not membership.all_stores else None


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
