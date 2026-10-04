"""Combined-A precedence rules: soonest expiration, canonical name, gate/flag checks.

Task 10 adds the Combined-B half of this module.
"""

import sqlite3
from datetime import date
from typing import Literal

from sot.graph import Entity, get_entity, update_entity_attrs, neighbors, find_entity
from sot.rules import Rule, evaluate
from sot.resolver import _hr_full_name
from sot.flags import create_flag
from sot.facilities import normalize_facility

_HOURS_TOLERANCE = 0.01

_BORDERLINE_NOTE = " (note: this employee's identity match was borderline-confidence)"


def _with_borderline_note(reason: str, emp: Entity) -> str:
    """I8: append a borderline-confidence note if the employee's identity match was borderline."""
    if emp.attrs.get("resolution_confidence") == "borderline":
        return reason + _BORDERLINE_NOTE
    return reason

_FACT_EDGE_TYPE = {
    "PayrollRecord": "paid_for",
    "ShiftAssignment": "worked_shift",
}

STALENESS_WINDOW_DAYS = 180

# Role (HR job_title) -> expected license_type prefix mapping.
ROLE_TO_LICENSE_TYPE = {
    "Registered Nurse": "RN",
    "Certified Nursing Assistant": "CNA",
}


def _linked_license(conn: sqlite3.Connection, employee_id: str) -> Entity | None:
    lics = neighbors(conn, employee_id, "holds_license")
    return lics[0] if lics else None


def _license_needs_check(entity: Entity, conn: sqlite3.Connection) -> bool:
    resolved = entity.attrs.get("resolved_expiration")
    if not resolved:
        return True
    return date.fromisoformat(resolved) >= date.today()


def _role_matches_license(entity: Entity, conn: sqlite3.Connection) -> bool:
    job_title = entity.attrs.get("job_title")
    expected = ROLE_TO_LICENSE_TYPE.get(job_title)
    if expected is None:
        return True

    lic = _linked_license(conn, entity.id)
    if lic is None:
        return True

    return lic.attrs.get("license_type") == expected


def _license_staleness(entity: Entity, conn: sqlite3.Connection) -> bool:
    lic = _linked_license(conn, entity.id)
    if lic is None:
        return True

    last_verified = lic.attrs.get("last_verified")
    if not last_verified:
        return True

    age_days = (date.today() - date.fromisoformat(last_verified)).days
    return age_days <= STALENESS_WINDOW_DAYS


COMBINED_A_RULES: list[Rule] = [
    Rule(
        id="license_needs_check",
        applies_to="Employee",
        type="gate",
        check=_license_needs_check,
        on_fail={
            "set_status": "blocked",
            "flag_type": "license_needs_check",
            "severity": "high",
            "reason": "resolved_expiration is before today",
        },
    ),
    Rule(
        id="role_matches_license",
        applies_to="Employee",
        type="flag",
        check=_role_matches_license,
        on_fail={
            "flag_type": "attribute_disagreement",
            "severity": "medium",
            "reason": "job_title does not match license_type",
        },
    ),
    Rule(
        id="license_staleness",
        applies_to="Employee",
        type="flag",
        check=_license_staleness,
        on_fail={
            "flag_type": "staleness",
            "severity": "low",
            "reason": f"license last_verified is over {STALENESS_WINDOW_DAYS} days old",
        },
    ),
]


def build_combined_a(conn: sqlite3.Connection, employee_id: str) -> None:
    """
    Apply §7 precedence rules (soonest expiration, HR-canonical name) onto the
    Employee's attrs, then run the Combined-A gate/flag rules.
    """
    emp = get_entity(conn, employee_id)
    lic = _linked_license(conn, employee_id)

    hr_expiration = emp.attrs.get("license_expiration")
    license_expiration = lic.attrs.get("expiration_date") if lic else None
    candidates = [d for d in (hr_expiration, license_expiration) if d]

    updates = {"display_name": _hr_full_name(emp)}
    if candidates:
        updates["resolved_expiration"] = min(candidates)

    update_entity_attrs(conn, employee_id, updates)

    evaluate(conn, get_entity(conn, employee_id), COMBINED_A_RULES)

    # I3: a fully clean, license-verified employee should reach "active" (not stay
    # stuck at "pending" forever), and a later license renewal should clear "blocked".
    # Gate rules are evaluated directly here (rather than trusting the entity's
    # current `status` attr) because a passing gate rule leaves `status` untouched --
    # a stale "blocked" from a previous run would otherwise never clear.
    gate_rules_pass = all(
        rule.check(get_entity(conn, employee_id), conn)
        for rule in COMBINED_A_RULES if rule.type == "gate"
    )
    if gate_rules_pass and lic is not None:
        update_entity_attrs(conn, employee_id, {"status": "active"})


# --- Combined B: cross-table validation, payroll approval, cascade ---


def _hours_in_period(hours_by_day: dict, period_start: str, period_end: str) -> float:
    """Sum hours_by_day values whose trailing MM/DD (year from period_start) falls in [start, end]."""
    year = date.fromisoformat(period_start).year
    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)

    total = 0.0
    for key, hours in hours_by_day.items():
        mm_dd = key.strip().rsplit(" ", 1)[-1]
        month, day = (int(p) for p in mm_dd.split("/"))
        day_date = date(year, month, day)
        if start <= day_date <= end:
            total += hours
    return total


def build_combined_b(
    conn: sqlite3.Connection,
    fact_entity_id: str,
    fact_type: Literal["PayrollRecord", "ShiftAssignment"],
) -> None:
    """Cross-check a resolved Payroll/Schedule fact against its Employee and compute payroll_status."""
    fact = get_entity(conn, fact_entity_id)
    employee_id = fact.attrs.get("employee_id")
    if not employee_id:
        return  # Task 9 already flagged this as a referential_orphan.

    emp = get_entity(conn, employee_id)

    # 1. Facility check.
    if fact_type == "PayrollRecord":
        fact_facility = normalize_facility(fact.attrs.get("facility_code"))
        emp_facility = normalize_facility(emp.attrs.get("facility"))
        if fact_facility != emp_facility:
            create_flag(
                conn, fact_entity_id, "business_rule_violation", "high",
                _with_borderline_note(
                    f"facility mismatch: payroll facility={fact_facility!r} vs employee facility={emp_facility!r}",
                    emp,
                )
            )
    else:
        emp_facility_name = normalize_facility(emp.attrs.get("facility"))
        emp_facility_entity = find_entity(conn, "Facility", name=emp_facility_name) if emp_facility_name else None
        emp_facility_id = emp_facility_entity.id if emp_facility_entity else None
        fact_facility_id = fact.attrs.get("facility_id")
        if fact_facility_id is not None and emp_facility_id is not None and fact_facility_id != emp_facility_id:
            create_flag(
                conn, fact_entity_id, "business_rule_violation", "high",
                _with_borderline_note(
                    f"facility mismatch: shift facility_id={fact_facility_id!r} vs employee facility_id={emp_facility_id!r}",
                    emp,
                )
            )

    # 2. Hours check (only meaningful for PayrollRecord, the only fact type with hours_paid).
    if fact_type == "PayrollRecord":
        shifts = neighbors(conn, employee_id, "worked_shift")
        if shifts:
            period_start = fact.attrs.get("period_start")
            period_end = fact.attrs.get("period_end")
            worked_hours = sum(
                _hours_in_period(shift.attrs.get("hours_by_day", {}), period_start, period_end)
                for shift in shifts
            )
            hours_paid = fact.attrs.get("hours_paid", 0)
            if abs(worked_hours - hours_paid) > _HOURS_TOLERANCE:
                create_flag(
                    conn, fact_entity_id, "business_rule_violation", "high",
                    _with_borderline_note(
                        f"hours mismatch: hours_paid={hours_paid!r} vs worked hours={worked_hours!r}",
                        emp,
                    )
                )

    # 3. Payroll approval status, derived from the three-way period/resolved_expiration comparison.
    period_start = fact.attrs.get("period_start")
    period_end = fact.attrs.get("period_end")
    resolved_expiration = emp.attrs.get("resolved_expiration")

    if resolved_expiration and period_start and period_end:
        resolved = date.fromisoformat(resolved_expiration)
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)

        if resolved >= end:
            payroll_status = "approved"
        elif resolved < start:
            payroll_status = "held"
        else:
            payroll_status = "held"
            create_flag(
                conn, fact_entity_id, "partial_period_license_lapse", "high",
                f"resolved_expiration={resolved_expiration!r} falls within pay period "
                f"[{period_start!r}, {period_end!r}]"
            )

        update_entity_attrs(conn, fact_entity_id, {"payroll_status": payroll_status})


def cascade_from_employee(conn: sqlite3.Connection, employee_id: str) -> None:
    """Re-run build_combined_b on any of the Employee's facts still held/pending after an A-side change."""
    for fact_type, edge_type in _FACT_EDGE_TYPE.items():
        for fact in neighbors(conn, employee_id, edge_type):
            if fact.attrs.get("payroll_status") in (None, "held"):
                build_combined_b(conn, fact.id, fact_type)
