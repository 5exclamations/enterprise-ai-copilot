"""Small text helpers shared by embeddings, keyword search and the mock LLM."""
from __future__ import annotations

import re

STOPWORDS = frozenset(
    """a an the and or but if then of to in on at by for with from as is are was were be been being
    do does did have has had this that these those it its i we you they he she them our your their
    what which who whom when where why how can could should would will shall may might must not no
    about into over under than so such any all each per there here also just""".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")

# Tiny, hand-written synonym table used ONLY by the default hashing embedder, so the
# semantic channel can match paraphrases the keyword channel cannot. This is a stand-in
# for a neural embedding model, not a replacement (see docs/RAG_PIPELINE.md).
SYNONYMS = {
    "reimburse": "refund", "reimbursed": "refund", "defect": "damage", "defects": "damage", "reimbursement": "refund", "refunds": "refund", "moneyback": "refund",
    "send": "ship", "dispatch": "ship", "deliver": "ship", "delivery": "ship", "shipment": "ship",
    "shipping": "ship", "courier": "ship", "freight": "ship",
    "defective": "damage", "broken": "damage", "faulty": "damage", "damaged": "damage",
    "guarantee": "warranty", "guaranteed": "warranty",
    "invoice": "payment", "billing": "payment", "pay": "payment", "paid": "payment",
    "restock": "replenish", "reorder": "replenish", "replenishment": "replenish",
    "cancel": "cancel", "cancellation": "cancel", "cancelled": "cancel", "canceled": "cancel",
    "return": "return", "returns": "return", "returned": "return", "rma": "return",
    "hazardous": "hazmat", "chemical": "hazmat", "chemicals": "hazmat", "flammable": "hazmat",
    "privacy": "privacy", "confidential": "privacy", "pii": "privacy",
    "closed": "holiday", "holidays": "holiday", "hours": "hours",
}


def stem(word: str) -> str:
    """Very light suffix stripper (good enough for English business text)."""
    for suffix in ("ingly", "edly", "ing", "ies", "ied", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix in ("ies", "ied"):
                return word[: -len(suffix)] + "y"
            return word[: -len(suffix)]
    return word


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    if not keep_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return [stem(t) for t in tokens]


def expand_synonyms(text: str) -> list[str]:
    out = []
    for raw in _TOKEN_RE.findall(text.lower()):
        if raw in STOPWORDS:
            continue
        out.append(stem(SYNONYMS.get(raw, raw)))
    return out


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) used for chunk sizing and the mock provider."""
    return max(1, (len(text) + 3) // 4)


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def split_sentences(text: str) -> list[str]:
    parts = []
    for block in re.split(r"\n+", text):
        block = block.strip()
        if block:
            parts.extend(s.strip() for s in _SENTENCE_RE.split(block) if s.strip())
    return parts
