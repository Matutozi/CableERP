from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from accounts.models import AuditLog, record
from accounts.utils import get_business
from quotes.views import PdfRateThrottle

from .models import Waybill
from .pdf import waybill_pdf_bytes
from .serializers import WaybillCreateSerializer, WaybillListSerializer, WaybillSerializer


class WaybillPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class WaybillViewSet(viewsets.ModelViewSet):
    pagination_class = WaybillPagination

    def get_queryset(self):
        queryset = (
            Waybill.objects.filter(business=get_business(self.request))
            .select_related("business", "quote")
            .prefetch_related("items__colours")
        )
        quote = self.request.query_params.get("quote")
        if quote and quote.isdigit():
            queryset = queryset.filter(quote_id=int(quote))
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return WaybillListSerializer
        return WaybillCreateSerializer if self.action == "create" else WaybillSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "business": get_business(self.request)}

    def _record(self, waybill, action):
        record(waybill.business, self.request.user, action,
               f"{waybill.customer_name} · {len(waybill.items.all())} items", reference=waybill.reference_number)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        waybill = Waybill.from_quote(serializer.validated_data["quote"], request.user)
        waybill = self.get_queryset().get(pk=waybill.pk)
        self._record(waybill, AuditLog.Action.WAYBILL_CREATED)
        return Response(WaybillSerializer(waybill, context=self.get_serializer_context()).data,
                        status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        self._record(serializer.save(), AuditLog.Action.WAYBILL_UPDATED)

    def perform_destroy(self, instance):
        self._record(instance, AuditLog.Action.WAYBILL_DELETED)
        instance.delete()

    @action(detail=True, methods=["get"], throttle_classes=[PdfRateThrottle])
    def pdf(self, request, pk=None):
        waybill = self.get_object()
        response = HttpResponse(waybill_pdf_bytes(waybill), content_type="application/pdf")
        disposition = "inline" if request.query_params.get("inline") else "attachment"
        response["Content-Disposition"] = f'{disposition}; filename="{waybill.reference_number}.pdf"'
        return response
