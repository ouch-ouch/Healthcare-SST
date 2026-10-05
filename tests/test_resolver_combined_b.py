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


def test_attach_payroll_fact_rescan_does_not_duplicate_orphan_flag(conn):
    # Simulates the CLI's idempotent rescan: attach_payroll_or_shift_fact is called
    # again on a fact that will never resolve (e.g. an employee never in the HR file).
    # Should not accumulate a second referential_orphan flag.
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "NOBODY, NOONE", "facility_code": "BYS"})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")
    grouped = open_flags_grouped_by_entity(conn)
    orphan_flags = [f for f in grouped[pr] if f.flag_type == "referential_orphan"]
    assert len(orphan_flags) == 1


def test_attach_payroll_fact_auto_resolves_stale_orphan_flag_once_employee_appears(conn):
    """Stale-flag fix: a referential_orphan from before the Employee existed must
    auto-close once a matching Employee shows up and the fact links."""
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA", "facility_code": "BYS"})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")  # fails: no Employee yet
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[pr][0].flag_type == "referential_orphan"

    create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                      "facility": "Harborview Bayside", "status": "active"})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")  # rescan: now succeeds

    assert get_entity(conn, pr).attrs.get("employee_id") is not None
    grouped = open_flags_grouped_by_entity(conn)
    assert pr not in grouped


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


def test_fuzzy_match_tie_flags_identity_ambiguity_and_returns_none(conn):
    # Two Employees with identical names at the same facility -- a genuine tie at the top
    # score. Silently picking one would risk mis-attaching the fact to the wrong Employee.
    create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                      "facility": "Harborview Bayside", "status": "active"})
    create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                      "facility": "Harborview Bayside", "status": "active"})
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA", "facility_code": "BYS"})

    assert resolve_payroll_employee(conn, pr) is None

    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[pr][0].flag_type == "identity_ambiguity"
    assert "tie" in grouped[pr][0].reason


def test_attach_fact_cross_corroborates_through_orchestrator_matching(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "facility": "Harborview Bayside", "status": "active"})
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA",
                                                "facility_code": "BYS", "job_code": "RN"})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")

    from sot.graph import find_entity
    facility = find_entity(conn, "Facility", name="Harborview Bayside")
    shift = create_entity(conn, "ShiftAssignment", {"staff_name": "Sofia Reyes", "role": "RN",
                                                     "facility_id": facility.id})
    attach_payroll_or_shift_fact(conn, shift, "ShiftAssignment")

    assert get_entity(conn, shift).attrs.get("employee_id") == emp
    grouped = open_flags_grouped_by_entity(conn)
    assert emp not in grouped


def test_borderline_fuzzy_match_tags_resolution_confidence_and_business_rule_flag_carries_note(conn):
    """I8: a borderline (score < 95) passing match tags the employee; a later business_rule_violation
    flag against it should mention the borderline match as context."""
    from sot.combiner import build_combined_b

    emp = create_entity(conn, "Employee", {"first_name": "Marcus", "last_name": "Bell",
                                            "facility": "Harborview Bayside", "status": "active"})
    # "Marc Bell" vs "Marcus Bell" is a close-but-not-exact fuzzy match (< 95, >= threshold).
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "BELL, MARC",
                                                "facility_code": "BYS", "job_code": "RN",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 999})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")
    assert get_entity(conn, emp).attrs.get("resolution_confidence") == "borderline"

    # Give the employee a linked shift whose hours don't match the (deliberately
    # bogus) hours_paid=999, so the hours check fires a business_rule_violation.
    from sot.graph import create_edge
    shift = create_entity(conn, "ShiftAssignment", {"hours_by_day": {"Mon 09/14": 8.0}})
    create_edge(conn, emp, shift, "worked_shift")

    build_combined_b(conn, pr, "PayrollRecord")
    grouped = open_flags_grouped_by_entity(conn)
    violation = next(f for f in grouped[pr] if f.flag_type == "business_rule_violation")
    assert "borderline" in violation.reason


def test_attach_fact_cross_corroborates_through_orchestrator_mismatch(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "facility": "Harborview Bayside", "status": "active"})
    pr = create_entity(conn, "PayrollRecord", {"employee_name": "REYES, SOFIA",
                                                "facility_code": "BYS", "job_code": "RN"})
    attach_payroll_or_shift_fact(conn, pr, "PayrollRecord")

    from sot.graph import find_entity
    facility = find_entity(conn, "Facility", name="Harborview Bayside")
    shift = create_entity(conn, "ShiftAssignment", {"staff_name": "Sofia Reyes", "role": "CNA",
                                                     "facility_id": facility.id})
    attach_payroll_or_shift_fact(conn, shift, "ShiftAssignment")

    assert get_entity(conn, shift).attrs.get("employee_id") == emp
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "identity_ambiguity" and "role_code" in f.reason for f in grouped[emp])
