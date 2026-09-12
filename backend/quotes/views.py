from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from accounts.models import AuditLog, BusinessProfile, naira, record

from accounts.utils import get_business

from .models import Quote
from .pdf import quote_pdf_bytes
from .serializers import QuoteListSerializer, QuoteSerializer


class QuotePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class PdfRateThrottle(UserRateThrottle):
    """Rendering a PDF is the most expensive thing one request can ask for."""

    scope = "pdf"


class QuoteViewSet(viewsets.ModelViewSet):
    pagination_class = QuotePagination

    def get_queryset(self):
        queryset = (
            Quote.objects.filter(business=get_business(self.request))
            .select_related("business")
            .prefetch_related("line_items__colours")
        )
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(customer_name__icontains=search) | Q(reference_number__icontains=search))
        return queryset

    def get_serializer_class(self):
        return QuoteListSerializer if self.action == "list" else QuoteSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "business": get_business(self.request)}

    def _record(self, quote, action):
        record(quote.business, self.request.user, action,
               f"{quote.customer_name} · {naira(quote.grand_total)}", reference=quote.reference_number)

    def perform_create(self, serializer):
        self._record(serializer.save(), AuditLog.Action.QUOTE_CREATED)

    def perform_update(self, serializer):
        was_draft = serializer.instance.status == Quote.Status.DRAFT
        quote = serializer.save()
        sent_now = was_draft and quote.status == Quote.Status.SENT
        self._record(quote, AuditLog.Action.QUOTE_SENT if sent_now else AuditLog.Action.QUOTE_UPDATED)

    def perform_destroy(self, instance):
        if instance.is_locked:
            raise ValidationError(
                "A sent quote is the record of what the customer received, so it can't be deleted."
            )
        self._record(instance, AuditLog.Action.QUOTE_DELETED)
        instance.delete()

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        """Copy a quote into a new draft, leaving the original exactly as it was sent."""
        quote = self.get_object()
        with transaction.atomic():
            # Same lock as creating a quote, so the new reference number can't collide.
            BusinessProfile.objects.select_for_update().get(pk=quote.business_id)
            revision = quote.create_revision()
        revision = self.get_queryset().get(pk=revision.pk)
        record(revision.business, request.user, AuditLog.Action.QUOTE_REVISED,
               f"{revision.reference_number} replaces {quote.reference_number}", reference=revision.reference_number)
        return Response(self.get_serializer(revision).data, status=201)

    @action(detail=True, methods=["get"], throttle_classes=[PdfRateThrottle])
    def pdf(self, request, pk=None):
        quote = self.get_object()
        response = HttpResponse(quote_pdf_bytes(quote), content_type="application/pdf")
        disposition = "inline" if request.query_params.get("inline") else "attachment"
        response["Content-Disposition"] = f'{disposition}; filename="{quote.reference_number}.pdf"'
        return response
