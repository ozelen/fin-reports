"""Long-poll Telegram and run the finance agent. No public webhook needed."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core import agent, telegram as tg
from core.ai import AiNotConfigured, AiUnavailable
from core.models import Receipt, TelegramLink
from core.receipts import candidate_transactions, save_receipt

log = logging.getLogger("telegram_bot")

HELP = (
    "I can talk about your finances, summarise periods, and file receipts.\n"
    "Send a photo or PDF of a receipt/invoice — I'll parse the line items, "
    "save them, and try to match a bank transaction (or wait until one is imported).\n"
    "/reset — clear this chat's memory."
)
MAX_HISTORY = 30


class Command(BaseCommand):
    help = "Poll Telegram and handle finance-agent messages."

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stderr.write("TELEGRAM_BOT_TOKEN is not set; bot idle.")
            while True:
                time.sleep(3600)

        while True:
            try:
                me = tg.get_me()
                break
            except tg.TelegramError as exc:
                self.stderr.write(f"Telegram not ready: {exc}")
                time.sleep(5)
        self.stdout.write(self.style.SUCCESS(f"Polling as @{me.get('username')}"))
        offset = _load_offset()
        while True:
            try:
                updates = tg.get_updates(offset)
            except tg.TelegramError as exc:
                log.warning("getUpdates: %s", exc)
                time.sleep(3)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                _save_offset(offset)
                message = update.get("message") or {}
                try:
                    _handle_message(message)
                except Exception:  # noqa: BLE001 - never die the poll loop
                    log.exception("update %s", update.get("update_id"))
                    chat = (message.get("chat") or {}).get("id")
                    if chat:
                        try:
                            tg.send_message(chat, "Something went wrong handling that. Try again.")
                        except tg.TelegramError:
                            pass


def _offset_path() -> Path:
    return Path(settings.MEDIA_ROOT) / ".telegram_offset"


def _load_offset() -> int:
    try:
        return int(_offset_path().read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _save_offset(value: int) -> None:
    path = _offset_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value))


def _owner():
    return get_user_model().objects.filter(is_superuser=True).order_by("id").first()


def _handle_message(message: dict) -> None:
    if not message:
        return
    from_user = message.get("from") or {}
    user_id = from_user.get("id")
    chat_id = (message.get("chat") or {}).get("id")
    if user_id is None or chat_id is None:
        return

    allowed = settings.TELEGRAM_ALLOWED_USER_IDS
    if not allowed:
        tg.send_message(
            chat_id,
            f"This bot is private. Your Telegram user id is {user_id}. "
            f"Add TELEGRAM_ALLOWED_USER_IDS={user_id} to .env and restart the bot.",
        )
        return
    if user_id not in allowed:
        tg.send_message(chat_id, "Not authorized.")
        return

    owner = _owner()
    if owner is None:
        tg.send_message(chat_id, "No app user is set up yet (need a Django superuser).")
        return

    link, _ = TelegramLink.objects.get_or_create(
        telegram_user_id=user_id,
        defaults={"owner": owner, "chat_id": chat_id, "messages": []},
    )
    if link.chat_id != chat_id:
        link.chat_id = chat_id
        link.save(update_fields=["chat_id"])

    text = (message.get("text") or message.get("caption") or "").strip()
    cmd = text.split()[0].split("@")[0] if text.startswith("/") else ""
    if cmd in ("/start", "/help"):
        tg.send_message(chat_id, HELP)
        return
    if cmd == "/reset":
        link.messages = []
        link.save(update_fields=["messages", "updated_at"])
        tg.send_message(chat_id, "Chat memory cleared.")
        return

    tg.send_chat_action(chat_id)
    extra = ""
    file_id, filename, mime = _file_from_message(message)
    if file_id:
        data, default_name, dl_mime = tg.download_file(file_id)
        filename = filename or default_name
        mime = mime or dl_mime
        receipt = save_receipt(
            owner,
            data=data,
            filename=filename,
            mime_type=mime,
            caption=text,
            telegram_file_id=file_id,
        )
        extra = _receipt_context(receipt)
        if not text:
            text = f"(sent file {filename})"

    if not text and not extra:
        return

    history = list(link.messages or [])
    try:
        answer = agent.reply(owner, history, extra_user_text=_compose_user(text, extra))
    except (AiNotConfigured, AiUnavailable) as exc:
        note = extra or str(exc)
        if extra:
            note = f"{extra}\n\n{exc}"
        tg.send_message(chat_id, note)
        return
    except Exception as exc:  # noqa: BLE001
        if extra:
            tg.send_message(chat_id, extra)
            return
        tg.send_message(chat_id, f"AI is not available: {exc}")
        return

    history.append({"role": "user", "content": _compose_user(text, extra)})
    history.append({"role": "assistant", "content": answer})
    link.messages = _trim(history)
    link.save(update_fields=["messages", "updated_at"])
    tg.send_message(chat_id, answer)


def _compose_user(text: str, extra: str) -> str:
    if extra and text:
        return f"{text}\n\n{extra}"
    return extra or text


def _trim(history: list) -> list:
    if len(history) <= MAX_HISTORY:
        return history
    return history[-MAX_HISTORY:]


def _file_from_message(message: dict) -> tuple[str, str, str]:
    photos = message.get("photo") or []
    if photos:
        biggest = max(photos, key=lambda p: p.get("file_size") or 0)
        return biggest.get("file_id") or "", "photo.jpg", "image/jpeg"
    doc = message.get("document") or {}
    if doc.get("file_id"):
        return (
            doc["file_id"],
            doc.get("file_name") or "document",
            doc.get("mime_type") or "",
        )
    return "", "", ""


def _receipt_context(receipt: Receipt) -> str:
    parts = [
        f"[Saved as receipt #{receipt.id}]",
        f"kind={receipt.kind}",
        f"merchant={receipt.merchant or '?'}",
        f"amount={receipt.amount if receipt.amount is not None else '?' } {receipt.currency}",
        f"date={receipt.document_date or '?'}",
        f"file={receipt.original_filename}",
    ]
    items = list(receipt.items.all()[:25])
    if items:
        lines = [
            f"- {it.name} x{it.quantity} = {it.amount or '?'} ({it.category or '?'})"
            for it in items
        ]
        parts.append("items:\n" + "\n".join(lines))
    else:
        parts.append("items: none parsed")
    if receipt.transaction_id:
        parts.append(f"auto-attached to transaction #{receipt.transaction_id}")
        return "\n".join(parts)
    hits = list(
        candidate_transactions(
            receipt.owner, receipt.amount, receipt.document_date, receipt.currency
        )
    )
    if hits:
        lines = [
            f"#{tx.id} {tx.operation_date} {tx.amount} {tx.currency} {(tx.counterparty or tx.concept)[:60]}"
            for tx in hits
        ]
        parts.append("candidates:\n" + "\n".join(lines))
    else:
        parts.append("no matching bank transaction yet; will wait for a later import.")
    return "\n".join(parts)
