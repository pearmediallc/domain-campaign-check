from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx

from .checker import run_full_check
from .config import MAX_TELEGRAM_MESSAGES_PER_RUN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .log import log
from .redtrack import RedTrackClient
from .results_store import append_run
from .storage import load_config
from .telegram import TelegramError, send_many, send_message

# Check if we should use webhook mode (for production on Render)
USE_WEBHOOK = os.getenv("TELEGRAM_USE_WEBHOOK", "false").lower() in ("1", "true", "yes")
# Force redeploy to pick up environment variable changes


class TelegramBot:
    """Telegram bot that listens for commands and triggers domain checks."""

    def __init__(self):
        self.offset = 0
        self.running = False
        self._check_running = False
        self._thread: threading.Thread | None = None

    def start(self):
        """Start the bot polling in a background thread."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            log("telegram.bot.skip", reason="not_configured")
            return

        if USE_WEBHOOK:
            log("telegram.bot.skip", reason="webhook_mode_enabled")
            return

        # Delete any existing webhook before starting polling
        self._delete_webhook()

        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log("telegram.bot.start", mode="polling")

    def stop(self):
        """Stop the bot polling."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        log("telegram.bot.stop")

    def _delete_webhook(self):
        """Delete any existing webhook to avoid 409 conflicts."""
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook"
            params = {"drop_pending_updates": True}
            r = httpx.post(url, json=params, timeout=10)
            if r.status_code == 200:
                log("telegram.bot.webhook_deleted")
            else:
                log("telegram.bot.webhook_delete_error", status=r.status_code)
        except Exception as e:
            log("telegram.bot.webhook_delete_exception", error=str(e))

    def _poll_loop(self):
        """Main polling loop that fetches updates from Telegram."""
        while self.running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception as e:
                log("telegram.bot.poll_error", error=str(e))
                print(f"[telegram_bot] poll error: {e}")

            # Poll every 2 seconds
            time.sleep(2)

    def _get_updates(self) -> list[dict[str, Any]]:
        """Fetch updates from Telegram using long polling."""
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {
            "offset": self.offset,
            "timeout": 10,  # Long polling timeout
        }

        try:
            r = httpx.get(url, params=params, timeout=15)
            if r.status_code == 409:
                log("telegram.bot.conflict", message="Another instance is running. Deleting webhook...")
                self._delete_webhook()
                return []
            if r.status_code != 200:
                log("telegram.bot.get_updates_error", status=r.status_code)
                return []

            data = r.json()
            if not data.get("ok"):
                return []

            updates = data.get("result", [])
            if updates:
                # Update offset to acknowledge processed updates
                self.offset = updates[-1]["update_id"] + 1

            return updates
        except Exception as e:
            log("telegram.bot.get_updates_exception", error=str(e))
            return []

    def _handle_update(self, update: dict[str, Any]):
        """Handle a single update from Telegram."""
        message = update.get("message")
        if not message:
            return

        text = message.get("text", "")
        chat_id = message.get("chat", {}).get("id")
        from_user = message.get("from", {})
        username = from_user.get("username", "unknown")

        # Only process commands from the configured chat
        if str(chat_id) != str(TELEGRAM_CHAT_ID):
            log(
                "telegram.bot.wrong_chat",
                chat_id=chat_id,
                expected=TELEGRAM_CHAT_ID,
                text=text[:50],
            )
            return

        # Handle commands
        if text.startswith("/check") or text.startswith("/run"):
            log("telegram.bot.command.check", user=username, chat_id=chat_id)
            self._handle_check_command()
        elif text.startswith("/status"):
            log("telegram.bot.command.status", user=username, chat_id=chat_id)
            self._handle_status_command()
        elif text.startswith("/help"):
            log("telegram.bot.command.help", user=username, chat_id=chat_id)
            self._handle_help_command()

    def _handle_check_command(self):
        """Handle the /check or /run command to trigger a domain check."""
        if self._check_running:
            try:
                send_message("⏳ A domain check is already running. Please wait...")
            except Exception as e:
                log("telegram.bot.send_error", error=str(e))
            return

        # Run check in background thread
        t = threading.Thread(target=self._run_check_in_background, daemon=True)
        t.start()

    def _run_check_in_background(self):
        """Run the domain check in a background thread."""
        self._check_running = True
        try:
            send_message("🔍 Starting domain check...")
            log("telegram.bot.check.start")

            cfg = load_config()
            redtrack = RedTrackClient()
            results = run_full_check(
                redtrack,
                date_from=cfg.date_from,
                date_to=cfg.date_to,
                days_lookback=cfg.days_lookback,
            )

            total = len(results)
            failing = sum(1 for r in results if any(not ch.get("ok") for ch in r.get("checks", [])))

            log("telegram.bot.check.results", total=total, failing=failing)

            # Save results
            append_run(
                {
                    "kind": "telegram",
                    "ts": int(time.time()),
                    "date_from": cfg.date_from,
                    "date_to": cfg.date_to,
                    "days_lookback": cfg.days_lookback,
                    "total_checked": total,
                    "failing": failing,
                    "results": results,
                }
            )

            # Send summary
            send_message(f"✅ Check complete! Checked {total} campaigns. Failures: {failing}.")

            # Send failure details if any
            if failing:
                lines: list[str] = [f"🚨 {failing} failing campaign(s) (checked {total})"]
                for r in results:
                    c = r.get("campaign", {})
                    failed = [ch for ch in r.get("checks", []) if not ch.get("ok")]
                    if not failed:
                        continue
                    lines.append(
                        f"FAIL | {c.get('title') or 'Campaign'} | {c.get('id')} | {c.get('domain_name') or ''}"
                    )
                    if c.get("trackback_url"):
                        lines.append(f"  url: {c.get('trackback_url')}")
                    for ch in failed[:8]:
                        lines.append(
                            f"  - {ch.get('kind')}: {ch.get('failure_type')} {ch.get('message')} {ch.get('tested_url')}"
                        )
                    lines.append("")

                send_many(lines, max_messages=MAX_TELEGRAM_MESSAGES_PER_RUN)

        except Exception as e:
            log("telegram.bot.check.error", error=str(e))
            try:
                send_message(f"❌ Domain check failed: {e}")
            except Exception:
                pass
        finally:
            self._check_running = False

    def _handle_status_command(self):
        """Handle the /status command to show current configuration."""
        try:
            cfg = load_config()
            status_msg = f"""📊 *Domain Check Status*

Schedule: {cfg.schedule_mode}
Run time: {cfg.run_at_hhmm if cfg.schedule_mode == 'daily_at' else f'Every {cfg.interval_minutes} minutes'}
Days lookback: {cfg.days_lookback}
Date range: {cfg.date_from or 'auto'} to {cfg.date_to or 'auto'}

Use /check to trigger a manual check
Use /help for more commands"""
            send_message(status_msg, parse_mode="Markdown")
        except Exception as e:
            log("telegram.bot.status_error", error=str(e))

    def _handle_help_command(self):
        """Handle the /help command to show available commands."""
        try:
            help_msg = """🤖 *Available Commands*

/check or /run - Trigger a domain check immediately
/status - Show current configuration and status
/help - Show this help message

The bot also runs scheduled checks automatically based on your configuration."""
            send_message(help_msg, parse_mode="Markdown")
        except Exception as e:
            log("telegram.bot.help_error", error=str(e))


# Global bot instance
_bot: TelegramBot | None = None
_webhook_handler: TelegramBot | None = None


def start_telegram_bot():
    """Start the Telegram bot (call this on app startup)."""
    global _bot, _webhook_handler
    if _bot is None:
        _bot = TelegramBot()
        _bot.start()

    # Create a separate instance for webhook handling
    if _webhook_handler is None:
        _webhook_handler = TelegramBot()

    return _bot


def stop_telegram_bot():
    """Stop the Telegram bot (call this on app shutdown)."""
    global _bot
    if _bot:
        _bot.stop()
        _bot = None


def handle_telegram_update(update: dict[str, Any]):
    """Handle a Telegram update received via webhook."""
    global _webhook_handler
    if _webhook_handler is None:
        _webhook_handler = TelegramBot()

    _webhook_handler._handle_update(update)
