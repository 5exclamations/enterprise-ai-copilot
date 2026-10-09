"""Input validation and the structured-output contract."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")

SKU_PATTERN = r"^[A-Z]{2}-\d{4}$"
ORDER_PATTERN = r"^SO-\d{5}$"


class InputRejected(ValueError):
    pass


def sanitize_user_text(text: str, max_chars: int) -> str:
    """Normalise and bound untrusted user text. Strips control / bidi-override characters."""
    if not isinstance(text, str):
        raise InputRejected("Message must be a string.")
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL_RE.sub("", text).strip()
    if not text:
        raise InputRejected("Message is empty.")
    if len(text) > max_chars:
        raise InputRejected(f"Message too long ({len(text)} > {max_chars} characters).")
    return text


class AssistantAnswer(BaseModel):
    """Contract every model response must satisfy before it reaches the user."""

    answer: str = Field(min_length=1, max_length=6000)
    citations: list[str] = Field(default_factory=list, max_length=20)
    confidence: Literal["high", "medium", "low"] = "medium"

    @field_validator("citations")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


def extract_json_object(raw: str) -> dict:
    """Parse a JSON object from model text, tolerating code fences / surrounding prose."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise
        obj = json.loads(raw[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object")
    return obj


def parse_answer(raw: str) -> AssistantAnswer:
    try:
        return AssistantAnswer.model_validate(extract_json_object(raw))
    except (ValueError, ValidationError) as exc:
        raise ValueError(str(exc)) from exc
