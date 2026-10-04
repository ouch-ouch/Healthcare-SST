"""Combined-A precedence rules: soonest expiration, canonical name, gate/flag checks.

Task 10 adds the Combined-B half of this module.
"""

import sqlite3
from datetime import date

from sot.graph import Entity, get_entity, update_entity_attrs, neighbors
from sot.rules import Rule, evaluate
from sot.resolver import _hr_full_name

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
