"""Tests for Schedule PDF adapter."""

from sot.adapters.schedule import extract_pages, store_schedule_batch, annotate_daily_hours, PageTable
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


def test_hours_by_day_stored_as_top_level_attr_not_nested_in_shifts(conn):
    """C1 regression: hours_by_day must be its own top-level attrs key, not nested inside shifts."""
    pages = extract_pages("tests/fixtures/schedule_sample.pdf")
    annotated = annotate_daily_hours(pages[0])
    store_schedule_batch(conn, annotated)
    shifts = all_entities_of_type(conn, "ShiftAssignment")
    assert shifts
    for s in shifts:
        assert "hours_by_day" in s.attrs
        assert "hours_by_day" not in s.attrs["shifts"]


def test_reingesting_same_schedule_page_does_not_duplicate(conn):
    """I5 regression: re-running store_schedule_batch on the same page must update, not duplicate."""
    pages = extract_pages("tests/fixtures/schedule_sample.pdf")
    annotated = annotate_daily_hours(pages[0])
    store_schedule_batch(conn, annotated)
    store_schedule_batch(conn, annotated)  # same page, fed twice
    shifts = all_entities_of_type(conn, "ShiftAssignment")
    staff_names = [s.attrs["staff_name"] for s in shifts]
    assert len(staff_names) == len(set(staff_names))


def test_empty_page_rows_raises_data_source_anomaly_flag(conn):
    """I6: a page whose table failed to extract (empty rows) must not silently drop data."""
    page = PageTable(facility_name="Harborview Bayside", rows=[], raw_text="")
    store_schedule_batch(conn, page)
    grouped = open_flags_grouped_by_entity(conn)
    anomaly_flags = [f for fs in grouped.values() for f in fs if f.flag_type == "data_source_anomaly"]
    assert len(anomaly_flags) == 1
