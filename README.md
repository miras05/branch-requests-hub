# Branch Requests Hub — AI digest across Telegram, email and Bitrix24

![CI](https://github.com/miras05/branch-requests-hub/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.12-blue)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)

A company with 7 branches and ~400 employees talks in 7 Telegram groups, by email and in Bitrix24
(CRM + tasks). The director was drowning in three streams. This system collects everything into
one PostgreSQL table and sends management a **daily AI digest with priorities**; critical items
automatically become tasks in Bitrix24.

**Key principle: employees install nothing.** They keep chatting in their groups as before; the
bot silently reads and stores. Commands are available only to a whitelist of managers.

## Architecture

```mermaid
flowchart LR
    TG[Telegram groups<br/>7 branches] --> DB[(PostgreSQL<br/>messages)]
    MAIL[Email via IMAP<br/>every 5 min] --> DB
    BX[Bitrix24 REST<br/>tasks + leads<br/>every 10 min] --> DB
    DB --> AI[Groq · Llama 3.3 70B]
    AI -->|09:00 daily digest| DIR[Director in Telegram]
    AI -->|🔴 critical items| TASK[Bitrix24 task]
```

| Command | What it does |
|---|---|
| `/digest` | AI digest across all sources, grouped 🔴 critical / 🟡 important / 🔵 info / ⚪ background |
| `/search <text>` | Full-text search across all sources at once |
| `/client <name>` | Customer card |
| `/task <description>` | Creates a task in Bitrix24 (and adds it to the next digest immediately) |
| `/myid` | Shows your Telegram ID for the whitelist |

## Engineering notes

- **Balanced digest.** A plain `ORDER BY created_at DESC LIMIT 20` let twenty newsletters push
  Bitrix24 tasks out of the digest. The query takes the latest N per source with
  `ROW_NUMBER() OVER (PARTITION BY source …)`. Telegram and email are limited to today; Bitrix24
  tasks have no date filter, because a task opened a week ago may still need attention. Covered
  by an integration test against a real PostgreSQL in CI.
- **Token budget.** Groq's free tier allows 12,000 tokens per minute, so the number of messages
  per source and the characters per message are sized to fit, otherwise the API returns 413.
- **Idempotent ingestion.** Every external record keeps its `source_id`; a partial unique index on
  `(source, source_id)` guarantees an email or a Bitrix24 task is stored once.
- **Noise filtering.** Emails from `noreply`, newsletters and notification senders are skipped.
- **Scheduling inside the bot.** Periodic jobs run on python-telegram-bot's `job_queue` instead
  of `AsyncIOScheduler`, which fails with "no running event loop" when started outside the bot's
  loop.
- **Modular connectors.** Each source is a separate module (`integrations/mail.py`,
  `integrations/bitrix.py`); the LLM provider can be swapped without touching the rest.
- `pgvector` is enabled for the next step: semantic deduplication of the same event reported in
  three sources in different words.

## Run

```bash
cp .env.example .env              # bot token, Groq key, IMAP, Bitrix24 webhook
docker compose up -d              # PostgreSQL 16 + pgvector
pip install -r requirements.txt
python db/init.py && python db/seed.py
python bot/collector.py
```

## Tests

```bash
pip install -r requirements-dev.txt
ruff check . && pytest -q
# integration tests need a database:
TEST_DATABASE_URL=postgresql://admin:admin@localhost:5432/ai_system pytest -q
```

## Status

A working prototype, tested on a test chat, a personal mailbox and a test Bitrix24 portal. Not
yet done: deployment to a VPS, application-level error handling and logging, semantic
deduplication. The company works in Russian, so prompts, bot replies and comments are in Russian.
