"""Flag management for the SOT (Source of Truth) system."""

import sqlite3
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Flag:
    """Represents a flag on an entity."""
    id: str
    entity_id: str
    flag_type: str
    severity: str
    reason: str
    detail: dict
    status: str
    resolved_by: Optional[str]
    resolution: Optional[str]
    resolved_at: Optional[str]
    created_at: str


def _now() -> str:
    """Return current ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def create_flag(
    conn: sqlite3.Connection,
    entity_id: str,
    flag_type: str,
    severity: str,
    reason: str,
    detail: Optional[dict] = None
) -> str:
    """
    Create a new flag on an entity.

    Args:
        conn: Database connection.
        entity_id: ID of the entity being flagged.
        flag_type: Type of flag (e.g., "identity_ambiguity").
        severity: Severity level (e.g., "high", "medium", "low").
        reason: Human-readable reason for the flag.
        detail: Optional dictionary of additional details.

    Returns:
        str: The ID of the created flag.
    """
    flag_id = str(uuid.uuid4())
    now = _now()
    detail_json = json.dumps(detail) if detail is not None else None

    conn.execute(
        """
        INSERT INTO flags (id, entity_id, flag_type, severity, reason, detail, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (flag_id, entity_id, flag_type, severity, reason, detail_json, "open", now)
    )
    conn.commit()

    return flag_id


def open_flags_grouped_by_entity(conn: sqlite3.Connection) -> dict[str, list[Flag]]:
    """
    Get all open flags grouped by entity ID.

    Returns:
        dict[str, list[Flag]]: Dictionary mapping entity_id to list of open Flag objects.
    """
    cursor = conn.execute(
        "SELECT id, entity_id, flag_type, severity, reason, detail, status, resolved_by, resolution, resolved_at, created_at FROM flags WHERE status = 'open' ORDER BY entity_id, created_at"
    )

    result = {}
    for row in cursor.fetchall():
        flag = Flag(
            id=row[0],
            entity_id=row[1],
            flag_type=row[2],
            severity=row[3],
            reason=row[4],
            detail=json.loads(row[5]) if row[5] else {},
            status=row[6],
            resolved_by=row[7],
            resolution=row[8],
            resolved_at=row[9],
            created_at=row[10]
        )
        if flag.entity_id not in result:
            result[flag.entity_id] = []
        result[flag.entity_id].append(flag)

    return result


def resolve_flag(
    conn: sqlite3.Connection,
    flag_id: str,
    resolved_by: str,
    resolution: str
) -> None:
    """
    Mark a flag as resolved.

    Args:
        conn: Database connection.
        flag_id: ID of the flag to resolve.
        resolved_by: Username or ID of the person resolving the flag.
        resolution: Text describing how the flag was resolved.
    """
    now = _now()
    conn.execute(
        """
        UPDATE flags SET status = ?, resolved_by = ?, resolution = ?, resolved_at = ? WHERE id = ?
        """,
        ("resolved", resolved_by, resolution, now, flag_id)
    )
    conn.commit()


def get_all_flags_for_entity(conn: sqlite3.Connection, entity_id: str) -> list[Flag]:
    """
    Get all flags (open and resolved) for an entity.

    Args:
        conn: Database connection.
        entity_id: ID of the entity.

    Returns:
        list[Flag]: List of all Flag objects for the entity.
    """
    cursor = conn.execute(
        "SELECT id, entity_id, flag_type, severity, reason, detail, status, resolved_by, resolution, resolved_at, created_at FROM flags WHERE entity_id = ? ORDER BY created_at",
        (entity_id,)
    )

    result = []
    for row in cursor.fetchall():
        flag = Flag(
            id=row[0],
            entity_id=row[1],
            flag_type=row[2],
            severity=row[3],
            reason=row[4],
            detail=json.loads(row[5]) if row[5] else {},
            status=row[6],
            resolved_by=row[7],
            resolution=row[8],
            resolved_at=row[9],
            created_at=row[10]
        )
        result.append(flag)

    return result
