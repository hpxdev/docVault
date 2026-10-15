"""Write the committed sample documents (self-written, known facts) used by the README
walkthrough and the demo:
    docker compose -f compose.test.yml run --rm tests python -m tests.make_samples
then copy backend/tests/.generated/samples/* to samples/.
"""

from pathlib import Path

from tests import fixtures
from tests.live.eval_set import PAGES, make_eval_pdf

# Revised brief for the versions demo: known changes on pages 1, 3 and 4; pages 2, 5, 6 unchanged.
BRIEF_V2_CHANGES = {
    "Northwind Solar Farm - Project Brief": (
        "Northwind Solar Farm - Project Brief (revised May 2026)"
    ),
    "The total capital budget is 41.5 million euros.": (
        "The total capital budget is 44.0 million euros."
    ),
    "The steering committee approved the budget on 4 March 2026.": (
        "The steering committee approved the revised budget on 12 May 2026."
    ),
    "A contingency reserve of 3.2 million euros is included in the total.": (
        "A contingency reserve of 3.6 million euros is included in the total."
    ),
    "Construction is planned to start in June 2026.": (
        "Construction is planned to start in September 2026."
    ),
    "Grid connection is targeted for the second quarter of 2027.": (
        "Grid connection is targeted for the fourth quarter of 2027."
    ),
}


def brief_v2_pages() -> dict[int, list[str]]:
    return {n: [BRIEF_V2_CHANGES.get(line, line) for line in lines] for n, lines in PAGES.items()}


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
    (out / "northwind-brief-v2.pdf").write_bytes(make_eval_pdf(brief_v2_pages()))
    (out / "employee-handbook.docx").write_bytes(fixtures.make_docx())
    (out / "onboarding-guide.md").write_text(ONBOARDING, encoding="utf-8")
    (out / "not-a-document.exe").write_bytes(b"MZ\x90\x00\x03\x00\x00\x00" + bytes(range(256)) * 4)
    print(f"wrote samples to {out}")


if __name__ == "__main__":
    main()
