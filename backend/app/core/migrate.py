"""Additive schema migration for the local SQLite database.

`Base.metadata.create_all()` creates missing tables but never alters an existing one, so
adding a column used to mean deleting `backend/var/data/` and losing every document, chat
report and benchmark run. This adds any column the models declare that the table lacks.

Deliberately narrow: it only ever ADDs nullable (or defaulted) columns. It never drops,
renames or retypes anything, so it cannot lose data; a change that needs more than that
still needs a hand-written step.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Connection, inspect, text
from sqlalchemy.schema import CreateColumn

from app.core.db import Base

logger = logging.getLogger(__name__)


def _default_literal(column: Any) -> str | None:
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def add_missing_columns(conn: Connection) -> list[str]:
    """Returns the "table.column" names it added, for the startup log."""
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all() just made it, with every column
        present = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            ddl = str(CreateColumn(column).compile(dialect=conn.dialect))
            # SQLite refuses ADD COLUMN ... NOT NULL without a default; every column added
            # this way is filled for existing rows by its literal default or left NULL.
            ddl = ddl.replace(" NOT NULL", "")
            literal = _default_literal(column)
            if literal is not None:
                ddl += f" DEFAULT {literal}"
            conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))
            added.append(f"{table.name}.{column.name}")
    if added:
        logger.info("Schema migration added %d column(s): %s", len(added), ", ".join(added))
    return added
