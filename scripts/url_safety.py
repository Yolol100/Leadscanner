from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


_BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".home.arpa",
)


def _is_global_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(str(value).split("%", 1)[0]).is_global
    except ValueError:
        return False


def is_public_http_url(value: object, *, resolver=None) -> bool:
    """Return True only for HTTP(S) URLs whose resolved addresses are public.

    This blocks direct private/local IPs, local-only hostnames, credentials in URLs,
    and DNS answers that point at non-global addresses. Call this before every
    outbound request, including redirect targets.
    """
    text = str(value or "").strip()
    if not text:
        return False

    try:
        parsed = urlparse(text)
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    except (TypeError, ValueError):
        return False

    if parsed.scheme.casefold() not in {"http", "https"}:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False

    host = (parsed.hostname or "").strip().casefold().rstrip(".")
    if not host or "%" in host:
        return False
    if host == "localhost" or any(host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES):
        return False

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return literal.is_global

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False

    resolver = resolver or socket.getaddrinfo
    try:
        answers = resolver(ascii_host, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror):
        return False

    addresses = {
        str(answer[4][0])
        for answer in answers
        if len(answer) >= 5 and answer[4] and answer[4][0]
    }
    return bool(addresses) and all(_is_global_ip(address) for address in addresses)
