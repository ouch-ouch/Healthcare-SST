"""Smoke test for the web UI -- it's a thin wrapper over sot.cli's functions,
so this only checks the routes actually call through and render, not the
underlying ingestion/flag logic (already covered elsewhere)."""

import pytest

from app import app as flask_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOT_DB", str(tmp_path / "web_test.db"))
    import app as app_module
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "web_test.db"))
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_index_loads_with_no_open_flags(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"No open flags" in r.data


def test_ingest_hr_file_and_look_up_employee(client):
    with open("tests/fixtures/hr_roster.csv", "rb") as f:
        r = client.post(
            "/ingest",
            data={"files": [(f, "hr_roster.csv")]},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
    assert r.status_code == 200
    assert b"Ingested hr_roster.csv" in r.data

    r = client.get("/employee?name=Sofia")
    assert r.status_code == 200
    assert b"Employee: Sofia" in r.data


def test_bulk_ingest_multiple_files_in_one_request(client):
    with open("tests/fixtures/hr_roster.csv", "rb") as hr, \
         open("tests/fixtures/licenses.csv", "rb") as lic, \
         open("tests/fixtures/payroll.csv", "rb") as pay:
        r = client.post(
            "/ingest",
            data={"files": [
                (hr, "hr_roster.csv"),
                (lic, "licenses.csv"),
                (pay, "payroll.csv"),
            ]},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
    assert r.status_code == 200
    assert b"Ingested hr_roster.csv" in r.data
    assert b"Ingested licenses.csv" in r.data
    assert b"Ingested payroll.csv" in r.data

    # all three actually landed, not just the status messages
    r = client.get("/employee?name=Sofia")
    assert b"License:" in r.data
    assert b"none linked" not in r.data


def test_resolve_unknown_flag_shows_error_not_a_crash(client):
    r = client.post(
        "/resolve",
        data={"flag_id": "not-a-real-id", "resolved_by": "tester", "resolution": "n/a"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"Error resolving" in r.data
