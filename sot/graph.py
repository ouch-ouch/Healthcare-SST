"""Graph entities and edge operations for the SOT (Source of Truth) system."""

import sqlite3
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Entity:
    """Represents a graph entity with id, type, and attributes."""
    id: str
    type: str
    attrs: dict


def _now() -> str:
    """Return current ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def create_entity(conn: sqlite3.Connection, type: str, attrs: dict) -> str:
    """
    Create a new entity in the graph.

    Args:
        conn: Database connection.
        type: Entity type (e.g., "Employee", "License", "Facility").
        attrs: Dictionary of entity attributes.

    Returns:
        str: The ID of the created entity.
    """
    entity_id = str(uuid.uuid4())
    now = _now()

    conn.execute(
        """
        INSERT INTO entities (id, type, attrs, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (entity_id, type, json.dumps(attrs), now, now)
    )
    conn.commit()

    return entity_id


def get_entity(conn: sqlite3.Connection, entity_id: str) -> Optional[Entity]:
    """
    Retrieve an entity by ID.

    Args:
        conn: Database connection.
        entity_id: The entity ID to retrieve.

    Returns:
        Entity | None: The entity if found, None otherwise.
    """
    cursor = conn.execute(
        "SELECT id, type, attrs FROM entities WHERE id = ?",
        (entity_id,)
    )
    row = cursor.fetchone()

    if row is None:
        return None

    return Entity(id=row[0], type=row[1], attrs=json.loads(row[2]))


def update_entity_attrs(conn: sqlite3.Connection, entity_id: str, attrs: dict) -> None:
    """
    Shallow-merge attributes into an existing entity.

    Args:
        conn: Database connection.
        entity_id: The entity ID to update.
        attrs: Dictionary of attributes to merge.
    """
    # Get current attributes
    cursor = conn.execute("SELECT attrs FROM entities WHERE id = ?", (entity_id,))
    row = cursor.fetchone()

    if row is None:
        raise ValueError(f"Entity {entity_id} not found")

    # Merge with new attributes
    current_attrs = json.loads(row[0])
    current_attrs.update(attrs)

    # Update the entity
    now = _now()
    conn.execute(
        "UPDATE entities SET attrs = ?, updated_at = ? WHERE id = ?",
        (json.dumps(current_attrs), now, entity_id)
    )
    conn.commit()


def find_entity(conn: sqlite3.Connection, type: str, **attr_filters) -> Optional[Entity]:
    """
    Find an entity by type and exact attribute matches.

    Args:
        conn: Database connection.
        type: Entity type to search for.
        **attr_filters: Keyword arguments representing attribute filters.

    Returns:
        Entity | None: First matching entity if found, None otherwise.
    """
    cursor = conn.execute(
        "SELECT id, type, attrs FROM entities WHERE type = ?",
        (type,)
    )

    for row in cursor.fetchall():
        entity_attrs = json.loads(row[2])
        # Check if all filters match
        if all(entity_attrs.get(k) == v for k, v in attr_filters.items()):
            return Entity(id=row[0], type=row[1], attrs=entity_attrs)

    return None


def create_edge(
    conn: sqlite3.Connection,
    from_id: str,
    to_id: str,
    type: str,
    attrs: Optional[dict] = None
) -> None:
    """
    Create an edge between two entities.

    Args:
        conn: Database connection.
        from_id: Source entity ID.
        to_id: Target entity ID.
        type: Edge type (e.g., "holds_license", "works_at").
        attrs: Optional dictionary of edge attributes.
    """
    now = _now()
    attrs_json = json.dumps(attrs) if attrs is not None else None

    conn.execute(
        """
        INSERT OR REPLACE INTO edges (from_id, to_id, type, attrs, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (from_id, to_id, type, attrs_json, now)
    )
    conn.commit()


def neighbors(conn: sqlite3.Connection, entity_id: str, edge_type: str) -> list[Entity]:
    """
    Get all neighboring entities connected by a specific edge type.

    Args:
        conn: Database connection.
        entity_id: Source entity ID.
        edge_type: Type of edges to follow.

    Returns:
        list[Entity]: List of neighboring entities.
    """
    cursor = conn.execute(
        """
        SELECT e.id, e.type, e.attrs
        FROM entities e
        JOIN edges ed ON e.id = ed.to_id
        WHERE ed.from_id = ? AND ed.type = ?
        """,
        (entity_id, edge_type)
    )

    result = []
    for row in cursor.fetchall():
        result.append(Entity(id=row[0], type=row[1], attrs=json.loads(row[2])))

    return result


def remove_edge(conn: sqlite3.Connection, from_id: str, to_id: str, type: str) -> None:
    """
    Remove an edge between two entities.

    Args:
        conn: Database connection.
        from_id: Source entity ID.
        to_id: Target entity ID.
        type: Edge type.
    """
    conn.execute(
        "DELETE FROM edges WHERE from_id = ? AND to_id = ? AND type = ?",
        (from_id, to_id, type)
    )
    conn.commit()
