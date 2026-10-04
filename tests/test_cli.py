"""Tests for the CLI orchestration layer: ingest dispatch + rescan, flags, employee lookup."""

import pytest

from sot.graph import find_entity
from sot.cli import ingest, list_open_flags, show_employee, resolve_flag_cmd


HR_HEADER = "employee_id,first_name,last_name,job_title,facility,phone,license_number,license_expiration,hire_date"
LICENSES_HEADER = "license_number,name_on_license,license_type,expiration_date,last_verified"
PAYROLL_HEADER = "payroll_id,employee_name,job_code,facility_code,period_start,period_end,hours_paid"


@pytest.fixture
def tmp_hr_csv(tmp_path):
    path = tmp_path / "hr.csv"
    path.write_text(
        HR_HEADER + "\n"
        'E201,Sofia,Reyes,Registered Nurse,Harborview Bayside,555-1234,RN-551203,2026-12-31,2020-01-15\n'
    )
    return str(path)


@pytest.fixture
def tmp_licenses_csv(tmp_path):
    path = tmp_path / "licenses.csv"
    path.write_text(
        LICENSES_HEADER + "\n"
        '"RN-551203","REYES, SOFIA",RN,2027-12-31,2026-09-01\n'
    )
    return str(path)


@pytest.fixture
def tmp_payroll_csv(tmp_path):
    path = tmp_path / "payroll.csv"
    path.write_text(
        PAYROLL_HEADER + "\n"
        'P-3001,"REYES, SOFIA",RN,BYS,2026-09-14,2026-09-20,36\n'
    )
    return str(path)


def test_ingest_dispatches_hr_csv_by_header(conn, tmp_hr_csv):
    ingest(conn, tmp_hr_csv)
    assert find_entity(conn, "Employee", employee_id="E201") is not None


def test_ingest_dispatches_licenses_csv_by_header(conn, tmp_licenses_csv):
    ingest(conn, tmp_licenses_csv)
    assert find_entity(conn, "License", license_number="RN-551203") is not None


def test_ingest_payroll_runs_resolver_and_combiner(conn, tmp_hr_csv, tmp_payroll_csv):
    ingest(conn, tmp_hr_csv)
    ingest(conn, tmp_payroll_csv)
    pr = find_entity(conn, "PayrollRecord", payroll_id="P-3001")
    assert pr.attrs.get("payroll_status") is not None  # Combined B ran, not left unresolved


def test_list_open_flags_groups_by_entity(conn):
    ingest(conn, "tests/fixtures/hr_roster_duplicate_id.csv")
    output = list_open_flags(conn)
    assert "data_source_anomaly" in output


def test_show_employee_reports_status(conn, tmp_hr_csv):
    ingest(conn, tmp_hr_csv)
    output = show_employee(conn, "Sofia Reyes")
    assert "status" in output.lower()


def test_ingest_schedule_pdf_creates_shift_assignments(conn):
    ingest(conn, "tests/fixtures/schedule_sample.pdf")
    from sot.graph import find_entity as fe
    # At least one ShiftAssignment should have been created from the PDF.
    import json
    cur = conn.execute("SELECT COUNT(*) FROM entities WHERE type = 'ShiftAssignment'")
    assert cur.fetchone()[0] > 0


def test_resolve_flag_cmd_resolves_flag(conn):
    ingest(conn, "tests/fixtures/hr_roster_duplicate_id.csv")
    grouped = list(__import__("sot.flags", fromlist=["open_flags_grouped_by_entity"])
                   .open_flags_grouped_by_entity(conn).values())
    flag_id = grouped[0][0].id
    resolve_flag_cmd(conn, flag_id, "tester", "confirmed duplicate, ignoring")
    from sot.flags import open_flags_grouped_by_entity
    remaining = open_flags_grouped_by_entity(conn)
    remaining_ids = [f.id for flags in remaining.values() for f in flags]
    assert flag_id not in remaining_ids
