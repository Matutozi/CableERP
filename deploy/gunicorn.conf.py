"""Gunicorn settings for CableERP. Used by deploy/cableerp.service."""

import os


def _workers():
    """One worker per ~700 MB: WeasyPrint holds a lot of memory while rendering."""
    total_mb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 * 1024)
    return max(1, min(3, int(total_mb // 700)))


bind = "127.0.0.1:8000"          # nginx proxies to this; never exposed directly
workers = int(os.environ.get("WEB_WORKERS", _workers()))
timeout = 120                     # a large quote's PDF takes a few seconds to render
graceful_timeout = 30
max_requests = 500                # recycle workers: WeasyPrint holds on to memory
max_requests_jitter = 50
accesslog = "-"                   # journald captures both
errorlog = "-"
