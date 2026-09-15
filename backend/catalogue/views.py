from django.db.models import Max
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog, naira, record
from accounts.utils import get_business

from .models import Accessory, CableSize, CableType, record_price
from .serializers import (
    AccessorySerializer,
    CableSizeSerializer,
    CableTypeSerializer,
    ItemHistorySerializer,
    PriceMovementSerializer,
)


def next_order(queryset):
    """Position for a new entry so it lands at the end of the list."""
    return (queryset.aggregate(Max("order"))["order__max"] or 0) + 1


def item_history(row):
    """Everything known about how one item's money has moved: what it sold for, what it cost.

    Two independent series — the seller sets the price, the market sets the cost — charted
    together so the gap between them is visible as it opens and closes.
    """
    from purchasing.models import PurchaseItem  # imported here: purchasing depends on catalogue, not the reverse

    field = "cable_size" if isinstance(row, CableSize) else "accessory"
    purchases = (
        PurchaseItem.objects.filter(**{field: row})
        .exclude(landed_unit_cost__isnull=True)
        .select_related("purchase")
        .order_by("purchase__date", "purchase_id", "id")
    )
    return {
        "price": [
            {"date": change.changed_at.date(), "value": change.price}
            for change in row.price_changes.all()
        ],
        "cost": [
            {
                "date": item.purchase.date,
                "value": item.landed_unit_cost,
                "quantity": item.sale_quantity,
                "supplier": item.purchase.supplier_name,
            }
            for item in purchases
        ],
    }


class ItemHistoryMixin:
    """Adds `GET /{id}/history/` to a catalogue viewset."""

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        return Response(ItemHistorySerializer(item_history(self.get_object())).data)


class BusinessCatalogueMixin:
    """For catalogue lists owned by the signed-in business: gives serializers the business and appends new entries."""

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "business": get_business(self.request)}

    def perform_create(self, serializer):
        extra = {} if "order" in serializer.validated_data else {"order": next_order(self.get_queryset())}
        serializer.save(business=get_business(self.request), **extra)


class CableTypeViewSet(BusinessCatalogueMixin, viewsets.ModelViewSet):
    serializer_class = CableTypeSerializer

    def get_queryset(self):
        return CableType.objects.filter(business=get_business(self.request)).prefetch_related("sizes")

    @action(detail=True, methods=["get", "post"])
    def sizes(self, request, pk=None):
        cable_type = self.get_object()
        if request.method == "GET":
            return Response(CableSizeSerializer(cable_type.sizes.all(), many=True).data)

        serializer = CableSizeSerializer(data=request.data, context={"cable_type": cable_type})
        serializer.is_valid(raise_exception=True)
        extra = {} if "order" in serializer.validated_data else {"order": next_order(cable_type.sizes)}
        size = serializer.save(cable_type=cable_type, **extra)
        record_price(size, request.user)  # the opening point of this size's price history
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CableSizeViewSet(
    ItemHistoryMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CableSizeSerializer

    def get_queryset(self):
        return CableSize.objects.filter(cable_type__business=get_business(self.request)).select_related("cable_type")

    def perform_update(self, serializer):
        was = serializer.instance.default_price
        size = serializer.save()
        if size.default_price != was:
            record_price(size, self.request.user)
            record(
                get_business(self.request), self.request.user, AuditLog.Action.PRICE_CHANGED,
                f"{naira(was)} → {naira(size.default_price)}",
                reference=f"{size.size_label} {size.cable_type.name}",
            )


class AccessoryViewSet(ItemHistoryMixin, BusinessCatalogueMixin, viewsets.ModelViewSet):
    serializer_class = AccessorySerializer

    def get_queryset(self):
        return Accessory.objects.filter(business=get_business(self.request))

    def perform_create(self, serializer):
        super().perform_create(serializer)
        record_price(serializer.instance, self.request.user)

    def perform_update(self, serializer):
        was = serializer.instance.default_price
        accessory = serializer.save()
        if accessory.default_price != was:
            record_price(accessory, self.request.user)
            record(
                get_business(self.request), self.request.user, AuditLog.Action.PRICE_CHANGED,
                f"{naira(was)} → {naira(accessory.default_price)}",
                reference=accessory.name,
            )


# How many movers the dashboard shows. Small on purpose: the panel answers "has anything moved
# since I last looked?", and a list long enough to scroll stops answering it.
MOVEMENT_LIMIT = 6


class PriceMovementsView(APIView):
    """Catalogue items whose cost has moved most recently, newest first.

    One request rather than a history call per item: the dashboard would otherwise make a
    dozen, and a seller opening the app on mobile data pays for every one of them.
    """

    def get(self, request):
        from purchasing.models import PurchaseItem

        business = get_business(request)
        restocked = PurchaseItem.objects.exclude(landed_unit_cost__isnull=True)

        latest = {
            ("size", pk): date
            for pk, date in restocked.filter(cable_size__cable_type__business=business)
            .values_list("cable_size")
            .annotate(last=Max("purchase__date"))
        }
        latest.update({
            ("accessory", pk): date
            for pk, date in restocked.filter(accessory__business=business)
            .values_list("accessory")
            .annotate(last=Max("purchase__date"))
        })

        recent = sorted(latest.items(), key=lambda entry: (entry[1], entry[0][1]), reverse=True)[:MOVEMENT_LIMIT]
        rows = {
            "size": CableSize.objects.select_related("cable_type").in_bulk(
                [pk for (kind, pk), _ in recent if kind == "size"]
            ),
            "accessory": Accessory.objects.in_bulk([pk for (kind, pk), _ in recent if kind == "accessory"]),
        }

        movements = []
        for (kind, pk), moved_on in recent:
            row = rows[kind].get(pk)
            if row is None:
                continue
            movements.append({
                "kind": kind,
                "id": row.pk,
                "name": str(row),
                "unit": row.sale_unit,
                "price": row.default_price,
                "last_unit_cost": row.last_unit_cost,
                "margin_percentage": row.margin_percentage,
                "last_moved": moved_on,
                "history": item_history(row),
            })
        return Response(PriceMovementSerializer(movements, many=True).data)
