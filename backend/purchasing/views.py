from django.db import transaction
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination

from accounts.models import AuditLog, naira, record
from accounts.utils import get_business

from . import costing
from .models import Purchase
from .serializers import PurchaseListSerializer, PurchaseSerializer


class PurchasePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class PurchaseViewSet(viewsets.ModelViewSet):
    """Deliveries, and the cost they leave behind on the catalogue.

    Every write recomputes the cached cost of the rows it touches. That work is small — one
    business restocks a handful of items at a time — and doing it inline keeps the ledger and
    the cache consistent within the request, with no background job to fall behind.
    """

    pagination_class = PurchasePagination

    def get_queryset(self):
        return (
            Purchase.objects.filter(business=get_business(self.request))
            .prefetch_related("items__cable_size__cable_type", "items__accessory")
            .select_related("created_by")
        )

    def get_serializer_class(self):
        return PurchaseListSerializer if self.action == "list" else PurchaseSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "business": get_business(self.request)}

    def _record(self, purchase, action=AuditLog.Action.PURCHASE_RECORDED):
        supplier = purchase.supplier_name or "supplier not named"
        record(
            purchase.business,
            self.request.user,
            action,
            f"{supplier} · {naira(purchase.total_cost)}",
            reference=str(purchase.date),
        )

    # The save and the cost recalculation are one unit of work: if the arithmetic turns out
    # impossible, the delivery must not be left behind without it.
    @transaction.atomic
    def perform_create(self, serializer):
        purchase = serializer.save()
        costing.refresh(purchase)
        self._record(purchase)

    @transaction.atomic
    def perform_update(self, serializer):
        # Rows that were on the delivery before the edit still need their cost corrected,
        # even if this edit removed them from it.
        before = costing.rows_of(serializer.instance)
        purchase = serializer.save()
        costing.refresh(purchase, also=before)
        self._record(purchase)

    @transaction.atomic
    def perform_destroy(self, instance):
        rows = costing.rows_of(instance)
        self._record(instance, AuditLog.Action.PURCHASE_DELETED)
        instance.delete()
        costing.recalculate_rows(rows)
