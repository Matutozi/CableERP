"""Gunicorn settings for CableERP. Used by deploy/cableerp.service."""

bind = "127.0.0.1:8000"          # nginx proxies to this; never exposed directly
workers = 3                       # a 2-vCPU droplet handles 3 comfortably
timeout = 120                     # a large quote's PDF takes a few seconds to render
graceful_timeout = 30
max_requests = 500                # recycle workers: WeasyPrint holds on to memory
max_requests_jitter = 50
accesslog = "-"                   # journald captures both
errorlog = "-"
