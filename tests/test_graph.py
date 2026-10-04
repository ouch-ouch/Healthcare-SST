import pytest
from sot.graph import (
    Entity,
    create_entity,
    get_entity,
    update_entity_attrs,
    find_entity,
    create_edge,
    neighbors,
    remove_edge,
)
from tests.conftest import all_entities_of_type


def test_create_and_get_entity(conn):
    eid = create_entity(conn, "Employee", {"first_name": "Sofia"})
    e = get_entity(conn, eid)
    assert e.type == "Employee"
    assert e.attrs["first_name"] == "Sofia"


def test_update_entity_attrs_merges(conn):
    eid = create_entity(conn, "Employee", {"first_name": "Sofia"})
    update_entity_attrs(conn, eid, {"status": "active"})
    e = get_entity(conn, eid)
    assert e.attrs == {"first_name": "Sofia", "status": "active"}


def test_find_entity_by_attr(conn):
    create_entity(conn, "License", {"license_number": "RN-551203"})
    found = find_entity(conn, "License", license_number="RN-551203")
    assert found is not None


def test_neighbors_by_edge_type(conn):
    emp = create_entity(conn, "Employee", {})
    lic = create_entity(conn, "License", {"license_number": "RN-551203"})
    create_edge(conn, emp, lic, "holds_license")
    result = neighbors(conn, emp, "holds_license")
    assert len(result) == 1 and result[0].id == lic


def test_remove_edge(conn):
    emp = create_entity(conn, "Employee", {})
    lic = create_entity(conn, "License", {})
    create_edge(conn, emp, lic, "holds_license")
    remove_edge(conn, emp, lic, "holds_license")
    assert neighbors(conn, emp, "holds_license") == []


def test_init_db_seeds_known_facilities(conn):
    bayside = find_entity(conn, "Facility", name="Harborview Bayside")
    riverdale = find_entity(conn, "Facility", name="Harborview Riverdale")
    assert bayside is not None and riverdale is not None


def test_init_db_is_idempotent_on_facilities(tmp_path):
    import sqlite3
    from sot.db import init_db

    path = str(tmp_path / "test.db")
    init_db(path)
    init_db(path)  # second call on the same file must not duplicate
    conn = init_db(path)
    all_facilities = [e for e in all_entities_of_type(conn, "Facility")]
    assert len(all_facilities) == 2
