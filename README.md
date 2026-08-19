# Income Share

A small self-hosted app to parse bank statements, browse and filter transactions,
group them into folders, and export a folder to an Excel file with totals — for
sharing income/expenses with an accountant.

Built with **Django + DRF + Postgres** (backend), **React + MUI** (frontend),
served together via **Docker Compose**.

## Features

- Upload a bank statement (`.xls`, `.xlsx`, `.csv`) — parsed synchronously on upload.
- Handles the BBVA-style Spanish `.xls` layout (metadata header rows, `dd/mm/yyyy`
  dates, comma decimals, signed amounts). Income vs. expense is the sign of the amount.
- Best-effort `counterparty` (merchant/payer) extracted from the concept at import.
- Duplicate rows are skipped on re-upload (content hash).
- Browse transactions in a data grid: filter by income/expense, keyword, counterparty,
  date range, quarter (This/Previous/Q1-Q4 + year), tag, and tag source; running totals.
- Tags with a rule engine: ordered rules match transactions (by the shared criteria +
  optional regex) and auto-assign tags on upload or on demand. Manual tags are never
  overwritten.
- Hierarchical smart folders: a folder can nest under another and auto-includes
  transactions matching its tags and/or a saved filter, plus manual include/exclude.
  Parent folders roll up all descendants for totals and export.
- AI classification (Gemini): suggest tags for untagged transactions; review and apply.
- Export any folder to `.xlsx` with totals (income, expenses, or both), recursively.
- Invoicing: clients, issuer profile, draft→issued registry (immutable once issued),
  working-days hour advisor (`8 × Mon–Fri`), bank-account requisites snapshotted onto
  each invoice, XLSX/PDF generation, and import of existing `.xlsx` invoices.
- Documents registry: per-client files (agreements, orders, offers) and personal files
  (tax declarations, certificates), with upload/download and filters.
- JWT authentication. A single superuser is seeded from environment variables.
- Telegram finance agent: chat about transactions, drop receipt/invoice photos or PDFs. Files are stored as receipts and attached to a bank transaction when one matches (or later, on statement import).

### The shared "criteria" concept

One criteria shape (a subset of the transaction filter params: `kind`, `keyword`,
`counterparty`, `date_from`/`date_to`, `quarter`/`year`, `min_amount`/`max_amount`,
`tags`/`tag_match`) is reused by the transaction list filter, smart-folder membership,
and rule matching, so behavior is consistent everywhere.

## Quick start

```bash
cp .env.example .env
# edit .env: set strong DJANGO_SECRET_KEY, DB + superuser passwords
docker compose up --build
```

Then open <http://localhost:8080> and log in with the seeded superuser
(`DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD`).

Django admin is available at <http://localhost:8080/admin/>.

### Telegram bot

1. Put `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY` in `.env`.
2. `docker compose up --build`, then message the bot. If `TELEGRAM_ALLOWED_USER_IDS`
   is empty, it replies with your numeric Telegram user id.
3. Set `TELEGRAM_ALLOWED_USER_IDS` to that id and restart: `docker compose restart bot`.

Receipt photos are sent to Gemini for extraction (merchant, totals, and line items).
PDFs are stored as-is (no OCR). Unmatched receipts attach automatically when a later
statement import has exactly one amount+date hit (merchant name breaks ties).

## Architecture

```
web (React/MUI, nginx)  ──/api──▶  api (Django/DRF, gunicorn)  ──▶  db (Postgres)
bot (Telegram long-poll)  ──▶  db + media, Gemini, api.telegram.org
```

- `web` serves the built SPA and reverse-proxies `/api`, `/admin`, `/static`,
  `/media` to the `api` service — so everything is one origin.
- `api` runs migrations, collects static, and seeds the superuser on boot
  (see `backend/entrypoint.sh`).
- `bot` long-polls Telegram (no public webhook). Needs `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_ALLOWED_USER_IDS`. Chat and receipt OCR need `GEMINI_API_KEY`.
- Uploaded files and generated exports live on the `media` volume.

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/auth/token/` | Obtain JWT (username/password) |
| POST | `/api/auth/token/refresh/` | Refresh access token |
| POST | `/api/uploads/` | Upload + parse a statement (multipart `file`) |
| GET | `/api/transactions/` | List; filters: `kind`, `keyword`/`search`, `counterparty`, `date_from`, `date_to`, `quarter`, `year`, `tags`, `tag_match`, `source`, `untagged`, `folder` |
| GET | `/api/transactions/summary/` | Totals for the current filter |
| POST | `/api/transactions/tag/` | Bulk add/remove tags: `{ "transaction_ids": [...], "add": [...], "remove": [...] }` |
| GET/POST | `/api/tags/` | List / create tags |
| GET/POST | `/api/rules/` | List / create rules |
| GET | `/api/rules/{id}/preview/` | Dry-run: match count + sample |
| POST | `/api/rules/apply/` | Apply active rules (optionally `{ "transaction_ids": [...] }`) |
| GET/POST | `/api/folders/` | List / create folders (`parent`, `tags`, `tag_match`, `criteria`) |
| GET | `/api/folders/tree/` | Nested folder tree with rollup counts |
| GET | `/api/folders/{id}/transactions/?recursive=true` | Effective members |
| POST | `/api/folders/{id}/update-transactions/` | Manual include/exclude: `{ "add": [...], "remove": [...] }` |
| GET | `/api/folders/{id}/export/?totals=both&recursive=true` | Download folder as `.xlsx` |
| POST | `/api/ai/classify/` | Suggest tags for untagged/selected transactions |
| POST | `/api/ai/apply/` | Persist accepted AI suggestions |

### AI classification & privacy

AI features are enabled only when `GEMINI_API_KEY` is set. When you run a
classification, the transaction `concept`, `counterparty`, and `amount` for the
selected transactions plus your tag names/descriptions are sent to Gemini
(`GEMINI_MODEL`, default `gemini-flash-latest`). Suggestions are returned for
review; nothing is written until you apply them. The Telegram agent also sends
chat text and receipt images to Gemini. Leave `GEMINI_API_KEY` blank to disable.
On Gemini's free tier, prompts may be used to improve Google's models.

## Local development

Backend (uses SQLite so no Postgres/driver needed for tooling):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # needs Postgres client libs for psycopg
DJANGO_DB_ENGINE=sqlite DJANGO_SECRET_KEY=dev python manage.py migrate
DJANGO_DB_ENGINE=sqlite DJANGO_SECRET_KEY=dev python manage.py runserver
```

Frontend:

```bash
cd frontend
npm install
npm run dev        # Vite dev server on :5173, proxies /api to :8000
```

## Design notes / extension seams

- `Transaction.metadata` is a `JSONField` reserved for later enrichment
  (e.g. matching Amazon order exports) without a migration on populated data.
- The parser is a dispatcher keyed by extension (`core/parsing.py`); adding a new
  bank/format means adding one reader that returns a matrix — nothing else changes.
- Multi-role access (a read-only accountant login) is intentionally deferred.
- Incoming receipts attach to transactions via Telegram (and auto-match on
  statement import). A receipts page in the web UI is not built yet; use admin
  or ask the bot.
