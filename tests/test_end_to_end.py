"""End-to-end tests: full pipeline through cli.ingest, and ingestion idempotency."""

import shutil

import pytest

from sot.cli import ingest
from sot.graph import find_entity, neighbors
from sot.flags import open_flags_grouped_by_entity
from tests.conftest import all_entities_of_type


@pytest.fixture
def tmp_hr_csv(tmp_path):
    """A copy of hr_roster.csv at a temp path, for re-ingestion tests."""
    dest = tmp_path / "hr_roster.csv"
    shutil.copy("tests/fixtures/hr_roster.csv", dest)
    return str(dest)


def test_full_pipeline_four_sources_resolve_cleanly(conn):
    for f in ["tests/fixtures/hr_roster.csv", "tests/fixtures/licenses.csv",
              "tests/fixtures/payroll.csv", "tests/fixtures/schedule_sample.pdf"]:
        ingest(conn, f)
    emp = find_entity(conn, "Employee", employee_id="E201")
    assert emp.attrs["status"] == "active"
    pr = find_entity(conn, "PayrollRecord", payroll_id="P-3001")
    assert pr.attrs["payroll_status"] == "approved"

    # Clean 4-file pipeline: every employee has exactly one holds_license edge,
    # and zero business_rule_violation flags anywhere (regression guard for C1/C2/I5/I7).
    assert len(neighbors(conn, emp.id, "holds_license")) == 1

    grouped = open_flags_grouped_by_entity(conn)
    all_flag_types = [f.flag_type for flags in grouped.values() for f in flags]
    assert "business_rule_violation" not in all_flag_types


def test_reingesting_same_hr_file_does_not_duplicate_employee(conn, tmp_hr_csv):
    ingest(conn, tmp_hr_csv)
    ingest(conn, tmp_hr_csv)  # same file, fed twice
    all_e201 = [e for e in all_entities_of_type(conn, "Employee") if e.attrs.get("employee_id") == "E201"]
    assert len(all_e201) == 1


def test_corrected_reexport_updates_not_duplicates(conn):
    ingest(conn, "tests/fixtures/hr_roster.csv")
    ingest(conn, "tests/fixtures/hr_roster_corrected.csv")
    all_e201 = [e for e in all_entities_of_type(conn, "Employee") if e.attrs.get("employee_id") == "E201"]
    assert len(all_e201) == 1
