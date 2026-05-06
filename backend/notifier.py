"""Push notifications.

Tries Telegram first (if configured via TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).
Falls back to macOS native notification via osascript. Both are best-effort —
never block the calling code.

Setup Telegram (5 min):
  1. Open Telegram → search @BotFather → /newbot → follow prompts → save the token.
  2. Send any message to your new bot.
  3. Open https://api.telegram.org/bot<TOKEN>/getUpdates → copy "chat":{"id":...}
  4. Add to backend/.env:
        TELEGRAM_BOT_TOKEN=123:ABC...
        TELEGRAM_CHAT_ID=123456
"""
from __future__ import annotations

import os
import shutil
import logging
import subprocess
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _telegram_token() -> Optional[str]:
    t = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    return t if t and not t.startswith("COLA_") else None


def _telegram_chat() -> Optional[str]:
    c = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return c if c and not c.startswith("COLA_") else None


def telegram_enabled() -> bool:
    return _telegram_token() is not None and _telegram_chat() is not None


def send_telegram(text: str, *, parse_mode: str = "Markdown", silent: bool = False) -> bool:
    """Best-effort Telegram send. Returns True on success."""
    token = _telegram_token()
    chat = _telegram_chat()
    if not (token and chat):
        return False
    try:
        # Telegram limit is 4096 chars per message
        body = text[:4000]
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": body,
                "parse_mode": parse_mode,
                "disable_notification": silent,
                "disable_web_page_preview": True,
            },
            timeout=8,
        )
        if r.status_code != 200:
            logger.warning(f"Telegram send {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")
        return False


def send_macos(title: str, message: str) -> bool:
    """Native macOS notification via osascript. Only visible if Mac is unlocked."""
    if not shutil.which("osascript"):
        return False
    safe_title = title.replace('"', "'")
    safe_msg = message.replace('"', "'")[:200]
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe_msg}" with title "{safe_title}"'],
            capture_output=True, timeout=5,
        )
        return True
    except Exception as e:
        logger.debug(f"osascript failed: {e}")
        return False


def notify(title: str, message: str, *, severity: str = "info", markdown: bool = True) -> dict:
    """Send via all available channels. Returns delivery status per channel.

    severity: 'info' | 'warning' | 'critical' — only affects emoji prefix.
    """
    prefix = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "ℹ️")

    full_text = f"{prefix} *{title}*\n\n{message}" if markdown else f"{prefix} {title}\n\n{message}"

    return {
        "telegram": send_telegram(full_text, parse_mode="Markdown" if markdown else None),
        "macos": send_macos(f"{prefix} {title}", message),
    }
