"""Sensitive-data detection and redaction.

Two tiers:
* `secrets` (card numbers, SSNs, API keys) are redacted from every model/user-facing output.
* `contact` details (email, phone) are redacted for roles below `manager`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_CARD_RE = re.compile(r"(?<![\w-])(?:\d[ -]?){13,19}(?![\w-])")
_SSN_RE = re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])")
_KEY_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w])(?:\+?1[ -.]?)?\(?\d{3}\)?[ -.]\d{3}[ -.]\d{4}(?![\w])")


def luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits][::-1]
    total = sum(n if i % 2 == 0 else (n * 2 - 9 if n * 2 > 9 else n * 2) for i, n in enumerate(nums))
    return total % 10 == 0


@dataclass
class Redaction:
    text: str
    findings: list[str] = field(default_factory=list)


def redact_secrets(text: str) -> Redaction:
    findings: list[str] = []

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            findings.append("card_number")
            return "[REDACTED:CARD]"
        return m.group(0)

    out = _CARD_RE.sub(card, text)
    out, n = _SSN_RE.subn("[REDACTED:SSN]", out)
    findings += ["ssn"] * n
    out, n = _KEY_RE.subn("[REDACTED:KEY]", out)
    findings += ["api_key"] * n
    return Redaction(out, findings)


def mask_email(value: str) -> str:
    m = _EMAIL_RE.fullmatch(value.strip())
    if not m:
        return value
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"


def redact_contact(text: str) -> Redaction:
    findings: list[str] = []
    out, n = _EMAIL_RE.subn(lambda m: mask_email(m.group(0)), text)
    findings += ["email"] * n
    out, n = _PHONE_RE.subn(lambda m: mask_phone(m.group(0)), out)
    findings += ["phone"] * n
    return Redaction(out, findings)


def redact_output(text: str, role: str) -> Redaction:
    r = redact_secrets(text)
    if role == "viewer":
        c = redact_contact(r.text)
        return Redaction(c.text, r.findings + c.findings)
    return r
