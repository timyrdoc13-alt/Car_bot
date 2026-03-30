# Car channel Telegram bot — instructions for the AI agent

## Product

Async Telegram bot for a car sales channel: admin private chat with **manual post** (photo + raw text → LLM → preview → publish), **auto mode** (parse → dedupe → batch approve), **stats** (publications, approve rate). Target post format: **short, scannable, selling** — first line trim, 4–6 fact bullets, one price line (BY / RU + manager), one CTA; aim **~350–600 chars**, hard cap for media caption **1024** (prompt budget e.g. 900).

## Stack

- Python **3.9+** (как в `pyproject.toml`), **aiogram 3** (async only in handlers and I/O).
- LLM: **OpenAI-compatible** HTTP API (`/v1/chat/completions`), e.g. **DeepSeek** via `LLM_BASE_URL` + key + `deepseek-chat`.
- **httpx** async for LLM; **aiosqlite** + SQLite for listings dedupe (30d), posts/events.
- **Playwright** async for scraping (headless, delays, user agents); **structlog** for JSON logs.
- **Docker**: `Dockerfile` (Chromium в образе), `docker-compose.yml`, прод-инструкция — `DEPLOY.md`. Graceful shutdown (SIGTERM/SIGINT).

## Layout (planned)

- `bot/` — routers, FSM, keyboards, middleware (admin-only).
- `services/` — llm client, publishing, stats.
- `parsers/` — `ListingSource`, `fields` / `embed_json` / `common` / `quality`, stub + Lalafo + Mashina (`LISTING_SOURCE`).
- `db/` — schema, repositories.
- `config/` — pydantic-settings from `.env`.

## Rules of engagement

1. Follow `.cursor/rules/*.mdc` in this repo.
2. **Do not invent** listing facts in LLM prompts; missing fields → “ask manager”.
3. **Scope**: implement only what the agreed plan/todo says; no drive-by refactors.
4. **If uncertain** (parser domain, legal/ToS, secrets, ambiguous UX): **stop and ask the project owner** — do not guess.
5. For large codebase search, use thorough exploration; keep changes focused.

## Secrets

Never commit real tokens. Use `.env` / `.env.example` only; document variables in README when the code phase starts.
