"""CLI orchestration layer: ties ingestion, resolution, combining, and flag review together."""

import csv
import json
import pathlib
import sqlite3

from rapidfuzz import fuzz

from sot.graph import Entity, get_entity, neighbors
from sot.adapters.hr import ingest_hr_roster
from sot.adapters.licenses import ingest_licenses
from sot.adapters.payroll import ingest_payroll
from sot.adapters.schedule import extract_pages, annotate_daily_hours, store_schedule_batch
from sot.resolver import attach_license, attach_payroll_or_shift_fact
from sot.combiner import build_combined_a, build_combined_b
from sot.flags import open_flags_grouped_by_entity, resolve_flag

_FUZZY_NAME_THRESHOLD = 85

_FACT_TYPES = ("PayrollRecord", "ShiftAssignment")


def _entities_of_type(conn: sqlite3.Connection, type: str) -> list[Entity]:
    """All entities of a given type. CLI-local counterpart of the test-only helper
    in tests/conftest.py (find_entity only finds one match at a time)."""
    cursor = conn.execute("SELECT id, type, attrs FROM entities WHERE type = ?", (type,))
    return [Entity(id=row[0], type=row[1], attrs=json.loads(row[2])) for row in cursor.fetchall()]


def _rescan(conn: sqlite3.Connection) -> None:
    """Full idempotent rescan: link whatever can now be linked, then rebuild Combined A/B.

    Simple on purpose -- small data volumes, every step here is safe to repeat.
    """
    for emp in _entities_of_type(conn, "Employee"):
        if not neighbors(conn, emp.id, "holds_license"):
            attach_license(conn, emp.id)

    for fact_type in _FACT_TYPES:
        for fact in _entities_of_type(conn, fact_type):
            if fact.attrs.get("employee_id") is None:
                attach_payroll_or_shift_fact(conn, fact.id, fact_type)

    for emp in _entities_of_type(conn, "Employee"):
        build_combined_a(conn, emp.id)

    for fact_type in _FACT_TYPES:
        for fact in _entities_of_type(conn, fact_type):
            if fact.attrs.get("employee_id") is not None:
                build_combined_b(conn, fact.id, fact_type)


def ingest(conn: sqlite3.Connection, file_path: str) -> None:
    """Sniff file_path's type, run the matching adapter, then do a full rescan."""
    path = pathlib.Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        for page in extract_pages(file_path):
            store_schedule_batch(conn, annotate_daily_hours(page))
    elif suffix == ".csv":
        with open(file_path, newline="") as f:
            header_row = next(csv.reader(f), None)

        if header_row is None:
            raise ValueError(f"Unrecognized CSV header in {file_path!r}: empty file")

        header = set(header_row)

        if "employee_id" in header:
            ingest_hr_roster(conn, file_path)
        elif "payroll_id" in header:
            ingest_payroll(conn, file_path)
        elif "license_number" in header:
            ingest_licenses(conn, file_path)
        else:
            raise ValueError(f"Unrecognized CSV header in {file_path!r}: {header}")
    else:
        raise ValueError(f"Unsupported file type: {file_path!r}")

    _rescan(conn)


def list_open_flags(conn: sqlite3.Connection) -> str:
    """Format open_flags_grouped_by_entity into readable text, one block per entity."""
    grouped = open_flags_grouped_by_entity(conn)
    if not grouped:
        return "No open flags."

    blocks = []
    for entity_id, flags in grouped.items():
        entity = get_entity(conn, entity_id)
        label = entity.attrs.get("display_name") if entity else None
        header = f"{entity.type} {entity_id}" if entity else entity_id
        if label:
            header += f" ({label})"

        lines = [header]
        for flag in flags:
            lines.append(f"  [{flag.severity}] {flag.flag_type}: {flag.reason}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def show_employee(conn: sqlite3.Connection, name: str) -> str:
    """Fuzzy/substring look up an Employee by name; report status, license, and linked facts."""
    employees = _entities_of_type(conn, "Employee")
    name_lower = name.lower()

    def display_of(emp: Entity) -> str:
        return emp.attrs.get("display_name") or f"{emp.attrs.get('first_name', '')} {emp.attrs.get('last_name', '')}".strip()

    match = next((emp for emp in employees if name_lower in display_of(emp).lower()), None)

    if match is None and employees:
        scored = [(fuzz.token_sort_ratio(display_of(emp).lower(), name_lower), emp) for emp in employees]
        best_score, best_emp = max(scored, key=lambda pair: pair[0])
        if best_score >= _FUZZY_NAME_THRESHOLD:
            match = best_emp

    if match is None:
        return f"No employee found matching {name!r}."

    lines = [
        f"Employee: {display_of(match)}",
        f"Status: {match.attrs.get('status', 'unknown')}",
    ]

    licenses = neighbors(conn, match.id, "holds_license")
    if licenses:
        lic = licenses[0]
        lines.append(
            f"License: {lic.attrs.get('license_number')} "
            f"({lic.attrs.get('license_type')}), expires {lic.attrs.get('expiration_date')}"
        )
    else:
        lines.append("License: none linked")

    for payroll in neighbors(conn, match.id, "paid_for"):
        lines.append(f"Payroll {payroll.attrs.get('payroll_id')}: payroll_status={payroll.attrs.get('payroll_status')}")

    for shift in neighbors(conn, match.id, "worked_shift"):
        lines.append(f"Shift (facility_id={shift.attrs.get('facility_id')}): payroll_status={shift.attrs.get('payroll_status')}")

    return "\n".join(lines)


def resolve_flag_cmd(conn: sqlite3.Connection, flag_id: str, resolved_by: str, resolution: str) -> None:
    """Thin wrapper over flags.resolve_flag."""
    resolve_flag(conn, flag_id, resolved_by, resolution)


if __name__ == "__main__":
    import argparse

    from sot.db import init_db

    parser = argparse.ArgumentParser(prog="sot", description="Harborview SOT CLI")
    parser.add_argument("--db", default="harborview.db", help="Path to the SQLite database file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest an HR/Licenses/Payroll CSV or Schedule PDF")
    ingest_parser.add_argument("path")

    subparsers.add_parser("flags", help="List all open flags grouped by entity")

    employee_parser = subparsers.add_parser("employee", help="Look up an Employee by name")
    employee_parser.add_argument("name")

    resolve_parser = subparsers.add_parser("resolve", help="Resolve an open flag")
    resolve_parser.add_argument("flag_id")
    resolve_parser.add_argument("resolved_by")
    resolve_parser.add_argument("resolution")

    args = parser.parse_args()
    db_conn = init_db(args.db)

    if args.command == "ingest":
        ingest(db_conn, args.path)
        print(f"Ingested {args.path}")
    elif args.command == "flags":
        print(list_open_flags(db_conn))
    elif args.command == "employee":
        print(show_employee(db_conn, args.name))
    elif args.command == "resolve":
        resolve_flag_cmd(db_conn, args.flag_id, args.resolved_by, args.resolution)
        print(f"Resolved flag {args.flag_id}")
