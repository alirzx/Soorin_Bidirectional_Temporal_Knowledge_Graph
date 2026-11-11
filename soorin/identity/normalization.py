"""Deterministic, locale-independent SOC identifier normalization."""

from __future__ import annotations

import ipaddress
import re
import unicodedata


class IdentityNormalizationError(ValueError):
    pass


def normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise IdentityNormalizationError("identifier must be a string")
    value = " ".join(unicodedata.normalize("NFKC", value).strip().split())
    if not value or any(ord(char) < 32 for char in value):
        raise IdentityNormalizationError("identifier is empty or contains control characters")
    return value


def normalize_hostname(value: str) -> str:
    value = normalize_text(value).rstrip(".").casefold()
    if "\\" in value or "/" in value or " " in value:
        raise IdentityNormalizationError("invalid hostname")
    try:
        ascii_name = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise IdentityNormalizationError("invalid international hostname") from exc
    if len(ascii_name) > 253:
        raise IdentityNormalizationError("hostname is too long")
    labels = ascii_name.split(".")
    if any(not label or len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels):
        raise IdentityNormalizationError("invalid hostname label")
    return ascii_name


def normalize_ip(value: str) -> str:
    try:
        return ipaddress.ip_address(normalize_text(value).strip("[]")).compressed.casefold()
    except ValueError as exc:
        raise IdentityNormalizationError("invalid IP address") from exc


def normalize_principal(value: str) -> str:
    value = normalize_text(value)
    if value.count("\\") > 1:
        raise IdentityNormalizationError("invalid Windows principal")
    if "\\" in value:
        domain, account = value.split("\\", 1)
        if not domain or not account:
            raise IdentityNormalizationError("invalid Windows principal")
        return f"{domain.casefold()}\\{account.casefold()}"
    if "@" in value:
        account, domain = value.rsplit("@", 1)
        if not account or not domain:
            raise IdentityNormalizationError("invalid UPN")
        return f"{account.casefold()}@{normalize_hostname(domain)}"
    return value.casefold()


def normalize_entity_value(entity_type: str, value: str) -> str:
    key = entity_type.replace("_", "").casefold()
    if key in {"host", "hostname"}:
        return normalize_hostname(value)
    if key in {"ip", "ipaddress"}:
        return normalize_ip(value)
    if key in {"user", "useraccount", "principal"}:
        return normalize_principal(value)
    if key in {"mitretechnique"}:
        result = normalize_text(value).upper()
        if not re.fullmatch(r"T\d{4}(?:\.\d{3})?", result):
            raise IdentityNormalizationError("invalid MITRE ATT&CK technique")
        return result
    if key in {"filehash", "indicator"}:
        result = normalize_text(value).casefold()
        if re.fullmatch(r"[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64}", result):
            return result
    return normalize_text(value).casefold()
