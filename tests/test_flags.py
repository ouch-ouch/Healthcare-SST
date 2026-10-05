import pytest
from sot.graph import create_entity, get_entity
from sot.flags import create_flag, open_flags_grouped_by_entity, resolve_flag, auto_resolve_open_flags


def test_create_flag_and_group_by_entity(conn):
    eid = create_entity(conn, "Employee", {})
    create_flag(conn, eid, "identity_ambiguity", "high", "name mismatch")
    grouped = open_flags_grouped_by_entity(conn)
    assert eid in grouped
    assert grouped[eid][0].flag_type == "identity_ambiguity"
    assert grouped[eid][0].status == "open"


def test_create_flag_dedupes_same_entity_type_and_reason(conn):
    """I4: repeated create_flag calls with the same (entity_id, flag_type, reason) must not duplicate."""
    eid = create_entity(conn, "Employee", {})
    fid1 = create_flag(conn, eid, "business_rule_violation", "high", "hours mismatch")
    fid2 = create_flag(conn, eid, "business_rule_violation", "high", "hours mismatch")
    assert fid1 == fid2
    grouped = open_flags_grouped_by_entity(conn)
    assert len(grouped[eid]) == 1


def test_create_flag_does_not_dedupe_different_reasons(conn):
    """Two different reasons for the same flag_type on one entity are legitimately distinct."""
    eid = create_entity(conn, "Employee", {})
    create_flag(conn, eid, "business_rule_violation", "high", "hours mismatch")
    create_flag(conn, eid, "business_rule_violation", "high", "facility mismatch")
    grouped = open_flags_grouped_by_entity(conn)
    assert len(grouped[eid]) == 2


def test_resolve_flag_raises_on_unknown_id(conn):
    """M13: resolve_flag must not silently report success when nothing was updated."""
    with pytest.raises(ValueError):
        resolve_flag(conn, "not-a-real-flag-id", resolved_by="reviewer1", resolution="n/a")


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


def test_auto_resolve_open_flags_closes_all_matching_open_flags(conn):
    """Stale-flag fix: once an entity's underlying condition clears (e.g. a license
    link succeeds after an earlier referential_orphan flag), the old flag must be
    auto-closed rather than sitting open forever."""
    eid = create_entity(conn, "Employee", {})
    create_flag(conn, eid, "referential_orphan", "high", "no License entity found for license_number='X'")
    auto_resolve_open_flags(conn, eid, "referential_orphan", resolution="license linked on rescan")
    grouped = open_flags_grouped_by_entity(conn)
    assert eid not in grouped
    from sot.flags import get_all_flags_for_entity
    all_flags = get_all_flags_for_entity(conn, eid)
    assert all_flags[0].status == "resolved"
    assert all_flags[0].resolved_by == "system"
    assert all_flags[0].resolution == "license linked on rescan"


def test_auto_resolve_open_flags_is_a_noop_when_nothing_open(conn):
    """Must not raise when there's nothing to resolve -- called unconditionally on every success."""
    eid = create_entity(conn, "Employee", {})
    auto_resolve_open_flags(conn, eid, "referential_orphan", resolution="n/a")  # no error
