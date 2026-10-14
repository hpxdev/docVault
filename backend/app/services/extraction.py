"""Text extraction into segments with truthful locators.

- PDF: one segment per physical page, `{type: "page", page: N}` (1-based; printed labels ignored).
- DOCX: one per heading section,
  `{type: "section", heading, index, paragraph_start, paragraph_end}`.
  DOCX has no reliable page numbers, so none are invented.
- MD: one per ATX heading section, with the heading path.
- TXT: one per line range, `{type: "lines", start, end}` (1-based, inclusive).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.stage_errors import StageError

# A page with fewer non-whitespace characters than this is treated as having no text layer.
MIN_PAGE_CHARS = 10
TXT_TARGET_LINES = 40
TXT_MAX_LINES = 60


@dataclass
class Segment:
    locator: dict[str, Any]
    text: str


@dataclass
class ExtractionResult:
    segments: list[Segment]
    page_count: int | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _has_text(text: str) -> bool:
    return len(re.sub(r"\s+", "", text)) >= MIN_PAGE_CHARS


# ---------------------------------------------------------------- PDF


def extract_pdf(path: Path, max_pages: int) -> ExtractionResult:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        encrypted = reader.is_encrypted
    except Exception as exc:  # pypdf raises many types for damaged files
        name = "PdfReadError" if isinstance(exc, PdfReadError) else type(exc).__name__
        raise StageError("CORRUPT_DOCUMENT", f"The PDF could not be parsed ({name}).") from exc

    if encrypted:
        try:
            # Owner-password-only PDFs open with an empty user password; real protection doesn't.
            decrypted = bool(reader.decrypt(""))
        except Exception:
            decrypted = False
        if not decrypted:
            raise StageError(
                "ENCRYPTED_DOCUMENT",
                "The PDF is password-protected. Remove the password and upload it again.",
            )

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise StageError(
            "CORRUPT_DOCUMENT", f"The PDF page tree is unreadable ({type(exc).__name__})."
        ) from exc
    if page_count > max_pages:
        raise StageError(
            "PAGE_LIMIT_EXCEEDED",
            f"The PDF has {page_count} pages; the limit is {max_pages}.",
        )
    if page_count == 0:
        raise StageError("CORRUPT_DOCUMENT", "The PDF has no pages.")

    segments: list[Segment] = []
    empty_pages: list[int] = []
    for number in range(1, page_count + 1):
        try:
            text = _clean(reader.pages[number - 1].extract_text() or "")
        except Exception:
            text = ""
        if not _has_text(text):
            empty_pages.append(number)
        segments.append(Segment({"type": "page", "page": number}, text))

    if len(empty_pages) == page_count:
        raise StageError(
            "NO_EXTRACTABLE_TEXT",
            "No text layer found: the PDF appears to be scanned or image-only. "
            "OCR is not supported in this version.",
        )
    warnings = [{"code": "EMPTY_PAGES", "pages": empty_pages}] if empty_pages else []
    return ExtractionResult(segments, page_count=page_count, warnings=warnings)


# ---------------------------------------------------------------- DOCX


def _is_heading(paragraph: Any) -> bool:
    try:
        name = (paragraph.style.name or "") if paragraph.style is not None else ""
    except Exception:
        return False
    return name.startswith("Heading") or name == "Title"


def extract_docx(path: Path) -> ExtractionResult:
    import docx
    from docx.table import Table

    try:
        document = docx.Document(str(path))
        blocks = list(document.iter_inner_content())
    except Exception as exc:
        raise StageError(
            "CORRUPT_DOCUMENT", f"The DOCX could not be parsed ({type(exc).__name__})."
        ) from exc

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] = {"heading": None, "lines": [], "start": 1, "end": 0}
    for block_index, block in enumerate(blocks, start=1):
        if isinstance(block, Table):
            rows = []
            for row in block.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            text = "\n".join(rows)
            heading = False
        else:
            text = block.text.strip()
            heading = bool(text) and _is_heading(block)
        if heading:
            if current["lines"] or current["heading"]:
                sections.append(current)
            current = {"heading": text, "lines": [text], "start": block_index, "end": block_index}
            continue
        if text:
            current["lines"].append(text)
            current["end"] = block_index
    if current["lines"] or current["heading"]:
        sections.append(current)

    segments = []
    for index, sec in enumerate(sections, start=1):
        locator = {
            "type": "section",
            "heading": sec["heading"],
            "index": index,
            "paragraph_start": sec["start"],
            "paragraph_end": max(sec["start"], sec["end"]),
        }
        segments.append(Segment(locator, _clean("\n".join(sec["lines"]))))
    if not any(_has_text(s.text) for s in segments):
        raise StageError("NO_EXTRACTABLE_TEXT", "The DOCX contains no text.")
    return ExtractionResult(segments)


# ---------------------------------------------------------------- text formats


def decode_text(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise StageError(
            "UNSUPPORTED_ENCODING",
            "UTF-16/UTF-32 text is not supported. Save the file as UTF-8 and upload it again.",
        )
    for encoding in ("utf-8", "cp1252"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            break
        return text
    raise StageError(
        "UNSUPPORTED_ENCODING",
        "The text is not valid UTF-8, UTF-8 with BOM or Windows-1252.",
    )


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def extract_markdown(text: str) -> ExtractionResult:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[dict[str, Any]] = []
    path: list[tuple[int, str]] = []
    current: dict[str, Any] = {"heading": None, "path": [], "start": 1, "lines": []}
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _MD_HEADING.match(line)
        if match:
            if any(x.strip() for x in current["lines"]) or current["heading"]:
                current["end"] = number - 1
                sections.append(current)
            level, title = len(match.group(1)), match.group(2).strip()
            path = [p for p in path if p[0] < level] + [(level, title)]
            current = {"heading": title, "path": [p[1] for p in path], "start": number, "lines": []}
        current["lines"].append(line)
    if any(x.strip() for x in current["lines"]) or current["heading"]:
        current["end"] = len(lines)
        sections.append(current)

    segments = []
    for index, sec in enumerate(sections, start=1):
        locator = {
            "type": "section",
            "heading": sec["heading"],
            "heading_path": sec["path"],
            "index": index,
            "line_start": sec["start"],
            "line_end": max(sec["start"], sec["end"]),
        }
        segments.append(Segment(locator, _clean("\n".join(sec["lines"]))))
    if not any(_has_text(s.text) for s in segments):
        raise StageError("NO_EXTRACTABLE_TEXT", "The Markdown file contains no text.")
    return ExtractionResult(segments)


def extract_plain_text(text: str) -> ExtractionResult:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    segments = []
    start = 1
    buffer: list[str] = []
    for number, line in enumerate(lines, start=1):
        buffer.append(line)
        size = len(buffer)
        if (size >= TXT_TARGET_LINES and not line.strip()) or size >= TXT_MAX_LINES:
            segments.append(
                Segment({"type": "lines", "start": start, "end": number}, _clean("\n".join(buffer)))
            )
            start, buffer = number + 1, []
    if buffer:
        segments.append(
            Segment({"type": "lines", "start": start, "end": len(lines)}, _clean("\n".join(buffer)))
        )
    segments = [s for s in segments if s.text]
    if not any(_has_text(s.text) for s in segments):
        raise StageError("NO_EXTRACTABLE_TEXT", "The text file contains no text.")
    return ExtractionResult(segments)


def extract(path: Path, file_type: str, max_pages: int) -> ExtractionResult:
    if file_type == "pdf":
        return extract_pdf(path, max_pages)
    if file_type == "docx":
        return extract_docx(path)
    if file_type in ("md", "txt"):
        text = decode_text(path.read_bytes())
        return extract_markdown(text) if file_type == "md" else extract_plain_text(text)
    raise StageError("UNSUPPORTED_FILE_TYPE", f"Unsupported file type: {file_type}")
