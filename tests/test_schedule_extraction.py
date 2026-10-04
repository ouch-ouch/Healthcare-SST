"""Tests for Schedule PDF adapter."""

from sot.adapters.schedule import extract_pages, store_schedule_batch
from tests.conftest import all_entities_of_type
from sot.flags import open_flags_grouped_by_entity


def test_extract_pages_finds_known_facility(conn):
    pages = extract_pages("tests/fixtures/schedule_sample.pdf")
    assert pages[0].facility_name == "Harborview Bayside"
    assert len(pages[0].rows) > 0


def test_unresolvable_facility_holds_batch(conn):
    pages = extract_pages("tests/fixtures/schedule_unknown_facility.pdf")
    store_schedule_batch(conn, pages[0])
    shifts = [e for e in all_entities_of_type(conn, "ShiftAssignment")]
    assert all(s.attrs["batch_status"] == "held" for s in shifts)
    grouped = open_flags_grouped_by_entity(conn)
    anomaly_flags = [f for fs in grouped.values() for f in fs if f.flag_type == "data_source_anomaly"]
    assert len(anomaly_flags) == 1  # one flag for the whole page, not per row


def test_known_facility_links_batch(conn):
    pages = extract_pages("tests/fixtures/schedule_sample.pdf")
    store_schedule_batch(conn, pages[0])
    shifts = [e for e in all_entities_of_type(conn, "ShiftAssignment")]
    assert all(s.attrs["batch_status"] == "linked" for s in shifts)
