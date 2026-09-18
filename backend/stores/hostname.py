"""Hostname normalization shared by the store registry and the request resolver.

ADR-0005 §3: lowercase, strip the port, strip a trailing dot and IDNA-decode so
that `Shop.Example.COM:8443`, `shop.example.com.` and `shop.example.com` are one
hostname. No wildcard or default hostname is representable here.
"""

from __future__ import annotations

_FORBIDDEN = set("/\\@?#[] \t\r\n")


class InvalidHostnameError(ValueError):
    """Raised when a Host header value cannot be normalized safely."""


def normalize_hostname(host: str) -> str:
    if not isinstance(host, str):
        raise InvalidHostnameError("host must be a string")
    value = host.strip()
    if not value:
        raise InvalidHostnameError("host is empty")
    if any(character in _FORBIDDEN for character in value):
        raise InvalidHostnameError("host contains invalid characters")
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            raise InvalidHostnameError("malformed IPv6 host")
        value = value[1:end]
    elif ":" in value:
        value = value.split(":", 1)[0]
    value = value.rstrip(".").lower()
    if not value or value == "*" or "*" in value:
        raise InvalidHostnameError("host is empty or a wildcard")
    try:
        # IDNA-decode so a punycode host and its Unicode form resolve together.
        value = value.encode("ascii").decode("idna").lower()
    except (UnicodeError, UnicodeDecodeError):
        pass
    if any(character in _FORBIDDEN for character in value):
        raise InvalidHostnameError("host contains invalid characters")
    return value
