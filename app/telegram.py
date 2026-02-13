from __future__ import annotations

import httpx

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class TelegramError(RuntimeError):
    pass


def send_message(text: str, parse_mode: str | None = None, disable_web_page_preview: bool = True) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise TelegramError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    r = httpx.post(url, json=payload, timeout=20)
    if r.status_code >= 400:
        raise TelegramError(f"Telegram send failed: {r.status_code} {r.text[:400]}")
