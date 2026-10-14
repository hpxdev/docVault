"""Write the committed sample documents (self-written, known facts) used by the README
walkthrough and the demo:
    docker compose -f compose.test.yml run --rm tests python -m tests.make_samples
then copy backend/tests/.generated/samples/* to samples/.
"""

from pathlib import Path

from tests import fixtures
from tests.live.eval_set import make_eval_pdf

ONBOARDING = """# Onboarding Guide

Welcome to the Northwind engineering team. This guide covers your first week.

## Accounts

Request your laptop from IT on day one. The VPN client is called Tunnelbear-X.
Your manager will add you to the on-call rota after 30 days.

## Deployments

### Staging

Deploys to staging happen every Tuesday at 14:00 UTC.

### Production

Production deploys need two approvals and are frozen during the last week of each quarter.
"""


def main() -> None:
    out = Path("tests/.generated/samples")
    out.mkdir(parents=True, exist_ok=True)
    (out / "northwind-brief.pdf").write_bytes(make_eval_pdf())
    (out / "employee-handbook.docx").write_bytes(fixtures.make_docx())
    (out / "onboarding-guide.md").write_text(ONBOARDING, encoding="utf-8")
    (out / "not-a-document.exe").write_bytes(b"MZ\x90\x00\x03\x00\x00\x00" + bytes(range(256)) * 4)
    print(f"wrote samples to {out}")


if __name__ == "__main__":
    main()
