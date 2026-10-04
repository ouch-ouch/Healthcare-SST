"""Core models and constants for the SOT (Source of Truth) system."""

# Entity types
ENTITY_TYPES = ("Employee", "License", "Facility", "Assignment")

# Edge types
EDGE_TYPES = ("holds_license", "works_at", "assigned_to")

# Flag types (eight flag types from spec §9)
FLAG_TYPES = (
    "identity_ambiguity",
    "attribute_disagreement",
    "license_needs_check",
    "assignment_conflict",
    "employment_gap",
    "license_type_mismatch",
    "facility_missing_data",
    "role_license_mismatch",
)

# SST (Source of Truth) statuses
SST_STATUSES = ("pending", "active", "blocked")

# Payroll statuses
PAYROLL_STATUSES = ("approved", "held", "rejected")
