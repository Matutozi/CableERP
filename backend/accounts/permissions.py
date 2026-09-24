"""Who may do what, in one place.

Every access decision in the product routes through `member_can`. The serializers, the viewsets and
anything added later ask the same question, so a rule cannot be changed in one path and left stale
in another — see SYSTEM_DESIGN.md Q29.

Two shapes of gate, because the requirements need both:

* **Endpoint** — `requires(Feature.PURCHASES)` refuses the whole view. Right when the feature is
  the thing being protected: a salesperson has no business reading the purchase ledger at all.
* **Field** — `HidesRestrictedFields` drops keys from the payload. Right when the endpoint must
  still work: a salesperson cannot quote without reading the catalogue, they just must not see what
  the stock cost (PRD P6-F5).
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Feature
from .utils import get_membership


def member_can(request, feature):
    """Whether the signed-in user holds `feature` in the business they are working in.

    A user still on the legacy one-to-one holds everything: they are the sole owner of their own
    business and predate memberships entirely (SYSTEM_DESIGN.md Q20).
    """
    if request is None or not getattr(getattr(request, "user", None), "is_authenticated", False):
        return False
    membership = get_membership(request)
    if membership is None:
        return getattr(request.user, "business_profile", None) is not None
    return membership.has(feature)


def can_see_costs(request):
    """The single predicate behind every cost figure the product shows.

    Asked by the catalogue, quote, price-history and dashboard serializers. Anything that learns to
    show cost later must ask this too rather than repeat the check.
    """
    return member_can(request, Feature.VIEW_COSTS)


def requires(feature, write_feature=None):
    """A DRF permission class gating a view on one feature.

    `write_feature` gates unsafe methods more tightly than reads, which is how the catalogue works:
    everyone who sells needs to read it, only some may reprice it (PRD P6-F6).
    """

    class _RequiresFeature(BasePermission):
        message = "Your access does not include this."

        def has_permission(self, request, view):
            needed = feature
            if write_feature is not None and request.method not in SAFE_METHODS:
                needed = write_feature
            return member_can(request, needed)

    _RequiresFeature.__name__ = f"Requires{feature.replace('_', ' ').title().replace(' ', '')}"
    return _RequiresFeature


class NotRestricted(BasePermission):
    """Refuse writes from a business an operator has restricted (SYSTEM_DESIGN.md Q34).

    Reads pass through, so the business keeps its catalogue, its quotes and its PDFs. Only adding
    to them stops.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        business = getattr(getattr(request, "user", None), "business_profile", None)
        membership = get_membership(request)
        if membership is not None:
            business = membership.business
        if business is None or not business.is_restricted:
            return True
        self.message = business.restricted_reason or (
            "This account is read-only. Your records are still here and still downloadable. "
            "Contact us to reactivate it."
        )
        return False


class HidesRestrictedFields:
    """Serializer mixin that removes fields the caller may not see.

    Declare `restricted_fields = {feature: [names]}`. The fields are dropped from the serializer
    rather than blanked in the output, so nothing downstream — a nested serializer, a `.values()`
    call, a future export — can reach a value that was never declared.

    **Fails closed.** With no request in the context the fields are hidden, because the only callers
    without one are internal, and a security control that defaults to permissive is one bad wiring
    away from leaking. Anything internal that genuinely needs cost should read the model.
    """

    restricted_fields = {}

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        for feature, names in self.restricted_fields.items():
            if not member_can(request, feature):
                for name in names:
                    fields.pop(name, None)
        return fields
