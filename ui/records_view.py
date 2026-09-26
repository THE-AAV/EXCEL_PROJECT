"""Clean table view of the entries in a sheet: real column names, no empty rows or columns, formatted
numbers and dates, quick filters, totals and download."""
from __future__ import annotations

import io
import re
import warnings

import pandas as pd
import streamlit as st

from .common import inr

QUICK = [("Party", r"party|customer|supplier"), ("Product", r"commodity|quality|product"),
         ("Broker", r"broker"), ("Status", r"^status$"), ("Type", r"^type$"), ("Reason", r"^reason$")]
CODE_COLS = r"hsn|gstn|gstin|bill no|contract|sr\.? ?no|psn|truck|lorry|note no|inv$|^p inv|^s inv"
TOTAL_HINT = r"amount|amt|weight|qty|total|gst|value|tds|paid|received|recd|balance"


def load_tables(source) -> dict[str, pd.DataFrame]:
    """Every sheet as a clean table (header row found automatically). source: path or bytes."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
        raw = pd.read_excel(data, sheet_name=None, header=None, engine="openpyxl")
        if isinstance(data, io.BytesIO):
            data.seek(0)
        try:
            import openpyxl
            wb = openpyxl.load_workbook(data, read_only=False)
            filters = {ws.title: ws.auto_filter.ref for ws in wb.worksheets if ws.auto_filter and ws.auto_filter.ref}
        except Exception:
            filters = {}
    return {name: clean_table(df, filters.get(name)) for name, df in raw.items()}


def _header_row(df: pd.DataFrame, af_ref: str | None) -> int | None:
    if af_ref:
        m = re.match(r"[A-Z]+(\d+)", af_ref)
        if m and int(m.group(1)) - 1 < len(df):
            return int(m.group(1)) - 1
    best, best_n = None, 1
    for i in range(min(15, len(df))):
        row = df.iloc[i]
        n = sum(isinstance(v, str) and v.strip() != "" and not v.startswith("=") for v in row)
        if n > best_n:
            best, best_n = i, n
    return best


def clean_table(df: pd.DataFrame, af_ref: str | None = None) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    h = _header_row(df, af_ref)
    if h is None:
        body, names = df, [f"Column {i + 1}" for i in range(df.shape[1])]
        first = 1
    else:
        body = df.iloc[h + 1:]
        names, seen = [], {}
        for i, v in enumerate(df.iloc[h]):
            name = re.sub(r"\s+", " ", str(v)).strip() if pd.notna(v) and str(v).strip() else ""
            name = name or _letter(i)
            seen[name] = seen.get(name, 0) + 1
            names.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
        first = h + 2
    out = body.copy()
    out.columns = names
    out.insert(0, "Sheet row", range(first, first + len(out)))
    data_cols = [c for c in out.columns if c != "Sheet row"]
    out = out[out[data_cols].notna().any(axis=1)]
    keep = ["Sheet row"] + [c for c in data_cols if out[c].notna().any()]
    out = out[keep].reset_index(drop=True)
    for c in keep[1:]:
        col = out[c]
        vals = col.dropna()
        if len(vals) and all(isinstance(v, (pd.Timestamp,)) or hasattr(v, "year") and not isinstance(v, str)
                             for v in vals):
            out[c] = pd.to_datetime(col, errors="coerce")
        else:
            num = pd.to_numeric(col, errors="coerce")
            if re.search(CODE_COLS, c, re.I):
                num = pd.Series(float("nan"), index=col.index)   # codes and numbers stay as text
            if len(vals) and num.notna().sum() >= 0.9 * len(vals) and not vals.map(lambda v: isinstance(v, bool)).any():
                out[c] = num
            else:
                out[c] = col.map(lambda v: "" if pd.isna(v) else (str(int(v)) if isinstance(v, float) and v.is_integer()
                                                                  else str(v)))
    return out


def _letter(i: int) -> str:
    s, n = "", i + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _find(df: pd.DataFrame, pattern: str) -> str | None:
    for c in df.columns:
        if c != "Sheet row" and re.search(pattern, c, re.I) and _is_text(df[c]):
            return c
    return None


def _is_text(col: pd.Series) -> bool:
    return not pd.api.types.is_numeric_dtype(col) and not pd.api.types.is_datetime64_any_dtype(col)


TOTAL_PRIORITY = [r"^(wh )?weight$|^qty", r"amount bef", r"^bill amt", r"^final amt", r"^amt$|^amount$",
                  r"total", r"closing", r"payable|receivable"]


def render(df: pd.DataFrame, key: str, title: str):
    if df.empty:
        st.info(f"'{title}' has no entries.")
        return
    total_rows = len(df)
    view = df

    # ---- quick filter bar
    st.markdown("**Filter**")
    c = st.columns([2, 2, 2, 2])
    search = c[0].text_input("🔍 Search", key=f"{key}_q", placeholder="Any text or number")
    quick = [(label, col) for label, pat in QUICK if (col := _find(df, pat))][:3]
    for i, (label, col) in enumerate(quick, 1):
        options = sorted({v for v in df[col] if v}, key=str.lower)
        picked = c[i].multiselect(f"{label} ({col})" if label.lower() not in col.lower() else col, options,
                                  key=f"{key}_quick_{col}", placeholder=f"All")
        if picked:
            view = view[view[col].isin(picked)]
    date_cols = [col for col in df.columns if pd.api.types.is_datetime64_any_dtype(df[col])]
    if date_cols:
        d = st.columns([2, 2, 4])
        dcol = d[0].selectbox("Date column", date_cols, key=f"{key}_dcol")
        lo, hi = df[dcol].min(), df[dcol].max()
        if pd.notna(lo):
            rng = d[1].date_input("Between", value=(lo.date(), hi.date()), key=f"{key}_drange_{dcol}",
                                  format="DD/MM/YYYY")
            if isinstance(rng, (list, tuple)) and len(rng) == 2 and (rng[0] != lo.date() or rng[1] != hi.date()):
                view = view[(view[dcol] >= pd.Timestamp(rng[0])) & (view[dcol] <= pd.Timestamp(rng[1]))]
    if search:
        s = search.lower()
        view = view[view.astype(str).apply(lambda col: col.str.lower().str.contains(s, regex=False)).any(axis=1)]

    with st.expander("➕ More filters (any column)"):
        cols = [col for col in df.columns if col != "Sheet row"]
        chosen = st.multiselect("Columns to filter", cols, key=f"{key}_more")
        for col in chosen:
            if pd.api.types.is_numeric_dtype(df[col]):
                a, b = st.columns(2)
                lo = a.number_input(f"{col}: from", value=None, key=f"{key}_{col}_lo")
                hi = b.number_input(f"{col}: to", value=None, key=f"{key}_{col}_hi")
                if lo is not None:
                    view = view[view[col] >= lo]
                if hi is not None:
                    view = view[view[col] <= hi]
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                rng = st.date_input(f"{col}: between", value=(), key=f"{key}_{col}_dr", format="DD/MM/YYYY")
                if isinstance(rng, (list, tuple)) and len(rng) == 2:
                    view = view[(view[col] >= pd.Timestamp(rng[0])) & (view[col] <= pd.Timestamp(rng[1]))]
            else:
                vals = sorted({v for v in df[col] if v}, key=str.lower)
                a, b = st.columns([3, 2])
                picked = a.multiselect(f"{col}: show only", vals + ["(Blanks)"], key=f"{key}_{col}_vals")
                text = b.text_input(f"{col}: contains", key=f"{key}_{col}_txt")
                if picked:
                    view = view[view[col].isin([("" if v == "(Blanks)" else v) for v in picked])]
                if text:
                    view = view[view[col].str.contains(text, case=False, regex=False)]
        hide = st.multiselect("Hide columns", cols, key=f"{key}_hide")
        if hide:
            view = view.drop(columns=hide)

    # ---- totals
    nums = [col for col in view.columns if col != "Sheet row" and pd.api.types.is_numeric_dtype(view[col])]
    default = []
    for pat in TOTAL_PRIORITY:
        for col in nums:
            if col not in default and re.search(pat, col, re.I):
                default.append(col)
    default = (default or [col for col in nums if re.search(TOTAL_HINT, col, re.I)])[:4]
    st.markdown(f"**Showing {len(view):,} of {total_rows:,} entries**")
    if nums:
        pick = st.multiselect("Totals of", nums, default=default, key=f"{key}_tot")
        if pick:
            m = st.columns(min(len(pick), 4))
            for i, col in enumerate(pick):
                m[i % len(m)].metric(col, inr(view[col].sum(), 2))

    config = {"Sheet row": st.column_config.NumberColumn(format="%d", width="small")}
    for col in view.columns:
        if col == "Sheet row":
            continue
        if pd.api.types.is_datetime64_any_dtype(view[col]):
            config[col] = st.column_config.DateColumn(format="DD-MMM-YYYY")
        elif pd.api.types.is_numeric_dtype(view[col]):
            config[col] = st.column_config.NumberColumn(format="localized")
    st.dataframe(view, hide_index=True, width="stretch", height=min(38 * (len(view) + 1) + 4, 620),
                 column_config=config)
    st.caption("Click a column heading to sort. 'Sheet row' is the row number in the workbook.")
    st.download_button("⬇️ Download these entries (CSV)", view.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{title}.csv", key=f"{key}_csv")
