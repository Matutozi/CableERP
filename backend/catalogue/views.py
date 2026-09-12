from django.db.models import Max
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import AuditLog, naira, record
from accounts.utils import get_business

from .models import Accessory, CableSize, CableType
from .serializers import AccessorySerializer, CableSizeSerializer, CableTypeSerializer


def next_order(queryset):
    """Position for a new entry so it lands at the end of the list."""
    return (queryset.aggregate(Max("order"))["order__max"] or 0) + 1


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
        serializer.save(cable_type=cable_type, **extra)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CableSizeViewSet(
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
            record(
                get_business(self.request), self.request.user, AuditLog.Action.PRICE_CHANGED,
                f"{naira(was)} → {naira(size.default_price)}",
                reference=f"{size.size_label} {size.cable_type.name}",
            )


class AccessoryViewSet(BusinessCatalogueMixin, viewsets.ModelViewSet):
    serializer_class = AccessorySerializer

    def get_queryset(self):
        return Accessory.objects.filter(business=get_business(self.request))

    def perform_update(self, serializer):
        was = serializer.instance.default_price
        accessory = serializer.save()
        if accessory.default_price != was:
            record(
                get_business(self.request), self.request.user, AuditLog.Action.PRICE_CHANGED,
                f"{naira(was)} → {naira(accessory.default_price)}",
                reference=accessory.name,
            )
