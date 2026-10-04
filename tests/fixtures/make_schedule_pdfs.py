"""One-off script to generate the Schedule PDF fixtures used by test_schedule_extraction.py.

Not part of the shipped package — run once locally to (re)produce:
    tests/fixtures/schedule_sample.pdf
    tests/fixtures/schedule_unknown_facility.pdf

Usage:
    .venv/bin/python tests/fixtures/make_schedule_pdfs.py
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

HEADER = ["Staff", "Role", "Mon 09/14", "Tue 09/15"]
ROWS = [
    ["Sofia Reyes", "RN", "7a-3p", "OFF"],
    ["Marc Bell", "LPN", "3p-11p", "7a-3p"],
]


def make_pdf(path: str, facility_heading: str) -> None:
    doc = SimpleDocTemplate(path, pagesize=letter)
    styles = getSampleStyleSheet()
    table = Table([HEADER] + ROWS)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    story = [
        Paragraph(f"Schedule: {facility_heading}", styles["Title"]),
        Spacer(1, 12),
        table,
    ]
    doc.build(story)


if __name__ == "__main__":
    make_pdf("tests/fixtures/schedule_sample.pdf", "Harborview Bayside")
    make_pdf("tests/fixtures/schedule_unknown_facility.pdf", "Unit 7")
    print("wrote tests/fixtures/schedule_sample.pdf and tests/fixtures/schedule_unknown_facility.pdf")
