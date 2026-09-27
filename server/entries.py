"""Entering transactions in the web app: orders, invoices, debit / credit notes, expenses, payments and receipts.

The same entry code as the desktop app (mis_reports/entries.py) does the work, so both apps number contracts,
split expenses, update orders and mark bills paid exactly alike:

    database -> Master Sheet workbook -> entry written into it -> read back -> saved as the new data

Each entry is kept as a version of the data (an import batch of kind 'entry', with its workbook), so
'Undo last entry' brings back the version before it. Entries are made one at a time; a form sends the data
version it was filled in against, and a save made after someone else's change is refused, so bill and order
rows always point at what the person saw.
"""
from __future__ import annotations

import io
import os
import tempfile
import threading
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy import delete, select, update

from mis_reports import reports as R
from mis_reports.entries import (EXPENSE_FIELDS, NOTE_EXPENSES, NOTE_REASONS, PRE_BILL_FIELDS, EntryError,
                                 MasterFile, next_number)
from mis_reports.loader import MasterData, load_master
from mis_reports.master_sheet import build_master_sheet

from . import db, store

KEEP_ENTRY_FILES = 60     # workbooks kept for undo / restore; older entry versions keep only their summary
LOCK = threading.Lock()   # one change to the data at a time


class Workbooks:
    """The Master Sheet of the current data version and the data read back from it (rows as in that file)."""

    def __init__(self, engine):
        self.engine = engine
        self._cur: tuple[str, bytes, MasterData] | None = None

    def get(self) -> tuple[str, bytes, MasterData]:
        with self.engine.connect() as conn:
            version = store.data_version(conn)
            if self._cur and self._cur[0] == version:
                return self._cur
            content = build_master_sheet(store.load_data(conn))
        self._cur = (version, content, load_master(io.BytesIO(content)))
        return self._cur

    def put(self, version: str, content: bytes, data: MasterData) -> None:
        self._cur = (version, content, data)


# ------------------------------------------------------------------ what the forms need
def _names(*series) -> list[str]:
    seen = {}
    for s in series:
        if s is None:
            continue
        for v in pd.Series(s).dropna():
            t = " ".join(str(v).split())
            if t:
                seen.setdefault(t.lower(), t)
    return sorted(seen.values(), key=str.lower)


def _v(v):
    if v is None or (isinstance(v, float) and v != v) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if hasattr(v, "item"):
        v = v.item()
    return v


def _records(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{c: _v(r.get(c)) for c in cols} for r in df.to_dict(orient="records")]


def _open_orders(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[(df["status"].fillna("").astype(str).str.lower() != "closed") & (df["bal_qty_mt"].fillna(0) > 0)]


def _party_defaults(*frames) -> dict:
    """For each party: the details of its latest entry (broker, company, type ...), used to fill forms in."""
    out = {}
    for df in frames:
        if df is None or df.empty:
            continue
        for r in df.to_dict(orient="records"):
            if not r.get("party") or pd.isna(r.get("party")):
                continue
            key = " ".join(str(r["party"]).split()).lower()
            cur = out.setdefault(key, {})
            for f in ("broker", "company", "type", "sub_type", "warehouse", "gstin", "branch"):
                if f in r and _v(r[f]) not in (None, ""):
                    cur[f] = _v(r[f])
    return out


def context(workbooks: Workbooks, aliases: dict) -> dict:
    version, _, d = workbooks.get()
    today = date.today()
    ledgers = {"Purchase": R.creditors(d, R.Filters(as_of=today, aliases=aliases)),
               "Sales": R.debtors(d, R.Filters(as_of=today, aliases=aliases))}
    bill_cols = ["source_row", "party", "bill_no", "bill_date", "commodity", "qty", "rate", "amount", "net_amount",
                 "gst", "bill_amt", "final_amt", "note", "paid", "tds", "type"]
    order_cols = ["source_row", "contract_no", "date", "party", "commodity", "qty_mt", "bal_qty_mt", "rate",
                  "amount", "status"]
    bills = {}
    for kind, df in (("Purchase", d.purchase), ("Sales", d.sales)):
        fields = [f for fs in EXPENSE_FIELDS[kind].values() for f in fs]
        bills[kind] = _records(df, bill_cols + [f for f in fields if f not in bill_cols])
    outstanding = {}
    for kind, led in ledgers.items():
        b = led.bills[led.bills["source_row"].notna()]
        outstanding[kind] = [{"row": int(r["source_row"]), "party": r["party"], "bill_no": _v(r["bill_no"]),
                              "bill_date": _v(r["bill_date"]), "days": _v(r["days"]),
                              "outstanding": round(float(r["outstanding"]), 2)}
                             for r in b.to_dict(orient="records")]
    notes = {}
    for kind, df in (("Purchase", d.debit_notes), ("Sales", d.credit_notes)):
        notes[kind] = _records(df, ["note_no", "date", "party", "bill_no", "bill_row", "reason", "qty", "taxable",
                                    "gst", "other", "total"])
    both = [d.purchase, d.sales]
    return {
        "version": version,
        "lists": {
            "party:Purchase": _names(d.purchase["party"], d.po["party"]),
            "party:Sales": _names(d.sales["party"], d.so["party"]),
            "product": _names(*(x["commodity"] for x in both), d.po["commodity"], d.so["commodity"]),
            "broker": _names(*(x["broker"] for x in both), d.po["broker"], d.so["broker"]),
            "company": _names(*(x["company"] for x in both), d.po["company"], d.so["company"]),
            "warehouse": _names(*(x["warehouse"] for x in both), d.po["warehouse"], d.so["warehouse"]),
            "type": _names(*(x["type"] for x in both), ["Local", "Import"]),
            "sub_type": _names(*(x["sub_type"] for x in both)),
            "branch": _names(*(x["branch"] for x in both), d.po["branch"], d.so["branch"]),
            "place": _names(d.po["delivery_place"], d.so["delivery_place"]),
            "packing": _names(d.po["packing"], d.so["packing"]),
            "reason": NOTE_REASONS,
            "expense": NOTE_EXPENSES,
        },
        "party_defaults": {
            "Purchase": _party_defaults(d.po, d.purchase),
            "Sales": _party_defaults(d.so, d.sales),
        },
        "hsn": {" ".join(str(k).split()).lower(): _v(v) for k, v in
                pd.concat(both).dropna(subset=["commodity", "hsn"]).groupby("commodity")["hsn"].last().items()},
        "orders": {"PO": _records(_open_orders(d.po), order_cols), "SO": _records(_open_orders(d.so), order_cols)},
        "all_contracts": {"PO": [_v(v) for v in d.po["contract_no"].dropna()],
                          "SO": [_v(v) for v in d.so["contract_no"].dropna()]},
        "next": {
            "PO": _v(next_number(list(d.po["contract_no"].dropna()))),
            "SO": _v(next_number(list(d.so["contract_no"].dropna()))),
            "Purchase": _v(next_number(list(d.debit_notes["note_no"].dropna()), "DN-0001")),
            "Sales": _v(next_number(list(d.credit_notes["note_no"].dropna()), "CN-0001")),
            "sales_bill": _v(next_number(list(d.sales["bill_no"].dropna()), "1")),
        },
        "bills": bills,
        "outstanding": outstanding,
        "notes": notes,
        "note_numbers": {k: [x["note_no"] for x in v] for k, v in notes.items()},
        "expense_fields": EXPENSE_FIELDS,
        "pre_bill_fields": PRE_BILL_FIELDS,
    }


# ------------------------------------------------------------------ saving
def _day(v) -> date | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _clean(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if isinstance(v, str):
            v = " ".join(v.split()) or None
        out[k] = v
    return out


OPERATIONS = {
    # action: (label, function(MasterFile, body) -> message)
    "order": "Order",
    "invoice": "Invoice",
    "note": "Note",
    "expenses": "Expenses",
    "settlement": "Payment / receipt",
}


def _run(mf: MasterFile, action: str, body: dict) -> str:
    if action == "order":
        kind = body["kind"]
        f = _clean(body["fields"])
        for k in ("date", "delivery_date"):
            f[k] = _day(f.get(k))
        for k in ("qty_mt", "rate"):
            f[k] = float(f.get(k) or 0)
        if f["qty_mt"] <= 0 or f["rate"] <= 0:
            raise EntryError("Enter the quantity and the rate")
        mf.add_order(kind, f, contract_no=body.get("contract_no") or None)
        return f"{'Purchase' if kind == 'PO' else 'Sales'} order saved for {f['party']}"
    if action == "invoice":
        kind = body["kind"]
        header = _clean(body["header"])
        header["bill_date"] = _day(header.get("bill_date"))
        header["stock_date"] = _day(header.get("stock_date")) or header["bill_date"]
        lines = []
        for ln in body["lines"]:
            ln = _clean(ln)
            for k in ("qty", "rate", "gst_pct"):
                ln[k] = float(ln.get(k) or 0)
            for k in ("order_row", "link_row"):
                ln[k] = int(ln[k]) if ln.get(k) else None
            if ln["qty"] <= 0 or ln["rate"] <= 0:
                raise EntryError(f"Item {len(lines) + 1}: enter the weight and the rate")
            lines.append(ln)
        expenses = {k: float(v) for k, v in (body.get("expenses") or {}).items() if v}
        mf.add_invoice_lines(kind, header, lines, expenses)
        return (f"{kind} invoice {header.get('bill_no') or ''} saved for {header['party']} "
                f"({len(lines)} item{'s' if len(lines) > 1 else ''})").replace("  ", " ")
    if action == "note":
        kind = body["kind"]
        note = {"note_no": body.get("note_no") or None, "date": _day(body.get("date")) or date.today(),
                "lines": body.get("lines") or [], "expenses": body.get("expenses") or []}
        no = mf.add_note_detailed(kind, int(body["row"]), note)
        return f"{'Debit' if kind == 'Purchase' else 'Credit'} note {no} saved"
    if action == "expenses":
        mf.set_expenses(body["kind"], int(body["row"]), {k: v for k, v in body["changes"].items()})
        return "Expenses saved"
    if action == "settlement":
        kind = body["kind"]
        alloc = [(int(a["row"]), float(a.get("amount") or 0), float(a.get("tds") or 0)) for a in body["allocations"]]
        outstanding = {int(a["row"]): float(a["outstanding"]) for a in body["allocations"] if "outstanding" in a}
        mf.add_settlement(kind, _day(body.get("date")) or date.today(), alloc, outstanding)
        return f"{'Payment' if kind == 'Purchase' else 'Receipt'} saved"
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown entry")


def save_entry(engine, workbooks: Workbooks, user, action: str, body: dict) -> dict:
    with LOCK:
        version, content, _ = workbooks.get()
        if body.get("version") and body["version"] != version:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Someone else saved a change a moment ago. The lists have been refreshed: "
                                "please check the entry and save again.")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Master Sheet.xlsx"
            path.write_bytes(content)
            mf = MasterFile(path, backup_dir=Path(tmp) / "backups", log_path=Path(tmp) / "log.csv")
            try:
                message = _run(mf, action, body)
            except EntryError as e:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
            except (KeyError, TypeError, ValueError) as e:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Something is missing or not valid ({e})")
            new = path.read_bytes()
            log = list(reversed(mf.read_log()))
        if action in ("note", "expenses", "settlement") and log and log[-1].get("Party"):
            message += f" for {log[-1]['Party']}"
        data = load_master(io.BytesIO(new))
        with engine.begin() as conn:
            batch_id = conn.execute(db.import_batches.insert().values(
                kind="entry", filename=message, stored_as="db", status="active",
                summary={"counts": store.row_counts(data), "entry": message, "action": action, "lines": log},
                warnings=[], created_by=user["id"], created_at=db.utcnow(), confirmed_by=user["id"],
                confirmed_at=db.utcnow())).inserted_primary_key[0]
            conn.execute(update(db.import_batches).where(db.import_batches.c.status == "active",
                                                         db.import_batches.c.id != batch_id)
                         .values(status="replaced"))
            conn.execute(db.import_files.insert().values(batch_id=batch_id, content=new))
            store.replace_all(conn, data, batch_id)
            store.audit(conn, user, f"entry.{action}", batch=batch_id, entry=message,
                        details="; ".join(f"{x['Action']}: {x['Details']}" for x in log))
            _prune(conn)
            new_version = store.data_version(conn)
        workbooks.put(new_version, new, data)
        return {"message": message, "version": new_version, "batch": batch_id}


def _prune(conn) -> None:
    """Keeps the workbooks of the latest entries only (older ones can no longer be undone to)."""
    keep = [r.id for r in conn.execute(
        select(db.import_batches.c.id).where(db.import_batches.c.kind == "entry")
        .order_by(db.import_batches.c.id.desc()).limit(KEEP_ENTRY_FILES))]
    if len(keep) == KEEP_ENTRY_FILES:
        old = select(db.import_batches.c.id).where(db.import_batches.c.kind == "entry",
                                                  db.import_batches.c.id < min(keep),
                                                  db.import_batches.c.status != "active")
        conn.execute(delete(db.import_files).where(db.import_files.c.batch_id.in_(old)))


def undo_last(engine, workbooks: Workbooks, user) -> dict:
    """Brings back the data as it was before the latest entry."""
    with LOCK, engine.begin() as conn:
        active = conn.execute(select(db.import_batches).where(db.import_batches.c.status == "active")).first()
        if active is None or active.kind != "entry":
            raise HTTPException(status.HTTP_409_CONFLICT, "The latest change is not an entry, so there is nothing "
                                "to undo here. An import can be undone by restoring an earlier one on the Import page.")
        prev = conn.execute(
            select(db.import_batches, db.import_files.c.content)
            .join(db.import_files, db.import_files.c.batch_id == db.import_batches.c.id)
            .where(db.import_batches.c.id < active.id, db.import_batches.c.status == "replaced")
            .order_by(db.import_batches.c.id.desc()).limit(1)).first()
        if prev is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "There is no earlier version kept to go back to")
        data = load_master(io.BytesIO(bytes(prev.content)))
        store.replace_all(conn, data, prev.id)
        conn.execute(update(db.import_batches).where(db.import_batches.c.id == active.id).values(status="undone"))
        conn.execute(update(db.import_batches).where(db.import_batches.c.id == prev.id)
                     .values(status="active", confirmed_at=db.utcnow()))
        store.audit(conn, user, "entry.undo", batch=active.id, entry=active.filename)
    return {"message": f"Undone: {active.filename}"}


def recent(conn, limit: int = 30) -> list[dict]:
    names = {r.id: r.username for r in conn.execute(select(db.users.c.id, db.users.c.username))}
    rows = conn.execute(select(db.import_batches).where(db.import_batches.c.kind == "entry")
                        .order_by(db.import_batches.c.id.desc()).limit(limit))
    return [{"id": b.id, "entry": b.filename, "status": b.status, "by": names.get(b.created_by),
             "at": b.created_at, "lines": (b.summary or {}).get("lines", [])} for b in rows]


class LiveFile:
    """Keeps an up-to-date copy of the Master Sheet on the computer running the app, for people who like to look at
    the Excel file. Excel locks a file while it is open, so when it can't be replaced the copy is written again a
    little later (it is a copy: changes go through the app)."""

    def __init__(self, path: Path, workbooks: Workbooks):
        self.path, self.workbooks = Path(path), workbooks
        self._pending: bytes | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def write(self, content: bytes | None = None) -> None:
        with self._lock:
            self._pending = content
        threading.Thread(target=self._flush, daemon=True).start()

    def _flush(self) -> None:
        with self._lock:
            content = self._pending
            try:
                if content is None:
                    content = self.workbooks.get()[1]
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_name(self.path.name + ".saving")
                tmp.write_bytes(content)
                os.replace(tmp, self.path)
                self._pending = None
            except PermissionError:   # open in Excel: try again in a while
                self._pending = content
                if self._timer is None or not self._timer.is_alive():
                    self._timer = threading.Timer(20, self._flush)
                    self._timer.daemon = True
                    self._timer.start()
            except Exception:  # never let the copy break an entry
                pass
