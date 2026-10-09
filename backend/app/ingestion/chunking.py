"""Structure-aware chunking.

Sections (markdown headings / PDF pages) are never merged across boundaries, so a chunk
always has one well-defined heading/page for citation. Within a section, paragraphs are
packed up to `target_chars`; oversized paragraphs are split on sentences; consecutive
chunks of a section share a small sentence-level overlap to preserve context.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..text import estimate_tokens, split_sentences
from .parsing import ParsedDocument


@dataclass
class ChunkDraft:
    index: int
    content: str
    section: str | None
    page: int | None

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.content)


def _pack(units: list[str], target: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for unit in units:
        if cur and cur_len + len(unit) + 1 > target:
            chunks.append("\n".join(cur))
            # carry trailing units as overlap, bounded by `overlap` chars
            carry: list[str] = []
            carried = 0
            for u in reversed(cur):
                if carried + len(u) > overlap:
                    break
                carry.insert(0, u)
                carried += len(u)
            cur, cur_len = carry, carried
        cur.append(unit)
        cur_len += len(unit) + 1
    if cur and (not chunks or "\n".join(cur) != chunks[-1]):
        chunks.append("\n".join(cur))
    return chunks


def chunk_document(doc: ParsedDocument, target_chars: int = 900, overlap_chars: int = 120) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for section in doc.sections:
        units: list[str] = []
        for para in (p.strip() for p in section.text.split("\n\n")):
            if not para:
                continue
            para = " ".join(para.split()) if "\n- " not in para and not para.startswith(("-", "*", "|")) else para
            if len(para) <= target_chars:
                units.append(para)
            else:
                units.extend(split_sentences(para))
        for text in _pack(units, target_chars, overlap_chars):
            drafts.append(ChunkDraft(index=len(drafts), content=text, section=section.heading, page=section.page))
    return drafts
