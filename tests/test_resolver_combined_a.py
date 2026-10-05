"""Tests for the Combined A resolver: corroboration, precedence, SST gate."""

from sot.graph import create_entity, create_edge, get_entity, neighbors, update_entity_attrs
from sot.flags import open_flags_grouped_by_entity
from sot.resolver import attach_license, corroborate_combined_a
from sot.combiner import build_combined_a


def test_attach_license_creates_edge_on_number_match(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "license_number": "RN-551203"})
    create_entity(conn, "License", {"license_number": "RN-551203", "name_on_license": "REYES, SOFIA",
                                     "expiration_date": "2027-05-31", "license_type": "RN"})
    attach_license(conn, emp)
    assert len(neighbors(conn, emp, "holds_license")) == 1


def test_license_not_found_raises_referential_orphan(conn):
    emp = create_entity(conn, "Employee", {"license_number": "RN-999999"})
    attach_license(conn, emp)
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[emp][0].flag_type == "referential_orphan"


def test_attach_license_rescan_does_not_duplicate_orphan_flag(conn):
    # Simulates the CLI's idempotent rescan: attach_license is called again on an
    # Employee that still doesn't resolve. Should not accumulate a second flag.
    emp = create_entity(conn, "Employee", {"license_number": "RN-999999"})
    attach_license(conn, emp)
    attach_license(conn, emp)
    grouped = open_flags_grouped_by_entity(conn)
    orphan_flags = [f for f in grouped[emp] if f.flag_type == "referential_orphan"]
    assert len(orphan_flags) == 1


def test_attach_license_auto_resolves_stale_orphan_flag_once_license_appears(conn):
    """Stale-flag fix: a referential_orphan from before the License existed must
    auto-close once a matching License shows up and the edge is created."""
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "license_number": "RN-551203"})
    attach_license(conn, emp)  # fails: no License yet
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[emp][0].flag_type == "referential_orphan"

    create_entity(conn, "License", {"license_number": "RN-551203", "name_on_license": "REYES, SOFIA",
                                     "expiration_date": "2027-05-31", "license_type": "RN"})
    attach_license(conn, emp)  # rescan: now succeeds

    assert len(neighbors(conn, emp, "holds_license")) == 1
    grouped = open_flags_grouped_by_entity(conn)
    assert emp not in grouped  # the earlier orphan flag is no longer open


def test_corroboration_name_mismatch_flags_identity_ambiguity(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes",
                                            "license_number": "RN-551203"})
    lic = create_entity(conn, "License", {"license_number": "RN-551203", "name_on_license": "BELL, MARCUS"})
    corroborate_combined_a(conn, emp, lic)
    grouped = open_flags_grouped_by_entity(conn)
    f = grouped[emp][0]
    assert f.flag_type == "identity_ambiguity"
    assert "name" in f.reason


def test_combined_a_uses_soonest_expiration(conn):
    emp = create_entity(conn, "Employee", {"license_expiration": "2027-05-31"})
    lic = create_entity(conn, "License", {"expiration_date": "2026-12-31"})
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["resolved_expiration"] == "2026-12-31"


def test_combined_a_sets_status_active_when_clean_and_licensed(conn):
    """I3: a fully clean, license-verified employee must reach 'active', not stay 'pending'."""
    emp = create_entity(conn, "Employee", {"status": "pending", "license_expiration": "2099-01-01"})
    lic = create_entity(conn, "License", {"expiration_date": "2099-01-01"})
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["status"] == "active"


def test_combined_a_clears_blocked_after_license_renewal(conn):
    """I3: a previously-blocked employee must clear to 'active' once the license is renewed."""
    emp = create_entity(conn, "Employee", {"status": "blocked", "license_expiration": "2020-01-01"})
    lic = create_entity(conn, "License", {"expiration_date": "2020-01-01"})
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["status"] == "blocked"  # still expired -> still blocked

    update_entity_attrs(conn, emp, {"license_expiration": "2099-01-01"})
    update_entity_attrs(conn, lic, {"expiration_date": "2099-01-01"})
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["status"] == "active"


def test_combined_a_sets_display_name_from_hr(conn):
    emp = create_entity(conn, "Employee", {"first_name": "Sofia", "last_name": "Reyes"})
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["display_name"] == "Sofia Reyes"


def test_blocked_when_resolved_expiration_in_past(conn):
    emp = create_entity(conn, "Employee", {"license_expiration": "2020-01-01"})
    lic = create_entity(conn, "License", {"expiration_date": "2020-01-01"})
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    assert get_entity(conn, emp).attrs["status"] == "blocked"
    grouped = open_flags_grouped_by_entity(conn)
    assert grouped[emp][0].flag_type == "license_needs_check"


def test_role_license_mismatch_flagged(conn):
    emp = create_entity(conn, "Employee", {"job_title": "Registered Nurse"})
    lic = create_entity(conn, "License", {"license_type": "CNA", "expiration_date": "2099-01-01"})
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "attribute_disagreement" for f in grouped[emp])


def test_stale_last_verified_flagged(conn):
    emp = create_entity(conn, "Employee", {"job_title": "Registered Nurse", "license_expiration": "2099-01-01"})
    lic = create_entity(conn, "License", {"license_type": "RN", "expiration_date": "2099-01-01",
                                           "last_verified": "2020-01-01"})  # far past the 180-day window
    create_edge(conn, emp, lic, "holds_license")
    build_combined_a(conn, emp)
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "staleness" for f in grouped[emp])
