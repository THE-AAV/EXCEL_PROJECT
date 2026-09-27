"""Headless checks of the Enter Transactions page: every section renders in both entry styles, the
'➕ Add new…' choices work, and the table style fills in the same details as the form."""
from datetime import date

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from mis_reports import load_master
from tests.test_entries import build_master
from ui.entries_page import NUMS, STEPS


def _page(path):
    import streamlit as st

    from mis_reports import load_master
    from mis_reports.entries import MasterFile
    from ui import entries_page

    p = st.session_state["master_path"]
    entries_page.render(load_master(p), MasterFile(p), {})


@pytest.fixture
def master(tmp_path):
    path = tmp_path / "master.xlsx"
    build_master(path)
    return path


def _app(master, step, style):
    at = AppTest.from_function(_page, args=(None,), default_timeout=30)
    at.session_state["master_path"] = str(master)
    at.session_state["entry_step"] = f"{NUMS[STEPS.index(step)]} {step}"
    at.session_state["entry_style"] = style
    return at.run()


@pytest.mark.parametrize("style", ["📝 Form", "📊 Table (like Excel)"])
@pytest.mark.parametrize("step", STEPS)
def test_every_section_renders(master, step, style):
    at = _app(master, step, style)
    assert not at.exception, at.exception


def test_form_add_new_party(master):
    at = _app(master, "Purchase Order", "📝 Form")
    party = next(s for s in at.selectbox if s.label == "Party *")
    assert party.options[0] == "➕ Add new…" and "OLD SUPPLIER" in party.options
    party.select("➕ Add new…").run()
    new = next(t for t in at.text_input if t.label == "New party *")
    new.input("BRAND NEW TRADERS").run()
    assert not at.exception
    # the new name is now offered in the table's dropdown too
    assert "BRAND NEW TRADERS" in at.session_state["added_names"]["party:Purchase"]


def test_table_add_new_box_and_order_defaults(master):
    at = _app(master, "Purchase Order", "📊 Table (like Excel)")
    at.text_area[0].input("NEW SUPPLIER\nOld Supplier").run()   # the second is already known
    at.button(key="tbl_PO_addbtn").click().run()
    assert at.session_state["added_names"]["party:Purchase"] == ["NEW SUPPLIER"]
    assert not at.exception


def test_table_order_fills_party_usual_details(master):
    from ui import table_entry

    data = load_master(master)
    usual = table_entry._party_defaults(data.purchase, data.po)
    prev = usual("old supplier")
    assert prev["party"] == "OLD SUPPLIER"
    assert usual("nobody") == {}


def _fill(at, key, rows: dict):
    at.session_state[f"{key}_0"] = {"edited_rows": rows, "added_rows": [], "deleted_rows": []}
    return at.run()


def _fill_and_save(at, key, rows: dict):
    _fill(at, key, rows)   # the Save button is enabled once the table has rows to save
    at.session_state[f"{key}_0"] = {"edited_rows": rows, "added_rows": [], "deleted_rows": []}
    at.button(key=f"{key}_save").click()
    return at.run()


def test_table_order_saves_new_names_and_extra_fields(master):
    at = _app(master, "Purchase Order", "📊 Table (like Excel)")
    at.toggle(key="tbl_PO_free").set_value(True).run()   # type names freely
    _fill_and_save(at, "tbl_PO", {0: {"Party": "NEW MILLS", "Product": "Tur", "Qty (MT)": 10, "Rate (₹/kg)": 95,
                                      "Company": "NEWCO", "Warehouse": "WH-9", "Branch": "Indore",
                                      "Delivery Place": "Mandi", "Packing": "50 kg"}})
    assert not at.exception and not at.error
    row = load_master(master).po.iloc[-1]
    assert (row["party"], row["commodity"], row["company"], row["branch"], row["delivery_place"], row["packing"]) \
        == ("NEW MILLS", "Tur", "NEWCO", "Indore", "Mandi", "50 kg")


def test_table_invoice_fills_party_usual_details(master):
    at = _app(master, "Purchase Invoice", "📊 Table (like Excel)")
    _fill_and_save(at, "tbl_inv_Purchase", {0: {"Bill No": "B-77", "Party": "OLD SUPPLIER", "Product": "Urad",
                                                "Weight (kg)": 500, "Rate (₹/kg)": 92}})
    assert not at.exception and not at.error
    row = load_master(master).purchase.iloc[-1]
    assert (row["party"], row["bill_no"], row["qty"], row["company"], row["type"]) == \
        ("OLD SUPPLIER", "B-77", 500, "SCPL", "Local")
    assert round(row["gst"] / row["net_amount"] * 100, 1) == 5.0   # empty GST % = 5% for a Local bill


def test_table_payment_more_than_outstanding_is_blocked(master):
    at = _app(master, "Payment", "📊 Table (like Excel)")
    from mis_reports import reports as R
    from ui import table_entry

    ledger = R.creditors(load_master(master), R.Filters(as_of=date.today(), aliases={}))
    b = ledger.bills[ledger.bills["source_row"].notna()].iloc[0]
    label = f"{b.party} · Bill {b.bill_no} · due ₹{table_entry.inr(b.outstanding)} · row {int(b.source_row)}"
    _fill(at, "tbl_settle_Purchase", {0: {"Invoice": label, "Amount (₹)": float(b.outstanding) + 5000}})
    assert any("more than" in w.value for w in at.warning)
    assert at.button(key="tbl_settle_Purchase_save").disabled
    _fill_and_save(at, "tbl_settle_Purchase", {0: {"Invoice": label, "Amount (₹)": float(b.outstanding) + 5000,
                                                   "Advance": True}})
    assert not at.error
    paid = load_master(master).purchase.loc[lambda d: d["source_row"] == b.source_row, "paid"].iloc[0]
    assert round(paid, 2) == round(float(b.outstanding) + 5000, 2)
