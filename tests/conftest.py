import pytest
import sqlite3
from sot.db import init_db
from sot.graph import Entity


@pytest.fixture
def conn():
    """Provide an in-memory SQLite database initialized with the SOT schema."""
    return init_db(":memory:")


def all_entities_of_type(conn: sqlite3.Connection, type: str) -> list[Entity]:
    """Test-only helper to fetch all entities of a given type."""
    from sot.graph import Entity
    import json

    cursor = conn.execute("SELECT id, type, attrs FROM entities WHERE type = ?", (type,))
    return [Entity(id=row[0], type=row[1], attrs=json.loads(row[2])) for row in cursor.fetchall()]
