"""One call that turns a Master Sheet into every report."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import reports as R
from .excel_export import build_workbook
from .loader import MasterData, load_master

ALIAS_FILE = Path(__file__).resolve().parent.parent / "config" / "product_aliases.csv"


@dataclass
class ReportSet:
    data: MasterData
    filters: R.Filters
    pnl: pd.DataFrame
    creditors: R.Ledger
    debtors: R.Ledger
    orders: pd.DataFrame
    checks: pd.DataFrame

    def to_excel(self) -> bytes:
        return build_workbook(self.pnl, self.creditors, self.debtors, self.orders, self.checks, self.filters)


def load_aliases(path: Path = ALIAS_FILE) -> dict:
    """Product name mapping kept in config/product_aliases.csv (columns: name_in_sheet, report_as)."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return {row["name_in_sheet"].strip(): row["report_as"].strip()
                for row in csv.DictReader(fh)
                if row.get("name_in_sheet", "").strip() and row.get("report_as", "").strip()}


def save_aliases(aliases: dict, path: Path = ALIAS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name_in_sheet", "report_as"])
        for k, v in sorted(aliases.items()):
            w.writerow([k, v])


def run_reports(source, filters: R.Filters | None = None, data: MasterData | None = None) -> ReportSet:
    f = filters or R.Filters()
    if not f.aliases:
        f.aliases = load_aliases()
    data = data or load_master(source)
    return ReportSet(data, f, R.product_pnl(data, f), R.creditors(data, f), R.debtors(data, f),
                     R.open_orders(data, f), R.data_checks(data, f))
