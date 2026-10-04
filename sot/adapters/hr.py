"""HR roster adapter for ingesting employee data."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
import pandas as pd

from sot.graph import create_entity
from sot.flags import create_flag


@dataclass
class IngestResult:
    """Result of ingesting HR roster data."""
    created: int
    flagged: int


def ingest_hr_roster(conn: sqlite3.Connection, csv_path: str) -> IngestResult:
    """
    Ingest HR roster from CSV file and create Employee entities.

    Performs sanity checks:
    - Duplicate employee_id within file → flag as data_source_anomaly
    - hire_date in future → flag as data_source_anomaly
    - license_expiration in past → flag as data_source_anomaly

    Args:
        conn: Database connection.
        csv_path: Path to the HR roster CSV file.

    Returns:
        IngestResult: Count of created entities and flagged entities.
    """
    df = pd.read_csv(csv_path)

    created_count = 0
    flagged_count = 0
    seen_employee_ids = set()
    today = datetime.now().date()

    for idx, row in df.iterrows():
        # Convert row to dict, preserving all CSV columns, and cast to native Python types
        attrs = {k: v.item() if hasattr(v, "item") else v for k, v in row.to_dict().items()}

        # Add required status field
        attrs["status"] = "pending"

        # Create the entity first (even if flagged, per spec)
        entity_id = create_entity(conn, "Employee", attrs)
        created_count += 1

        employee_id = attrs.get("employee_id")
        hire_date_str = attrs.get("hire_date")
        license_expiration_str = attrs.get("license_expiration")

        # Check for duplicate employee_id
        if employee_id in seen_employee_ids:
            create_flag(
                conn,
                entity_id,
                "data_source_anomaly",
                "medium",
                f"Duplicate employee_id in CSV: {employee_id}"
            )
            flagged_count += 1

        seen_employee_ids.add(employee_id)

        # Check hire_date <= today
        if hire_date_str:
            try:
                hire_date = datetime.strptime(hire_date_str, "%Y-%m-%d").date()
                if hire_date > today:
                    create_flag(
                        conn,
                        entity_id,
                        "data_source_anomaly",
                        "medium",
                        f"Hire date is in the future: {hire_date_str}"
                    )
                    flagged_count += 1
            except (ValueError, TypeError):
                pass

        # Check license_expiration >= today
        if license_expiration_str:
            try:
                license_expiration = datetime.strptime(license_expiration_str, "%Y-%m-%d").date()
                if license_expiration < today:
                    create_flag(
                        conn,
                        entity_id,
                        "data_source_anomaly",
                        "medium",
                        f"License expiration is in the past: {license_expiration_str}"
                    )
                    flagged_count += 1
            except (ValueError, TypeError):
                pass

    return IngestResult(created=created_count, flagged=flagged_count)
