# Business Reports from the Master Sheet

Turns the **Master Sheet (Domestic)** Excel file into these reports automatically:

| Report | What it shows |
|---|---|
| **Product-wise P&L** (exclusive of GST) | For each product: purchase, pre-bill expenses, discount, sales, closing stock, cost of goods sold, gross and net profit, margin |
| **Creditors** (payables) | Every purchase party: opening balance, amount payable, paid, TDS, debit notes, closing balance, split by age (0-30 / 31-60 / 61-90 / over 90 days / undated) |
| **Debtors** (receivables) | Every sales party: the same layout for what customers owe us |
| **Outstanding bills** | Bill-by-bill list behind each creditor and debtor balance |
| **Open orders** | Pending PO / SO quantity and value per product |
| **Data checks** | Rows in the Master Sheet with a missing date, quantity or amount |

You don't change anything in the Master Sheet. Keep entering data as you do now.

---

## For everyday users

### First-time setup (once per computer)
1. Install **Python 3.10 or newer** from <https://www.python.org/downloads/>.
   On Windows, tick **"Add Python to PATH"** during installation.
2. Download or copy this folder to the computer.

### Viewing reports on screen
1. Double-click **`Start_Reports_App.bat`** (Windows) or run `./start_app.sh` (Mac/Linux).
   The first run takes a few minutes to set up. After that it opens in seconds.
2. The app opens in your web browser.
3. **Step 1:** Upload the Master Sheet with the *Upload* button, or copy the file into the
   **`input`** folder. The app opens the newest file in that folder by itself.
4. **Step 2:** Pick the *Balances as on* date. You can also narrow the reports to a P&L period,
   products, Type (Local/Import), Sub Type or Company.
5. Use the tabs to switch between **Dashboard**, **Product P&L**, **Creditors**, **Debtors**,
   **Open Orders** and **Data Checks**. In the Creditors and Debtors tabs you can search for a party
   and pick one to see its outstanding bills.
6. **Step 3:** Click **Download all reports (Excel)** to get the full formatted report file.

### Getting the Excel reports without opening the app
- Put the Master Sheet in the **`input`** folder and double-click **`Generate_Reports_Now.bat`**.
  A file named `Business_Reports_<date>_<time>.xlsx` appears in the **`output`** folder.

### Fully automatic (no one has to click anything)
Choose one of these:
- **Scheduled:** in Windows *Task Scheduler*, create a daily task that runs
  `Generate_Reports_Now.bat` (for example every morning at 9:00).
- **On every save:** run `python generate_reports.py --watch`. It checks the `input` folder
  every 30 seconds and builds new reports whenever the Master Sheet is saved there.
  If the `input` folder is a shared or OneDrive folder, the reports stay up to date on their own.

### When a product has two names
If the same product is typed differently in Purchase and Sales (e.g. `SOYA BEANS` and `Soyabean`),
open the **Product Names** tab in the app and add a row: *Name in sheet* → *Report as*.
Capital/small letters and extra spaces are already ignored. The mapping is saved in
`config/product_aliases.csv`.

---

## How the numbers are worked out

**Product P&L (all amounts before GST)**
- *Net Purchase Cost* = Amount before GST + pre-bill expenses (Adhat, AMC, Labour, Transportation,
  WH Load, Bags, Other) − Discount. This is the same as the `Display` sheet.
- *Net Sales* = Sales Amount before GST − Discount.
- *Closing stock* = purchased kg − sold kg, valued at the average landed cost per kg.
- *Cost of Goods Sold* = Net Purchase Cost − Closing Stock Value.
- *Net Profit* = Net Sales − Cost of Goods Sold − post-bill expenses (purchase: storage, brokerage,
  sampling, repacking, transport; sales: brokerage, loading/unloading, repacking).
- When everything bought has been sold, this gives exactly the `Display` sheet's figure (Urad:
  −7,43,854.50). When stock is left over, the `Display` sheet counts its full cost as a loss.
  These reports carry it forward as closing stock instead.
- The P&L period filter uses the bill date. If a row has no bill date, the WH In / Delivery date is used.

**Creditors / Debtors (amounts include GST, like the `Total Debtor Creditor` sheet)**
- Creditors: Final Amt (Bill Amt − Vatav) − Paid Amount − TDS − Debit Note.
- Debtors: Bill Amt − Received Amount − TDS − Credit Note.
- Opening balances are taken from the `Opening Bal.` columns of the `Total Debtor Creditor` sheet.
- A party spelt slightly differently (`R.R. Impex` / `R R IMPEX`) is counted as one party.
- Payments are adjusted against the opening balance first, then the oldest bills (FIFO).
  Each bill left unpaid is aged from its bill date to the *Balances as on* date.
  Payments dated after that date are ignored.

The downloaded Excel file uses live formulas for totals, net amounts, rates and closing balances,
so it stays correct if you edit a figure.

---

## For IT / developers

```
app.py                  Streamlit web app (the UI)
generate_reports.py     command-line / scheduled / --watch report generation
mis_reports/loader.py   reads Purchase, Sales, PO, SO and opening balances from the Master Sheet
mis_reports/reports.py  P&L, creditor/debtor ledgers with FIFO ageing, open orders, data checks
mis_reports/excel_export.py   formatted Excel report pack
config/product_aliases.csv    product name mapping
tests/                  pytest suite (builds its own small Master Sheet, no real data needed)
```

```bash
pip install -r requirements.txt pytest
python -m pytest -q
streamlit run app.py
python generate_reports.py --input path/to/Master.xlsx --as-of 2026-09-30
```

Columns are found by their header text on the header row (the row containing `PARTY NAME`),
so adding or moving columns in the Master Sheet does not break the reports.
The reader uses the values Excel last calculated. A file generated by another program and never
opened in Excel should be opened and saved in Excel first.
The `input/` and `output/` folders are git-ignored, so business data is never committed.
