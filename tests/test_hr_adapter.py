"""Tests for HR roster adapter."""

import pytest
from sot.adapters.hr import ingest_hr_roster
from sot.graph import find_entity
from sot.flags import open_flags_grouped_by_entity


@pytest.fixture
def tmp_hr_csv(tmp_path):
    """Create a temporary HR CSV file with valid data."""
    csv_content = """employee_id,first_name,last_name,hire_date,license_expiration
E201,Sofia,Reyes,2020-01-15,2026-12-31
E202,Marcus,Bell,2019-06-20,2025-08-15
"""
    csv_file = tmp_path / "hr_roster.csv"
    csv_file.write_text(csv_content)
    return str(csv_file)


def test_ingest_creates_employee_entities(conn, tmp_hr_csv):
    """Test that ingest_hr_roster creates Employee entities from CSV."""
    result = ingest_hr_roster(conn, tmp_hr_csv)
    assert result.created == 2  # fixture has 2 rows
    e = find_entity(conn, "Employee", employee_id="E201")
    assert e is not None
    assert e.attrs["first_name"] == "Sofia"


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
