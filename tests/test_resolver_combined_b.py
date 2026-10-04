from sot.graph import create_entity, get_entity
from sot.flags import open_flags_grouped_by_entity
from sot.resolver import (
    resolve_payroll_employee,
    resolve_schedule_employee,
    corroborate_combined_b,
    attach_payroll_or_shift_fact,
)


def test_resolve_payroll_employee_fuzzy_match(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "facility": "Harborview Bayside", "status": "active"})
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA",
                                                "facility_code": "BYS"})
    matched = resolve_payroll_employee(conn, pr)
    assert matched == emp


def test_similar_names_different_facility_not_confused(conn):
    reyes_bayside = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                                       "facility": "Harborview Bayside", "status": "active"})
    create_entity(conn, "Employee", {"first_name": "Sara", "last_name": "Reyes",
                                      "facility": "Harborview Riverdale", "status": "active"})
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA", "facility_code": "BYS"})
    assert resolve_payroll_employee(conn, pr) == reyes_bayside


def test_no_match_returns_none(conn):
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "NOBODY, NOONE", "facility_code": "BYS"})
    assert resolve_payroll_employee(conn, pr) is None


def test_role_code_mismatch_flags_identity_ambiguity(conn):
    emp = create_entity(conn, "Employee", {})
    result = corroborate_combined_b(conn, emp, "RN", "CNA")
    assert result is False
    grouped = open_flags_grouped_by_entity(conn)
    assert "role_code" in grouped[emp][0].reason


def test_role_code_match_returns_true_no_flag(conn):
    emp = create_entity(conn, "Employee", {})
    result = corroborate_combined_b(conn, emp, "RN", "RN")
    assert result is True
    grouped = open_flags_grouped_by_entity(conn)
    assert emp not in grouped


def test_attach_payroll_fact_sets_pending_on_no_match(conn):
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "NOBODY, NOONE", "facility_code": "BYS"})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs.get("employee_id") is None
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[pr][0].flag_type == "referential_orphan"


def test_attach_payroll_fact_links_employee_on_match(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "facility": "Harborview Bayside", "status": "active"})
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA",
                                                "facility_code": "BYS", "job_code": "RN"})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs.get("employee_id") == emp

    from sot.graph import neighbors
    linked = neighbors(conn, emp, "paid_for")
    assert any(e.id == pr for e in linked)


def test_resolve_schedule_employee_scoped_by_facility_id(conn):
    from sot.graph import create_entity as ce, find_entity
    # init_db already seeds the two canonical Facility entities; reuse it rather than
    # creating a duplicate that resolve_schedule_employee's facility lookup won't match.
    facility = find_entity(conn, "Facility", name="Harborview Bayside")
    emp = ce(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                 "facility": "Harborview Bayside", "status": "active"})
    shift = ce(conn, "ShiftAssignment", {"staff_name": "Sofia Reyes", "role": "RN",
                                          "facility_id": facility.id})
    assert resolve_schedule_employee(conn, shift) == emp


def test_resolve_schedule_employee_falls_back_when_facility_none(conn):
    from sot.graph import create_entity as ce
    emp = ce(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                 "facility": "Harborview Bayside", "status": "active"})
    shift = ce(conn, "ShiftAssignment", {"staff_name": "Sofia Reyes", "role": "RN",
                                          "facility_id": None})
    assert resolve_schedule_employee(conn, shift) == emp
