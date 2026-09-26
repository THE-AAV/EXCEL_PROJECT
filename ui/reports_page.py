"""Reports page: dashboard, product P&L, creditors, debtors, orders, data checks, product names."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from mis_reports import reports as R
from mis_reports.pipeline import save_aliases

from .common import AGE_COLORS, LOSS, PROFIT, inr, short_inr, show_table, total


def render(data, rs, opts, aliases, as_of, source_name):
    # --------------------------------------------------------------------------- header
    st.title("Business Reports")
    st.markdown(f"<span class='hint'>Source: <b>{source_name}</b> · {len(data.purchase)} purchase bills · "
                f"{len(data.sales)} sales bills · balances as on {as_of:%d-%b-%Y}</span>", unsafe_allow_html=True)
    if len(rs.checks):
        st.warning(f"⚠️ {len(rs.checks)} row(s) in the Master Sheet may need attention - see the **Data Checks** tab.")

    tabs = st.tabs(["🏠 Dashboard", "📦 Product P&L", "🏭 Creditors (we pay)", "🧾 Debtors (we receive)",
                    "📑 Open Orders", "⚠️ Data Checks", "⚙️ Product Names"])

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
        left, right = st.columns(2)
        with left:
            st.subheader("Net profit by product")
            if len(pnl):
                chart_df = pnl[["product", "net_profit", "net_sales"]].copy()
                chart_df["result"] = chart_df["net_profit"].map(lambda v: "Profit" if v >= 0 else "Loss")
                chart_df["amount"] = chart_df["net_profit"].map(inr)
                chart = alt.Chart(chart_df).mark_bar(cornerRadiusEnd=4, size=16).encode(
                    y=alt.Y("product:N", sort="-x", title=None),
                    x=alt.X("net_profit:Q", title="Net profit (₹ lakh)",
                            axis=alt.Axis(labelExpr="format(datum.value / 1e5, ',.0f') + ' L'", grid=True)),
                    color=alt.Color("result:N", scale=alt.Scale(domain=["Profit", "Loss"], range=[PROFIT, LOSS]),
                                    legend=alt.Legend(title=None, orient="top")),
                    tooltip=[alt.Tooltip("product:N", title="Product"), alt.Tooltip("amount:N", title="Net profit ₹")],
                ).properties(height=max(32 * len(chart_df), 200))
                st.altair_chart(chart, width="stretch")
        with right:
            st.subheader("Outstanding by age")
            age = pd.DataFrame([
                {"side": side, "bucket": b, "amount": total(led.summary, b)}
                for side, led in (("Payable", cred), ("Receivable", debt))
                for b in R.BUCKET_NAMES])
            age["label"] = age["amount"].map(inr)
            chart = alt.Chart(age).mark_bar(size=40, stroke="white", strokeWidth=2).encode(
                x=alt.X("side:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("amount:Q", title="Outstanding (₹ crore)",
                        axis=alt.Axis(labelExpr="format(datum.value / 1e7, ',.0f') + ' Cr'")),
                color=alt.Color("bucket:N", sort=R.BUCKET_NAMES,
                                scale=alt.Scale(domain=R.BUCKET_NAMES, range=AGE_COLORS),
                                legend=alt.Legend(title="Age", orient="right")),
                order=alt.Order("bucket_order:Q"),
                tooltip=[alt.Tooltip("side:N", title=""), alt.Tooltip("bucket:N", title="Age"),
                         alt.Tooltip("label:N", title="Amount ₹")],
            ).transform_calculate(
                bucket_order=f"indexof({R.BUCKET_NAMES!r}, datum.bucket)"
            ).properties(height=320)
            st.altair_chart(chart, width="stretch")

    # --------------------------------------------------------------------------- product P&L
    STATEMENT = [
        ("PURCHASE", None), ("Purchase Qty (kg)", "purchase_qty"), ("Purchase Value", "purchase_value"),
        ("Add: Pre-bill Expenses", "pre_bill_exp"), ("Less: Purchase Discount", "purchase_discount"),
        ("Net Purchase Cost", "net_purchase"), ("Avg Landed Cost / kg", "avg_cost_rate"),
        ("SALES", None), ("Sales Qty (kg)", "sales_qty"), ("Sales Value", "sales_value"),
        ("Less: Sales Discount", "sales_discount"), ("Net Sales", "net_sales"), ("Avg Sale Rate / kg", "avg_sales_rate"),
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
                row["avg_cost_rate"] = row["net_purchase"] / row["purchase_qty"] if row["purchase_qty"] else 0
                row["avg_sales_rate"] = row["net_sales"] / row["sales_qty"] if row["sales_qty"] else 0
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
                    "WH load, bags, other) − discount.<br>"
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


    with tabs[2]:
        st.subheader("Creditors - purchase parties we have to pay (incl. GST)")
        ledger_tab(cred, "Creditors", "Payable", "Paid", "Debit Note / Ded.", "cred")
    with tabs[3]:
        st.subheader("Debtors - sales parties who have to pay us (incl. GST)")
        ledger_tab(debt, "Debtors", "Receivable", "Received", "Credit Note / Ded.", "debt")

    # --------------------------------------------------------------------------- orders, checks, settings
    with tabs[4]:
        st.subheader("Pending purchase and sales orders")
        if len(rs.orders):
            o = rs.orders.rename(columns={"order_type": "Order", "product": "Product", "contracts": "Contracts",
                                          "bal_qty_kg": "Balance Qty (kg)", "amount": "Amount",
                                          "avg_rate": "Avg Rate / kg"})
            show_table(o[["Order", "Product", "Contracts", "Balance Qty (kg)", "Amount", "Avg Rate / kg"]],
                       money=["Balance Qty (kg)", "Amount"], rate=["Avg Rate / kg"])
        else:
            st.info("No open orders.")

    with tabs[5]:
        st.subheader("Rows in the Master Sheet that need attention")
        st.caption("These rows are still included where possible, but a missing date, quantity or amount can make "
                   "the reports less accurate. Fix them in the Master Sheet; the reports update automatically.")
        if len(rs.checks):
            st.dataframe(rs.checks.rename(columns=str.title), hide_index=True, width="stretch")
        else:
            st.success("No problems found. 🎉")

    with tabs[6]:
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
