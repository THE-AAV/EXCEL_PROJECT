"""Entering transactions in the web app, undo, live updates and the office set-up."""
import time
from datetime import date, timedelta

import openpyxl
import pytest

from server.main import create_app

from server.office import daily_backup, office_urls
from tests.test_server import (AS_OF, H, add_user, assert_same, client, rich_master, settings, setup_admin,  # noqa: F401
                               sign_in, upload)

P = {"as_of": AS_OF}


def ctx(client):
    r = client.get("/api/entry/context")
    assert r.status_code == 200, r.text
    return r.json()


def entry(client, action, body):
    r = client.post(f"/api/entry/{action}", json={**body, "version": ctx(client)["version"]})
    assert r.status_code == 200, r.text
    return r.json()


def imported(client, path):
    setup_admin(client)
    client.post(f"/api/imports/{upload(client, path).json()['id']}/confirm")


def test_the_whole_purchase_flow_updates_the_reports(client, rich_master, settings):
    imported(client, rich_master)
    before = client.get("/api/reports", params=P).json()

    entry(client, "order", {"kind": "PO", "fields": {"party": "New Mill", "commodity": "Urad", "qty_mt": 10, "rate": 90,
                                                     "date": "2026-09-10"}})
    order = next(o for o in ctx(client)["orders"]["PO"] if o["party"] == "New Mill")
    assert order["bal_qty_mt"] == 10

    r = entry(client, "invoice", {"kind": "Purchase", "header": {"party": "New Mill", "bill_no": "NM-1",
                                                                  "bill_date": "2026-09-12"},
                                  "lines": [{"commodity": "Urad", "qty": 4000, "rate": 90, "gst_pct": 5,
                                             "order_row": order["source_row"]}],
                                  "expenses": {"labour": 1000}})
    assert r["message"] == "Purchase invoice NM-1 saved for New Mill (1 item)"
    c = ctx(client)
    assert next(o for o in c["orders"]["PO"] if o["party"] == "New Mill")["bal_qty_mt"] == 6
    bill = next(b for b in c["bills"]["Purchase"] if b["bill_no"] == "NM-1")
    assert (bill["amount"], bill["net_amount"], bill["gst"], bill["bill_amt"]) == (360000, 361000, 18050, 378050)

    entry(client, "note", {"kind": "Purchase", "row": bill["source_row"], "date": "2026-09-13",
                           "lines": [{"reason": "Weight shortage", "qty": 100, "rate": 90, "gst_pct": 5}]})
    entry(client, "expenses", {"kind": "Purchase", "row": bill["source_row"], "changes": {"storage": 500}})
    due = next(b for b in ctx(client)["outstanding"]["Purchase"] if b["party"] == "New Mill")
    assert due["outstanding"] == 378050 - 9450
    entry(client, "settlement", {"kind": "Purchase", "date": "2026-09-20",
                                 "allocations": [{"row": due["row"], "amount": 368600, "tds": 0, "outstanding": 368600}]})

    after = client.get("/api/reports", params=P).json()
    mill = next(p for p in after["creditors"]["summary"] if p["party"] == "New Mill")
    assert (mill["billed"], mill["note"], mill["paid"], mill["closing"]) == (378050, 9450, 368600, 0)
    assert after["dashboard"]["purchase_bills"] == before["dashboard"]["purchase_bills"] + 1
    assert [e["entry"] for e in client.get("/api/entry-recent").json()][:2] == [
        "Payment saved for New Mill", "Expenses saved for New Mill"]
    actions = [a["action"] for a in client.get("/api/audit").json()]
    assert actions[:5] == ["entry.settlement", "entry.expenses", "entry.note", "entry.invoice", "entry.order"]

    # the Master Sheet kept on the computer running the app follows every change
    live = settings.data_dir / "Master Sheet (live).xlsx"
    for _ in range(50):
        if live.exists() and "NM-1" in {c.value for c in openpyxl.load_workbook(live)["Purchase"]["K"]}:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("live Master Sheet not written")


def test_an_entry_leaves_everything_else_as_it_was(client, rich_master):
    imported(client, rich_master)
    before = client.get("/api/reports", params=P).json()
    entry(client, "order", {"kind": "SO", "fields": {"party": "C", "commodity": "Moong", "qty_mt": 1, "rate": 100,
                                                     "date": "2026-09-01"}})
    after = client.get("/api/reports", params=P).json()
    for k in ("pnl", "creditors", "debtors", "margins", "debit_notes", "credit_notes", "checks"):
        assert_same(after[k], before[k], k)
    assert len(after["so"]) == len(before["so"]) + 1


def test_undo_and_saving_against_old_lists(client, rich_master):
    imported(client, rich_master)
    old = ctx(client)
    before = client.get("/api/reports", params=P).json()
    entry(client, "invoice", {"kind": "Sales", "header": {"party": "C", "bill_no": "S-9", "bill_date": "2026-09-05"},
                              "lines": [{"commodity": "Urad", "qty": 100, "rate": 130, "gst_pct": 5}]})
    # a form filled in before that entry is refused, so rows can't point at the wrong bill
    r = client.post("/api/entry/order", json={"version": old["version"], "kind": "PO", "fields": {
        "party": "S", "commodity": "Urad", "qty_mt": 1, "rate": 1, "date": "2026-09-05"}})
    assert r.status_code == 409 and "Someone else saved" in r.json()["detail"]

    assert client.post("/api/entry-undo").json() == {"message": "Undone: Sales invoice S-9 saved for C (1 item)"}
    assert_same(client.get("/api/reports", params=P).json()["pnl"], before["pnl"])
    assert client.get("/api/entry-recent").json()[0]["status"] == "undone"
    assert client.post("/api/entry-undo").status_code == 409   # the import itself is undone on the Import page


def test_mistakes_are_explained_and_viewers_cannot_enter(client, rich_master):
    imported(client, rich_master)
    r = client.post("/api/entry/order", json={"kind": "PO", "fields": {"party": "S", "commodity": "Urad",
                                                                        "qty_mt": 0, "rate": 5, "date": "2026-09-01"}})
    assert r.status_code == 422 and r.json()["detail"] == "Enter the quantity and the rate"
    no = ctx(client)["all_contracts"]["PO"][0]
    r = client.post("/api/entry/order", json={"kind": "PO", "contract_no": str(no), "fields": {
        "party": "S", "commodity": "Urad", "qty_mt": 1, "rate": 5, "date": "2026-09-01"}})
    assert r.status_code == 422 and "already used" in r.json()["detail"]

    add_user(client, "reader", "viewer")
    sign_in(client, "reader")
    assert client.get("/api/entry/context").status_code == 403
    assert client.post("/api/entry/order", json={}).status_code == 403
    assert client.get("/api/sheets").status_code == 200


def test_starting_with_no_workbook_at_all(client):
    setup_admin(client)
    entry(client, "order", {"kind": "PO", "fields": {"party": "First Supplier", "commodity": "Chana", "qty_mt": 2,
                                                     "rate": 60, "date": "2026-09-01"}})
    order = ctx(client)["orders"]["PO"][0]
    assert order["contract_no"] in (1, "1")
    entry(client, "invoice", {"kind": "Purchase", "header": {"party": "First Supplier", "bill_no": "1",
                                                              "bill_date": "2026-09-02"},
                              "lines": [{"commodity": "Chana", "qty": 2000, "rate": 60, "gst_pct": 5,
                                         "order_row": order["source_row"]}]})
    body = client.get("/api/reports", params=P).json()
    assert body["dashboard"]["purchase_bills"] == 1 and body["pnl"][0]["product"] == "CHANA"
    sheets = {s["key"]: s for s in client.get("/api/sheets").json()}
    assert len(sheets["purchase"]["rows"]) == 1 and len(sheets["po"]["rows"]) == 1
    headers = [c[1] for c in sheets["purchase"]["cols"]]
    assert "PARTY NAME" in headers and "BILL NO." in headers


def test_live_updates_and_office_details(client, rich_master):
    imported(client, rich_master)
    v1 = client.get("/api/version").json()
    entry(client, "order", {"kind": "PO", "fields": {"party": "S", "commodity": "Urad", "qty_mt": 1, "rate": 5,
                                                     "date": "2026-09-01"}})
    v2 = client.get("/api/version").json()
    assert v1["version"] != v2["version"]
    assert v2 == {"version": v2["version"], "last_change": "Purchase order saved for S", "by": "owner"}
    office = client.get("/api/office").json()
    assert office["urls"] and all(u.startswith("http://") for u in office["urls"])
    assert office["live_file"].endswith("Master Sheet (live).xlsx")


def test_on_koyeb_the_app_shows_its_web_address_and_needs_an_online_database(client, settings, monkeypatch):
    setup_admin(client)
    assert client.get("/api/office").json()["online"] is False
    monkeypatch.setenv("KOYEB_APP_NAME", "business-reports")
    monkeypatch.setenv("KOYEB_PUBLIC_DOMAIN", "business-reports-shubham.koyeb.app")
    office = client.get("/api/office").json()
    assert office["online"] and office["urls"] == []
    assert office["public_url"] == "https://business-reports-shubham.koyeb.app"
    if settings.database_url.startswith("sqlite"):   # its disk is wiped on restarts, so a file database is refused
        with pytest.raises(SystemExit, match="DATABASE_URL"):
            create_app(settings)


def test_daily_backups_keep_the_last_30(tmp_path):
    db_file = tmp_path / "business.db"
    db_file.write_text("data")
    folder = tmp_path / "backups"
    folder.mkdir()
    for i in range(35):
        (folder / f"business-{date(2026, 1, 1) + timedelta(days=i):%Y-%m-%d}.db").write_text("old")
    made = daily_backup(db_file)
    assert made.read_text() == "data"
    kept = sorted(p.name for p in folder.iterdir())
    assert len(kept) == 30 and kept[-1] == made.name
    assert office_urls(8000)[-1].endswith(":8000")


def test_a_table_of_rows_is_saved_together_and_undone_together(client, rich_master):
    imported(client, rich_master)
    before = client.get("/api/reports", params=P).json()
    order = {"kind": "PO", "fields": {"party": "Grid Mill", "commodity": "Urad", "qty_mt": 2, "rate": 80,
                                      "date": "2026-09-02"}}
    bad = {"kind": "PO", "fields": {**order["fields"], "qty_mt": 0}}
    r = client.post("/api/entry/batch", json={"version": ctx(client)["version"], "what": "purchase orders", "items": [
        {"action": "order", "label": "Row 1", "body": order}, {"action": "order", "label": "Row 2", "body": bad}]})
    assert r.status_code == 422 and r.json()["detail"] == "Row 2: Enter the quantity and the rate"
    assert len(client.get("/api/reports", params=P).json()["po"]) == len(before["po"])   # nothing was saved

    r = entry(client, "batch", {"what": "purchase orders", "items": [
        {"action": "order", "label": f"Row {i}", "body": order} for i in (1, 2, 3)]})
    assert r["message"] == "3 purchase orders saved for Grid Mill"
    po = client.get("/api/reports", params=P).json()["po"]
    assert len(po) == len(before["po"]) + 3 and len({o["contract_no"] for o in po}) == len(po)
    assert client.get("/api/audit").json()[0]["action"] == "entry.order"
    assert client.post("/api/entry-undo").json()["message"] == "Undone: 3 purchase orders saved for Grid Mill"
    assert len(client.get("/api/reports", params=P).json()["po"]) == len(before["po"])
    assert client.post("/api/entry/batch", json={"items": []}).status_code == 422
