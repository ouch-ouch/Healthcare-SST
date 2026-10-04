"""Rule engine for the SOT (Source of Truth) system."""

import sqlite3
from dataclasses import dataclass
from typing import Callable, Literal
from sot.graph import Entity, update_entity_attrs
from sot.flags import create_flag


@dataclass
class Rule:
    """Represents a rule that can gate or flag an entity."""
    id: str
    applies_to: str
    type: Literal["gate", "flag"]
    check: Callable[[Entity, sqlite3.Connection], bool]
    on_fail: dict


def evaluate(conn: sqlite3.Connection, entity: Entity, rule_list: list[Rule]) -> None:
    """
    Evaluate a list of rules against an entity.

    For each rule:
    - Skip if rule.applies_to != entity.type
    - Call rule.check(entity, conn)
    - If check returns False (failure), create a flag with on_fail details
    - If rule.type == "gate", also update entity status to on_fail["set_status"]

    Args:
        conn: Database connection.
        entity: The entity to evaluate rules against.
        rule_list: List of Rule objects to evaluate.
    """
    for rule in rule_list:
        # Skip rules that don't apply to this entity type
        if rule.applies_to != entity.type:
            continue

        # Evaluate the rule check
        if not rule.check(entity, conn):
            # Rule failed - create a flag
            create_flag(
                conn,
                entity.id,
                rule.on_fail["flag_type"],
                rule.on_fail["severity"],
                rule.on_fail["reason"]
            )

            # If it's a gate rule, also update the entity status
            if rule.type == "gate":
                update_entity_attrs(conn, entity.id, {"status": rule.on_fail["set_status"]})
