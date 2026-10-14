"""Write the generated fixtures to disk for manual/API checks:
docker compose -f compose.test.yml run --rm tests python -m tests.make_fixtures
"""

import sys
from pathlib import Path

from tests import fixtures


def main(out_dir: str = "tests/.generated") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "falcon-5-pages.pdf": fixtures.five_page_pdf(),
        "heron-120-pages.pdf": fixtures.long_pdf(120),
        "handbook.docx": fixtures.make_docx(),
        "onboarding.md": fixtures.MARKDOWN.encode(),
        "maintenance.txt": fixtures.TEXT.encode(),
        "encrypted.pdf": fixtures.make_pdf(2, encrypt_password="s3cret"),
        "scanned-image-only.pdf": fixtures.make_image_only_pdf(),
        "corrupt.pdf": b"%PDF-1.4\nthis file is damaged\n",
        "too-many-pages-301.pdf": fixtures.make_pdf(301),
        "supplier-injection.pdf": fixtures.injection_pdf(),
        "renamed-binary.pdf": b"MZ\x90\x00" + bytes(range(256)) * 8,
        "empty.txt": b"",
        "utf16.txt": "hello in utf-16".encode("utf-16"),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
    print(f"wrote {len(files)} files to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
