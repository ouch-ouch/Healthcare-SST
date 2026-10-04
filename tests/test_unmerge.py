"""Tests for the unmerge function: reversing merged entities."""

from sot.graph import create_entity, create_edge, get_entity, neighbors
from sot.resolver import unmerge


def test_unmerge_detaches_without_deleting_either_entity(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia"})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp, "hours_paid": 36})
    create_edge(conn, emp, pr, "paid_for")

    new_id = unmerge(conn, emp, pr, "paid_for")

    assert get_entity(conn, emp) is not None
    assert get_entity(conn, pr) is not None
    assert neighbors(conn, emp, "paid_for") == []
    assert get_entity(conn, new_id).attrs["hours_paid"] == 36


def test_unmerge_clears_employee_id_on_original_fact(conn):
    emp = create_entity(conn, "Employee", {})
    pr = create_entity(conn, "PayrollRecord", {"employee_id": emp})
    create_edge(conn, emp, pr, "paid_for")
    unmerge(conn, emp, pr, "paid_for")
    assert get_entity(conn, pr).attrs.get("employee_id") is None
