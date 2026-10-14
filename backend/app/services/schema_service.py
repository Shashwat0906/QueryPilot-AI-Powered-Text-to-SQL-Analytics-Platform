"""Schema inspection.

Discovers the business database's tables, columns, keys and relationships with
SQLAlchemy's `inspect()` (works for SQLite today and Postgres later), keeps
only the approved tables, and turns them into:

* a structured `DatabaseSchema` for the API / frontend, and
* a compact text block for the LLM prompt (`to_prompt_context`).

The schema also gets a *version* - a hash of its structure. The cache uses it
in its keys, so if a column is added or renamed, old cached answers can no
longer be returned.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field

from sqlalchemy import Engine, inspect, text

from app.db import semantic_notes


@dataclass(frozen=True)
class ForeignKey:
    column: str
    references_table: str
    references_column: str


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool
    primary_key: bool
    note: str | None = None
    sample_values: list[str] | None = None


@dataclass(frozen=True)
class Table:
    name: str
    columns: list[Column]
    primary_key: list[str]
    foreign_keys: list[ForeignKey]
    row_count: int
    note: str | None = None


@dataclass(frozen=True)
class DatabaseSchema:
    tables: list[Table]
    version: str
    data_reference_date: str | None = None
    business_rules: list[str] = field(default_factory=list)
    # Tables that exist but are NOT approved. Never sent to the LLM or the API;
    # the validator uses it to classify a query on them as a security violation.
    hidden_table_names: frozenset[str] = frozenset()

    def table(self, name: str) -> Table | None:
        lowered = name.lower()
        return next((t for t in self.tables if t.name.lower() == lowered), None)

    @property
    def table_names(self) -> set[str]:
        return {t.name.lower() for t in self.tables}

    def column(self, table: str, name: str) -> Column | None:
        found = self.table(table)
        if not found:
            return None
        lowered = name.lower()
        return next((c for c in found.columns if c.name.lower() == lowered), None)

    def columns_of(self, table: str) -> set[str]:
        found = self.table(table)
        return {c.name.lower() for c in found.columns} if found else set()

    @property
    def relationships(self) -> list[dict[str, str]]:
        return [
            {
                "from_table": t.name,
                "from_column": fk.column,
                "to_table": fk.references_table,
                "to_column": fk.references_column,
            }
            for t in self.tables
            for fk in t.foreign_keys
        ]

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "data_reference_date": self.data_reference_date,
            "business_rules": self.business_rules,
            "tables": [asdict(t) for t in self.tables],
            "relationships": self.relationships,
        }

    def to_prompt_context(self) -> str:
        """Compact, token-cheap description of the schema for the LLM.

        Example line:
            orders(order_id INTEGER PK, customer_id INTEGER FK->customers.customer_id, ...)
        No data rows are sent - only structure, notes and a handful of distinct
        values for small categorical columns (so the model spells them right).
        """

        lines: list[str] = []
        for t in self.tables:
            fks = {fk.column: fk for fk in t.foreign_keys}
            parts = []
            for c in t.columns:
                piece = f"{c.name} {c.type}"
                if c.primary_key:
                    piece += " PK"
                if c.name in fks:
                    fk = fks[c.name]
                    piece += f" FK->{fk.references_table}.{fk.references_column}"
                if c.sample_values:
                    piece += " {" + ", ".join(repr(v) for v in c.sample_values) + "}"
                parts.append(piece)
            header = f"{t.name}({', '.join(parts)})"
            if t.note:
                header += f"  -- {t.note}"
            lines.append(header)
            for c in t.columns:
                if c.note:
                    lines.append(f"  * {t.name}.{c.name}: {c.note}")
        if self.business_rules:
            lines.append("Business rules:")
            lines.extend(f"  - {rule}" for rule in self.business_rules)
        if self.data_reference_date:
            lines.append(
                f"Data reference date: {self.data_reference_date} (the newest order). "
                "Interpret relative periods relative to this date, not today's date. "
                "'Last N months' means the N most recent calendar months including the "
                "reference month (e.g. order_date >= date(reference, 'start of month', "
                "'-(N-1) months'))."
            )
        return "\n".join(lines)


def _compute_version(tables: list[Table]) -> str:
    structure = [
        {
            "name": t.name,
            "columns": [(c.name, c.type, c.nullable, c.primary_key) for c in t.columns],
            "fks": [asdict(fk) for fk in t.foreign_keys],
        }
        for t in tables
    ]
    digest = hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest()
    return digest[:16]


def inspect_schema(engine: Engine, approved_tables: list[str], sample_limit: int = 12) -> DatabaseSchema:
    inspector = inspect(engine)
    available = inspector.get_table_names()
    approved = {name.lower() for name in approved_tables}
    selected = [
        name
        for name in available
        if not name.startswith("sqlite_") and (not approved or name.lower() in approved)
    ]

    tables: list[Table] = []
    with engine.connect() as conn:
        for name in selected:
            pk_cols = inspector.get_pk_constraint(name).get("constrained_columns") or []
            fks = [
                ForeignKey(col, fk["referred_table"], ref_col)
                for fk in inspector.get_foreign_keys(name)
                for col, ref_col in zip(fk["constrained_columns"], fk["referred_columns"])
            ]
            col_notes = semantic_notes.COLUMN_NOTES.get(name, {})
            columns = []
            for col in inspector.get_columns(name):
                col_type = str(col["type"])
                samples = None
                if sample_limit and col_type.upper() in ("TEXT", "VARCHAR") and col["name"] not in pk_cols:
                    samples = _low_cardinality_values(conn, name, col["name"], sample_limit)
                columns.append(
                    Column(
                        name=col["name"],
                        type=col_type,
                        nullable=bool(col["nullable"]),
                        primary_key=col["name"] in pk_cols,
                        note=col_notes.get(col["name"]),
                        sample_values=samples,
                    )
                )
            row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
            tables.append(
                Table(
                    name=name,
                    columns=columns,
                    primary_key=pk_cols,
                    foreign_keys=fks,
                    row_count=row_count,
                    note=semantic_notes.TABLE_NOTES.get(name),
                )
            )

        reference_date = None
        orders = next((t for t in tables if t.name == "orders"), None)
        if orders and any(c.name == "order_date" for c in orders.columns):
            reference_date = conn.execute(text("SELECT MAX(order_date) FROM orders")).scalar()

    return DatabaseSchema(
        tables=tables,
        version=_compute_version(tables),
        data_reference_date=str(reference_date) if reference_date else None,
        business_rules=list(semantic_notes.BUSINESS_RULES),
        hidden_table_names=frozenset(n.lower() for n in available if n not in selected),
    )


def _low_cardinality_values(conn, table: str, column: str, limit: int) -> list[str] | None:
    """Return distinct values if the column has at most `limit` of them."""

    rows = conn.execute(
        text(f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT :n'),
        {"n": limit + 1},
    ).fetchall()
    if len(rows) > limit:
        return None
    return sorted(str(r[0]) for r in rows)


class SchemaService:
    """Caches the inspected schema and notices when it changes."""

    def __init__(self, engine: Engine, approved_tables: list[str], sample_limit: int = 12):
        self._engine = engine
        self._approved = approved_tables
        self._sample_limit = sample_limit
        self._schema: DatabaseSchema | None = None
        self._lock = threading.Lock()
        self._listeners: list = []

    def on_change(self, callback) -> None:
        """Register `callback(old_version, new_version)` (used by the cache)."""
        self._listeners.append(callback)

    def get_schema(self) -> DatabaseSchema:
        with self._lock:
            if self._schema is None:
                self._schema = inspect_schema(self._engine, self._approved, self._sample_limit)
            return self._schema

    def refresh(self) -> DatabaseSchema:
        """Re-inspect the database; notify listeners if the structure changed."""
        with self._lock:
            old = self._schema
            self._schema = inspect_schema(self._engine, self._approved, self._sample_limit)
            new = self._schema
        if old is not None and old.version != new.version:
            for callback in self._listeners:
                callback(old.version, new.version)
        return new
