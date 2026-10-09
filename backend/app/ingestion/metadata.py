"""Rule-based metadata extraction (deterministic, no LLM needed)."""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .parsing import ParsedDocument

CATEGORIES = ("policy", "sop", "catalog", "legal", "support", "other")

_CATEGORY_KEYWORDS = {
    "policy": ["policy", "terms", "pricing", "discount", "warranty", "returns", "refund", "privacy", "security", "code of conduct"],
    "sop": ["procedure", "sop", "checklist", "replenishment", "handling", "onboarding", "step"],
    "catalog": ["catalog", "catalogue", "product guide", "specifications", "sku"],
    "legal": ["agreement", "contract", "liability", "indemn"],
    "support": ["support", "hours", "contact", "holiday", "faq"],
}
_SKU_RE = re.compile(r"\b[A-Z]{2}-\d{4}\b")
_DATE_RE = re.compile(
    r"effective(?:\s+date)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2}, \d{4})", re.IGNORECASE
)
_VERSION_RE = re.compile(r"\bversion\s*[:\-]?\s*(v?\d+(?:\.\d+)*)", re.IGNORECASE)


def _parse_date(raw: str) -> str | None:
    for fmt in ("%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def guess_category(title: str, text: str) -> str:
    haystack = (title + " " + title + " " + text[:1500]).lower()
    scores = {c: sum(haystack.count(k) for k in kws) for c, kws in _CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def extract_metadata(filename: str, parsed: ParsedDocument, *, title: str | None = None,
                     category: str | None = None) -> dict:
    stem = Path(filename).stem.replace("-", " ").replace("_", " ").title()
    final_title = (title or parsed.title_hint or stem).strip()[:300]
    head = parsed.full_text[:3000]
    eff = _DATE_RE.search(head)
    ver = _VERSION_RE.search(head)
    skus = sorted(set(_SKU_RE.findall(parsed.full_text)))
    return {
        "title": final_title,
        "category": category if category in CATEGORIES else guess_category(final_title, parsed.full_text),
        "effective_date": _parse_date(eff.group(1)) if eff else None,
        "doc_version_label": ver.group(1) if ver else None,
        "mentioned_skus": skus[:50],
        "word_count": len(parsed.full_text.split()),
        "page_count": parsed.page_count,
        "language": "en",
        "extracted_on": date.today().isoformat(),
    }
