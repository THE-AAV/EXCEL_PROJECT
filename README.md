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

### Which one should I use?

This repository has **two apps** that share the same report calculations. Both are free.

| | **Web app with logins** (new) | **Desktop app** (Streamlit, the original) |
|---|---|---|
| Who uses it | Everyone, each with their own ID and password, from any computer or phone (online, or on the office network) | One person on one computer |
| Where the data lives | A free online database (or a database file on the office computer that runs the app) | The Master Sheet Excel file itself |
| Entering transactions | **Enter transactions** page: all 9 steps, same as the desktop app | **Enter transactions** page |
| Master Sheet | Kept up to date for you, plus **Download Master Sheet** | Is the working file |
| Who changed what | **Audit log**: every entry with the person, time and details | Activity log file |
| How to start | Online for everyone ([details](#put-it-online-for-free-no-card-needed)), or double-click **`Start_Web_App.bat`** on an office computer ([details](#run-it-for-the-whole-office-free)) | Double-click **`Start_Reports_App.bat`** ([details](#starting-the-app)) |

---

## The web app with logins

People sign in with their own user ID and password. Every entry anyone saves shows up for everyone within a few
seconds, on the dashboard, the reports and the Sheets page, and the admin can see who made each change.

| Role | Can do |
|---|---|
| **admin** | Everything: users, importing workbooks, files, product names, the audit log |
| **editor** | Enter transactions (and undo their last entry), see every report and file, download |
| **viewer** | Read-only: dashboard, reports, sheets, files, downloads |

On the **Users** page the admin also ticks **Files: can change** for each person who may upload, rename, move and
delete files (admins always can; everyone else can look at and download them). Switching a user off takes their
access away at once.

### Put it online for free (no card needed)

The app runs on **Hugging Face** (a free home for web apps, which also keeps your files privately) and keeps the
data in **Neon** (a free online database). Neither asks for a card. Nobody has to install anything: people open a
web address and sign in. It takes about 20 minutes, all in the browser.

**1. The database (Neon)**
1. Go to <https://neon.com> and click **Sign up** (with Google, GitHub or an email address).
2. Create a project: any name (for example `business`), and the region closest to you.
3. On the project page click **Connect**, and copy the **connection string** (it starts with `postgresql://`).
   Keep it somewhere private for step 2.5.

**2. The app (Hugging Face)**
1. Go to <https://huggingface.co/join> and make an account (confirm your email address).
2. Click your picture (top right) → **Settings** → **Access Tokens** → **Create new token**. Choose **Write**,
   name it `business-app`, click **Create**, and copy the token (it starts with `hf_`).
3. Go to <https://huggingface.co/new-space>. Name it (for example `business-reports`), choose **Docker** and then
   **Blank**, keep **CPU basic · Free**, choose **Public** (the app has its own sign-in; no data is kept in the
   Space itself), and click **Create Space**.
4. In the new Space open **Files**:
   - **+ Add file** → **Create a new file**, name it `Dockerfile`, paste everything from
     [`deploy/huggingface/Dockerfile`](deploy/huggingface/Dockerfile), and click **Commit**.
   - Open `README.md` → **edit**, replace everything with [`deploy/huggingface/README.md`](deploy/huggingface/README.md),
     and click **Commit**.
5. Open the Space's **Settings** → **Variables and secrets** and add:

   | Type | Name | Value |
   |---|---|---|
   | Secret | `DATABASE_URL` | the Neon connection string from step 1.3 |
   | Secret | `HF_TOKEN` | the token from step 2.2 |
   | Secret | `ADMIN_PASSWORD` | the password you will sign in with (at least 8 characters) |
   | Variable | `HF_FILES_REPO` | your Hugging Face name, then `/business-files` (for example `shubham/business-files`) |

6. The Space builds by itself (a few minutes) and then shows **Running**. Your app's address is
   `https://<your name>-<space name>.hf.space`, for example `https://shubham-business-reports.hf.space`.
   Open it and sign in as **admin** with the password from step 5.
7. **Import** your workbook, add people on **Users**, and give them the address and their password.

**Good to know**
- Everything is kept outside the Space, so restarts lose nothing: the data in Neon, the uploaded files in a
  private Hugging Face dataset called `business-files` (free space: 100 GB; one file can be up to 1 GB in the
  app).
- If nobody opens the app for two days it goes to sleep. The next visit wakes it up, which takes about a minute.
- **Getting a newer version:** in the Space's **Settings**, click **Factory rebuild**.
- Use the `.hf.space` address. The Space's page on huggingface.co shows the app in a frame that can't sign in.

### Run it for the whole office (free)

One computer in the office runs the app; everyone else just opens it in their browser. There is nothing to pay
for and no account to create anywhere.

**On the office computer** (Windows; it has to be switched on while people use the app):

1. Install **Python 3.10 or newer** from <https://www.python.org/downloads/>. On the first installer screen tick
   **"Add Python to PATH"**.
2. Download this repository: green **Code** button → **Download ZIP**, then unzip it (for example into Documents).
3. Double-click **`Start_Web_App.bat`** in that folder. The first time it sets itself up, which takes a few
   minutes.
4. If Windows asks whether Python may use networks, tick **Private networks** and click **Allow**. (This is what
   lets the other computers reach the app.)
5. The browser opens the app. The first time, create the **admin** account (your own user ID and password).
6. The black window shows the address for everyone else, like `http://192.168.1.20:8000`. Keep that window open;
   closing it stops the app. The same address is shown in the app under **Users**.

**Getting started in the app**

1. **Import** (admin): upload your Master Sheet, or a workbook with just the Purchase, Sales, PO and SO sheets.
   Check the preview and click **Confirm**. (You can also start empty and enter everything in the app.)
2. **Users** (admin): add each person with a user ID, a password and a role. Give them the address from step 6.
3. From then on, everyone enters transactions on **Enter transactions**, and the reports, the **Sheets** page and
   the Master Sheet file update by themselves.

**Where things are kept** (all in the `data` folder next to `Start_Web_App.bat`):
- `business.db`: all the data. Copied every day into `data/backups` (the last 30 days are kept).
- `Master Sheet (live).xlsx`: the Master Sheet with every entry, rewritten after each change. Open it in Excel to
  look at it; make changes in the app. (While it is open in Excel, Windows won't let it be replaced, so it
  catches up shortly after you close it.)

**Next day:** double-click `Start_Web_App.bat` again. **Getting a newer version:** download the ZIP again, unzip
it over the old folder (the `data` folder is kept), and double-click `Start_Web_App.bat`.

**Forgot the admin password?** Close the app window, then open a Command Prompt in the folder and run
`.venv\Scripts\python -m server.manage reset-password <your user ID>`.

On a Mac or Linux computer use `./start_web_app.sh` instead of the `.bat` file.

### Using the web app

- **Enter transactions** (editors and admins): the same nine steps as the desktop app, in the same order:
  Purchase Order → Purchase Invoice → Debit Note → Expenses → Payment, and Sales Order → Sales Invoice →
  Credit Note → Receipt. Contract and note numbers are automatic (or your own), a known party fills in its broker,
  company, type, warehouse, GSTIN and branch, picking a contract fills in the product, balance quantity and rate,
  and every form shows the amounts before you save. Every name box is a dropdown that suggests names from your
  data as you type, and has **+ Add new** for a party, product, broker, warehouse, branch and so on that isn't
  there yet (it is marked **new** and offered in every dropdown on the page).
  Payments and receipts are adjusted against the oldest bills with one click. **Undo last entry** takes the last
  entry back out.
  Switch to **Table (like Excel)** at the top of any step to type many rows at once: Tab moves right, Enter moves
  down, and a block copied from Excel can be pasted in. The table shows what will be saved and any problem per
  row; all rows are saved together (or none), and **Undo last entry** takes the whole table back out.
- **Files**: every file of the business in folders, like the file manager on Windows. Click a file to see the
  Excel sheets inside it (with a preview), every earlier version with who uploaded it, and who renamed, moved,
  deleted or downloaded it. Upload with the button or by dragging files onto the list (up to 1 GB each);
  uploading a file with the same name again keeps the old one as an earlier version. Deleted files go to
  **Recently deleted**, from where they can be brought back. The **Master Sheet (live)** at the top is the
  workbook the reports come from, with the list of every change anyone made to it. An admin can make any
  uploaded workbook the Master Sheet (**Use as Master Sheet**, then confirm on Import).
- **Sheets**: every entry, sheet by sheet (Purchase, Sales, PO, SO, notes), with the Master Sheet's column names,
  search, filters, sorting and totals.
- **Audit log** (admin): who did what and when, with the details of each entry.
- **Import** (admin): uploads a workbook: a full Master Sheet, or just the data sheets (**Purchase**, **Sales**,
  **PO**, **SO**, and **Debit Notes** / **Credit Notes** if you use them; names like `Purchase Register` are
  recognised too). You see what was found before anything is saved. Confirming replaces all the data, and the
  previous import can be **restored**.
- **Download Master Sheet** (top of every report page, and on the Sheets page): the complete Master Sheet, laid
  out like the hand-made one (Main Display, Display, Purchase, PO, SO, Sales, Total Debtor Creditor, masters, and
  Debit / Credit Notes), with the same columns and formulas.
- **Download all reports (Excel)** gives the formatted report pack.

Admin commands (in a Command Prompt in the folder; on Mac / Linux use `.venv/bin/python`):
```
.venv\Scripts\python -m server.manage add-user <id> --role admin      (or editor / viewer; asks for the password)
.venv\Scripts\python -m server.manage reset-password <id>
.venv\Scripts\python -m server.manage import "Master Sheet.xlsx"
```

<details><summary>Other ways to run it (Docker, PostgreSQL)</summary>

`docker compose up -d --build` runs the app with a PostgreSQL database (copy `.env.example` to `.env` first and put
two long random values in it), on <http://localhost:8000>. Setting `DATABASE_URL` makes the app use any PostgreSQL
database instead of the `data/business.db` file.
</details>

---

## The desktop app (Streamlit)

For everyday users on one computer; the Master Sheet file is the data.

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

Web app (backend in `server/`, pages in `web/`):
```
server/main.py          FastAPI routes: sign-in, users, imports, reports, product names, audit log
server/auth.py          bcrypt passwords, signed session cookie, lockout after wrong passwords, role checks
server/db.py            database tables (one per Master Sheet sheet, plus users, imports, audit log)
server/store.py         Master Sheet data <-> database; rebuilds the loader's tables for the report code
server/imports.py       upload -> preview -> confirm / discard / restore (uploaded files are kept in the database)
mis_reports/master_sheet.py   builds the Master Sheet workbook (all sheets, formulas and their values) from the data
server/reports_api.py   runs mis_reports on the database data, caches results, turns them into JSON
web/                    React + AG Grid pages (npm run dev; npm run build -> web/dist, which is committed so the
                        office computer needs no Node.js, and served by the backend)
server/entries.py       entering transactions: runs mis_reports/entries.py on the Master Sheet made from the data,
                        saves the result as a new version (undo = the version before), keeps the live Master Sheet
server/office.py        Start_Web_App.bat: runs the app for the office network, prints the addresses, daily backups
server/sheets.py        the data sheets for the Sheets page
server/files.py         the Files page: folders, versions, uploads in pieces, kept on disk or in a Hugging Face dataset
deploy/huggingface/     the two files for the free Hugging Face Space (see "Put it online for free")
tests/test_server.py    roles, sign-in, import, "database reports equal file reports" and the generated Master Sheet
tests/test_web_entry.py entering transactions, undo, live updates, office addresses and backups
tests/test_files.py     the Files page
Dockerfile, docker-compose.yml   optional: the app with PostgreSQL in Docker
```

Run each line on its own (this works the same in Windows PowerShell, Command Prompt and a Mac/Linux terminal):
```bash
pip install -r requirements-server.txt pytest httpx
python -m uvicorn server.main:create_app --factory --reload
```
That is the backend on http://localhost:8000 (SQLite in `./data` by default). For live-reloading pages, open a
second window in the project folder and run:
```bash
cd web
npm install
npm run dev
```
and open http://localhost:5173 (if PowerShell says *running scripts is disabled on this system*, type `npm.cmd`
instead of `npm`). After changing anything in `web/`, run `npm run build` (still inside `web`) and
commit the updated `web/dist` folder, because the office computer uses it as it is.

Tests on PostgreSQL: set `TEST_DATABASE_URL` (for example `postgresql+psycopg://user@host/db`) and run
`python -m pytest tests/test_server.py tests/test_web_entry.py`.

Streamlit app:
```bash
pip install -r requirements.txt pytest
python -m pytest -q
streamlit run app.py
python generate_reports.py --input path/to/Master.xlsx --as-of 2026-09-30
```

Columns are found by their header text on the header row (the row containing `PARTY NAME`),
so adding or moving columns in the Master Sheet does not break the reports.
The reader uses the values Excel last calculated. A file generated by another program and never
opened in Excel should be opened and saved in Excel first (the Master Sheet the web app generates already
carries its calculated values).
The `input/` and `output/` folders are git-ignored, so business data is never committed.

New invoice rows copy the formula most of the last 30 rows use in each column (like Excel's
fill-down). A few columns always use a fixed formula: purchase amount = weight × rate, pre-bill total,
net amount, GST at the rate entered, and final amount = bill amount − Vatav. The file is saved with
"recalculate on open", and the workbook's calcChain part is removed so Excel rebuilds it.
