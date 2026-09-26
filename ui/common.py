"""Helpers shared by the app's pages."""
from __future__ import annotations

import pandas as pd
import streamlit as st

PROFIT, LOSS = "#2a78d6", "#e34948"
AGE_COLORS = ["#86b6ef", "#3987e5", "#1c5cab", "#123e75", "#b9b8b3"]  # light (new) -> dark (old); gray = undated

CSS = """
<style>
  .block-container {padding-top: 1.5rem;}
  div[data-testid="stMetricValue"] {font-size: 1.6rem;}
  .hint {color: #52514e; font-size: 0.9rem;}
  .flow {display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin: 0 0 0.6rem 0;}
  .flow span.step {background:#eef3fb; border:1px solid #cde2fb; border-radius:14px; padding:2px 10px;
                   font-size:0.85rem; color:#1c5cab;}
  .flow span.arrow {color:#86b6ef;}
  .preview {background:#f6f8fb; border:1px solid #e3e8ef; border-radius:8px; padding:10px 14px;}
</style>"""


# --------------------------------------------------------------------------- helpers
def inr(v, decimals: int = 0) -> str:
    """Indian digit grouping: 12,34,56,789."""
    if v is None or pd.isna(v):
        return ""
    neg, v = v < 0, abs(float(v))
    whole, frac = f"{v:.{decimals}f}".split(".") if decimals else (f"{v:.0f}", "")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join([head[max(i - 2, 0):i] for i in range(len(head), 0, -2)][::-1])
        whole = f"{head},{tail}"
    out = whole + (f".{frac}" if frac else "")
    return f"-{out}" if neg else out


def short_inr(v) -> str:
    """Crore / lakh shorthand for headline numbers."""
    a = abs(v)
    if a >= 1e7:
        return f"₹ {v / 1e7:,.2f} Cr"
    if a >= 1e5:
        return f"₹ {v / 1e5:,.2f} L"
    return f"₹ {inr(v)}"


def show_table(df: pd.DataFrame, money=(), rate=(), pct=(), dates=(), height=None):
    view = df.copy()
    for c in money:
        view[c] = view[c].map(inr)
    for c in rate:
        view[c] = view[c].map(lambda v: inr(v, 2))
    for c in pct:
        view[c] = view[c].map(lambda v: "" if pd.isna(v) else f"{v * 100:.1f}%")
    for c in dates:
        view[c] = pd.to_datetime(view[c]).dt.strftime("%d-%b-%Y").fillna("")
    right = {c: st.column_config.TextColumn(c, alignment="right") for c in [*money, *rate, *pct]}
    st.dataframe(view, hide_index=True, width="stretch", column_config=right,
                 height=height or min(38 * (len(view) + 1) + 4, 600))


def total(df, col):
    return float(df[col].sum()) if len(df) and col in df else 0.0
