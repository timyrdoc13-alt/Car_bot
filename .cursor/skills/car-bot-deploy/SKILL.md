---
name: car-bot-deploy
description: >-
  Checklist for deploying the car-channel Telegram bot (env, Telegram, Docker).
  Use when setting up a new environment or troubleshooting startup.
---

# Car channel bot — deploy checklist

## Before first run

1. Copy `.env.example` to `.env` (when available) and set:
   - `BOT_TOKEN`, `CHANNEL_ID`, `ADMIN_IDS`
   - `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (e.g. DeepSeek `https://api.deepseek.com` + `deepseek-chat`)
   - `MANAGER_USERNAME` for post CTAs
2. In Telegram: create bot via BotFather; add bot to the **channel as admin** with **Post messages** permission.
3. `ADMIN_IDS`: comma-separated numeric user IDs of operators.

## Docker

1. From repo root: `docker compose up -d --build`
2. Confirm volume path for SQLite exists and is writable.
3. Logs: follow container logs for structlog lines and startup errors (Playwright, missing env).

## When stuck

- **403 / chat not found**: channel ID format (`-100…`) and bot membership.
- **LLM errors**: base URL must resolve to `/v1/chat/completions`; verify key and model name.
- **Playwright in container**: ensure Chromium deps installed in image, not only local dev.

After checklist, if still failing, ask the project owner for redacted `.env` key names (not values) and exact error lines.
