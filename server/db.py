"""Database tables.

The transaction tables mirror the Master Sheet: one table per sheet (Purchase, Sales, PO, SO, Debit Notes,
Credit Notes) with one column per field the reports use, named like the fields in mis_reports/loader.py.
`source_row` keeps the row number the entry has in the Master Sheet, so debit / credit notes still point
at their bill and the Master Sheet can be rebuilt in the same order.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table,
                        Text, create_engine, event, select)
from sqlalchemy.engine import Engine

from mis_reports.loader import (DATE_FIELDS, NOTE_COLUMNS, ORDER_COLUMNS, PURCHASE_COLUMNS, SALES_COLUMNS,
                                TEXT_FIELDS)

metadata = MetaData()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLES = ("admin", "editor", "viewer")

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(64), nullable=False, unique=True),
    Column("full_name", String(128), nullable=False, default=""),
    Column("password_hash", String(128), nullable=False),
    Column("role", String(16), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("failed_logins", Integer, nullable=False, default=0),
    Column("locked_until", DateTime),
    Column("token_version", Integer, nullable=False, default=0),  # bumped to sign a user out everywhere
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("last_login", DateTime),
)

import_batches = Table(
    "import_batches", metadata,
    Column("id", Integer, primary_key=True),
    Column("kind", String(32), nullable=False),  # 'master_sheet'
    Column("filename", String(255), nullable=False),
    Column("stored_as", String(255), nullable=False),
    # pending (previewed, not saved) -> active (current data) -> replaced (a later import took over)
    # or discarded (never confirmed)
    Column("status", String(16), nullable=False),
    Column("summary", JSON, nullable=False, default=dict),
    Column("warnings", JSON, nullable=False, default=list),
    Column("created_by", Integer, ForeignKey("users.id")),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("confirmed_by", Integer, ForeignKey("users.id")),
    Column("confirmed_at", DateTime),
)

audit_log = Table(
    "audit_log", metadata,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime, nullable=False, default=utcnow),
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("username", String(64), nullable=False, default=""),
    Column("action", String(64), nullable=False),
    Column("details", JSON, nullable=False, default=dict),
)

product_aliases = Table(
    "product_aliases", metadata,
    Column("name_in_sheet", String(255), primary_key=True),
    Column("report_as", String(255), nullable=False),
)

opening_balances = Table(
    "opening_balances", metadata,
    Column("id", Integer, primary_key=True),
    Column("batch_id", Integer, ForeignKey("import_batches.id")),
    Column("side", String(16), nullable=False),  # 'creditor' or 'debtor'
    Column("party_key", String(255), nullable=False),
    Column("party", String(255), nullable=False),
    Column("amount", Float, nullable=False),
)


def _field_column(name: str) -> Column:
    if name in TEXT_FIELDS:
        return Column(name, Text)
    if name in DATE_FIELDS:
        return Column(name, DateTime)
    return Column(name, Float)


def _txn_table(name: str, fields: dict) -> Table:
    return Table(
        name, metadata,
        Column("id", Integer, primary_key=True),
        Column("batch_id", Integer, ForeignKey("import_batches.id"), index=True),
        Column("source_row", Integer, nullable=False),
        *[_field_column(f) for f in fields],
    )


# kind -> (table, column map as in the loader)
TXN = {
    "purchase": (_txn_table("purchase_rows", PURCHASE_COLUMNS), PURCHASE_COLUMNS),
    "sales": (_txn_table("sales_rows", SALES_COLUMNS), SALES_COLUMNS),
    "po": (_txn_table("po_rows", ORDER_COLUMNS), ORDER_COLUMNS),
    "so": (_txn_table("so_rows", ORDER_COLUMNS), ORDER_COLUMNS),
    "debit_notes": (_txn_table("debit_note_rows", NOTE_COLUMNS), NOTE_COLUMNS),
    "credit_notes": (_txn_table("credit_note_rows", NOTE_COLUMNS), NOTE_COLUMNS),
}


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    else:
        engine = create_engine(url, pool_pre_ping=True)
    return engine


def init_db(engine: Engine, alias_seed: dict | None = None) -> None:
    """Create missing tables; on a fresh database copy the product name mapping from the CSV file."""
    metadata.create_all(engine)
    with engine.begin() as conn:
        if alias_seed and conn.execute(select(product_aliases).limit(1)).first() is None:
            conn.execute(product_aliases.insert(),
                         [{"name_in_sheet": k, "report_as": v} for k, v in alias_seed.items()])
