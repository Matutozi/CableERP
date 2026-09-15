"""Render a waybill to PDF with WeasyPrint, the same way quotations are."""

from django.core.cache import cache
from django.template.loader import render_to_string
from weasyprint import HTML

from quotes.pdf import PDF_CACHE_SECONDS, image_uri


def waybill_pdf_bytes(waybill):
    """Render once per version of the waybill and of the business profile; repeat downloads come from cache."""
    key = f"waybill-pdf:{waybill.pk}:{waybill.updated_at.timestamp()}:{waybill.business.updated_at.timestamp()}"
    pdf = cache.get(key)
    if pdf is None:
        pdf = render_waybill_pdf(waybill)
        cache.set(key, pdf, PDF_CACHE_SECONDS)
    return pdf


def waybill_context(waybill):
    business = waybill.business
    return {
        "waybill": waybill,
        "business": business,
        "logo_uri": image_uri(business.logo),
        "brand_logo_uri": image_uri(business.brand_logo),
    }


def render_waybill_pdf(waybill):
    """Expects `waybill` fetched with items__colours prefetched."""
    return HTML(string=render_to_string("waybills/waybill_pdf.html", waybill_context(waybill))).write_pdf()
