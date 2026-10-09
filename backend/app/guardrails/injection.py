"""Heuristic prompt-injection detection.

Pattern matching is a *tripwire*, not the security boundary: it catches the common cases
cheaply and produces audit signals. The real boundary is structural (tenant-scoped tools,
strict tool schemas, confirmation-gated writes) and holds even if every pattern is bypassed.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_P = re.IGNORECASE
_PATTERNS: list[tuple[str, float, re.Pattern]] = [
    ("override_instructions", 0.9, re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your|the|system)\b[^.\n]{0,30}\b(instructions?|prompts?|rules?|guidelines?|polic(?:y|ies)|guardrails?)\b", _P)),
    ("reveal_prompt", 0.85, re.compile(
        r"\b(reveal|show|print|repeat|output|leak|display|tell me)\b[^.\n]{0,40}\b(system prompt|hidden prompt|initial instructions|your instructions|your prompt)\b", _P)),
    ("persona_hijack", 0.8, re.compile(
        r"\b(you are now|act as|pretend to be|from now on you)\b[^.\n]{0,50}\b(dan|unrestricted|jailbroken|developer mode|no restrictions|without (any )?restrictions)\b", _P)),
    ("jailbreak_keyword", 0.6, re.compile(r"\b(jailbreak|developer mode|do anything now)\b", _P)),
    ("raw_sql", 0.8, re.compile(
        r"(\b(run|execute|exec)\b[^.\n]{0,30}\b(sql|query|statement)\b|\bdrop\s+table\b|\bdelete\s+from\b|\bunion\s+select\b|;\s*--)", _P)),
    ("skip_confirmation", 0.85, re.compile(
        r"\b(without|skip|no|bypass)\b[^.\n]{0,20}\b(confirm(?:ation)?|approval|asking)\b|\b(auto[- ]?confirm|confirm (it|this|the action) (yourself|for me))\b", _P)),
    ("cross_tenant", 0.85, re.compile(
        r"\b(other|another|all|every|different)\s+(tenants?|compan(?:y|ies)|organi[sz]ations?|customers' accounts)\b|\btenant[_ ]?id\b", _P)),
    ("role_markup", 0.6, re.compile(r"(<\|im_start\|>|<\|system\|>|\[/?INST\]|<system>|###\s*system\b|^\s*system\s*:)", _P | re.MULTILINE)),
    ("exfiltrate", 0.7, re.compile(
        r"\b(send|email|post|upload|forward)\b[^.\n]{0,40}\b(to|at)\b[^.\n]{0,40}(https?://|@\w+\.)", _P)),
]


@dataclass
class InjectionScan:
    score: float = 0.0
    matches: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:  # for direct user input
        return self.score >= 0.8

    @property
    def suspicious(self) -> bool:  # for untrusted document text
        return self.score >= 0.5


def scan(text: str) -> InjectionScan:
    normalized = unicodedata.normalize("NFKC", text)
    hits = [(name, w) for name, w, rx in _PATTERNS if rx.search(normalized)]
    if not hits:
        return InjectionScan()
    top = max(w for _, w in hits)
    score = min(1.0, top + 0.05 * (len(hits) - 1))
    return InjectionScan(score=round(score, 2), matches=[n for n, _ in hits])
