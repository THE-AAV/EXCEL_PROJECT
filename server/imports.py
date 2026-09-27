"""Workbook import: upload -> preview (nothing saved) -> confirm (all rows saved together) -> restore.

Phase 1 imports a whole Master Sheet: confirming it replaces the current business data. The uploaded file is
kept, so an earlier import can be brought back with 'restore'.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from mis_reports.loader import MasterData, load_master, party_key
from mis_reports.reports import Filters, data_checks, product_name

from . import db, store

MAX_UPLOAD_MB = 50
ALLOWED = (".xlsx", ".xlsm")


def safe_name(name: str) -> str:
    base = Path(name or "workbook.xlsx").name
    return re.sub(r"[^A-Za-z0-9._ ()-]+", "_", base)[:200] or "workbook.xlsx"


def read_workbook(path: Path) -> MasterData:
    try:
        return load_master(path)
    except ValueError as e:  # missing sheets / header rows
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"This workbook can't be read: {e}")
    except Exception as e:  # not an Excel file, corrupt zip, ...
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"This file could not be opened as an Excel workbook ({type(e).__name__})")


def _names(df: pd.DataFrame, col: str, key, show) -> dict:
    if df is None or df.empty:
        return {}
    return {key(v): show(v) for v in df[col].dropna() if str(v).strip()}


def summarise(new: MasterData, current: MasterData | None, aliases: dict) -> dict:
    """What the preview shows: rows per sheet, names not seen before, totals and rows to look at."""
    counts = store.row_counts(new)
    old_counts = store.row_counts(current) if current is not None else None

    def fresh(kind_frames, col, key, show=str):
        seen = {}
        for df in kind_frames(current) if current is not None else []:
            seen |= _names(df, col, key, show)
        found = {}
        for df in kind_frames(new):
            found |= _names(df, col, key, show)
        return sorted((v for k, v in found.items() if k not in seen), key=str.lower)

    prod = lambda v: product_name(v, aliases)  # noqa: E731
    checks = data_checks(new, Filters(aliases=aliases))
    return {
        "counts": counts,
        "current_counts": old_counts,
        "new_parties": fresh(lambda d: [d.purchase, d.sales], "party", party_key),
        "new_products": fresh(lambda d: [d.purchase, d.sales], "commodity", prod, prod),
        "totals": {
            "purchase_before_gst": float(pd.to_numeric(new.purchase["amount"], errors="coerce").sum()),
            "sales_before_gst": float(pd.to_numeric(new.sales["amount"], errors="coerce").sum()),
        },
        "checks": store_checks(checks),
    }


def store_checks(checks: pd.DataFrame, limit: int = 200) -> dict:
    rows = checks.head(limit).fillna("").astype(str).to_dict(orient="records")
    return {"count": int(len(checks)), "rows": rows}


def create_preview(engine, settings, user, filename: str, content: bytes) -> dict:
    name = safe_name(filename)
    if not name.lower().endswith(ALLOWED):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please upload an Excel file (.xlsx or .xlsm)")
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"The file is larger than {MAX_UPLOAD_MB} MB")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    path = settings.upload_dir / stored
    path.write_bytes(content)
    try:
        data = read_workbook(path)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    with engine.begin() as conn:
        has_current = conn.execute(select(db.import_batches.c.id)
                                   .where(db.import_batches.c.status == "active")).first() is not None
        current = store.load_data(conn) if has_current else None
        summary = summarise(data, current, store.load_aliases(conn))
        batch_id = conn.execute(db.import_batches.insert().values(
            kind="master_sheet", filename=name, stored_as=stored, status="pending", summary=summary,
            warnings=list(data.warnings), created_by=user["id"], created_at=db.utcnow())).inserted_primary_key[0]
        store.audit(conn, user, "import.preview", batch=batch_id, filename=name)
        return batch_row(conn, batch_id)


def _load_into_db(engine, settings, user, batch, action: str) -> None:
    data = read_workbook(settings.upload_dir / batch.stored_as)
    with engine.begin() as conn:
        store.replace_all(conn, data, batch.id)
        conn.execute(update(db.import_batches).where(db.import_batches.c.status == "active")
                     .values(status="replaced"))
        conn.execute(update(db.import_batches).where(db.import_batches.c.id == batch.id).values(
            status="active", warnings=list(data.warnings), confirmed_by=user["id"], confirmed_at=db.utcnow()))
        store.audit(conn, user, action, batch=batch.id, filename=batch.filename, **{
            k: v for k, v in store.row_counts(data).items()})


def _get(conn: Connection, batch_id: int):
    b = conn.execute(select(db.import_batches).where(db.import_batches.c.id == batch_id)).first()
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return b


def confirm(engine, settings, user, batch_id: int) -> None:
    with engine.connect() as conn:
        b = _get(conn, batch_id)
    if b.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "This import has already been confirmed or discarded")
    _load_into_db(engine, settings, user, b, "import.confirm")


def restore(engine, settings, user, batch_id: int) -> None:
    with engine.connect() as conn:
        b = _get(conn, batch_id)
    if b.status != "replaced":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an earlier, replaced import can be restored")
    _load_into_db(engine, settings, user, b, "import.restore")


def discard(engine, settings, user, batch_id: int) -> None:
    with engine.begin() as conn:
        b = _get(conn, batch_id)
        if b.status != "pending":
            raise HTTPException(status.HTTP_409_CONFLICT, "Only an import that was not confirmed can be discarded")
        conn.execute(update(db.import_batches).where(db.import_batches.c.id == batch_id).values(status="discarded"))
        store.audit(conn, user, "import.discard", batch=batch_id, filename=b.filename)
    (settings.upload_dir / b.stored_as).unlink(missing_ok=True)


def batch_row(conn: Connection, batch_id: int) -> dict:
    return batch_dict(_get(conn, batch_id), _usernames(conn))


def _usernames(conn: Connection) -> dict:
    return {r.id: r.username for r in conn.execute(select(db.users.c.id, db.users.c.username))}


def batch_dict(b, names: dict) -> dict:
    return {"id": b.id, "filename": b.filename, "status": b.status, "summary": b.summary, "warnings": b.warnings,
            "created_by": names.get(b.created_by), "created_at": b.created_at,
            "confirmed_by": names.get(b.confirmed_by), "confirmed_at": b.confirmed_at}


def list_batches(conn: Connection, limit: int = 50) -> list[dict]:
    names = _usernames(conn)
    rows = conn.execute(select(db.import_batches).order_by(db.import_batches.c.id.desc()).limit(limit))
    return [batch_dict(b, names) for b in rows]
