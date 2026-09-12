"""Render a quote to PDF with WeasyPrint."""

from pathlib import Path

from django.core.cache import cache
from django.template.loader import render_to_string
from weasyprint import HTML

PDF_CACHE_SECONDS = 60 * 60 * 24


def _logo_uri(business):
    if not business.logo:
        return None
    try:
        path = Path(business.logo.path)
    except NotImplementedError:  # storage without local files (e.g. S3): let WeasyPrint fetch the URL
        return business.logo.url
    return path.as_uri() if path.exists() else None


def quote_pdf_bytes(quote):
    """Render once per version of the quote and of the business profile; repeat downloads come from cache."""
    key = f"quote-pdf:{quote.pk}:{quote.updated_at.timestamp()}:{quote.business.updated_at.timestamp()}"
    pdf = cache.get(key)
    if pdf is None:
        pdf = render_quote_pdf(quote)
        cache.set(key, pdf, PDF_CACHE_SECONDS)
    return pdf


def render_quote_pdf(quote):
    """Return the quote as PDF bytes. Expects `quote` fetched with line_items__colours prefetched."""
    html = render_to_string(
        "quotes/quote_pdf.html",
        {"quote": quote, "business": quote.business, "logo_uri": _logo_uri(quote.business)},
    )
    return HTML(string=html).write_pdf()
