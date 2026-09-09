# WhatsApp Order Status Bot

Two things only: **WATI** (WhatsApp) and **this backend** (Python/FastAPI + MySQL, with a built-in admin dashboard).
No n8n, no Docker, no logic inside WATI.

```
Customer types "hii" ──▶ WATI ──webhook (message + number)──▶ POST /webhook/wati
                                                                    │
                                    1. verify number against the SAP customer Excel (phone → customer name)
                                    2. take that customer's rows from the BOM PPC table (external API, cached every 5 min)
                                       – only rows whose Customer Name is byte-identical to the Excel name
                                    3. reply with a WhatsApp LIST of their SO numbers  ──▶ one tap
                                    4. if the SO has several FG items: LIST of item codes ──▶ one tap
                                    5. reply with the Real Status (PPC) + buttons "Check another SO" / "Done"
Customer ◀── WATI ◀── sendSessionMessage / sendInteractiveListMessage / sendInteractiveButtonsMessage ◀──┘
```

Only **Real Status (PPC)** is ever sent to a customer. Connection status and other customers' data never leave the server (there is a test that proves it).

---

## 1. Run it now (dev: no WATI, no PPC API, SQLite, dummy data)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env                              # dev defaults: SQLite, WATI mocked, dummy fixtures
.\.venv\Scripts\python -m app.seed                  # creates tables, imports fixtures, prints test phone/SO pairs
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Open **http://localhost:8000/admin** and sign in with `ADMIN_KEY` from `.env`.
**Simulator** → pick a customer → type `hi` → tap an SO → tap an item → see the status. Everything you see there is exactly what WhatsApp will show.

Tests (SQLite by default; set `TEST_DATABASE_URL` to a MySQL URL to run the same suite on MySQL):

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
```

Dashboard rebuild is only needed after changing `dashboard/src`:

```powershell
cd dashboard
npm install
npm run build          # outputs to backend/app/static/admin (served by the backend)
```

### Dummy data (dev)

| Phone (waId) | Excel name | What happens |
|---|---|---|
| 919167861236 | Shree Packaging Pvt Ltd | list shows SO 45232, SO 45231 → each has 1 item → status directly |
| 919876543210 | Mehta Foods | SO 45240 has 3 FG items → item list |
| 919898012345 | Gujarat Polymers | SO 45250 has 2 FG items |
| 919925001122 | Patel Agro Industries | PPC name has a trailing space → **mismatch** → verification failed |
| 919033445566 | Sunrise Pharma | PPC name is upper-case → **mismatch** |
| 919712345678 | Royal Textiles | SO 45280, also reachable by typing `PO PO-7777` |
| 919081726354 / 919427000111 | Anand Dairy / Om Snacks | in Excel but no PPC rows → "no orders found" |
| 910000000000 | — | not in Excel → verification failed (EN + HI + GU) |

The customer import intentionally rejects row 10 (5-digit number) and row 11 (duplicate number); see **Imports**.

---

## 2. What the customer sees (menus)

```
first message of a window ─▶ greeting (one text for everyone)
                             "Please choose your language"  [English] [हिंदी] [ગુજરાતી]
                       ─▶ "Hello {customer_name}, how can we help you today?"
                             [Order status] [Change language] [Contact us]
Order status ─▶ this customer's SO numbers as buttons (≤3) or a list ─▶ items of the SO (buttons / list)
             ─▶ "Hello {customer_name}, Order: SO … Real Status: …"  [Check another SO] [Main menu] [Done]
```

| Step | Type | Options |
|---|---|---|
| first message after `SESSION_TIMEOUT_MIN` (30 min) of silence, or after `Done` | text + **Buttons** | greeting, then the language question with `English` · `हिंदी` · `ગુજરાતી` (typed "english" / "hindi" / "1" also work) |
| language chosen, "menu", "hi" | **Buttons** | `Order status` · `Change language` · `Contact us` |
| Order status | **Buttons** (≤3 SOs) or **List** (button "Select SO") | one per SO of *this customer only*, newest first, max 10. Settings → Conversation can force "always a list" |
| SO with several items | **Buttons** (≤3) or **List** (button "Select item") | one per FG item code (max 10, else plain text) |
| status delivered | **Buttons** | `Check another SO` · `Main menu` · `Done` |
| SO / item not found | **Buttons** | `Show my orders` · `Main menu` |
| no orders under this name | **Buttons** | `Main menu` · `Contact us` |
| after a voice note | **Buttons** | `Yes` · `No` (confirms the transcribed number; speech-to-text misreads digits) |
| number not in Excel / name mismatch | plain text | apology in EN + HI + GU with your support contact |

The chosen language sticks for the whole window whatever script the customer types in; `Change language` shows the buttons again.
A tapped row or button arrives from WATI as text (its title), so typed and tapped answers go through the **same** parser and the same security checks. If WATI ever rejects an interactive message, the same text is sent with the options as numbered lines.
Every text and every button label above is editable in dashboard → Messages; the button sets under the main menu, result, not-found and contact messages can be changed too.

---

## 3. Messages — the visual editor (dashboard → Messages)

Built for someone who does not write code. Nothing here needs a restart or a developer.

**Conversation map** — the whole chat drawn as a picture: grey bubbles are what the customer sends,
white bubbles are the bot's replies, arrows show what happens next ("taps an order with several items",
"wrong item code", "taps Done"). Click any white bubble to edit that message.

For each message you can:

- **Change the words** in English / Hindi / Gujarati, with a live WhatsApp-style preview beside the editor.
- **Insert real values** by clicking a chip — *Order number*, *Item code*, *Real status*, *Number of items*,
  *Support contact*. No `{braces}` to type.
- **Choose the buttons** under the message (add / remove *Check another SO*, *Done*, *Show my orders*,
  *Main menu*), with WhatsApp's 3-button limit enforced. Renaming a button is safe: the bot learns the new
  name, so a renamed *Done* still ends the chat.
- **Send a test to a real WhatsApp number** — the exact message you are looking at, including unsaved edits.
- **See history** of every change and **Restore built-in** at any time.

**Custom replies** let you add your own keyword answers (e.g. `timing, office hours, समय` → your office
hours, with buttons). They never interrupt an order lookup or a Yes/No answer.

Every save is checked before it can go live: missing or unknown placeholders, WhatsApp length limits
(buttons 20 characters, list rows 24/72, section titles 24, footers 60, body 1024), and button labels that
the bot could no longer understand. A change that would break a message is refused with a plain explanation.

**How a change reaches the customer:** saved text goes to the `templates` table → the in-memory cache
reloads immediately → `replies.build()` → `processor` → the WATI API → WhatsApp. The header of the page
shows the live WATI connection status (green = connected, amber = test mode with no token, red = a problem
with the token or URL).

---

## 4. What to do in WATI (configuration only — do NOT use the workflow builder)

1. **Settings → API Docs**: copy the tenant endpoint (`https://live-mt-server.wati.io/<tenantId>`) and the bearer token → `WATI_BASE_URL`, `WATI_TOKEN`.
2. **Settings → Webhooks**: add `https://<your-domain>/webhook/wati?token=<WATI_WEBHOOK_TOKEN>` for the event **Message received**. WATI does not sign payloads, so the secret lives in the URL and the backend checks it.
3. **Automation / Chatbots**: turn off every chatbot flow and default reply. An active flow intercepts messages before your webhook fires.
4. Optional: one approved template (e.g. `order_status_followup`) if you ever need to message a customer first (outside the 24-hour window). Lists and buttons themselves need no template inside the window.
5. Before you have a public server: `ngrok http 8000` and use that HTTPS URL in step 2.

Why not the builder: verification needs database lookups and byte-exact name matching, voice notes need speech-to-text, the menus are built from live PPC data, and an active flow would swallow messages.

WATI endpoints used (verified against WATI's OpenAPI):
`POST /api/v1/sendSessionMessage/{waId}?messageText=…` · `POST /api/v1/sendInteractiveListMessage?whatsappNumber=…` · `POST /api/v1/sendInteractiveButtonsMessage?whatsappNumber=…` · `GET /api/v1/getMedia?fileName=…`.
Inbound webhook fields used: `id`, `waId`, `type`, `text`, `data`, `listReply`, `interactiveButtonReply`, `buttonReply`, `eventType`, `owner`.
`WATI_API_VERSION=v3` switches the interactive sends to `/api/ext/v3/conversations/messages/interactive`.

---

## 5. Data sources (dashboard → **Data**)

Both connections are set up on screen — no `.env` editing, no restart. What you save is stored in the
database and wins over `.env`; **Reset** puts the `.env` value back. Passwords are encrypted before they
are stored and are never shown again, only `••••1234`.

### Order data (PPC) — Data → Order data
Choose one of three sources:

| Source | What you fill in |
|---|---|
| **API endpoint** | URL, GET/POST, the API key and how to send it (header / in the URL / bearer token) |
| **Database query** | A read-only connection string and a SELECT |
| **File on this server** | A path the PPC system writes to |

Then set the file format (leave on *Detect automatically* — JSON, CSV, Excel and HTML tables are all
recognised), press **Test connection**, and match the columns: the six dropdowns fill themselves with the
column names actually found in your table. Order number, Customer name and Real status are required.
Set how often to check for new data (default every 5 minutes) and when to warn you that data has gone
stale. **Load data now** runs it immediately.

### Customer Excel (SAP) — Data → Customer Excel
Choose where the SAP B1 export lives:

| Source | What you fill in |
|---|---|
| **Folder or network share** | `D:\SAP\exports\customers.xlsx` or `\\server\sap\customers.xlsx` |
| **Dropbox** | App key, app secret, refresh token (scoped app with `files.content.read`) and the file path |
| **Download link** | Any HTTPS link — SharePoint / OneDrive / web — with an optional key |

Match the three columns (customer code, customer name, WhatsApp number), pick the daily import time, and
press **Test connection**: it reads the file without importing and shows exactly which rows would be
accepted and which skipped, and why. **Import now** runs it immediately; **Upload an Excel once** on the
Import history tab handles a one-off file.

Phone numbers are normalised to `91XXXXXXXXXX`; invalid and duplicate numbers are rejected and listed per
run. Customer names are stored **exactly** as in the Excel — the byte-exact match against the PPC table
depends on it.

Every run, successful or not, is listed under **Import history** with the columns it saw, the rows it
skipped and the reason.

---

## 6. Production (WATI + backend only)

1. **Server**: any Windows or Linux machine reachable from the internet over HTTPS (WATI will not call plain HTTP). Install Python 3.12 and MySQL 8 (Windows: `winget install Oracle.MySQL` or the MySQL installer; Linux: your distro's package). Create the database:
   ```sql
   CREATE DATABASE order_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
   ```
   `utf8mb4_bin` keeps name comparisons byte-exact in SQL as well (the code re-checks in Python regardless).
2. **.env**: `APP_MODE=prod`, `DATABASE_URL=mysql+aiomysql://user:pass@localhost:3306/order_bot`, a long random `ADMIN_KEY` and `WATI_WEBHOOK_TOKEN`, `SUPPORT_CONTACT`, WATI values from section 4, PPC values from section 5, Dropbox values, optional `GROQ_API_KEY` (voice notes), `OPENAI_API_KEY` (better intent/language; the bot works without it), `ALERT_SLACK_WEBHOOK`.
3. **HTTPS**: either give uvicorn the certificate directly (`-CertFile`/`-KeyFile` below; a free certificate via win-acme / certbot) or put your existing reverse proxy in front on 443.
4. **Run at boot**
   - Windows (built-in Task Scheduler, no extra software): elevated PowerShell → `cd backend; .\scripts\install_windows_task.ps1 -Port 443 -CertFile C:\certs\fullchain.pem -KeyFile C:\certs\privkey.pem`. Logs in `backend\logs\`.
   - Linux: `scripts/order-status-bot.service` (systemd).
5. **Dashboard**: `cd dashboard; npm install; npm run build` once on your machine and deploy the `backend/app/static/admin` folder with the backend (or build on the server).
6. **Go-live check** (also on the dashboard Settings page): Test fetch green → Import customers → Imports shows expected rejects → `/admin/mismatches` empty or explained → message the number from your own phone (text, tap a menu, voice note).
7. **Operations**: daily `scripts/backup_db.ps1` (Task Scheduler) or `scripts/backup_db.sh` (cron); uptime monitor on `GET /health` (reports last customer sync, last PPC refresh, stale flag); rate limit `RATE_LIMIT_MSGS` per `RATE_LIMIT_WINDOW_MIN` per phone; sessions reset after `SESSION_TIMEOUT_MIN` idle.

---

## 7. Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/webhook/wati?token=…` | webhook token | WATI entry point (dedup by message id, enqueue, 200 in < 1 s) |
| GET | `/health` | none | liveness + last sync times + stale flag |
| GET | `/admin/` | admin key (UI login) | dashboard |
| * | `/admin/api/*` | `X-Admin-Key` | overview, sessions, messages, mismatches, imports, import-customers, refresh-orders, test-fetch, orders-source, customers, orders, outbox, queue, simulate |
| * | `/admin/api/templates…` | `X-Admin-Key` | template editor: catalog, preview, save, reset, history, custom replies |
| POST/GET | `/admin/import-customers`, `/admin/refresh-orders`, `/admin/mismatches`, `/admin/sessions/{phone}` | `X-Admin-Key` | spec aliases |
| GET | `/docs` | none | OpenAPI |

## 8. Layout

```
backend/app/
  main.py            FastAPI app; startup = tables + migrations, template cache, queue worker, scheduler, dev autoload; serves /admin
  config.py          all settings (from .env)
  models.py          customers, orders_cache, sessions, message_log, inbound_queue, name_mismatch_log, sync_runs, templates, template_history
  routers/           webhook.py, admin.py, templates.py, health.py
  services/          processor.py (pipeline), state_machine.py, verify.py, intent.py, menus.py, replies.py, templates.py, wati.py, stt.py, rate_limit.py, alerts.py
  jobs/              queue_worker.py, customer_sync.py, order_refresh.py, session_cleanup.py, scheduler.py
  adapters/          orders_http.py, orders_sql.py, orders_file.py, parsers/{json,csv,excel,html}_table.py, orders_base.py (column map)
  utils/phone.py     phone normalisation
backend/fixtures/    dummy data (10 customers xlsx, 10 orders in json/csv/xlsx/html)
backend/scripts/     make_fixtures.py, install_windows_task.ps1, run_prod.ps1, order-status-bot.service, backup_db.ps1 / .sh
backend/tests/       parsers, phone, verify, state machine, menus, templates, WATI HTTP, webhook, no-leak
dashboard/           React + TypeScript + Tailwind + Recharts → builds into backend/app/static/admin
```
