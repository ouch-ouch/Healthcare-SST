"""Combined-A identity resolution: license attach + name corroboration.

Task 9 adds the Combined-B half of this module.
"""

import sqlite3

from sot.graph import Entity, get_entity, find_entity, create_edge
from sot.flags import create_flag


def _normalize_name(name: str) -> set[str]:
    """Tokenize a name into a lowercase word set, tolerant of 'Last, First' order."""
    return {part.strip().lower() for part in name.replace(",", " ").split() if part.strip()}


def _hr_full_name(emp: Entity) -> str:
    return f"{emp.attrs.get('first_name', '')} {emp.attrs.get('last_name', '')}".strip()


def attach_license(conn: sqlite3.Connection, employee_id: str) -> None:
    """
    Look up the Employee's license_number against License entities, link on match,
    and corroborate identity. Raises a referential_orphan flag if no match exists.
    """
    emp = get_entity(conn, employee_id)
    license_number = emp.attrs.get("license_number")

    lic = find_entity(conn, "License", license_number=license_number) if license_number else None

    if lic is None:
        create_flag(
            conn, employee_id, "referential_orphan", "high",
            f"no License entity found for license_number={license_number!r}"
        )
        return

    create_edge(conn, employee_id, lic.id, "holds_license")
    corroborate_combined_a(conn, employee_id, lic.id)


def corroborate_combined_a(conn: sqlite3.Connection, employee_id: str, license_id: str) -> None:
    """Compare HR's name against the License's name_on_license; flag disagreement."""
    emp = get_entity(conn, employee_id)
    lic = get_entity(conn, license_id)

    hr_name = _hr_full_name(emp)
    license_name = lic.attrs.get("name_on_license", "")

    if _normalize_name(hr_name) != _normalize_name(license_name):
        create_flag(
            conn, employee_id, "identity_ambiguity", "medium",
            f"name mismatch: HR name={hr_name!r} vs license name_on_license={license_name!r}"
        )
