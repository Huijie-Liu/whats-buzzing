"""SSRF guards, IP helpers, and debug-mode checks."""

import ipaddress
import os
import socket
import urllib.error
import urllib.parse
import urllib.request


# Networks the preview endpoints must never reach: RFC1918, loopback,
# link-local (incl. cloud metadata), CGNAT, and the IPv6 equivalents.
# NOTE: 198.18.0.0/15 (RFC 2544 benchmarking) is intentionally NOT blocked —
# some local proxies (e.g. Clash fake-ip) resolve public domains into that
# range, and blocking it would disable all previews in those environments.
# 198.18/15 is not a routable internal-services range, so leaving it open
# does not create an SSRF path.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n) for n in (
        "0.0.0.0/8",        # "this" network
        "10.0.0.0/8",       # RFC1918
        "100.64.0.0/10",    # CGNAT
        "127.0.0.0/8",      # loopback
        "169.254.0.0/16",   # link-local (incl. cloud metadata)
        "172.16.0.0/12",    # RFC1918
        "192.168.0.0/16",   # RFC1918
        "224.0.0.0/4",      # multicast
        "240.0.0.0/4",      # reserved
        "::1/128",          # IPv6 loopback
        "fc00::/7",         # IPv6 unique-local
        "fe80::/10",        # IPv6 link-local
    )
]


def _is_blocked_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any(addr in net for net in _BLOCKED_NETWORKS)


def is_safe_url(url):
    """Reject URLs whose host resolves to a private / loopback / link-local
    IP.  Guards the preview endpoints against SSRF (e.g. clients pointing
    the server at 169.254.169.254 or an internal service).  A DNS-rebinding
    race between resolution and connection is still theoretically possible;
    this stops the common case of a literal internal IP or hostname."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        if _is_blocked_ip(info[4][0]):
            return False
    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects but re-validate every hop with ``is_safe_url`` so a
    public URL can't 302 into an internal address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_safe_url(newurl):
            raise urllib.error.URLError("blocked redirect to unsafe url")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SAFE_OPENER = urllib.request.build_opener(_SafeRedirectHandler)


def _last_hop(value):
    """Rightmost non-empty entry of a comma-separated proxy header."""
    if not value:
        return ""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts[-1] if parts else ""


def client_ip_from_headers(headers, fallback=""):
    """Originating client IP for rate-limiting.

    Prefers platform-trusted headers (``x-vercel-forwarded-for``,
    ``x-real-ip``), then falls back to the **rightmost** hop of
    ``X-Forwarded-For`` — that's the one appended by the last trusted proxy
    and the one a client cannot control.  The leftmost XFF hop is
    client-supplied and spoofable, so trusting it would let a single client
    rotate rate-limiter keys freely."""
    if headers:
        for name in ("x-vercel-forwarded-for", "x-real-ip"):
            hop = _last_hop(headers.get(name, ""))
            if hop:
                return hop
        hop = _last_hop(headers.get("X-Forwarded-For", ""))
        if hop:
            return hop
    return fallback


def debug_enabled():
    """/api/debug is local-only by default; opt in on Vercel production via
    ``ENABLE_DEBUG=1``."""
    if os.environ.get("ENABLE_DEBUG") == "1":
        return True
    return os.environ.get("VERCEL_ENV") not in ("production",)
