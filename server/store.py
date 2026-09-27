"""Move Master Sheet data between the loader's tables (MasterData) and the database."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.engine import Connection

from mis_reports.loader import DATE_FIELDS, TEXT_FIELDS, MasterData

from . import db

# MasterData attribute for each transaction kind
ATTR = {"purchase": "purchase", "sales": "sales", "po": "po", "so": "so",
        "debit_notes": "debit_notes", "credit_notes": "credit_notes"}


def _plain(v):
    """A value the database driver accepts: None for blanks, Python numbers and datetimes."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def row_counts(data: MasterData) -> dict:
    return {kind: int(len(getattr(data, attr))) for kind, attr in ATTR.items()} | {
        "opening_creditors": len(data.opening_creditors), "opening_debtors": len(data.opening_debtors)}


def replace_all(conn: Connection, data: MasterData, batch_id: int) -> None:
    """Make `data` the current business data (inside the caller's transaction)."""
    for kind, (table, fields) in db.TXN.items():
        conn.execute(delete(table))
        df = getattr(data, ATTR[kind])
        if df is None or df.empty:
            continue
        cols = ["source_row", *fields]
        rows = []
        extras = df["_extra"].tolist() if "_extra" in df else [None] * len(df)
        for rec, extra in zip(df.reindex(columns=cols).itertuples(index=False), extras):
            row = {c: _plain(v) for c, v in zip(cols, rec)}
            row["source_row"] = int(row["source_row"]) if row["source_row"] is not None else 0
            row["batch_id"] = batch_id
            row["extra"] = extra if isinstance(extra, dict) and extra else None
            rows.append(row)
        conn.execute(table.insert(), rows)
    conn.execute(delete(db.opening_balances))
    opening = [{"batch_id": batch_id, "side": side, "party_key": key, "party": name, "amount": float(amount)}
               for side, book in (("creditor", data.opening_creditors), ("debtor", data.opening_debtors))
               for key, (name, amount) in book.items()]
    if opening:
        conn.execute(db.opening_balances.insert(), opening)


def _frame(conn: Connection, kind: str) -> pd.DataFrame:
    table, fields = db.TXN[kind]
    cols = ["source_row", *fields]
    result = conn.execute(select(*[table.c[c] for c in cols], table.c.extra)
                          .order_by(table.c.source_row, table.c.id))
    df = pd.DataFrame(result.fetchall(), columns=[*cols, "_extra"])
    df["_extra"] = df["_extra"].map(lambda v: v if isinstance(v, dict) else {})
    for c in fields:
        if c in TEXT_FIELDS:
            df[c] = df[c].astype(object).where(df[c].notna(), np.nan)
        elif c in DATE_FIELDS:
            df[c] = pd.to_datetime(df[c], errors="coerce")
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["source_row"] = df["source_row"].astype(int)
    return df


def load_data(conn: Connection) -> MasterData:
    """The current business data, in the same shape load_master() gives for a Master Sheet file."""
    frames = {kind: _frame(conn, kind) for kind in db.TXN}
    opening = {"creditor": {}, "debtor": {}}
    for r in conn.execute(select(db.opening_balances).order_by(db.opening_balances.c.id)):
        opening[r.side][r.party_key] = (r.party, r.amount)
    active = conn.execute(select(db.import_batches.c.warnings)
                          .where(db.import_batches.c.status == "active")).first()
    return MasterData(frames["purchase"], frames["sales"], frames["po"], frames["so"],
                      opening["creditor"], opening["debtor"], list(active.warnings) if active else [],
                      frames["debit_notes"], frames["credit_notes"])


def load_aliases(conn: Connection) -> dict:
    return {r.name_in_sheet: r.report_as for r in conn.execute(select(db.product_aliases))}


def data_version(conn: Connection) -> str:
    """Changes whenever the business data changes; used to cache report results."""
    b = conn.execute(select(db.import_batches.c.id, db.import_batches.c.confirmed_at)
                     .where(db.import_batches.c.status == "active")).first()
    stamp = f"{b.id}:{b.confirmed_at}" if b else "empty"
    return stamp + "|" + str(sorted(load_aliases(conn).items()))


def audit(conn: Connection, user, action: str, **details) -> None:
    conn.execute(db.audit_log.insert().values(
        at=db.utcnow(), user_id=user["id"] if user else None,
        username=user["username"] if user else "", action=action,
        details={k: _plain(v) for k, v in details.items()}))
