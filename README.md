# Business Reports from the Master Sheet

A simple app for the **Master Sheet (Domestic)** Excel file. You can:

1. **Enter transactions** in the app, following the business flow below. Each entry is written
   straight into the Master Sheet, so the Excel file is always up to date.
2. **View reports** that are worked out automatically from the Master Sheet.

```
Purchase Order → Purchase Invoice → Debit Note → Expenses → Payment
Sales Order    → Sales Invoice    → Credit Note → Receipt
```

The reports are:

| Report | What it shows |
|---|---|
| **Product-wise P&L** (exclusive of GST) | For each product: purchase, pre-bill expenses, discount, sales, closing stock, cost of goods sold, gross and net profit, margin |
| **Creditors** (payables) | Every purchase party: opening balance, amount payable, paid, TDS, debit notes, closing balance, split by age (0-30 / 31-60 / 61-90 / over 90 days / undated) |
| **Debtors** (receivables) | Every sales party: the same layout for what customers owe us |
| **Outstanding bills** | Bill-by-bill list behind each creditor and debtor balance |
| **Stock summary** | How much of each product is in stock (kg and MT), its average cost and value, with totals - also on the dashboard. Purchased / sold / returns and open orders are one click away |
| **Purchase & sales orders** | Every contract: quantity, cancelled, received / delivered, balance, value, % done, status, invoices, days open |
| **Debit / credit notes** | Every note with quantity, value, GST, other charges and reason |
| **Bill-wise margin** | Margin on each sales bill linked to the purchase bill the goods came from |
| **Data checks** | Rows in the Master Sheet with a missing date, quantity or amount |

You can keep using Excel as well. Changes saved in Excel show up in the app within a few seconds.

---

## For everyday users

### First-time setup (once per computer)
1. Install **Python 3.10 or newer** from <https://www.python.org/downloads/>.
   On Windows, tick **"Add Python to PATH"** during installation.
2. Download or copy this folder to the computer.

### Starting the app
1. Double-click **`Start_Reports_App.bat`** (Windows) or run `./start_app.sh` (Mac/Linux).
   The first run takes a few minutes to set up. After that it opens in seconds.
2. The app opens in your web browser.
3. The first time, open **📁 Master Sheet file** on the left and upload the Master Sheet, or copy the
   file into the **`input`** folder. That file becomes the *working file*. The app reads it and saves
   entries into it. If there are several files in `input`, the newest one is used.

### Entering transactions (📝 Enter transactions)
Pick a step at the top, then an **Entry style**:
- **📝 Form** - one entry at a time with boxes and dropdowns. Fields marked * are required.
- **📊 Table (like Excel)** - a grid you type into like Excel (copy / paste from Excel works too). Enter
  as many rows as you like and click **Save all rows**: all rows are saved together, or - if any row has a
  problem - none are, and the message names the row. One **Undo** takes the whole batch back out. In the
  invoice tables, rows with the same party, bill no. and date become one bill; in the note tables, rows on
  the same bill with the same note no. (or date) become one note; in the payment / receipt tables, rows with
  the same party and date become one payment. Party and product names are matched to the spelling already
  in the sheet (capital letters and spaces don't matter), and new names are listed before saving.
  The tables have the same fields as the forms. Name columns (party, product, broker, company, warehouse,
  type, branch ...) are **dropdowns of the names already in the sheet**; add a new one with **➕ Add a new …**
  above the table (one per line, so a list pasted from Excel works), or turn on **✍️ Type names freely** to
  type or paste names straight into the cells. Details left empty are filled in the way the form suggests
  them: from the contract picked (party, product, balance quantity, rate) and from the party's last entry
  (broker, company, type, sub type, warehouse, GSTIN, branch); an empty GST % is 5% (0% for Import). The
  preview above the Save button shows what will be written.

In the form style:
Dropdowns list the names already in the sheet. Every name dropdown (party, product, broker, company,
warehouse, type, sub type, branch, delivery place, packing) starts with **➕ Add new…**: pick it and type
the new name in the box that appears (typing a new name straight into the dropdown works too). Note reasons
and note expenses can be extended with **➕ Add a new note reason / note expense**. Names added in one place
show up in the other dropdowns and tables for the rest of the session, and are in the sheet for good once an
entry using them is saved. Debit / credit notes, expenses and payments / receipts work on existing bills, so
a new party is entered through its invoice first.

| Step | What it does in the Master Sheet |
|---|---|
| ① Purchase Order | Adds a row to the **PO** sheet. Contract No. is **automatic** (next in your series, e.g. `PO/26-27/009` → `PO/26-27/010`) or **your own** (duplicates are blocked) |
| ② Purchase Invoice | One bill with **one or more items**, each item optionally **against a different contract** (the contract's product, rate and balance quantity are filled in). Each item becomes a row in the **Purchase** sheet with the sheet's own formulas, and each contract's *Recd Qty* is updated, closing it when fully received. The **💰 Pre-bill expenses** tab takes Adhat, AMC, Labour, Transportation, WH Load, Bags, Other and Discount for the whole bill and splits them over the items by value |
| ③ Debit Note | One note can have **several reasons** (goods returned, weight shortage, quality claim, rate difference, moisture / dust …), each by **quantity × rate** or as an amount, with **GST %** (defaults to the bill's rate), plus **several expenses** the supplier bears (freight, unloading, handling …, no GST). Automatic number (`DN-0001` …) or your own. Every reason and expense is a row in the **Debit Notes** sheet under the note number; the total is added to *Debit Note / Other de.* on the bill. Quantity and value come off purchases in the P&L and stock |
| ④ Expenses | Post-bill expenses (Storage, Brokerage, Sampling, Repacking, Transportation) and Vatav on a purchase bill, or Brokerage, Loading/Unloading, Repacking and Discount on a sales bill. Pre-bill expenses and the purchase discount are entered with the purchase invoice |
| ⑤ Payment | Enter the **total amount paid**, then **tick the invoices** it is adjusted against (or click *Adjust oldest first*). A ticked invoice is cleared in full unless you type a smaller amount; TDS can be added per invoice. *Total / Adjusted / Balance* are shown as you go; a balance left over can be kept as an advance. Writes *Date*, *Amount* and *TDS* on each invoice and marks fully paid ones **Paid** |
| ⑥ Sales Order | Adds a row to the **SO** sheet, with automatic or your own contract number |
| ⑦ Sales Invoice | Like the purchase invoice (several items, each against a sales contract). The invoice number is suggested as the next in your series. Each item can **optionally be linked to the purchase bill** the goods came from: the purchase bill no. goes in *P Inv* on the sales row and the sales bill no. in *S Inv* on the purchase row, and the **Bill-wise margin** report shows the profit on it |
| ⑧ Credit Note | Like the debit note, for sales bills (numbers `CN-0001` ...), listed in a new **Credit Notes** sheet. Its quantity goes back into stock and its value comes off sales |
| ⑨ Receipt | The same for customers: total amount received, adjusted against several invoices. Fully received invoices are marked **Recd** |

Things to know:
- **Close the Master Sheet in Excel before saving from the app.** Windows locks a file while Excel
  has it open. If it is open, the app says so and nothing you typed is lost. Close Excel, then click Save again.
- **Every save first makes a backup** in `input/backups` (the last 30 are kept). **↩️ Undo last entry**
  puts the file back the way it was before the last save.
- Every entry is listed under **Recent entries** and in `input/activity_log.csv`.
- The app changes only the rows it writes. Your formulas, dropdowns, the `masters` sheet lists
  and all other sheets are left as they are. Excel recalculates everything the next time you open the file.

### Viewing the sheets (📄 View sheets)
- **🧾 Clean table of entries** (the default): pick a sheet (the number of entries is shown on each tab) and
  see its entries as a clean table - the real column names, no empty rows or columns, dates and amounts
  formatted, codes such as HSN / GSTIN / bill numbers kept exactly as typed, and the sheet row of each entry.
  - **Filter:** a search box, quick filters for Party, Product and Broker, a date range, and
    **➕ More filters** for any column (values to show, *contains*, from / to for numbers and dates) and to
    hide columns. Click a column heading to sort.
  - **Totals** of the amount / weight columns for the rows shown, and **Download** of those rows (CSV).
- **📄 Excel layout**: the sheet exactly as Excel shows it (colours, borders, merged cells, frozen headers,
  formulas on hover), with Excel-style filter and sort.
- Works for the working Master Sheet, other files in `input`, saved reports in `output`, or any Excel file
  you open here (view only), and refreshes by itself when the file is saved.

### Viewing reports (📊 View reports)
1. Pick the *Balances as on* date. You can also narrow the reports to a P&L period,
   products, Type (Local/Import), Sub Type or Company.
2. Use the tabs to switch between **Dashboard**, **Product P&L**, **Creditors**, **Debtors**,
   **Open Orders** and **Data Checks**. In the Creditors and Debtors tabs you can search for a party
   and pick one to see its outstanding bills.
3. Click **Download all reports (Excel)** to get the full formatted report file.

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
- Debit notes: their quantity comes off the kg purchased and their value before GST plus other charges comes
  off the purchase cost. Credit notes do the same for sales.
- *Closing stock* = purchased kg − debit-note kg − sold kg + credit-note kg, valued at the average landed cost per kg.
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
app.py                  Streamlit web app shell (working file, mode switch, auto-reload)
ui/entries_page.py      the nine transaction forms
ui/table_entry.py       the 'Table (like Excel)' entry style for all nine sections
ui/reports_page.py      dashboard and report tabs
ui/viewer_page.py       'View sheets' page (file picker, sheet tabs, find, filter & sort)
ui/records_view.py      the 'clean table of entries' view with filters and totals
ui/sheet_viewer.py      turns a workbook into Excel-like HTML (styles, number formats, merges, frozen panes)
                        and does the filtering / sorting
generate_reports.py     command-line / scheduled / --watch report generation
mis_reports/loader.py   reads Purchase, Sales, PO, SO and opening balances from the Master Sheet
mis_reports/reports.py  P&L, creditor/debtor ledgers with FIFO ageing, open orders, data checks
mis_reports/entries.py  writes orders, invoices, notes, expenses, payments and receipts
mis_reports/xlsx_edit.py      edits only the touched rows in the .xlsx XML (keeps dynamic arrays,
                              data validation, shared formulas); fills formulas down like Excel and
                              stores their calculated values
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

New invoice rows copy the formula most of the last 30 rows use in each column (like Excel's
fill-down). A few columns always use a fixed formula: purchase amount = weight × rate, pre-bill total,
net amount, GST at the rate entered, and final amount = bill amount − Vatav. The file is saved with
"recalculate on open", and the workbook's calcChain part is removed so Excel rebuilds it.
