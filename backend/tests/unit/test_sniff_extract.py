import io
import zipfile

import pytest

from app.services.extraction import decode_text, extract
from app.services.sniff import sniff
from app.services.stage_errors import StageError
from tests import fixtures


def _write(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("report.pdf", fixtures.five_page_pdf(), "pdf"),
        ("renamed.txt", fixtures.five_page_pdf(), "pdf"),  # bytes win over the extension
        ("handbook.docx", fixtures.make_docx(), "docx"),
        ("guide.md", fixtures.MARKDOWN.encode(), "md"),
        ("notes.txt", b"plain text\n", "txt"),
    ],
)
def test_sniff_detects_type_from_bytes(tmp_path, name, data, expected):
    assert sniff(_write(tmp_path, name, data), name).file_type == expected


def test_sniff_rejects_binary_and_non_docx_zip(tmp_path):
    exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff" + bytes(range(256)) * 4
    assert sniff(_write(tmp_path, "setup.pdf", exe), "setup.pdf") is None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hi")
    assert sniff(_write(tmp_path, "a.docx", buf.getvalue()), "a.docx") is None


def test_pdf_pages_have_truthful_locators(tmp_path):
    result = extract(_write(tmp_path, "a.pdf", fixtures.five_page_pdf()), "pdf", 300)
    assert result.page_count == 5
    assert [s.locator for s in result.segments] == [
        {"type": "page", "page": n} for n in range(1, 6)
    ]
    assert "4.2 million" in result.segments[2].text
    assert all("4.2 million" not in s.text for i, s in enumerate(result.segments) if i != 2)
    assert result.warnings == []


def test_pdf_empty_pages_warning(tmp_path):
    data = fixtures.make_pdf(4, blank_pages={2, 4})
    result = extract(_write(tmp_path, "a.pdf", data), "pdf", 300)
    assert result.warnings == [{"code": "EMPTY_PAGES", "pages": [2, 4]}]


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (fixtures.make_pdf(2, encrypt_password="s3cret"), "ENCRYPTED_DOCUMENT"),
        (fixtures.make_image_only_pdf(), "NO_EXTRACTABLE_TEXT"),
        (fixtures.make_pdf(301), "PAGE_LIMIT_EXCEEDED"),
        (b"%PDF-1.7\n this is not really a pdf \x00\x01\x02", "CORRUPT_DOCUMENT"),
    ],
)
def test_pdf_failure_codes(tmp_path, data, code):
    with pytest.raises(StageError) as err:
        extract(_write(tmp_path, "x.pdf", data), "pdf", 300)
    assert err.value.code == code


def test_scanned_message_says_ocr_unsupported(tmp_path):
    with pytest.raises(StageError) as err:
        extract(_write(tmp_path, "x.pdf", fixtures.make_image_only_pdf()), "pdf", 300)
    assert "OCR is not supported" in err.value.message


def test_docx_sections_by_heading_without_pages(tmp_path):
    result = extract(_write(tmp_path, "h.docx", fixtures.make_docx()), "docx", 300)
    headings = [s.locator["heading"] for s in result.segments]
    assert headings == ["Employee Handbook", "Leave Policy", "Remote Work"]
    assert all(s.locator["type"] == "section" and "page" not in s.locator for s in result.segments)
    assert [s.locator["index"] for s in result.segments] == [1, 2, 3]
    assert "27 days" in result.segments[1].text
    assert "Home office | 450 EUR" in result.segments[2].text  # tables are kept
    assert result.page_count is None


def test_docx_corrupt(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<not-xml")
    with pytest.raises(StageError) as err:
        extract(_write(tmp_path, "c.docx", buf.getvalue()), "docx", 300)
    assert err.value.code == "CORRUPT_DOCUMENT"


def test_markdown_heading_paths_ignore_code_fences(tmp_path):
    result = extract(_write(tmp_path, "g.md", fixtures.MARKDOWN.encode()), "md", 300)
    paths = [s.locator["heading_path"] for s in result.segments]
    assert paths == [
        ["Onboarding Guide"],
        ["Onboarding Guide", "Accounts"],
        ["Onboarding Guide", "Deployments"],
        ["Onboarding Guide", "Deployments", "Staging"],
    ]
    staging = result.segments[-1]
    assert "Tuesday at 14:00" in staging.text
    assert staging.locator["line_start"] < staging.locator["line_end"]


def test_text_line_ranges(tmp_path):
    result = extract(_write(tmp_path, "t.txt", fixtures.TEXT.encode()), "txt", 300)
    locs = [s.locator for s in result.segments]
    assert locs[0]["type"] == "lines" and locs[0]["start"] == 1
    assert locs[-1]["end"] == 100
    for a, b in zip(locs, locs[1:], strict=False):
        assert b["start"] == a["end"] + 1
    last = result.segments[-1]
    assert "station 7" in last.text


def test_text_encodings():
    assert decode_text("café".encode()) == "café"
    assert decode_text(b"\xef\xbb\xbfhello") == "hello"
    assert decode_text("naïve".encode("cp1252")) == "naïve"
    for bad in ("hi".encode("utf-16"), b"\x81\x8d\x8f\x90\x9d"):
        with pytest.raises(StageError) as err:
            decode_text(bad)
        assert err.value.code == "UNSUPPORTED_ENCODING"
