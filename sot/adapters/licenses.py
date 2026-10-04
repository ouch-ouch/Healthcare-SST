"""Licenses adapter for ingesting license data."""

import sqlite3
from datetime import datetime
import pandas as pd

from sot.graph import create_entity, find_entity, update_entity_attrs
from sot.flags import create_flag
from sot.adapters.hr import IngestResult


def ingest_licenses(conn: sqlite3.Connection, csv_path: str) -> IngestResult:
    """
    Ingest licenses from CSV file and create License entities.

    Performs sanity checks:
    - expiration_date in past → flag as data_source_anomaly
    - last_verified in future → flag as data_source_anomaly
    - Duplicate license_number within file → flag as data_source_anomaly

    Args:
        conn: Database connection.
        csv_path: Path to the licenses CSV file.

    Returns:
        IngestResult: Count of created entities and flagged entities.
    """
    df = pd.read_csv(csv_path)

    created_count = 0
    flagged_count = 0
    seen_license_numbers = set()
    today = datetime.now().date()

    for idx, row in df.iterrows():
        # Convert row to dict, preserving all CSV columns, and cast to native Python types
        attrs = {k: v.item() if hasattr(v, "item") else v for k, v in row.to_dict().items()}

        # Create the entity first (even if flagged, per spec), unless it already
        # exists (same license_number re-ingested) -- then update it in place.
        existing = find_entity(conn, "License", license_number=attrs.get("license_number"))
        if existing is not None:
            update_entity_attrs(conn, existing.id, attrs)
            entity_id = existing.id
        else:
            entity_id = create_entity(conn, "License", attrs)
        created_count += 1

        license_number = attrs.get("license_number")
        expiration_date_str = attrs.get("expiration_date")
        last_verified_str = attrs.get("last_verified")

        # Check for duplicate license_number
        if license_number in seen_license_numbers:
            create_flag(
                conn,
                entity_id,
                "data_source_anomaly",
                "medium",
                f"Duplicate license_number in CSV: {license_number}"
            )
            flagged_count += 1

        seen_license_numbers.add(license_number)

        # Check expiration_date >= today
        if expiration_date_str:
            try:
                expiration_date = datetime.strptime(expiration_date_str, "%Y-%m-%d").date()
                if expiration_date < today:
                    create_flag(
                        conn,
                        entity_id,
                        "data_source_anomaly",
                        "medium",
                        f"License expiration is in the past: {expiration_date_str}"
                    )
                    flagged_count += 1
            except (ValueError, TypeError):
                pass

        # Check last_verified <= today
        if last_verified_str:
            try:
                last_verified = datetime.strptime(last_verified_str, "%Y-%m-%d").date()
                if last_verified > today:
                    create_flag(
                        conn,
                        entity_id,
                        "data_source_anomaly",
                        "medium",
                        f"Last verified date is in the future: {last_verified_str}"
                    )
                    flagged_count += 1
            except (ValueError, TypeError):
                pass

    return IngestResult(created=created_count, flagged=flagged_count)
