"""Database initialization and schema management for the SOT (Source of Truth) system."""

import sqlite3
import json
from typing import Optional


def init_db(path: str) -> sqlite3.Connection:
    """
    Initialize the SOT database schema and seed known entities.

    Creates tables for entities, edges, and flags if they don't exist.
    Seeds two known Facility entities (Harborview Bayside and Harborview Riverdale)
    if they don't already exist (idempotent).

    Args:
        path: Path to SQLite database file. Use ":memory:" for in-memory DB.

    Returns:
        sqlite3.Connection: Connection to the initialized database.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    # Create entities table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            attrs TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Create edges table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            type TEXT NOT NULL,
            attrs TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (from_id, to_id, type),
            FOREIGN KEY (from_id) REFERENCES entities(id),
            FOREIGN KEY (to_id) REFERENCES entities(id)
        )
    """)

    # Create flags table (from Task 2 schema, created here since both are schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flags (
            id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            flag_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT,
            detail TEXT,
            status TEXT,
            resolved_by TEXT,
            resolution TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (entity_id) REFERENCES entities(id)
        )
    """)

    conn.commit()

    # Seed known facilities (idempotent - only if they don't exist)
    from sot.graph import find_entity, create_entity

    bayside_name = "Harborview Bayside"
    riverdale_name = "Harborview Riverdale"

    if find_entity(conn, "Facility", name=bayside_name) is None:
        create_entity(conn, "Facility", {"name": bayside_name})

    if find_entity(conn, "Facility", name=riverdale_name) is None:
        create_entity(conn, "Facility", {"name": riverdale_name})

    return conn
