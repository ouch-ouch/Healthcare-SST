"""Tests for HR roster adapter."""

import pytest
from sot.adapters.hr import ingest_hr_roster
from sot.graph import find_entity, update_entity_attrs
from sot.flags import open_flags_grouped_by_entity


def test_ingest_creates_employee_entities(conn):
    """Test that ingest_hr_roster creates Employee entities from CSV."""
    result = ingest_hr_roster(conn, "tests/fixtures/hr_roster.csv")
    assert result.created == 2  # fixture has 2 rows
    e = find_entity(conn, "Employee", employee_id="E201")
    assert e is not None
    assert e.attrs["first_name"] == "Sofia"


def test_employee_starts_pending(conn):
    """Test that created Employee entities have status='pending'."""
    ingest_hr_roster(conn, "tests/fixtures/hr_roster.csv")
    e = find_entity(conn, "Employee", employee_id="E201")
    assert e is not None
    assert e.attrs["status"] == "pending"


def test_reingest_does_not_reset_status_already_set_by_gate_rule(conn):
    """Re-ingesting an existing employee must not clobber a status a gate rule already set."""
    ingest_hr_roster(conn, "tests/fixtures/hr_roster.csv")
    e = find_entity(conn, "Employee", employee_id="E201")
    update_entity_attrs(conn, e.id, {"status": "blocked"})  # simulate a prior gate rule

    ingest_hr_roster(conn, "tests/fixtures/hr_roster.csv")  # re-ingest same row

    e = find_entity(conn, "Employee", employee_id="E201")
    assert e.attrs["status"] == "blocked"


def test_reingesting_same_file_reports_zero_created(conn):
    """Re-ingesting rows that already exist must not count as newly created."""
    ingest_hr_roster(conn, "tests/fixtures/hr_roster.csv")
    result = ingest_hr_roster(conn, "tests/fixtures/hr_roster.csv")
    assert result.created == 0


def test_duplicate_employee_id_flagged_as_data_source_anomaly(conn):
    """Test that duplicate employee_id within file is flagged."""
    ingest_hr_roster(conn, "tests/fixtures/hr_roster_duplicate_id.csv")
    grouped = open_flags_grouped_by_entity(conn)
    reasons = [f.flag_type for flags in grouped.values() for f in flags]
    assert "data_source_anomaly" in reasons


def test_future_hire_date_flagged(conn):
    """Test that future hire_date is flagged as data_source_anomaly."""
    ingest_hr_roster(conn, "tests/fixtures/hr_roster_future_hire.csv")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "data_source_anomaly" for flags in grouped.values() for f in flags)


def test_license_expiration_in_past_flagged(conn):
    """Test that past license_expiration is flagged as data_source_anomaly."""
    ingest_hr_roster(conn, "tests/fixtures/hr_roster_past_expiration.csv")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "data_source_anomaly" for flags in grouped.values() for f in flags)
