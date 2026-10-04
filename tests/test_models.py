"""M9: ENTITY_TYPES/EDGE_TYPES must match what create_entity/create_edge actually use."""

from sot.models import ENTITY_TYPES, EDGE_TYPES


def test_entity_types_cover_every_real_entity_type():
    for t in ("Employee", "License", "Facility", "PayrollRecord", "ShiftAssignment"):
        assert t in ENTITY_TYPES
    assert "Assignment" not in ENTITY_TYPES


def test_edge_types_match_create_edge_calls():
    for t in ("holds_license", "paid_for", "worked_shift"):
        assert t in EDGE_TYPES
    assert "works_at" not in EDGE_TYPES
    assert "assigned_to" not in EDGE_TYPES
