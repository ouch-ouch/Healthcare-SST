"""Schedule PDF adapter: extracts per-page staff/day tables and resolves facility."""

import sqlite3
from dataclasses import dataclass, field

import pdfplumber

from sot.graph import create_entity, find_entity
from sot.flags import create_flag


@dataclass
class PageTable:
    """One PDF page's extracted schedule grid plus resolved facility."""
    facility_name: str | None
    rows: list[dict] = field(default_factory=list)
    raw_text: str = ""


# extract_pages has no `conn` (its signature is pdf_path -> list[PageTable]), so
# the known Facility names are hardcoded here rather than queried. This matches
# the fixed, pre-seeded pair from init_db (Task 1) — if that set ever grows or
# becomes dynamic, this needs a conn-aware lookup instead.
_KNOWN_FACILITY_NAMES = ("Harborview Bayside", "Harborview Riverdale")


def _match_facility_name(text: str) -> str | None:
    """Return the known Facility name found anywhere in text (case-insensitive), else None."""
    lowered = text.lower()
    for name in _KNOWN_FACILITY_NAMES:
        if name.lower() in lowered:
            return name
    return None


def extract_pages(pdf_path: str) -> list[PageTable]:
    """Extract one PageTable per page of the schedule PDF."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            raw_text = page.extract_text() or ""
            facility_name = _match_facility_name(raw_text)

            table = page.extract_table()
            rows = []
            if table:
                header, *body = table
                for raw_row in body:
                    rows.append(dict(zip(header, raw_row)))

            pages.append(PageTable(facility_name=facility_name, rows=rows, raw_text=raw_text))

    return pages


def store_schedule_batch(conn: sqlite3.Connection, page: PageTable) -> None:
    """Store each row of a PageTable as a ShiftAssignment entity, linked or held by facility."""
    facility = None
    if page.facility_name is not None:
        facility = find_entity(conn, "Facility", name=page.facility_name)

    facility_id = facility.id if facility else None
    batch_status = "linked" if facility_id else "held"

    for i, row in enumerate(page.rows):
        shifts = {k: v for k, v in row.items() if k not in ("Staff", "Role")}
        attrs = {
            "staff_name": row["Staff"],
            "role": row["Role"],
            "shifts": shifts,
            "facility_id": facility_id,
            "batch_status": batch_status,
        }
        entity_id = create_entity(conn, "ShiftAssignment", attrs)

        if batch_status == "held" and i == 0:
            create_flag(
                conn,
                entity_id,
                "data_source_anomaly",
                "medium",
                f"Unresolved facility on schedule page: {page.facility_name!r}",
            )
