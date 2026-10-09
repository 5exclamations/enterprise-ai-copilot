"""Document parsing: PDF and plain-text/markdown into structured sections."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field


class ParseError(ValueError):
    pass


@dataclass
class Section:
    text: str
    heading: str | None = None
    page: int | None = None


@dataclass
class ParsedDocument:
    sections: list[Section]
    full_text: str
    page_count: int | None = None
    title_hint: str | None = None
    warnings: list[str] = field(default_factory=list)


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")


def detect_kind(filename: str, data: bytes) -> str:
    """Decide by magic bytes first, extension second. Never trust the client content-type."""
    if data[:5] == b"%PDF-":
        return "pdf"
    name = filename.lower()
    if name.endswith(".pdf"):
        raise ParseError("File has a .pdf extension but is not a valid PDF.")
    if name.endswith((".txt", ".md", ".markdown", ".text")):
        return "text"
    raise ParseError("Unsupported file type. Upload a PDF, .txt or .md file.")


def parse_text(data: bytes) -> ParsedDocument:
    if b"\x00" in data[:4096]:
        raise ParseError("File looks binary, not text.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    title_hint = None

    def flush():
        body = "\n".join(buf).strip()
        if body:
            heading = " > ".join(h for _, h in stack) or None
            sections.append(Section(text=body, heading=heading))
        buf.clear()

    for line in text.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            if title_hint is None and level == 1:
                title_hint = title
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        else:
            buf.append(line)
    flush()
    return ParsedDocument(sections=sections, full_text=text, title_hint=title_hint)


def parse_pdf(data: bytes) -> ParsedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError("Encrypted PDFs are not supported.")
        pages = [(i + 1, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages)]
        info_title = (reader.metadata.title if reader.metadata else None) or None
    except ParseError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise ParseError(f"Could not read PDF: {exc}") from exc
    if not any(t for _, t in pages):
        raise ParseError("PDF has no extractable text (scanned images need OCR, which is not supported).")
    sections = [Section(text=t, page=n) for n, t in pages if t]
    first_line = next((ln.strip() for ln in pages[0][1].split("\n") if ln.strip()), None) if pages else None
    return ParsedDocument(
        sections=sections,
        full_text="\n\n".join(t for _, t in pages if t),
        page_count=len(pages),
        title_hint=info_title or first_line,
    )


def parse_document(filename: str, data: bytes) -> ParsedDocument:
    if not data:
        raise ParseError("File is empty.")
    kind = detect_kind(filename, data)
    return parse_pdf(data) if kind == "pdf" else parse_text(data)
