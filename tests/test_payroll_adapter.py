"""Tests for Payroll adapter."""

import pytest
from sot.adapters.payroll import ingest_payroll
from sot.graph import find_entity
from sot.flags import open_flags_grouped_by_entity


def test_ingest_creates_payroll_record_entities(conn):
    """Test that ingest_payroll creates PayrollRecord entities from CSV."""
    result = ingest_payroll(conn, "tests/fixtures/payroll.csv")
    assert result.created == 2
    pr = find_entity(conn, "PayrollRecord", payroll_id="P-3001")
    assert pr is not None
    assert pr.attrs["employee_name"] == "REYES, SOFIA"


def test_future_period_flagged(conn):
    """Test that future period_start or period_end is flagged as data_source_anomaly."""
    ingest_payroll(conn, "tests/fixtures/payroll_future_period.csv")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "data_source_anomaly"
               for flags in grouped.values() for f in flags)


def test_payroll_record_starts_unlinked(conn):
    """Test that PayrollRecord entities do not have employee_id set."""
    ingest_payroll(conn, "tests/fixtures/payroll.csv")
    pr = find_entity(conn, "PayrollRecord", payroll_id="P-3001")
    assert pr is not None
    assert pr.attrs.get("employee_id") is None
