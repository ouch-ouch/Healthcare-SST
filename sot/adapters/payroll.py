"""Payroll adapter for ingesting payroll data."""

import sqlite3
from datetime import datetime
import pandas as pd

from sot.graph import create_entity
from sot.flags import create_flag
from sot.adapters.hr import IngestResult


def ingest_payroll(conn: sqlite3.Connection, csv_path: str) -> IngestResult:
    """
    Ingest payroll data from CSV file and create PayrollRecord entities.

    PayrollRecord entities are attach-only facts that represent raw payroll data.
    They do NOT originate or link to Employee entities (per Global Constraints —
    only HR roster may originate Employee entities; linking is Task 9's job).

    Performs sanity check:
    - period_start or period_end in future → flag as data_source_anomaly

    Args:
        conn: Database connection.
        csv_path: Path to the payroll CSV file.

    Returns:
        IngestResult: Count of created entities and flagged entities.
    """
    df = pd.read_csv(csv_path)

    created_count = 0
    flagged_count = 0
    today = datetime.now().date()

    for idx, row in df.iterrows():
        # Convert row to dict, preserving all CSV columns, and cast to native Python types
        attrs = {k: v.item() if hasattr(v, "item") else v for k, v in row.to_dict().items()}

        # Create the entity first (even if flagged, per spec)
        entity_id = create_entity(conn, "PayrollRecord", attrs)
        created_count += 1

        period_start_str = attrs.get("period_start")
        period_end_str = attrs.get("period_end")

        # Check if period_start or period_end are in the future
        has_future_period = False

        if period_start_str:
            try:
                period_start = datetime.strptime(period_start_str, "%Y-%m-%d").date()
                if period_start > today:
                    has_future_period = True
            except (ValueError, TypeError):
                pass

        if period_end_str:
            try:
                period_end = datetime.strptime(period_end_str, "%Y-%m-%d").date()
                if period_end > today:
                    has_future_period = True
            except (ValueError, TypeError):
                pass

        if has_future_period:
            create_flag(
                conn,
                entity_id,
                "data_source_anomaly",
                "medium",
                f"Payroll period contains future dates: period_start={period_start_str}, period_end={period_end_str}"
            )
            flagged_count += 1

    return IngestResult(created=created_count, flagged=flagged_count)
