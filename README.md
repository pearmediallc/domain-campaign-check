# Domain Campaign Check (RedTrack)

Daily checker that:

1. Pulls **active campaigns** from RedTrack.
2. Keeps only campaigns with **spend OR revenue in the last 30 days**.
3. For each campaign, checks that:
   - the campaign's **redirect / tracking URL** is reachable (HTTP-only)
   - the campaign's **configured domain** resolves and responds
   - the **landing page URL(s)** behind the campaign load (HTTP-only)
4. Sends **Telegram alerts** for failures + stores results in a DB.
5. Provides a small **web dashboard** to view status/history.

## Deployment (Render)
This repo is set up to deploy on Render as:
- a **Web Service** (dashboard)
- a **Cron Job** (daily checker)

Render Blueprint: `render.yaml`

## Environment variables

### Required
- `REDTRACK_API_KEY` – RedTrack API key
- `DATABASE_URL` – Postgres URL from Render (recommended)
- `TELEGRAM_BOT_TOKEN` – Telegram bot token
- `TELEGRAM_CHAT_ID` – target chat id (group or user)

### Optional
- `REDTRACK_API_BASE` – default `https://api.redtrack.io`
- `TIMEZONE` – default `Asia/Calcutta`
- `DAYS_LOOKBACK` – default `30`
- `CHECK_TIMEOUT_SECONDS` – default `15`
- `CHECK_RETRIES` – default `2`
- `ALERT_ON_FIRST_FAILURE` – default `false` (send alert only after retries)

## Telegram bot creation
Create it yourself via **@BotFather** (Telegram requirement):
1. Open Telegram → search `@BotFather`
2. Send `/newbot`
3. Choose name + username → BotFather returns a token
4. Put token into `TELEGRAM_BOT_TOKEN`

To get `TELEGRAM_CHAT_ID`:
- Start a chat with the bot and send any message, then call:
  `https://api.telegram.org/bot<token>/getUpdates`
  and copy `message.chat.id`

## Local dev
```bash
cp .env.example .env
# fill env vars

npm i  # (not needed)

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# run web dashboard
uvicorn app.web:app --reload

# run checker once
python -m app.run_check
```
