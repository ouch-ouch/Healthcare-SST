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


def parse_shift_cell(cell_text: str) -> tuple[str, str] | None:
    """Parse a shift cell like '7a-3p' to 24-hour format ('07:00', '15:00'), or None for 'OFF'."""
    cell_text = cell_text.strip()
    if cell_text.upper() == "OFF":
        return None

    parts = cell_text.split("-")
    if len(parts) != 2:
        return None

    start_str, end_str = parts
    start_24h = _convert_12h_to_24h(start_str.strip())
    end_24h = _convert_12h_to_24h(end_str.strip())

    return (start_24h, end_24h)


def _convert_12h_to_24h(time_str: str) -> str:
    """Convert '7a', '3p', '11p' to '07:00', '15:00', '23:00' format."""
    time_str = time_str.strip().lower()

    # Determine AM/PM
    is_pm = time_str.endswith("p")
    is_am = time_str.endswith("a")

    # Extract hour
    hour_str = time_str[:-1] if (is_pm or is_am) else time_str
    hour = int(hour_str)

    # Convert to 24-hour format
    if is_pm:
        if hour != 12:
            hour += 12
    elif is_am:
        if hour == 12:
            hour = 0

    return f"{hour:02d}:00"


def compute_daily_hours(start_24h: str, end_24h: str) -> float:
    """Compute hours between two 24-hour times, handling overnight wraparound."""
    # Parse times to minutes since midnight
    start_h, start_m = map(int, start_24h.split(":"))
    end_h, end_m = map(int, end_24h.split(":"))

    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    # Handle overnight wraparound
    minutes_diff = (end_minutes - start_minutes) % (24 * 60)
    hours = minutes_diff / 60

    return hours


def annotate_daily_hours(page: PageTable) -> PageTable:
    """Return a new PageTable with each row annotated with 'hours_by_day' dict."""
    new_rows = []

    for row in page.rows:
        new_row = dict(row)  # Copy the row
        hours_by_day = {}

        # Iterate through all keys except Staff and Role
        for day_key, cell_value in row.items():
            if day_key not in ("Staff", "Role"):
                # Parse the shift cell
                parsed = parse_shift_cell(cell_value)
                if parsed is None:
                    hours_by_day[day_key] = 0.0
                else:
                    start_24h, end_24h = parsed
                    hours = compute_daily_hours(start_24h, end_24h)
                    hours_by_day[day_key] = hours

        new_row["hours_by_day"] = hours_by_day
        new_rows.append(new_row)

    return PageTable(
        facility_name=page.facility_name,
        rows=new_rows,
        raw_text=page.raw_text,
    )


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
