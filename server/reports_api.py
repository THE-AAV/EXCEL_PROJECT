"""Reports worked out from the database with the same code the Excel app uses (mis_reports)."""
from __future__ import annotations

import math
import threading
from collections import OrderedDict
from datetime import date

import numpy as np
import pandas as pd

from mis_reports import reports as R
from mis_reports.pipeline import ReportSet, build_reports

from . import store


def to_json(v):
    """A JSON-safe copy of report values: blanks -> null, dates -> 'YYYY-MM-DD'."""
    if isinstance(v, pd.DataFrame):
        return [{str(k): to_json(x) for k, x in rec.items()} for rec in v.to_dict(orient="records")]
    if isinstance(v, dict):
        return {str(k): to_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_json(x) for x in v]
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat() if v == v.normalize() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _total(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df[col], errors="coerce").sum()) if len(df) and col in df else 0.0


def dashboard(rs: ReportSet) -> dict:
    pnl, cred, debt = rs.pnl, rs.creditors.summary, rs.debtors.summary
    net_sales, net_profit = _total(pnl, "net_sales"), _total(pnl, "net_profit")
    return {
        "net_sales": net_sales, "net_profit": net_profit,
        "net_margin": net_profit / net_sales if net_sales else None,
        "gross_profit": _total(pnl, "gross_profit"), "closing_stock_value": _total(pnl, "closing_value"),
        "payable": _total(cred, "closing"), "receivable": _total(debt, "closing"),
        "payable_over_90": _total(cred, "Over 90 days"), "receivable_over_90": _total(debt, "Over 90 days"),
        "purchase_bills": int(len(rs.data.purchase)), "sales_bills": int(len(rs.data.sales)),
        "data_checks": int(len(rs.checks)),
        "products_without_purchase": pnl.loc[pnl["purchase_qty"] == 0, "product"].tolist() if len(pnl) else [],
    }


def report_json(rs: ReportSet) -> dict:
    return to_json({
        "filters": {"as_of": rs.filters.as_of, "date_from": rs.filters.date_from, "date_to": rs.filters.date_to},
        "dashboard": dashboard(rs),
        "pnl": rs.pnl,
        "stock": rs.stock,
        "creditors": {"summary": rs.creditors.summary, "bills": rs.creditors.bills},
        "debtors": {"summary": rs.debtors.summary, "bills": rs.debtors.bills},
        "open_orders": rs.orders,
        "po": rs.po_detail,
        "so": rs.so_detail,
        "debit_notes": rs.debit_notes,
        "credit_notes": rs.credit_notes,
        "margins": rs.margins,
        "checks": rs.checks,
        "age_buckets": R.BUCKET_NAMES,
    })


class ReportCache:
    """Loads the data once per data version and keeps the last few report results."""

    def __init__(self, engine, size: int = 16):
        self.engine, self.size = engine, size
        self._lock = threading.Lock()
        self._data = (None, None)       # (version, MasterData)
        self._results: OrderedDict = OrderedDict()

    def data(self):
        with self.engine.connect() as conn:
            version = store.data_version(conn)
            aliases = store.load_aliases(conn)
            with self._lock:
                if self._data[0] != version:
                    self._data = (version, store.load_data(conn))
                    self._results.clear()
                return version, self._data[1], aliases

    def reports(self, f: R.Filters) -> ReportSet:
        version, data, aliases = self.data()
        f.aliases = aliases
        key = (version, repr(f))
        with self._lock:
            if key in self._results:
                self._results.move_to_end(key)
                return self._results[key]
        rs = build_reports(data, f)
        with self._lock:
            self._results[key] = rs
            while len(self._results) > self.size:
                self._results.popitem(last=False)
        return rs

    def clear(self):
        with self._lock:
            self._data = (None, None)
            self._results.clear()
