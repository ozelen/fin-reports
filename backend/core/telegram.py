"""Minimal Telegram Bot API client (long poll + file download). Stdlib only."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class TelegramError(Exception):
    pass


def _token() -> str:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    return token


def call(method: str, payload: dict | None = None, timeout: int = 60):
    url = f"https://api.telegram.org/bot{_token()}/{method}"
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise TelegramError(f"{method} failed HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f"{method} network error: {exc}") from exc
    if not body.get("ok"):
        raise TelegramError(body.get("description") or str(body))
    return body["result"]


def get_updates(offset: int, timeout: int = 50):
    return call(
        "getUpdates",
        {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
        timeout=timeout + 10,
    )


def send_message(chat_id: int, text: str):
    # Telegram hard-caps a message at 4096 chars.
    text = text or ""
    for i in range(0, max(len(text), 1), 4000):
        call("sendMessage", {"chat_id": chat_id, "text": text[i : i + 4000]})


def send_chat_action(chat_id: int, action: str = "typing"):
    try:
        call("sendChatAction", {"chat_id": chat_id, "action": action}, timeout=10)
    except TelegramError:
        pass


def download_file(file_id: str) -> tuple[bytes, str, str]:
    """Return (bytes, filename, mime_type). mime may be empty."""
    meta = call("getFile", {"file_id": file_id}, timeout=30)
    path = meta.get("file_path") or ""
    url = f"https://api.telegram.org/file/bot{_token()}/{urllib.parse.quote(path, safe='/')}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
            mime = resp.headers.get_content_type() or ""
    except urllib.error.URLError as exc:
        raise TelegramError(f"file download failed: {exc}") from exc
    filename = path.rsplit("/", 1)[-1] or "file"
    return data, filename, mime


def get_me():
    return call("getMe", timeout=15)
