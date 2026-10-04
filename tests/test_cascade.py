from sot.graph import create_entity, get_entity, create_edge, update_entity_attrs
from sot.combiner import build_combined_a, build_combined_b, cascade_from_employee


def test_cascade_unblocks_held_payroll_on_license_renewal(conn):
    emp = create_entity(conn, "Employee", {"facility": "Harborview Bayside", "status": "blocked",
                                            "resolved_expiration": "2020-01-01",
                                            "license_expiration": "2020-01-01"})
    lic = create_entity(conn, "License", {"expiration_date": "2020-01-01"})
    create_edge(conn, emp, lic, "holds_license")
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "facility_code": "BYS",
                                                "period_start": "2026-09-14", "period_end": "2026-09-20",
                                                "hours_paid": 36})
    create_edge(conn, emp, pr, "paid_for")
    build_combined_b(conn, pr, "PayrollRecord")
    assert get_entity(conn, pr).attrs["payroll_status"] == "held"

    # license renewed
    update_entity_attrs(conn, lic, {"expiration_date": "2099-01-01"})
    update_entity_attrs(conn, emp, {"license_expiration": "2099-01-01"})
    build_combined_a(conn, emp)
    cascade_from_employee(conn, emp)

    assert get_entity(conn, pr).attrs["payroll_status"] == "approved"
