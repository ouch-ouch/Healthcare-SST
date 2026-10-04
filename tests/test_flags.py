import pytest
from sot.graph import create_entity, get_entity
from sot.flags import create_flag, open_flags_grouped_by_entity, resolve_flag


def test_create_flag_and_group_by_entity(conn):
    eid = create_entity(conn, "Employee", {})
    create_flag(conn, eid, "identity_ambiguity", "high", "name mismatch")
    grouped = open_flags_grouped_by_entity(conn)
    assert eid in grouped
    assert grouped[eid][0].flag_type == "identity_ambiguity"
    assert grouped[eid][0].status == "open"


def test_resolve_flag_is_additive_not_overwrite(conn):
    eid = create_entity(conn, "Employee", {})
    fid = create_flag(conn, eid, "identity_ambiguity", "high", "name mismatch")
    resolve_flag(conn, fid, resolved_by="reviewer1", resolution="confirmed same person")
    grouped = open_flags_grouped_by_entity(conn)
    assert eid not in grouped  # no longer open
    # original flag row still exists with its resolution recorded
    from sot.flags import get_all_flags_for_entity
    all_flags = get_all_flags_for_entity(conn, eid)
    assert all_flags[0].resolution == "confirmed same person"
