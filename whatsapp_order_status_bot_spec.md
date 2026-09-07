# WhatsApp order status bot — build specification (backend-only, production)

Stack: WATI (WhatsApp) → custom backend (Node.js or Python) → MySQL. No n8n.
Data sources: SAP B1 Excel export via Dropbox (customers), external API (orders, whole table).
STT: Groq Whisper API (`whisper-large-v3-turbo`), free tier.
Intent understanding: OpenAI (ChatGPT) API, `gpt-4o-mini` — reads the customer's text (typed or transcribed) and returns the intent plus any SO no / PO no / FG item code it finds. Called from the backend, never sees status data, never writes the reply. See section 7.

Only the customer's **Real Status (PPC)** is ever sent to the customer. Nothing else.

---

## 1. Decisions locked in

| Topic | Decision |
|---|---|
| Orchestration | Backend only. WATI webhook → backend → WATI API. No n8n. |
| Customer identity | WATI `waId` from the webhook. Never trust a number typed in the message. |
| Phone normalization | On Excel import, every contact becomes `91XXXXXXXXXX`. |
| Name match | Byte-for-byte between Excel `Customer Name` and external API customer name. No trimming, no case folding. Every mismatch is logged with both raw values. |
| Column E (`Y`) in Excel | Ignored. |
| Contacts per customer | One contact number → one customer name. Duplicate numbers in the export are treated as a data error and logged. |
| Order lookup | SO no first. If that SO has more than one FG item code, ask for FG item code. Then return Real Status for that SO + FG row. |
| PO no | Stored with each order row. If the customer sends a PO no instead of an SO no, backend resolves PO → SO. (Assumption: PO is an alternative key, not a required step. Confirm.) |
| Failure handling | Fixed apology message in EN + HI + GU, sent via WATI. Session resets. |
| External API | Returns the whole table. Backend pulls it on a schedule, stores it in `orders_cache`, filters locally. |
| Data freshness | Customers: as fresh as the last SAP export. Orders: as fresh as the last API pull (default every 5 min). |

---

## 2. Conversation flow (customer's view)

```
Customer: hi / any text / voice note
Bot:      Namaste! Please send your SO number to check order status.
          (Sent only if the number is verified. Otherwise: apology message.)
Customer: 45231
Bot:      [if SO has one FG]  Real Status for SO 45231: <status>
          [if SO has many FG] SO 45231 has 3 items. Please send the FG item code.
Customer: FG-1023
Bot:      Real Status for SO 45231, item FG-1023: <status>
          Send another SO number to check more, or type "menu".
```

Voice notes: after transcription the bot always echoes back before searching:
`Did you mean SO number 45231? Reply Yes or send the correct number.`
This is mandatory — STT will misread digits.

Session times out after 15 minutes of silence and returns to the start.

---

## 3. Session state machine (backend)

```
START ──verify phone──▶ VERIFIED ──▶ AWAIT_SO ──SO found, 1 FG──▶ DONE
   │                                   │
   │ not found                         │ SO found, many FG
   ▼                                   ▼
 FAILED (apology, reset)           AWAIT_FG ──FG found──▶ DONE
                                       │
                                       │ FG not in that SO
                                       ▼
                                   AWAIT_FG (re-ask, max 2 tries, then apology)
```

Every state transition also runs the name check (section 5.4). If it fails at any point → FAILED.

States stored per phone in `sessions` table: `step`, `so_no`, `po_no`, `fg_code`, `pending_confirm` (for STT echo-back), `attempts`, `updated_at`.

---

## 4. What to do in WATI

Everything in WATI is configuration, not building.

1. **Webhook**: Settings → Webhooks → add `https://<your-domain>/webhook/wati` for the "Message received" event. Note the webhook secret if WATI provides one; the backend will verify it.
2. **API token**: Settings → API Docs → copy tenant URL (`https://live-mt-server.wati.io/<tenantId>`) and bearer token. Store as environment variables in the backend.
3. **No-code builder**: leave empty, or a single welcome keyword that says "Send your SO number". Do not put verification or order logic in WATI. If a WATI chatbot flow is active it can intercept messages before your webhook — disable any default flow.
4. **Message templates** (optional, for re-engagement outside the 24h window): create one approved template like `order_status_followup` in case you ever need to message a customer first.
5. **Webhook payload fields the backend uses**: `waId`, `type` (`text` / `audio`), `text`, `data` (media filename for audio), `id` (message id, for dedup). `senderName` is display only, never used for matching.
6. **WATI endpoints the backend calls**:
   - `POST /api/v1/sendSessionMessage/{waId}?messageText=...` — reply within 24h window
   - `GET /api/v1/getMedia?fileName=...` — download voice note (OGG)

---

## 5. What to build in the backend

### 5.1 Components

| Component | Purpose |
|---|---|
| `POST /webhook/wati` | Receives every WATI message. Verifies secret, dedups by message id, returns 200 within 1 second, hands off to the processor (queue or async task). Never do slow work inside the request. |
| Message processor | Runs per incoming message: STT (if audio) → intent (OpenAI) → state machine → reply via WATI. |
| Customer sync job | Cron. Downloads Excel from Dropbox, normalizes, upserts `customers`. |
| Order refresh job | Cron. Pulls external API table, upserts `orders_cache`. |
| Admin endpoints | Import trigger, mismatch review, health. |
| Alerting | On any unhandled error: send "service unavailable" to the customer (if `waId` known) and post to Slack/email. |

### 5.2 Endpoints

| Method | Path | Called by | Purpose |
|---|---|---|---|
| POST | `/webhook/wati` | WATI | Entry point for all customer messages. |
| POST | `/admin/import-customers` | you / cron | Force a Dropbox import now. Returns counts + rejected rows. |
| POST | `/admin/refresh-orders` | you / cron | Force an external API pull now. |
| GET | `/admin/mismatches` | you | Lists name mismatches for review. |
| GET | `/admin/sessions/{phone}` | you | Debug a customer's session. |
| GET | `/health` | uptime monitor | Liveness + last sync timestamps. |

All `/admin` calls require header `X-Admin-Key`. `/webhook/wati` validates WATI's secret / IP allowlist.

### 5.3 Tables

```sql
customers (
  phone_e164     VARCHAR(15) PRIMARY KEY,   -- 91XXXXXXXXXX
  customer_code  VARCHAR(20),
  customer_name  VARCHAR(255),              -- stored EXACTLY as in Excel, no trim
  raw_contact    VARCHAR(50),               -- original cell value for audit
  imported_at    DATETIME
);

orders_cache (
  id             BIGINT AUTO_INCREMENT PRIMARY KEY,
  so_no          VARCHAR(50),
  po_no          VARCHAR(50),
  fg_item_code   VARCHAR(50),
  customer_name  VARCHAR(255),              -- EXACTLY as returned by API
  connection_status VARCHAR(100),           -- internal only, never sent to customer
  real_status    VARCHAR(100),              -- the only field shown to customer
  fetched_at     DATETIME,
  INDEX (so_no), INDEX (po_no), INDEX (customer_name)
);

sessions (
  phone_e164     VARCHAR(15) PRIMARY KEY,
  step           ENUM('START','AWAIT_SO','AWAIT_FG','CONFIRM','DONE','FAILED'),
  so_no          VARCHAR(50), po_no VARCHAR(50), fg_code VARCHAR(50),
  pending_value  VARCHAR(100),              -- value awaiting Yes/No after STT
  attempts       TINYINT DEFAULT 0,
  updated_at     DATETIME
);

message_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  wati_msg_id VARCHAR(100) UNIQUE,          -- dedup: WATI may retry webhooks
  phone_e164 VARCHAR(15), direction ENUM('in','out'),
  msg_type VARCHAR(10), text TEXT, created_at DATETIME
);

name_mismatch_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  phone_e164 VARCHAR(15), excel_name VARCHAR(255), api_name VARCHAR(255),
  so_no VARCHAR(50), created_at DATETIME
);
```

### 5.4 Verification logic (runs on every message)

```
1. customer = customers.find(phone_e164 = waId)
   none  → FAILED
2. rows = orders_cache.where(so_no = given SO)          [or po_no if PO given]
   none  → "order not found" apology
3. keep only rows where row.customer_name === customer.customer_name   (strict ===, bytes)
   none  → log to name_mismatch_log, FAILED
4. if rows.length == 1 → reply real_status
   else ask for FG item code, then filter rows by fg_item_code === given code
```

Step 3 is both the name check and the security check: a customer can only ever see orders where the API's customer name equals their Excel name exactly.

### 5.5 Reply rule

The reply builder receives only `{template, real_status, so_no, fg_code, n_items, language}`. `connection_status` is never passed to it. Add a unit test that asserts the outgoing text never contains any `connection_status` value from the fixture data.

### 5.6 Phone normalization (import)

```
input  → strip everything except digits
         drop leading "0" if 11 digits
         if 10 digits → prepend "91"
         if 12 digits and starts with "91" → keep
         else → reject row, report in import result
```

Examples: `9167861236` → `919167861236`; `+91 91678-61236` → `919167861236`; `09167861236` → `919167861236`.

Duplicate phone across two names → keep first, reject second, report.

### 5.7 Background jobs

| Job | Schedule | Steps |
|---|---|---|
| Customer sync | SAP export time + 10 min | Dropbox API `files/download` → parse xlsx → normalize → upsert `customers` → email rejected rows if any. |
| Order refresh | every 5 min (tune to table size) | GET external API → parse table → upsert `orders_cache` in a transaction → record `fetched_at`. Skip if API unreachable; keep last good cache; alert if stale > 30 min. |
| Session cleanup | every 5 min | Reset sessions idle > 15 min. |

Use the runtime's scheduler (`node-cron` / APScheduler) or system cron hitting the admin endpoints.

### 5.8 Production requirements

- Webhook must respond 200 in < 1 s; process in a background task or lightweight queue (BullMQ / Celery / RQ). WATI retries on timeouts, so also dedup on `wati_msg_id`.
- Secrets (WATI token, Groq key, OpenAI key, Dropbox token, DB password) in environment variables, never in code.
- HTTPS with a real certificate (WATI will not call plain HTTP).
- Structured logging with `phone_e164` and `wati_msg_id` on every line.
- Retry with backoff on WATI send, Groq, OpenAI, external API (3 attempts).
- Rate limit per phone: max 20 messages / 10 min to stop abuse.
- Daily DB backup; `orders_cache` can be rebuilt, `customers` and logs cannot.
- Uptime monitor on `/health`; it should report last customer sync and last order refresh time.

---

## 6. Message processing pipeline (inside the backend)

```
webhook → dedup → enqueue
   ↓
processor:
   1. if type == audio: WATI getMedia → Groq transcribe → text
   2. OpenAI intent → {intent, so_no, po_no, fg_code, language}
      (on failure: regex fallback)
   3. if input came from audio and a code was extracted → CONFIRM step (echo back)
   4. state machine (section 3) using verification logic (section 5.4)
   5. build reply from template (section 8) in detected language
   6. WATI sendSessionMessage
   7. log in/out to message_log
```

---

## 7. External AI APIs

### 7.1 STT — Groq
- Endpoint: `POST https://api.groq.com/openai/v1/audio/transcriptions`
- Model: `whisper-large-v3-turbo`; switch to `whisper-large-v3` if digits/codes are misread.
- Send WhatsApp OGG/Opus as-is. Multipart fields: `file`, `model`, `response_format=json`, optional `language`.
- Free tier limits change; check console.groq.com. Fallbacks: Sarvam AI Saarika, Google Cloud STT.

### 7.2 Intent — OpenAI
- Endpoint: `POST https://api.openai.com/v1/chat/completions`, model `gpt-4o-mini`, `response_format: json_object`.
- Input: the customer's message only. No customer data, no order data.
- Output: `{"intent": "check_status" | "greeting" | "confirm_yes" | "confirm_no" | "other", "so_no": "...", "po_no": "...", "fg_code": "...", "language": "en" | "hi" | "gu"}`.
- Used only to drive the state machine and choose the reply language. Customer-facing text always comes from the fixed templates in section 8.
- If the call fails or returns invalid JSON, fall back to a regex extractor and continue. The bot must work without OpenAI.

---

## 8. Messages

Placeholders: `[phone/email]` = your support contact.

**Verification failed** (EN / HI / GU sent together in one message)

Sorry, we could not verify your details for this number. Please contact our team at [phone/email] and we'll be happy to help.
क्षमा करें, इस नंबर से आपकी जानकारी सत्यापित नहीं हो सकी। कृपया हमारी टीम से [phone/email] पर संपर्क करें, हम आपकी सहायता करेंगे।
માફ કરશો, આ નંબર પરથી તમારી વિગતો ચકાસી શકાઈ નથી. કૃપા કરીને અમારી ટીમનો [phone/email] પર સંપર્ક કરો, અમે તમારી મદદ કરીશું.

**Order / item not found**

Sorry, we could not find that SO number / item code under your account. Please check and send it again, or contact our team at [phone/email].
क्षमा करें, यह SO नंबर / आइटम कोड आपके खाते में नहीं मिला। कृपया जांच कर दोबारा भेजें, या हमारी टीम से [phone/email] पर संपर्क करें।
માફ કરશો, આ SO નંબર / આઇટમ કોડ તમારા ખાતામાં મળ્યો નથી. કૃપા કરીને તપાસીને ફરી મોકલો, અથવા અમારી ટીમનો [phone/email] પર સંપર્ક કરો.

**Ask SO** — Please send your SO number. / कृपया अपना SO नंबर भेजें। / કૃપા કરીને તમારો SO નંબર મોકલો.

**Ask FG** — This SO has {n} items. Please send the FG item code. / इस SO में {n} आइटम हैं। कृपया FG आइटम कोड भेजें। / આ SO માં {n} આઇટમ છે. કૃપા કરીને FG આઇટમ કોડ મોકલો.

**Confirm (after voice)** — Did you mean SO number {value}? Reply Yes or send the correct number.

**Result** — Real Status for SO {so} {item}: {real_status}

**Service down** — Sorry, our system is temporarily unavailable. Please try again in a few minutes.

---

## 9. Open items (need your input)

1. External API: format (JSON/CSV/HTML), URL, auth, and exact column names for SO, PO, FG, customer name, connection status, real status. Until then the backend uses the placeholder column names above.
2. PO no: confirm it is an alternative lookup key (customer may send PO instead of SO), not a mandatory question.
3. Support contact for `[phone/email]`.
4. Real Excel row count (affects import batch size; not blocking).
5. Language: reply in all three languages every time, or detect from the customer's message (via OpenAI) and reply in one?
6. Dropbox: path of the export file and whether it is overwritten each time (recommended) or a new dated file.

---

## 10. Build order

1. Backend + MySQL, customer sync job, phone normalization. Import the real Excel. Check rejected rows.
2. Order refresh job against the external API. Run `/admin/mismatches` — this tells you immediately whether byte-exact matching works on real data.
3. State machine + verification logic, tested with curl against `/webhook/wati` using fake WATI payloads, text only.
4. Configure WATI webhook to the backend, go live with your own number, text only.
5. Groq STT branch + confirmation step.
6. OpenAI intent layer with regex fallback.
7. Alerting, rate limiting, backups, uptime monitor.
8. Pilot with a small customer group, then open to all.
