"""Detect file type from content bytes (never trust the extension alone)."""

import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SniffResult:
    file_type: str  # pdf | docx | md | txt
    mime_type: str
    ext: str


MD_EXTENSIONS = {".md", ".markdown"}
_TEXT_SAMPLE = 64 * 1024


def _looks_like_text(sample: bytes) -> bool:
    if b"\x00" in sample:
        return False
    # Reject if too many control bytes (other than tab/newline/carriage return/form feed).
    controls = sum(1 for b in sample if b < 32 and b not in (9, 10, 12, 13))
    return controls <= max(1, len(sample) // 200)


def sniff(path: Path, filename: str) -> SniffResult | None:
    """Return the detected type, or None if unsupported."""
    with path.open("rb") as f:
        head = f.read(_TEXT_SAMPLE)
    if head.startswith(b"%PDF-") or b"%PDF-" in head[:1024]:
        return SniffResult("pdf", "application/pdf", "pdf")
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names:
            return SniffResult(
                "docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "docx",
            )
        return None
    # UTF-16/32 byte-order marks: text, but not an encoding we support. Accept as txt so the
    # extraction stage can report UNSUPPORTED_ENCODING with a clear message.
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return SniffResult("txt", "text/plain", "txt")
    if _looks_like_text(head):
        if Path(filename).suffix.lower() in MD_EXTENSIONS:
            return SniffResult("md", "text/markdown", "md")
        return SniffResult("txt", "text/plain", "txt")
    return None
