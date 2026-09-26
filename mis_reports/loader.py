"""Read the Master Sheet (Domestic) workbook into clean pandas tables.

The workbook's formulas are not consistent from row to row, so we read the
values Excel last calculated and only fall back to recomputing a column
when Excel left it blank (e.g. a file that was never opened in Excel).
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

import pandas as pd

# canonical field -> header text in the sheet (compared after normalising)
PURCHASE_COLUMNS = {
    "company": "Com.",
    "type": "Type",
    "sub_type": "Sub Type",
    "warehouse": "Warehouse",
    "broker": "Broker",
    "party": "PARTY NAME",
    "gstin": "PARTY GSTN NO",
    "branch": "BRANCH",
    "bill_no": "BILL NO.",
    "bill_date": "BILL DATE",
    "stock_date": "WH In Date",
    "commodity": "COMMODITY",
    "qty": "WEIGHT",
    "rate": "RATE",
    "amount": "Amount befor GST",
    "adhat": "Adhat",
    "amc": "AMC",
    "labour": "Labour",
    "transport_pre": "Transporation",
    "wh_load": "WH Load",
    "bags": "Bags",
    "other_pre": "Other",
    "pre_exp": "Total Pre Bill Exp",
    "discount": "Discount",
    "net_amount": "Net Amount befor GST",
    "gst": "GST",
    "bill_amt": "Bill Amt",
    "vatav": "Vatav",
    "final_amt": "Final Amt.",
    "status": "Status",
    "pay_date": "Date",
    "paid": "Amount",
    "tds": "TDS",
    "note": "Debit Note / Other de.",
    "post_exp": "Total Post exp.",
    "storage": "Storage Amt.",
    "brokerage": "Brokerage",
    "sampling": "Sampling Expenses",
    "repacking": "Repacking charges",
    "transport_post": "Transportation",
}

SALES_COLUMNS = {
    "company": "Com",
    "type": "Type",
    "sub_type": "Sub Type",
    "warehouse": "Warehouse",
    "broker": "Broker",
    "party": "PARTY NAME",
    "gstin": "PARTY GSTN NO",
    "branch": "BRANCH",
    "bill_no": "BILL NO.",
    "bill_date": "BILL DATE",
    "stock_date": "Delivery Date",
    "commodity": "COMMODITY",
    "qty": "WH Weight",
    "rate": "RATE",
    "amount": "Amount before GST",
    "discount": "Discount",
    "net_amount": "Net Amount befor GST",
    "gst": "GST",
    "bill_amt": "Bill Amt",
    "status": "Status",
    "pay_date": "Date",
    "paid": "Amount",
    "tds": "TDS",
    "note": "Debit Note / Other de.",
    "post_exp": "Total Post Exp.",
    "brokerage": "Brokerage",
    "loading": "Loading / Unloading",
    "repacking": "Repacking",
}

ORDER_COLUMNS = {
    "contract_no": "Contract No",
    "date": "Date",
    "party": "Party Name",
    "broker": "Broker Name",
    "commodity": "Quality",
    "qty_mt": "Qty Mts",
    "rate": "Rate",
    "bal_qty_mt": "Bal Qty",
    "amount": "AMT",
    "status": "Status",
}

PURCHASE_PRE_PARTS = ["adhat", "amc", "labour", "transport_pre", "wh_load", "bags", "other_pre"]
PURCHASE_POST_PARTS = ["storage", "brokerage", "sampling", "repacking", "transport_post"]
SALES_POST_PARTS = ["brokerage", "loading", "repacking"]

TEXT_FIELDS = {"company", "type", "sub_type", "warehouse", "broker", "party", "gstin",
               "branch", "bill_no", "commodity", "status", "contract_no"}
DATE_FIELDS = {"bill_date", "stock_date", "pay_date", "date"}


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9/.+%]+", " ", str(text).lower()).strip()


def party_key(name) -> str:
    """Key used to group spellings of the same party ('R.R. Impex' / 'R R IMPEX')."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


@dataclass
class MasterData:
    purchase: pd.DataFrame
    sales: pd.DataFrame
    po: pd.DataFrame
    so: pd.DataFrame
    opening_creditors: dict = field(default_factory=dict)  # party_key -> (party name, opening balance)
    opening_debtors: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def _find_header_row(raw: pd.DataFrame, marker: str, max_scan: int = 15) -> int:
    for i in range(min(max_scan, len(raw))):
        if any(_norm(v) == _norm(marker) for v in raw.iloc[i].tolist()):
            return i
    raise ValueError(f"Could not find a header row containing '{marker}'")


def _read_table(xls: pd.ExcelFile, sheet: str, columns: dict, marker: str,
                key_field: str, problems: list) -> pd.DataFrame:
    raw = pd.read_excel(xls, sheet_name=sheet, header=None)
    hdr = _find_header_row(raw, marker)
    headers = [_norm(v) for v in raw.iloc[hdr].tolist()]
    body = raw.iloc[hdr + 1:].reset_index(drop=True)

    out = pd.DataFrame(index=body.index)
    out["source_row"] = body.index + hdr + 2  # 1-based Excel row number
    for fld, header in columns.items():
        want = _norm(header)
        idx = [i for i, h in enumerate(headers) if h == want]
        if idx:
            out[fld] = body.iloc[:, idx[0]]
        else:
            out[fld] = pd.NA
            problems.append(f"{sheet}: column '{header}' not found - treated as blank")

    out = out[out[key_field].notna() & (out[key_field].astype(str).str.strip() != "")]
    for fld in out.columns:
        if fld in TEXT_FIELDS:
            out[fld] = out[fld].where(out[fld].isna(), out[fld].astype(str).str.strip())
        elif fld in DATE_FIELDS:
            out[fld] = pd.to_datetime(out[fld], errors="coerce")
        elif fld != "source_row":
            out[fld] = pd.to_numeric(out[fld], errors="coerce")
    return out.reset_index(drop=True)


def _fill(df: pd.DataFrame, col: str, fallback: pd.Series) -> None:
    df[col] = df[col].where(df[col].notna(), fallback)


def _complete_purchase(df: pd.DataFrame) -> pd.DataFrame:
    _fill(df, "amount", df["qty"] * df["rate"])
    _fill(df, "pre_exp", df[PURCHASE_PRE_PARTS].sum(axis=1, min_count=1))
    _fill(df, "net_amount", df["amount"].fillna(0) + df["pre_exp"].fillna(0) - df["discount"].fillna(0))
    _fill(df, "bill_amt", df["net_amount"] + df["gst"].fillna(0))
    _fill(df, "final_amt", df["bill_amt"] - df["vatav"].fillna(0))
    _fill(df, "post_exp", df[PURCHASE_POST_PARTS].sum(axis=1, min_count=1))
    return df


def _complete_sales(df: pd.DataFrame) -> pd.DataFrame:
    _fill(df, "amount", df["qty"] * df["rate"])
    _fill(df, "net_amount", df["amount"] - df["discount"].fillna(0))
    _fill(df, "bill_amt", df["amount"] + df["gst"].fillna(0))
    _fill(df, "post_exp", df[SALES_POST_PARTS].sum(axis=1, min_count=1))
    return df


def _read_opening(xls: pd.ExcelFile) -> tuple[dict, dict]:
    """Opening balances typed into the 'Total Debtor Creditor' sheet (col C and M)."""
    if "Total Debtor Creditor" not in xls.sheet_names:
        return {}, {}
    raw = pd.read_excel(xls, sheet_name="Total Debtor Creditor", header=None)
    cred, debt = {}, {}
    for _, row in raw.iloc[3:].iterrows():
        for name_col, bal_col, target in ((1, 2, cred), (11, 12, debt)):
            if raw.shape[1] <= bal_col:
                continue
            name, bal = row.iloc[name_col], pd.to_numeric(row.iloc[bal_col], errors="coerce")
            if pd.notna(name) and str(name).strip() and pd.notna(bal) and bal != 0:
                k = party_key(name)
                target[k] = (target.get(k, (str(name).strip(), 0.0))[0], target.get(k, ("", 0.0))[1] + float(bal))
    return cred, debt


def load_master(source) -> MasterData:
    """source: a file path or file-like object for the Master Sheet workbook."""
    problems: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # openpyxl warns about data-validation extensions
        xls = pd.ExcelFile(source, engine="openpyxl")
        missing = [s for s in ("Purchase", "Sales") if s not in xls.sheet_names]
        if missing:
            raise ValueError(f"Workbook is missing required sheet(s): {', '.join(missing)}")

        purchase = _complete_purchase(
            _read_table(xls, "Purchase", PURCHASE_COLUMNS, "PARTY NAME", "party", problems))
        sales = _complete_sales(
            _read_table(xls, "Sales", SALES_COLUMNS, "PARTY NAME", "party", problems))

        orders = {}
        for sheet in ("PO", "SO"):
            if sheet in xls.sheet_names:
                df = _read_table(xls, sheet, ORDER_COLUMNS, "Contract No", "commodity", problems)
                orders[sheet] = df[df["qty_mt"].notna()].reset_index(drop=True)
            else:
                orders[sheet] = pd.DataFrame(columns=["source_row", *ORDER_COLUMNS])
        opening_c, opening_d = _read_opening(xls)

    if purchase[["qty", "amount"]].isna().all().all() and len(purchase):
        problems.append("Purchase sheet has no calculated amounts - open and save the file in Excel first")

    return MasterData(purchase, sales, orders["PO"], orders["SO"], opening_c, opening_d, problems)
