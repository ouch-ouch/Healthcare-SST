from sot.graph import create_entity, get_entity, create_edge, update_entity_attrs
from sot.flags import open_flags_grouped_by_entity
from sot.combiner import build_combined_b, build_combined_a, cascade_from_employee


def test_facility_mismatch_flags_business_rule_violation(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "active",
                                            "resolved_expiration": "2099-01-01"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "RVD",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    build_combined_b(conn, pr, "PayrollRecord")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "business_rule_violation" for f in grouped[pr])


def test_hours_mismatch_flagged(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "active",
                                            "resolved_expiration": "2099-01-01"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 50})
    shift = create_entity(conn, "ShiftAssignment", {"employee_id": emp,
                                                      "hours_by_day": {"Mon 09/14": 8, "Tue 09/15": 8}})  # 16, not 50
    create_edge(conn, emp, shift, "worked_shift")
    build_combined_b(conn, pr, "PayrollRecord")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "business_rule_violation" for f in grouped[pr])


def test_fully_blocked_period_is_held(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "blocked",
                                            "resolved_expiration": "2020-01-01"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    build_combined_b(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs["payroll_status"] == "held"


def test_mid_week_lapse_flagged_partial(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "blocked",
                                            "resolved_expiration": "2026-09-17"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    build_combined_b(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs["payroll_status"] == "held"
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "partial_period_license_lapse" for f in grouped[pr])


def test_orphan_fact_is_noop(conn):
    pr = create_entity(conn, "PayrollRecord", {"facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    build_combined_b(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs.get("payroll_status") is None
