import pytest
from sot.graph import create_entity, get_entity
from sot.rules import Rule, evaluate
from sot.flags import open_flags_grouped_by_entity


def test_gate_rule_sets_status_on_failure(conn):
    eid = create_entity(conn, "Employee", {"license_expired": True})
    rule = Rule(id="r1", applies_to="Employee", type="gate",
                check=lambda e, c: not e.attrs["license_expired"],
                on_fail={"set_status": "blocked", "flag_type": "license_needs_check",
                         "severity": "high", "reason": "license expired"})
    evaluate(conn, get_entity(conn, eid), [rule])
    assert get_entity(conn, eid).attrs["status"] == "blocked"


def test_flag_rule_creates_flag_on_failure(conn):
    eid = create_entity(conn, "Employee", {"role": "RN", "license_type": "CNA"})
    rule = Rule(id="r2", applies_to="Employee", type="flag",
                check=lambda e, c: e.attrs["role"] == e.attrs["license_type"],
                on_fail={"flag_type": "attribute_disagreement", "severity": "medium",
                         "reason": "role does not match license type"})
    evaluate(conn, get_entity(conn, eid), [rule])
    grouped = open_flags_grouped_by_entity(conn)
    assert eid in grouped


def test_gate_rule_also_creates_a_flag(conn):
    eid = create_entity(conn, "Employee", {"license_expired": True})
    rule = Rule(id="r4", applies_to="Employee", type="gate",
                check=lambda e, c: not e.attrs["license_expired"],
                on_fail={"set_status": "blocked", "flag_type": "license_needs_check",
                         "severity": "high", "reason": "license expired"})
    evaluate(conn, get_entity(conn, eid), [rule])
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[eid][0].flag_type == "license_needs_check"


def test_rule_skipped_when_applies_to_does_not_match(conn):
    eid = create_entity(conn, "Facility", {})
    rule = Rule(id="r3", applies_to="Employee", type="flag",
                check=lambda e, c: False,  # would always fail if run
                on_fail={"flag_type": "attribute_disagreement", "severity": "low", "reason": "n/a"})
    evaluate(conn, get_entity(conn, eid), [rule])
    assert eid not in open_flags_grouped_by_entity(conn)
