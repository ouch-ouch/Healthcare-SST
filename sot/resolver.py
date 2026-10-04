"""Combined-A identity resolution: license attach + name corroboration.

Task 9 adds the Combined-B half of this module.
"""

import json
import sqlite3
from typing import Literal, Optional

from rapidfuzz import fuzz

from sot.graph import Entity, get_entity, find_entity, create_edge, update_entity_attrs, neighbors, create_entity, remove_edge
from sot.flags import create_flag
from sot.facilities import normalize_facility

_FUZZY_MATCH_THRESHOLD = 85


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


# --- Combined B: identity resolution for Payroll/Schedule facts against Combined A ---


def _all_employees(conn: sqlite3.Connection) -> list[Entity]:
    """All Employee entities regardless of status (a fact can arrive before SST approval)."""
    cursor = conn.execute("SELECT id, type, attrs FROM entities WHERE type = 'Employee'")
    return [Entity(id=row[0], type=row[1], attrs=json.loads(row[2])) for row in cursor.fetchall()]


def _fuzzy_key(name: str) -> str:
    """Lowercase and strip commas so 'REYES, SOFIA' and 'Sofia Reyes' score as equal tokens."""
    return name.replace(",", " ").lower()


def _best_name_match(
    conn: sqlite3.Connection, fact_entity_id: str, candidates: list[Entity], fact_name: str
) -> Optional[Entity]:
    """Return the top fuzzy-matching candidate, or None if below threshold or tied.

    A genuine tie (the highest score shared by 2+ candidates) is an identity_ambiguity,
    not a silent pick -- flags on fact_entity_id and returns None.
    """
    fact_key = _fuzzy_key(fact_name)
    scored = [(fuzz.token_sort_ratio(_fuzzy_key(_hr_full_name(emp)), fact_key), emp) for emp in candidates]

    if not scored:
        return None

    best_score = max(score for score, _ in scored)
    if best_score < _FUZZY_MATCH_THRESHOLD:
        return None

    tied = [emp for score, emp in scored if score == best_score]
    if len(tied) > 1:
        names = ", ".join(_hr_full_name(emp) for emp in tied)
        create_flag(
            conn, fact_entity_id, "identity_ambiguity", "medium",
            f"fuzzy-match tie: candidates [{names}] all scored {best_score} against {fact_name!r}"
        )
        return None

    return tied[0]


def resolve_payroll_employee(conn: sqlite3.Connection, payroll_record_id: str) -> Optional[str]:
    """Fuzzy-match a PayrollRecord's employee_name + facility_code against Employee entities."""
    record = get_entity(conn, payroll_record_id)
    facility = normalize_facility(record.attrs.get("facility_code"))

    candidates = [
        emp for emp in _all_employees(conn)
        if normalize_facility(emp.attrs.get("facility")) == facility
    ]

    match = _best_name_match(conn, payroll_record_id, candidates, record.attrs.get("employee_name", ""))
    return match.id if match else None


def resolve_schedule_employee(conn: sqlite3.Connection, shift_assignment_id: str) -> Optional[str]:
    """Fuzzy-match a ShiftAssignment's staff_name against Employee entities, scoped by facility_id."""
    shift = get_entity(conn, shift_assignment_id)
    facility_id = shift.attrs.get("facility_id")

    if facility_id is None:
        # The page's facility didn't resolve (held page) -- can't scope, fuzzy-match by name alone.
        candidates = _all_employees(conn)
    else:
        candidates = []
        for emp in _all_employees(conn):
            fac_name = normalize_facility(emp.attrs.get("facility"))
            fac = find_entity(conn, "Facility", name=fac_name) if fac_name else None
            if fac is not None and fac.id == facility_id:
                candidates.append(emp)

    match = _best_name_match(conn, shift_assignment_id, candidates, shift.attrs.get("staff_name", ""))
    return match.id if match else None


def corroborate_combined_b(conn: sqlite3.Connection, employee_id: str, role_code_a: str, role_code_b: str) -> bool:
    """Compare Payroll job_code against Schedule role; flag disagreement."""
    if role_code_a != role_code_b:
        create_flag(
            conn, employee_id, "identity_ambiguity", "medium",
            f"role_code mismatch: {role_code_a!r} vs {role_code_b!r}"
        )
        return False
    return True


_FACT_EDGE_TYPE = {
    "PayrollRecord": "paid_for",
    "ShiftAssignment": "worked_shift",
}

_FACT_ROLE_ATTR = {
    "PayrollRecord": "job_code",
    "ShiftAssignment": "role",
}


def attach_payroll_or_shift_fact(
    conn: sqlite3.Connection,
    fact_entity_id: str,
    fact_type: Literal["PayrollRecord", "ShiftAssignment"],
) -> None:
    """Resolve a Payroll/Schedule fact to an Employee, link, and corroborate role codes."""
    resolver = resolve_payroll_employee if fact_type == "PayrollRecord" else resolve_schedule_employee
    employee_id = resolver(conn, fact_entity_id)

    if employee_id is None:
        create_flag(
            conn, fact_entity_id, "referential_orphan", "high",
            f"no Employee entity matched for {fact_type} id={fact_entity_id!r}"
        )
        return

    update_entity_attrs(conn, fact_entity_id, {"employee_id": employee_id})
    create_edge(conn, employee_id, fact_entity_id, _FACT_EDGE_TYPE[fact_type])

    fact = get_entity(conn, fact_entity_id)
    role_code = fact.attrs.get(_FACT_ROLE_ATTR[fact_type])

    other_type = "ShiftAssignment" if fact_type == "PayrollRecord" else "PayrollRecord"
    if role_code is not None:
        for other_fact in neighbors(conn, employee_id, _FACT_EDGE_TYPE[other_type]):
            other_role_code = other_fact.attrs.get(_FACT_ROLE_ATTR[other_type])
            if other_role_code is not None:
                payroll_code, schedule_code = (
                    (role_code, other_role_code) if fact_type == "PayrollRecord"
                    else (other_role_code, role_code)
                )
                corroborate_combined_b(conn, employee_id, payroll_code, schedule_code)


_EDGE_TYPE_TO_ENTITY_TYPE = {
    "paid_for": "PayrollRecord",
    "worked_shift": "ShiftAssignment",
    "holds_license": "License",
}


def unmerge(conn: sqlite3.Connection, from_id: str, to_id: str, edge_type: str) -> str:
    """
    Reverse a merge by detaching a fact entity from an Employee.

    Creates a new standalone copy of the fact entity with its attributes,
    removes the edge connecting them, and clears the employee_id link on
    the original fact entity.

    Args:
        conn: Database connection.
        from_id: Employee entity ID.
        to_id: Fact entity ID (PayrollRecord, ShiftAssignment, or License).
        edge_type: Type of edge to remove ("paid_for", "worked_shift", "holds_license").

    Returns:
        str: The ID of the new standalone fact entity.
    """
    # Map edge type to entity type
    entity_type = _EDGE_TYPE_TO_ENTITY_TYPE[edge_type]

    # Get the original fact entity and copy its attributes
    fact = get_entity(conn, to_id)
    attrs = dict(fact.attrs)

    # Remove employee_id from the copy
    attrs.pop("employee_id", None)

    # Create the new standalone entity
    new_id = create_entity(conn, entity_type, attrs)

    # Remove the edge
    remove_edge(conn, from_id, to_id, edge_type)

    # Clear employee_id on the original fact entity
    update_entity_attrs(conn, to_id, {"employee_id": None})

    return new_id
