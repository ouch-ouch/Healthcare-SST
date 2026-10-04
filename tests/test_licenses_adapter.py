"""Tests for Licenses adapter."""

import pytest
from sot.adapters.licenses import ingest_licenses
from sot.graph import find_entity
from sot.flags import open_flags_grouped_by_entity


def test_ingest_creates_license_entities(conn):
    """Test that ingest_licenses creates License entities from CSV."""
    result = ingest_licenses(conn, "tests/fixtures/licenses.csv")
    assert result.created == 2
    lic = find_entity(conn, "License", license_number="RN-551203")
    assert lic is not None
    assert lic.attrs["license_type"] == "RN"


def test_expiration_in_past_flagged(conn):
    """Test that expiration_date in the past is flagged as data_source_anomaly."""
    ingest_licenses(conn, "tests/fixtures/licenses_past_expiration.csv")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "data_source_anomaly" for flags in grouped.values() for f in flags)


def test_last_verified_in_future_flagged(conn):
    """Test that last_verified in the future is flagged as data_source_anomaly."""
    ingest_licenses(conn, "tests/fixtures/licenses_future_verified.csv")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "data_source_anomaly" for flags in grouped.values() for f in flags)


def test_duplicate_license_number_flagged(conn):
    """Test that duplicate license_number within file is flagged as data_source_anomaly."""
    ingest_licenses(conn, "tests/fixtures/licenses_duplicate_number.csv")
    grouped = open_flags_grouped_by_entity(conn)
    assert any(f.flag_type == "data_source_anomaly" for flags in grouped.values() for f in flags)
