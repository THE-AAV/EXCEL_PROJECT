"""The data sheets as clean tables for the 'Sheets' page: the Master Sheet's own column names and order,
columns nobody filled left out, dates and numbers typed."""
from __future__ import annotations

import pandas as pd

from mis_reports.loader import MasterData, _norm
from mis_reports.master_sheet import NOTES, ORDERS, PURCHASE, SALES, Col

SHEETS = [("purchase", "Purchase", PURCHASE), ("sales", "Sales", SALES), ("po", "PO", ORDERS), ("so", "SO", ORDERS),
          ("debit_notes", "Debit Notes", NOTES), ("credit_notes", "Credit Notes", NOTES)]


def _kind(col: Col) -> str:
    if col.date:
        return "date"
    return "num" if col.num else "text"


def _value(v):
    if v is None or v is pd.NaT or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return v.item() if hasattr(v, "item") else v


def sheet(df: pd.DataFrame, layout: list[Col]) -> dict:
    if df is None or df.empty:
        return {"cols": [], "rows": []}
    known = {_norm(c.header) for c in layout}
    extra_headers = []
    for extra in df["_extra"] if "_extra" in df else []:
        for h in extra or {}:
            if _norm(h) not in known and h not in extra_headers:
                extra_headers.append(h)
    cols = [c for c in layout if c.header not in ("SR.NO.", "PSN")] + [Col(h) for h in extra_headers]
    rows = []
    for rec in df.to_dict(orient="records"):
        extra = {_norm(k): v for k, v in (rec.get("_extra") or {}).items()}
        row = {"_row": _value(rec.get("source_row"))}
        for i, c in enumerate(cols):
            v = rec.get(c.field) if c.field else extra.get(_norm(c.header))
            row[f"c{i}"] = _value(v)
        rows.append(row)
    used = [i for i in range(len(cols)) if any(r[f"c{i}"] not in (None, "") for r in rows)]
    return {"cols": [[f"c{i}", " ".join(cols[i].header.split()), _kind(cols[i])] for i in used],
            "rows": [{"_row": r["_row"], **{f"c{i}": r[f"c{i}"] for i in used}} for r in rows]}


def all_sheets(data: MasterData) -> list[dict]:
    return [{"key": key, "name": name, **sheet(getattr(data, key), layout)} for key, name, layout in SHEETS]
