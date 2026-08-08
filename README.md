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
- AI classification (OpenAI): suggest tags for untagged transactions; review and apply.
- Export any folder to `.xlsx` with totals (income, expenses, or both), recursively.
- JWT authentication. A single superuser is seeded from environment variables.

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

## Architecture

```
web (React/MUI, nginx)  ──/api──▶  api (Django/DRF, gunicorn)  ──▶  db (Postgres)
```

- `web` serves the built SPA and reverse-proxies `/api`, `/admin`, `/static`,
  `/media` to the `api` service — so everything is one origin.
- `api` runs migrations, collects static, and seeds the superuser on boot
  (see `backend/entrypoint.sh`).
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

AI features are enabled only when `OPENAI_API_KEY` is set. When you run a
classification, the transaction `concept`, `counterparty`, and `amount` for the
selected transactions plus your tag names/descriptions are sent to OpenAI
(`OPENAI_MODEL`, default `gpt-4o-mini`). Suggestions are returned for review;
nothing is written until you apply them. Leave `OPENAI_API_KEY` blank to disable.

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
- Multi-role access (a read-only accountant login) and attaching invoices/agreements
  to transactions are intentionally deferred; both are additive to the current schema.
