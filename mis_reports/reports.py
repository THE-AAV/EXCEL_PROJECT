"""Debtor / creditor ledgers and product-wise P&L (all P&L figures exclusive of GST)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .loader import MasterData, party_key

AGE_BUCKETS = [(0, 30, "0-30 days"), (31, 60, "31-60 days"), (61, 90, "61-90 days"),
               (91, 10**6, "Over 90 days")]
UNDATED = "Undated"  # opening balances and bills without a date
BUCKET_NAMES = [b[2] for b in AGE_BUCKETS] + [UNDATED]


@dataclass
class Filters:
    date_from: date | None = None      # P&L period (bill date)
    date_to: date | None = None
    as_of: date | None = None          # cut-off for debtor/creditor balances and ageing
    types: list = field(default_factory=list)      # e.g. ["Local"]; empty = all
    sub_types: list = field(default_factory=list)
    companies: list = field(default_factory=list)
    products: list = field(default_factory=list)   # normalised product names; empty = all
    aliases: dict = field(default_factory=dict)    # raw product name -> reporting name


def product_name(raw, aliases: dict | None = None) -> str:
    name = re.sub(r"\s+", " ", str(raw)).strip().upper()
    if aliases:
        lookup = {re.sub(r"\s+", " ", str(k)).strip().upper(): v for k, v in aliases.items()}
        name = re.sub(r"\s+", " ", str(lookup.get(name, name))).strip().upper()
    return name


def _txn_date(df: pd.DataFrame) -> pd.Series:
    return df["bill_date"].fillna(df["stock_date"])


def apply_common_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    df = df.copy()
    df["product"] = df["commodity"].map(lambda v: product_name(v, f.aliases))
    df["txn_date"] = _txn_date(df)
    for col, wanted in (("type", f.types), ("sub_type", f.sub_types), ("company", f.companies),
                        ("product", f.products)):
        if wanted:
            df = df[df[col].isin(wanted)]
    return df


def _in_period(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if f.date_from:
        mask &= df["txn_date"] >= pd.Timestamp(f.date_from)
    if f.date_to:
        mask &= df["txn_date"] <= pd.Timestamp(f.date_to)
    return df[mask]


# --------------------------------------------------------------------------- P&L
def notes_in_scope(data: MasterData, kind: str, f: Filters) -> pd.DataFrame:
    """Debit notes (kind 'Purchase') or credit notes (kind 'Sales') from the app's registers, with the
    bill's product / type / company, filtered like the bills and dated by the note date."""
    notes = data.debit_notes if kind == "Purchase" else data.credit_notes
    bills = data.purchase if kind == "Purchase" else data.sales
    cols = ["note_no", "date", "party", "bill_no", "bill_row", "qty", "rate", "taxable", "gst_pct", "gst",
            "other", "total", "reason"]
    if notes is None or notes.empty:
        return pd.DataFrame(columns=cols + ["product", "txn_date"])
    ctx = bills[["source_row", "commodity", "type", "sub_type", "company", "bill_date", "stock_date"]]
    n = notes[cols].merge(ctx, left_on="bill_row", right_on="source_row", how="left")
    n["commodity"] = n["commodity"].fillna(notes["product"].reindex(n.index))
    n = apply_common_filters(n, f)
    n["txn_date"] = n["date"].fillna(n["txn_date"])
    for c in ("qty", "taxable", "other", "gst", "total"):
        n[c] = pd.to_numeric(n[c], errors="coerce").fillna(0)
    return _in_period(n, f)


def product_pnl(data: MasterData, f: Filters) -> pd.DataFrame:
    """One row per product. Cost of goods sold uses the average landed purchase rate,
    so unsold stock is carried as closing stock rather than charged to the P&L.
    Debit notes reduce purchases (quantity and value); credit notes reduce sales."""
    pur = _in_period(apply_common_filters(data.purchase, f), f)
    sal = _in_period(apply_common_filters(data.sales, f), f)
    dn, cn = notes_in_scope(data, "Purchase", f), notes_in_scope(data, "Sales", f)

    p = pur.groupby("product").agg(
        purchase_qty=("qty", "sum"), purchase_value=("amount", "sum"),
        pre_bill_exp=("pre_exp", "sum"), purchase_discount=("discount", "sum"),
        post_exp_purchase=("post_exp", "sum"), purchase_bills=("party", "size"))
    s = sal.groupby("product").agg(
        sales_qty=("qty", "sum"), sales_value=("amount", "sum"),
        sales_discount=("discount", "sum"), post_exp_sales=("post_exp", "sum"),
        sales_bills=("party", "size"))
    d = dn.assign(value=dn["taxable"] + dn["other"]).groupby("product").agg(
        purchase_return_qty=("qty", "sum"), purchase_returns=("value", "sum"))
    c = cn.assign(value=cn["taxable"] + cn["other"]).groupby("product").agg(
        sales_return_qty=("qty", "sum"), sales_returns=("value", "sum"))
    pnl = p.join(s, how="outer").join(d, how="outer").join(c, how="outer").fillna(0)
    if pnl.empty:
        return pnl.reset_index()

    pnl["net_purchase_qty"] = pnl["purchase_qty"] - pnl["purchase_return_qty"]
    pnl["net_purchase"] = (pnl["purchase_value"] + pnl["pre_bill_exp"] - pnl["purchase_discount"]
                           - pnl["purchase_returns"])
    pnl["avg_cost_rate"] = _ratio(pnl["net_purchase"], pnl["net_purchase_qty"])
    pnl["net_sales_qty"] = pnl["sales_qty"] - pnl["sales_return_qty"]
    pnl["net_sales"] = pnl["sales_value"] - pnl["sales_discount"] - pnl["sales_returns"]
    pnl["avg_sales_rate"] = _ratio(pnl["net_sales"], pnl["net_sales_qty"])
    pnl["closing_qty"] = pnl["net_purchase_qty"] - pnl["net_sales_qty"]
    pnl["closing_value"] = pnl["closing_qty"] * pnl["avg_cost_rate"]
    pnl["cogs"] = pnl["net_purchase"] - pnl["closing_value"]
    pnl["gross_profit"] = pnl["net_sales"] - pnl["cogs"]
    pnl["post_bill_exp"] = pnl["post_exp_purchase"] + pnl["post_exp_sales"]
    pnl["net_profit"] = pnl["gross_profit"] - pnl["post_bill_exp"]
    pnl["margin_pct"] = np.where(pnl["net_sales"] != 0,
                                 pnl["net_profit"] / pnl["net_sales"].where(pnl["net_sales"] != 0), 0)

    def remark(r):
        if r.net_purchase_qty <= 0 and r.net_sales_qty > 0:
            return "Sales without purchase in period - cost unknown"
        if r.closing_qty < 0:
            return "Sold more than purchased in period - check opening stock"
        if r.closing_qty > 0:
            return "Stock in hand valued at avg purchase rate"
        return ""
    pnl["remark"] = [remark(r) for r in pnl.itertuples()]
    return pnl.reset_index().sort_values("net_sales", ascending=False).reset_index(drop=True)


def _ratio(num: pd.Series, den: pd.Series) -> np.ndarray:
    return np.where(den > 0, num / den.where(den > 0), 0)


def stock_summary(data: MasterData, f: Filters, pnl: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per product: purchased, returned to suppliers, sold, returned by customers, stock in hand and its
    value, plus what is still to come in (open purchase orders) and go out (open sales orders)."""
    pnl = product_pnl(data, f) if pnl is None else pnl
    cols = ["product", "purchase_qty", "purchase_return_qty", "sales_qty", "sales_return_qty", "closing_qty",
            "avg_cost_rate", "closing_value"]
    st = pnl[cols].copy() if len(pnl) else pd.DataFrame(columns=cols)
    orders = open_orders(data, f)
    for label, col in (("Purchase Order", "pending_po_qty"), ("Sales Order", "pending_so_qty")):
        o = orders[orders["order_type"] == label].set_index("product")["bal_qty_kg"] if len(orders) else pd.Series()
        st = st.merge(o.rename(col), left_on="product", right_index=True, how="outer")
    st["product"] = st["product"].fillna("")
    st = st.fillna(0)
    st["projected_qty"] = st["closing_qty"] + st["pending_po_qty"] - st["pending_so_qty"]
    return st.sort_values("closing_value", ascending=False).reset_index(drop=True)


def orders_detail(data: MasterData, kind: str, f: Filters) -> pd.DataFrame:
    """Every purchase ('PO') or sales ('SO') contract with what has been received / delivered."""
    df = data.po if kind == "PO" else data.so
    cols = ["contract_no", "date", "party", "broker", "product", "qty_mt", "cancel_qty", "recd_qty", "bal_qty_mt",
            "rate", "order_value", "amount", "done_pct", "status", "delivery_date", "delivery_place", "bill_no",
            "days_open", "source_row"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    d = df.copy()
    d["product"] = d["commodity"].map(lambda v: product_name(v, f.aliases))
    for col, wanted in (("product", f.products), ("company", f.companies)):
        if wanted and col in d:
            d = d[d[col].isin(wanted)]
    for c in ("qty_mt", "cancel_qty", "recd_qty", "bal_qty_mt", "rate", "amount"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce").fillna(0)
    d["order_value"] = (d["qty_mt"] - d["cancel_qty"]) * 1000 * d["rate"]
    d["done_pct"] = _ratio(d["recd_qty"], d["qty_mt"] - d["cancel_qty"])
    as_of = pd.Timestamp(f.as_of or date.today())
    is_open = d["status"].fillna("").str.lower() != "closed"
    d["days_open"] = np.where(is_open & d["date"].notna(), (as_of - d["date"]).dt.days, np.nan)
    for c in cols:
        if c not in d:
            d[c] = np.nan
    return d[cols].reset_index(drop=True)


def bill_margins(data: MasterData, f: Filters) -> pd.DataFrame:
    """Margin on sales bills that were linked to the purchase bill the goods came from."""
    cols = ["sales_bill", "sales_date", "customer", "product", "qty", "sale_rate", "sales_value", "purchase_bill",
            "supplier", "cost_rate", "cost", "margin", "margin_per_kg", "margin_pct"]
    sal = _in_period(apply_common_filters(data.sales, f), f)
    sal = sal[sal["purchase_inv"].notna() & (sal["purchase_inv"].astype(str).str.strip() != "")]
    if sal.empty:
        return pd.DataFrame(columns=cols)
    pur = data.purchase.copy()
    pur["product"] = pur["commodity"].map(lambda v: product_name(v, f.aliases))
    pur["landed"] = pur["amount"].fillna(0) + pur["pre_exp"].fillna(0) - pur["discount"].fillna(0)
    pur["bill_key"] = pur["bill_no"].astype(str).str.strip().str.lower()
    rows = []
    for r in sal.itertuples():
        bills = [b.strip().lower() for b in str(r.purchase_inv).split(",") if b.strip()]
        match = pur[pur["bill_key"].isin(bills)]
        if (match["product"] == r.product).any():
            match = match[match["product"] == r.product]
        qty_p = match["qty"].sum()
        cost_rate = match["landed"].sum() / qty_p if qty_p else np.nan
        value = (r.amount or 0) - (0 if pd.isna(r.discount) else r.discount)
        cost = r.qty * cost_rate if pd.notna(cost_rate) and pd.notna(r.qty) else np.nan
        margin = value - cost if pd.notna(cost) else np.nan
        rows.append({"sales_bill": r.bill_no, "sales_date": r.txn_date, "customer": r.party, "product": r.product,
                     "qty": r.qty, "sale_rate": value / r.qty if r.qty else np.nan, "sales_value": value,
                     "purchase_bill": r.purchase_inv,
                     "supplier": ", ".join(sorted(set(match["party"].dropna()))) or "not found",
                     "cost_rate": cost_rate, "cost": cost, "margin": margin,
                     "margin_per_kg": margin / r.qty if r.qty and pd.notna(margin) else np.nan,
                     "margin_pct": margin / value if value and pd.notna(margin) else np.nan})
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------------------- ledgers
@dataclass
class Ledger:
    summary: pd.DataFrame   # one row per party
    bills: pd.DataFrame     # outstanding bills with ageing


def _ledger(df: pd.DataFrame, amount_col: str, opening: dict, f: Filters) -> Ledger:
    as_of = pd.Timestamp(f.as_of or date.today())
    df = apply_common_filters(df, f)
    df = df[df["txn_date"].isna() | (df["txn_date"] <= as_of)].copy()
    df["key"] = df["party"].map(party_key)
    paid_ok = df["pay_date"].isna() | (df["pay_date"] <= as_of)
    for c in ("paid", "tds", "note"):
        df[c + "_asof"] = df[c].where(paid_ok, 0).fillna(0)
    df["billed"] = df[amount_col].fillna(0)

    names = df.groupby("key")["party"].agg(lambda s: s.value_counts().index[0]).to_dict()
    for k, (name, _) in opening.items():
        names.setdefault(k, name)
    summary = df.groupby("key").agg(
        bills=("billed", "size"), billed=("billed", "sum"), paid=("paid_asof", "sum"),
        tds=("tds_asof", "sum"), note=("note_asof", "sum"),
        last_bill=("txn_date", "max"), last_payment=("pay_date", "max"))
    summary = summary.reindex(sorted(names, key=lambda k: names[k].lower()))
    for c in ("bills", "billed", "paid", "tds", "note"):
        summary[c] = summary[c].astype(float).fillna(0)
    summary.insert(0, "party", summary.index.map(names))
    summary.insert(1, "opening", summary.index.map(lambda k: opening.get(k, ("", 0.0))[1]).astype(float))
    summary["closing"] = summary["opening"] + summary["billed"] - summary["paid"] - summary["tds"] - summary["note"]

    # FIFO: settlements clear the opening balance first, then the oldest bills.
    bill_rows, ageing = [], {}
    groups = dict(list(df.sort_values("txn_date", na_position="last").groupby("key", sort=False)))
    for key in summary.index:
        grp = groups.get(key, df.iloc[0:0])
        # credit bills (negative amounts, e.g. returns) settle like payments
        pool = (grp["paid_asof"].sum() + grp["tds_asof"].sum() + grp["note_asof"].sum()
                - grp["billed"].clip(upper=0).sum())
        buckets = dict.fromkeys(BUCKET_NAMES, 0.0)
        open_bal = opening.get(key, ("", 0.0))[1]
        used = min(pool, max(open_bal, 0))
        pool -= used
        if open_bal - used > 0.5:
            buckets[UNDATED] += open_bal - used
            bill_rows.append({"party": names[key], "bill_no": "Opening balance", "bill_date": pd.NaT,
                              "product": "", "bill_amount": open_bal, "outstanding": open_bal - used,
                              "days": np.nan, "age_bucket": UNDATED, "source_row": np.nan})
        for r in grp[grp["billed"] > 0].itertuples():
            take = min(pool, r.billed)
            pool -= take
            left = r.billed - take
            if left <= 0.5:
                continue
            days = (as_of - r.txn_date).days if pd.notna(r.txn_date) else np.nan
            if pd.isna(days):
                bucket = UNDATED
            else:
                bucket = next((n for lo, hi, n in AGE_BUCKETS if lo <= days <= hi), BUCKET_NAMES[0])
            buckets[bucket] += left
            bill_rows.append({"party": names[key], "bill_no": r.bill_no, "bill_date": r.txn_date,
                              "product": r.product, "bill_amount": r.billed, "outstanding": left,
                              "days": days, "age_bucket": bucket, "source_row": r.source_row})
        ageing[key] = buckets

    for b in BUCKET_NAMES:
        summary[b] = summary.index.map(lambda k: ageing.get(k, {}).get(b, 0.0))
    summary["advance"] = (-summary["closing"]).clip(lower=0)
    summary["oldest_days"] = summary.index.map(
        lambda k: max([r["days"] for r in bill_rows if party_key(r["party"]) == k
                       and pd.notna(r["days"])], default=np.nan))
    summary = summary.sort_values("closing", ascending=False).reset_index(drop=True)
    bills = pd.DataFrame(bill_rows, columns=["party", "bill_no", "bill_date", "product", "bill_amount",
                                             "outstanding", "days", "age_bucket", "source_row"])
    return Ledger(summary, bills.sort_values(["party", "bill_date"]).reset_index(drop=True))


def creditors(data: MasterData, f: Filters) -> Ledger:
    """Suppliers we owe: Final Amt (incl. GST, after Vatav) less payments, TDS and debit notes."""
    return _ledger(data.purchase, "final_amt", data.opening_creditors, f)


def debtors(data: MasterData, f: Filters) -> Ledger:
    """Customers who owe us: Bill Amt (incl. GST) less receipts, TDS and credit notes."""
    return _ledger(data.sales, "bill_amt", data.opening_debtors, f)


# --------------------------------------------------------------------------- orders & checks
def open_orders(data: MasterData, f: Filters) -> pd.DataFrame:
    frames = []
    for label, df in (("Purchase Order", data.po), ("Sales Order", data.so)):
        if df.empty:
            continue
        d = df.copy()
        d["product"] = d["commodity"].map(lambda v: product_name(v, f.aliases))
        d = d[d["status"].fillna("").str.lower() != "closed"]
        if f.products:
            d = d[d["product"].isin(f.products)]
        d["order_type"] = label
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["order_type", "product", "contracts", "bal_qty_kg", "amount", "avg_rate"])
    d = pd.concat(frames)
    g = d.groupby(["order_type", "product"]).agg(contracts=("contract_no", "size"),
                                                 bal_qty_mt=("bal_qty_mt", "sum"), amount=("amount", "sum"))
    g["bal_qty_kg"] = g.pop("bal_qty_mt") * 1000
    g["avg_rate"] = np.where(g["bal_qty_kg"] > 0, g["amount"] / g["bal_qty_kg"].where(g["bal_qty_kg"] > 0), 0)
    return g.reset_index()


def data_checks(data: MasterData, f: Filters) -> pd.DataFrame:
    """Rows a person should look at: they may make the reports inaccurate."""
    issues = [{"sheet": "Workbook", "row": "", "party": "", "issue": w} for w in data.warnings]
    for sheet, df in (("Purchase", data.purchase), ("Sales", data.sales)):
        for r in df.itertuples():
            probs = []
            if pd.isna(r.bill_date) and pd.isna(r.stock_date):
                probs.append("no bill date")
            if pd.isna(r.qty) or r.qty == 0:
                probs.append("no quantity")
            if pd.isna(r.amount) or r.amount == 0:
                probs.append("no amount")
            if probs:
                issues.append({"sheet": sheet, "row": str(r.source_row), "party": r.party,
                               "issue": ", ".join(probs)})
    pur = set(data.purchase["commodity"].dropna().map(lambda v: product_name(v, f.aliases)))
    for prod in sorted(set(data.sales["commodity"].dropna().map(lambda v: product_name(v, f.aliases))) - pur):
        issues.append({"sheet": "Sales", "row": "", "party": "",
                       "issue": f"Product '{prod}' is sold but never purchased - add a product name mapping "
                                "if it is the same item under another name"})
    return pd.DataFrame(issues, columns=["sheet", "row", "party", "issue"])


def filter_options(data: MasterData, aliases: dict | None = None) -> dict:
    both = pd.concat([data.purchase, data.sales])
    dates = pd.concat([_txn_date(data.purchase), _txn_date(data.sales)]).dropna()
    return {
        "types": sorted(both["type"].dropna().unique()),
        "sub_types": sorted(both["sub_type"].dropna().unique()),
        "companies": sorted(both["company"].dropna().unique()),
        "products": sorted(both["commodity"].dropna().map(lambda v: product_name(v, aliases)).unique()),
        "min_date": dates.min().date() if len(dates) else None,
        "max_date": dates.max().date() if len(dates) else None,
    }
