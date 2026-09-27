"""Dropdown lists shared by the form and table entry styles, and the 'Add new' boxes that extend them.

Names added here (a new party, product, broker, reason ...) show up in every dropdown of that kind for the rest of
the session - in the forms and in the tables. Once an entry using the name is saved, the name is in the Master Sheet
and so in the lists for good.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

ADD_NEW = "➕ Add new…"
LABELS = {"party:Purchase": "Supplier", "party:Sales": "Customer", "product": "Product", "broker": "Broker",
          "company": "Company", "warehouse": "Warehouse", "type": "Type", "sub_type": "Sub Type",
          "branch": "Branch", "place": "Delivery place", "packing": "Packing", "reason": "Note reason",
          "expense": "Note expense"}


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def added(field: str) -> list[str]:
    return st.session_state.setdefault("added_names", {}).setdefault(field, [])


def remember(field: str, name) -> bool:
    """Adds a name to this session's list for `field`. False when it is empty or already there."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    lst = added(field)
    if not name or _norm(name) in {_norm(v) for v in lst}:
        return False
    lst.append(name)
    return True


def options(field: str | None, *series) -> list[str]:
    """Names already in the sheet (from any of `series`) plus names added this session, A-Z, one spelling each."""
    seen = {}
    for s in series:
        if s is None:
            continue
        for v in pd.Series(s).dropna():
            t = str(v).strip()
            if t:
                seen.setdefault(_norm(t), t)
    for v in (added(field) if field else []):
        seen.setdefault(_norm(v), v)
    return sorted(seen.values(), key=str.lower)


def pick(label, opts, key, default=None, required=False, help=None, field=None):
    """Dropdown of known names with an explicit '➕ Add new…' choice (typing a new name also works).
    Returns the chosen or new name, or None."""
    opts = [o for o in opts if o != ADD_NEW]
    if default and default not in opts:
        opts = [default] + opts
    choice = st.selectbox(label + (" *" if required else ""), [ADD_NEW] + opts,
                          index=opts.index(default) + 1 if default else None, key=key, accept_new_options=True,
                          placeholder="Choose, or type a new one", help=help)
    if choice != ADD_NEW:
        return choice
    new = st.text_input(f"New {label.lower()}" + (" *" if required else ""), key=f"{key}__new",
                        placeholder=f"Type the new {label.lower()}")
    new = re.sub(r"\s+", " ", new).strip()
    if new and field:
        remember(field, new)
    return new or None


def add_new_box(key: str, fields: dict[str, tuple] | list[str]):
    """'➕ Add new …' panel above a table: adds names to the table's dropdown lists.
    fields: {field: (series of the names already in the sheet, ...)} - those names are not added again."""
    if not isinstance(fields, dict):
        fields = {f: () for f in fields}
    with st.expander("➕ Add a new " + " / ".join(LABELS[f].lower() for f in fields)):
        c = st.columns([1, 3, 1])
        field = c[0].selectbox("What", list(fields), format_func=LABELS.get, key=f"{key}_addwhat")
        text = c[1].text_area("Name(s)", key=f"{key}_addtext", height=68,
                              placeholder="One per line - you can paste a list from Excel")
        c[2].markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)
        if c[2].button("Add", key=f"{key}_addbtn", width="stretch"):
            known = {_norm(v) for v in options(None, *fields[field])}
            typed = [n.strip() for n in text.splitlines() if n.strip()]
            new = [n for n in typed if _norm(n) not in known and remember(field, n)]
            there = [n for n in typed if _norm(n) in known]
            msg = []
            if new:
                msg.append(f"Added to the {LABELS[field].lower()} list: " + ", ".join(new) + ".")
            if there:
                msg.append("Already in the sheet: " + ", ".join(there) + ".")
            if msg:
                st.session_state["flash_added"] = " ".join(msg)
            st.session_state.pop(f"{key}_addtext", None)
            st.rerun()
        if msg := st.session_state.pop("flash_added", None):
            st.success(msg + " Pick names from the dropdowns in the table.")
        st.caption("New names are added to the dropdowns in the tables and forms. They are saved to the Master "
                   "Sheet with the first entry that uses them.")
