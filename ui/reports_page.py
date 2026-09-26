"""Reports page: dashboard, product P&L, creditors, debtors, orders, data checks, product names."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from mis_reports import reports as R
from mis_reports.pipeline import save_aliases

from .common import inr, short_inr, show_table, total


def render(data, rs, opts, aliases, as_of, source_name):
    # --------------------------------------------------------------------------- header
    st.title("Business Reports")
    st.markdown(f"<span class='hint'>Source: <b>{source_name}</b> · {len(data.purchase)} purchase bills · "
                f"{len(data.sales)} sales bills · balances as on {as_of:%d-%b-%Y}</span>", unsafe_allow_html=True)
    if len(rs.checks):
        st.warning(f"⚠️ {len(rs.checks)} row(s) in the Master Sheet may need attention - see the **Data Checks** tab.")

    tabs = st.tabs(["🏠 Dashboard", "📦 Product P&L", "🏬 Stock Summary", "🏭 Creditors (we pay)",
                    "🧾 Debtors (we receive)", "📑 Orders", "📝 Debit / Credit Notes", "⚠️ Data Checks",
                    "⚙️ Product Names"])

    pnl, cred, debt = rs.pnl, rs.creditors, rs.debtors

    # --------------------------------------------------------------------------- dashboard
    with tabs[0]:
        c = st.columns(4)
        c[0].metric("Net Sales (excl. GST)", short_inr(total(pnl, "net_sales")))
        np_ = total(pnl, "net_profit")
        c[1].metric("Net Profit / Loss", short_inr(np_),
                    delta=f"{np_ / total(pnl, 'net_sales') * 100:.1f}% margin" if total(pnl, "net_sales") else None,
                    delta_color="normal" if np_ >= 0 else "inverse")
        c[2].metric("Payable to Creditors", short_inr(total(cred.summary, "closing")),
                    help="What we owe suppliers, incl. GST")
        c[3].metric("Receivable from Debtors", short_inr(total(debt.summary, "closing")),
                    help="What customers owe us, incl. GST")
        c = st.columns(4)
        c[0].metric("Gross Profit", short_inr(total(pnl, "gross_profit")))
        c[1].metric("Closing Stock Value", short_inr(total(pnl, "closing_value")))
        c[2].metric("Payable overdue > 90 days", short_inr(total(cred.summary, "Over 90 days")))
        c[3].metric("Receivable overdue > 90 days", short_inr(total(debt.summary, "Over 90 days")))

        if len(pnl):
            no_cost = pnl.loc[pnl["purchase_qty"] == 0, "product"].tolist()
            if no_cost:
                st.info("ℹ️ No purchase found for **" + ", ".join(no_cost) + "**, so its sales are counted "
                        "without any cost and its profit is overstated. If it was bought under another name, "
                        "map the names in the **Product Names** tab.")
        st.subheader("Stock in hand")
        simple_stock(rs.stock)

    # --------------------------------------------------------------------------- product P&L
    STATEMENT = [
        ("PURCHASE", None), ("Purchase Qty (kg)", "purchase_qty"),
        ("Less: Qty on Debit Notes (kg)", "purchase_return_qty"), ("Net Purchase Qty (kg)", "net_purchase_qty"),
        ("Purchase Value", "purchase_value"), ("Add: Pre-bill Expenses", "pre_bill_exp"),
        ("Less: Purchase Discount", "purchase_discount"), ("Less: Debit Notes", "purchase_returns"),
        ("Net Purchase Cost", "net_purchase"), ("Avg Landed Cost / kg", "avg_cost_rate"),
        ("SALES", None), ("Sales Qty (kg)", "sales_qty"), ("Less: Qty on Credit Notes (kg)", "sales_return_qty"),
        ("Net Sales Qty (kg)", "net_sales_qty"), ("Sales Value", "sales_value"),
        ("Less: Sales Discount", "sales_discount"), ("Less: Credit Notes", "sales_returns"),
        ("Net Sales", "net_sales"), ("Avg Sale Rate / kg", "avg_sales_rate"),
        ("STOCK", None), ("Closing Stock Qty (kg)", "closing_qty"), ("Closing Stock Value", "closing_value"),
        ("PROFIT & LOSS", None), ("Cost of Goods Sold", "cogs"), ("Gross Profit", "gross_profit"),
        ("Less: Post-bill Exp. (Purchase)", "post_exp_purchase"), ("Less: Post-bill Exp. (Sales)", "post_exp_sales"),
        ("Net Profit / (Loss)", "net_profit"), ("Net Margin", "margin_pct"),
    ]

    with tabs[1]:
        st.subheader("Product-wise Profit & Loss (exclusive of GST)")
        if not len(pnl):
            st.info("No purchases or sales match the selected filters.")
        else:
            pick = st.selectbox("Show statement for", ["All products (total)", *pnl["product"].tolist()])
            row = pnl.sum(numeric_only=True) if pick.startswith("All") else pnl.set_index("product").loc[pick]
            if pick.startswith("All"):
                row["avg_cost_rate"] = row["net_purchase"] / row["net_purchase_qty"] if row["net_purchase_qty"] else 0
                row["avg_sales_rate"] = row["net_sales"] / row["net_sales_qty"] if row["net_sales_qty"] else 0
                row["margin_pct"] = row["net_profit"] / row["net_sales"] if row["net_sales"] else 0
            lines = []
            for label, key in STATEMENT:
                if key is None:
                    lines.append({"Particulars": f"**{label}**", "Amount": ""})
                elif key == "margin_pct":
                    lines.append({"Particulars": label, "Amount": f"{row[key] * 100:.1f}%"})
                else:
                    lines.append({"Particulars": label, "Amount": inr(row[key], 2 if "rate" in key else 0)})
            a, b = st.columns([2, 3])
            with a:
                st.table(pd.DataFrame(lines).set_index("Particulars"))
            with b:
                if not pick.startswith("All") and pnl.set_index("product").loc[pick, "remark"]:
                    st.info(pnl.set_index("product").loc[pick, "remark"])
                st.markdown(
                    "<div class='hint'><b>How it is worked out</b><br>"
                    "• All figures are <b>before GST</b>.<br>"
                    "• Net Purchase Cost = purchase value + pre-bill expenses (Adhat, AMC, labour, transport, "
                    "WH load, bags, other) − discount − debit notes.<br>"
                    "• Debit / credit note quantities come off the kg bought / sold; their value (before GST) "
                    "plus other charges comes off purchases / sales.<br>"
                    "• Stock not yet sold is valued at the average landed cost per kg and carried forward, so the "
                    "P&L only carries the cost of what was actually sold.<br>"
                    "• Post-bill expenses (storage, brokerage, sampling, repacking, transport, loading) are "
                    "charged in full.</div>", unsafe_allow_html=True)
            st.markdown("#### All products")
            cols = {"product": "Product", "purchase_qty": "Purchase Qty (kg)", "net_purchase": "Net Purchase",
                    "avg_cost_rate": "Cost / kg", "sales_qty": "Sales Qty (kg)", "net_sales": "Net Sales",
                    "avg_sales_rate": "Sale / kg", "closing_qty": "Closing Qty (kg)", "closing_value": "Closing Stock",
                    "gross_profit": "Gross Profit", "post_bill_exp": "Post-bill Exp.", "net_profit": "Net Profit",
                    "margin_pct": "Margin", "remark": "Remark"}
            view = pnl[list(cols)].rename(columns=cols)
            show_table(view, money=["Purchase Qty (kg)", "Net Purchase", "Sales Qty (kg)", "Net Sales",
                                    "Closing Qty (kg)", "Closing Stock", "Gross Profit", "Post-bill Exp.", "Net Profit"],
                       rate=["Cost / kg", "Sale / kg"], pct=["Margin"])

        st.markdown("#### Bill-wise margin (sales bills linked to a purchase bill)")
        m = rs.margins
        if not len(m):
            st.caption("No sales bills are linked to a purchase bill yet. Link them in ⑦ Sales Invoice.")
        else:
            mc = {"sales_bill": "Sales Bill", "sales_date": "Date", "customer": "Customer", "product": "Product",
                  "qty": "Qty (kg)", "sale_rate": "Sale / kg", "purchase_bill": "Purchase Bill", "supplier": "Supplier",
                  "cost_rate": "Cost / kg", "margin": "Margin", "margin_per_kg": "Margin / kg", "margin_pct": "Margin %"}
            show_table(m[list(mc)].rename(columns=mc), money=["Qty (kg)", "Margin"],
                       rate=["Sale / kg", "Cost / kg", "Margin / kg"], pct=["Margin %"], dates=["Date"])
            st.caption("Cost / kg is the landed cost of the linked purchase bill (value + pre-bill expenses − "
                       "discount). Post-bill expenses and notes are not included here.")

    # --------------------------------------------------------------------------- stock summary
    with tabs[2]:
        st.subheader("Stock Summary (kg)")
        stock = rs.stock
        if not len(stock):
            st.info("No stock movements match the selected filters.")
        else:
            simple_stock(stock)
            with st.expander("More detail: bought, sold, returns and open orders"):
                sc = {"product": "Product", "purchase_qty": "Purchased", "purchase_return_qty": "Returned to Suppliers",
                      "sales_qty": "Sold", "sales_return_qty": "Returned by Customers", "closing_qty": "Stock in Hand",
                      "pending_po_qty": "To Receive (PO)", "pending_so_qty": "To Deliver (SO)",
                      "projected_qty": "Stock after Orders"}
                show_table(stock[list(sc)].rename(columns=sc),
                           money=["Purchased", "Returned to Suppliers", "Sold", "Returned by Customers",
                                  "Stock in Hand", "To Receive (PO)", "To Deliver (SO)", "Stock after Orders"])
                st.caption("Stock in Hand = Purchased − Returned to Suppliers − Sold + Returned by Customers. "
                           "Stock after Orders also counts open purchase and sales contracts.")


    # --------------------------------------------------------------------------- ledgers
    def ledger_tab(led: R.Ledger, who: str, billed: str, paid: str, note: str, key: str):
        s = led.summary
        c = st.columns(4)
        c[0].metric(f"Total {billed}", short_inr(total(s, "billed")))
        c[1].metric(f"Total {paid}", short_inr(total(s, "paid")))
        c[2].metric("Closing balance", short_inr(total(s, "closing")))
        c[3].metric("Parties with balance", int((s["closing"] > 0.5).sum()) if len(s) else 0)

        f1, f2 = st.columns([3, 2])
        search = f1.text_input("🔍 Search party", key=f"{key}_search", placeholder="Type part of a name")
        only_open = f2.checkbox("Only parties with a balance", value=True, key=f"{key}_open")
        view = s.copy()
        if search:
            view = view[view["party"].str.contains(search, case=False, na=False, regex=False)]
        if only_open:
            view = view[view["closing"].abs() > 0.5]
        cols = {"party": "Party", "opening": "Opening", "bills": "Bills", "billed": billed, "paid": paid,
                "tds": "TDS", "note": note, "closing": "Closing Balance", **{b: b for b in R.BUCKET_NAMES},
                "oldest_days": "Oldest (days)", "last_bill": "Last Bill", "last_payment": "Last Payment"}
        show_table(view[list(cols)].rename(columns=cols),
                   money=["Opening", billed, paid, "TDS", note, "Closing Balance", *R.BUCKET_NAMES, "Oldest (days)"],
                   dates=["Last Bill", "Last Payment"], height=420)
        csv = view[list(cols)].rename(columns=cols).to_csv(index=False).encode()
        st.download_button(f"⬇️ Download this {who} list (CSV)", csv, file_name=f"{who}_{as_of:%d-%m-%Y}.csv",
                           key=f"{key}_csv")

        st.markdown("#### Outstanding bills of a party")
        parties = view["party"].tolist()
        if parties:
            party = st.selectbox("Choose party", parties, key=f"{key}_party")
            bills = led.bills[led.bills["party"] == party]
            if len(bills):
                bcols = {"bill_no": "Bill No.", "bill_date": "Bill Date", "product": "Product",
                         "bill_amount": "Bill Amount", "outstanding": "Outstanding", "days": "Days",
                         "age_bucket": "Age", "source_row": "Master Sheet Row"}
                show_table(bills[list(bcols)].rename(columns=bcols), money=["Bill Amount", "Outstanding", "Days"],
                           dates=["Bill Date"])
                st.caption("Payments are adjusted against the oldest bills first.")
            else:
                st.success("No bills outstanding for this party.")


    with tabs[3]:
        st.subheader("Creditors - purchase parties we have to pay (incl. GST)")
        ledger_tab(cred, "Creditors", "Payable", "Paid", "Debit Note / Ded.", "cred")
    with tabs[4]:
        st.subheader("Debtors - sales parties who have to pay us (incl. GST)")
        ledger_tab(debt, "Debtors", "Receivable", "Received", "Credit Note / Ded.", "debt")

    # --------------------------------------------------------------------------- orders, notes, checks, settings
    with tabs[5]:
        orders_tab(rs)
    with tabs[6]:
        notes_tab(rs)

    with tabs[7]:
        st.subheader("Rows in the Master Sheet that need attention")
        st.caption("These rows are still included where possible, but a missing date, quantity or amount can make "
                   "the reports less accurate. Fix them in the Master Sheet; the reports update automatically.")
        if len(rs.checks):
            st.dataframe(rs.checks.rename(columns=str.title), hide_index=True, width="stretch")
        else:
            st.success("No problems found. 🎉")

    with tabs[8]:
        st.subheader("Product name mapping")
        st.caption("If the same product is typed differently in the Purchase and Sales sheets (for example "
                   "'SOYA BEANS' and 'Soyabean'), add a row so both are reported together. Capital/small letters "
                   "and extra spaces are already ignored.")
        st.write("Product names found in the file:", ", ".join(opts["products"]))
        edit = st.data_editor(pd.DataFrame(sorted(aliases.items()), columns=["Name in sheet", "Report as"]),
                              num_rows="dynamic", width="stretch", key="alias_editor")
        if st.button("💾 Save product names", type="primary"):
            save_aliases({str(a).strip(): str(b).strip() for a, b in edit.itertuples(index=False)
                          if pd.notna(a) and pd.notna(b) and str(a).strip() and str(b).strip()})
            st.success("Saved. Reports now use the new names.")
            st.rerun()


ORDER_COLS = {"contract_no": "Contract", "date": "Date", "party": "Party", "broker": "Broker", "product": "Product",
              "qty_mt": "Qty (MT)", "cancel_qty": "Cancelled", "recd_qty": "{done} (MT)", "bal_qty_mt": "Balance (MT)",
              "rate": "Rate / kg", "order_value": "Order Value", "amount": "Balance Value", "done_pct": "{done} %",
              "status": "Status", "delivery_date": "Delivery Date", "delivery_place": "Delivery Place",
              "bill_no": "Invoices", "days_open": "Days Open"}


def orders_tab(rs):
    st.subheader("Purchase and sales orders")
    kind = st.radio("Orders", ["Purchase Orders", "Sales Orders", "Summary by product"], horizontal=True,
                    key="orders_kind", label_visibility="collapsed")
    if kind == "Summary by product":
        if len(rs.orders):
            o = rs.orders.rename(columns={"order_type": "Order", "product": "Product", "contracts": "Open Contracts",
                                          "bal_qty_kg": "Balance Qty (kg)", "amount": "Amount",
                                          "avg_rate": "Avg Rate / kg"})
            show_table(o[["Order", "Product", "Open Contracts", "Balance Qty (kg)", "Amount", "Avg Rate / kg"]],
                       money=["Balance Qty (kg)", "Amount"], rate=["Avg Rate / kg"])
        else:
            st.info("No open orders.")
        return
    df = rs.po_detail if kind == "Purchase Orders" else rs.so_detail
    done = "Received" if kind == "Purchase Orders" else "Delivered"
    if not len(df):
        st.info(f"No {kind.lower()} in the Master Sheet yet.")
        return
    is_open = df["status"].fillna("").str.lower() != "closed"
    c = st.columns(4)
    c[0].metric("Contracts", len(df))
    c[1].metric("Open", int(is_open.sum()))
    c[2].metric("Balance to " + ("receive" if done == "Received" else "deliver") + " (MT)",
                inr(df.loc[is_open, "bal_qty_mt"].sum(), 2))
    c[3].metric("Balance value", short_inr(df.loc[is_open, "amount"].sum()))
    f1, f2 = st.columns([2, 3])
    show = f1.radio("Show", ["Open", "Closed", "All"], horizontal=True, key=f"orders_show_{kind}")
    search = f2.text_input("🔍 Search party / product / contract", key=f"orders_search_{kind}")
    view = df[is_open] if show == "Open" else df[~is_open] if show == "Closed" else df
    if search:
        s = search.lower()
        view = view[view[["party", "product", "contract_no"]].astype(str).apply(
            lambda col: col.str.lower().str.contains(s, regex=False)).any(axis=1)]
    cols = {k: v.format(done=done) for k, v in ORDER_COLS.items()}
    show_table(view[list(cols)].rename(columns=cols),
               money=["Qty (MT)", "Cancelled", f"{done} (MT)", "Balance (MT)", "Order Value", "Balance Value",
                      "Days Open"],
               rate=["Rate / kg"], pct=[f"{done} %"], dates=["Date", "Delivery Date"])


def notes_tab(rs):
    st.subheader("Debit notes (to suppliers) and credit notes (to customers)")
    for df, name in ((rs.debit_notes, "Debit Notes"), (rs.credit_notes, "Credit Notes")):
        st.markdown(f"#### {name}")
        if not len(df):
            st.caption(f"No {name.lower()} entered from the app yet.")
            continue
        c = st.columns(4)
        c[0].metric("Notes", len(df))
        c[1].metric("Quantity (kg)", inr(df["qty"].sum()))
        c[2].metric("GST", short_inr(df["gst"].sum()))
        c[3].metric("Total", short_inr(df["total"].sum()))
        nc = {"note_no": "Note No", "date": "Date", "party": "Party", "bill_no": "Bill", "product": "Product",
              "qty": "Qty (kg)", "rate": "Rate", "taxable": "Value", "gst_pct": "GST %", "gst": "GST",
              "other": "Other Charges", "total": "Total", "reason": "Reason"}
        show_table(df[list(nc)].rename(columns=nc), money=["Qty (kg)", "Value", "GST", "Other Charges", "Total"],
                   rate=["Rate", "GST %"], dates=["Date"])


def simple_stock(stock):
    """Plain summary: how much of each product we have and what it is worth."""
    if stock is None or not len(stock):
        st.info("No stock yet.")
        return
    have = stock[stock["closing_qty"].round(3) != 0].copy()
    c = st.columns(3)
    c[0].metric("Products in stock", int((have["closing_qty"] > 0).sum()))
    c[1].metric("Total stock", f"{inr(have.loc[have['closing_qty'] > 0, 'closing_qty'].sum() / 1000, 2)} MT")
    c[2].metric("Stock value", short_inr(have.loc[have["closing_qty"] > 0, "closing_value"].sum()))
    neg = have.loc[have["closing_qty"] < 0, "product"].tolist()
    have = have[have["closing_qty"] > 0].sort_values("closing_qty", ascending=False)
    view = pd.DataFrame({"Product": have["product"], "Stock (kg)": have["closing_qty"],
                         "Stock (MT)": have["closing_qty"] / 1000, "Avg cost / kg": have["avg_cost_rate"],
                         "Stock value (₹)": have["closing_value"]})
    tot = pd.DataFrame([{"Product": "TOTAL", "Stock (kg)": view["Stock (kg)"].clip(lower=0).sum(),
                         "Stock (MT)": view["Stock (MT)"].clip(lower=0).sum(), "Avg cost / kg": float("nan"),
                         "Stock value (₹)": view.loc[view["Stock (kg)"] > 0, "Stock value (₹)"].sum()}])
    show_table(pd.concat([view, tot], ignore_index=True), money=["Stock (kg)", "Stock value (₹)"],
               rate=["Stock (MT)", "Avg cost / kg"])
    if neg:
        st.caption("⚠️ Not shown because more was sold than bought: " + ", ".join(neg) +
                   " - probably opening stock not in the Master Sheet, or a product name to map in ⚙️ Product Names.")
