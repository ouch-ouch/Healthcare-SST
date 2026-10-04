"""Core models and constants for the SOT (Source of Truth) system."""

# Entity types
ENTITY_TYPES = ("Employee", "License", "Facility", "PayrollRecord", "ShiftAssignment")

# Edge types (verified against actual create_edge()/neighbors() calls in the codebase;
# the spec's "employed_at" is not actually used -- Employee<->Facility is an attrs link, not an edge)
EDGE_TYPES = ("holds_license", "paid_for", "worked_shift")

# Flag types (eight flag types from spec §9)
FLAG_TYPES = (
    "data_source_anomaly",
    "identity_ambiguity",
    "attribute_disagreement",
    "referential_orphan",
    "business_rule_violation",
    "staleness",
    "license_needs_check",
    "partial_period_license_lapse",
)

# SST (Source of Truth) statuses
SST_STATUSES = ("pending", "active", "blocked")

# Payroll statuses
PAYROLL_STATUSES = ("approved", "held", "rejected")
