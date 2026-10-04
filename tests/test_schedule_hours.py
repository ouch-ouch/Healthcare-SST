"""Tests for schedule shift time parsing and hours computation."""

import pytest
from sot.adapters.schedule import (
    PageTable,
    parse_shift_cell,
    compute_daily_hours,
    annotate_daily_hours,
)


@pytest.mark.parametrize("cell,expected", [
    ("7a-3p", ("07:00", "15:00")),
    ("3p-11p", ("15:00", "23:00")),
    ("11p-7a", ("23:00", "07:00")),
    ("7a-7p", ("07:00", "19:00")),
    ("OFF", None),
    ("7:30a-3:30p", ("07:30", "15:30")),
    (None, None),  # I6: pdfplumber returns None for blank cells -- must not raise
    ("", None),
])
def test_parse_shift_cell(cell, expected):
    assert parse_shift_cell(cell) == expected


@pytest.mark.parametrize("start,end,expected", [
    ("07:00", "15:00", 8.0),
    ("23:00", "07:00", 8.0),   # overnight wraparound
    ("07:00", "19:00", 12.0),
])
def test_compute_daily_hours(start, end, expected):
    assert compute_daily_hours(start, end) == expected


def test_annotate_daily_hours_handles_off():
    page = PageTable(facility_name="Harborview Bayside",
                      rows=[{"Staff": "Marcus Bell", "Role": "CNA",
                             "Mon 09/14": "3p-11p", "Tue 09/15": "OFF"}],
                      raw_text="")
    annotated = annotate_daily_hours(page)
    hours = annotated.rows[0]["hours_by_day"]
    assert hours["Mon 09/14"] == 8.0
    assert hours["Tue 09/15"] == 0.0
