"""Live evaluation set: a self-written 6-page PDF with known facts on known pages, plus 10
questions (7 answerable with expected page and key phrase, 3 unanswerable → not_found)."""

import io
from dataclasses import dataclass

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PAGES: dict[int, list[str]] = {
    1: [
        "Northwind Solar Farm - Project Brief",
        "This brief summarises the Northwind Solar Farm project for the steering committee.",
        "The project is sponsored by the Halden County Energy Cooperative.",
        "The site is located 12 kilometres north of the town of Marlow.",
    ],
    2: [
        "2. Capacity and technology",
        "The farm will have an installed capacity of 48 megawatts.",
        "It will use 96,000 bifacial panels mounted on single-axis trackers.",
        "Expected annual generation is 82 gigawatt-hours.",
    ],
    3: [
        "3. Budget",
        "The total capital budget is 41.5 million euros.",
        "The steering committee approved the budget on 4 March 2026.",
        "A contingency reserve of 3.2 million euros is included in the total.",
    ],
    4: [
        "4. Schedule",
        "Construction is planned to start in June 2026.",
        "Grid connection is targeted for the second quarter of 2027.",
        "The main construction contractor is Brightline Builders.",
    ],
    5: [
        "5. Environment",
        "A 15-metre hedgerow buffer will surround the site to protect local wildlife.",
        "Sheep grazing will be used to manage vegetation between panel rows.",
    ],
    6: [
        "6. Community",
        "Residents of Marlow will receive a 10 percent discount on electricity tariffs.",
        "A community fund will receive 50,000 euros per year from project revenue.",
    ],
}


@dataclass(frozen=True)
class Question:
    text: str
    expected_page: int | None  # None → unanswerable, expect not_found
    key_phrase: str | None


QUESTIONS = [
    Question("What is the installed capacity of the Northwind Solar Farm?", 2, "48"),
    Question("What is the total capital budget?", 3, "41.5"),
    Question("When did the steering committee approve the budget?", 3, "4 March 2026"),
    Question("Who is the main construction contractor?", 4, "Brightline"),
    Question("How large is the contingency reserve?", 3, "3.2"),
    Question("How will vegetation between the panel rows be managed?", 5, "sheep"),
    Question("What discount will Marlow residents receive?", 6, "10"),
    Question("Who is the chief financial officer of the cooperative?", None, None),
    Question("What is the expected internal rate of return of the project?", None, None),
    Question("How many wind turbines will be installed at the site?", None, None),
]


def make_eval_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for number in sorted(PAGES):
        y = 800
        for line in PAGES[number]:
            c.drawString(60, y, line)
            y -= 20
        c.showPage()
    c.save()
    return buf.getvalue()
