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


def test_graph_page_loads(client):
    r = client.get("/graph")
    assert r.status_code == 200
    assert b"vis-network" in r.data


def test_graph_data_before_any_ingest_has_only_the_seeded_facilities(client):
    r = client.get("/graph-data")
    assert r.status_code == 200
    data = r.get_json()
    assert data["edges"] == []
    assert len(data["nodes"]) == 2  # the two Facility entities init_db always seeds
    assert all(n["group"] == "Facility" for n in data["nodes"])


def test_graph_data_reflects_ingested_entities_edges_and_flags(client):
    with open("tests/fixtures/hr_roster.csv", "rb") as hr, \
         open("tests/fixtures/licenses.csv", "rb") as lic:
        client.post(
            "/ingest",
            data={"files": [(hr, "hr_roster.csv"), (lic, "licenses.csv")]},
            content_type="multipart/form-data",
        )

    data = client.get("/graph-data").get_json()

    employee_nodes = [n for n in data["nodes"] if n["group"] == "Employee"]
    license_nodes = [n for n in data["nodes"] if n["group"] == "License"]
    assert len(employee_nodes) == 2
    assert len(license_nodes) == 2

    holds_license_edges = [e for e in data["edges"] if e["type"] == "holds_license"]
    assert len(holds_license_edges) == 2  # both employees' licenses linked cleanly

    # the two Facility entities seeded at init_db show up too, with no flags
    facility_nodes = [n for n in data["nodes"] if n["group"] == "Facility"]
    assert len(facility_nodes) == 2
    assert all(not n["flagged"] for n in facility_nodes)
