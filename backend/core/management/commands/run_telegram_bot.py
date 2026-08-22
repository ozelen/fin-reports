"""Long-poll Telegram and run the finance agent. No public webhook needed."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from core import agent, telegram as tg
from core.ai import AiNotConfigured, AiUnavailable
from core.filing import classify_upload, pdf_creation_date, save_personal_document
from core.models import Account, Document, PurchaseItem, Receipt, TelegramLink, Upload
from core.parsing import (
    ParseError,
    UnsupportedFormat,
    is_statement_file,
    match_accounts,
    parse as parse_statement,
    pick_account,
)
from core.receipts import (
    candidate_transactions,
    ingest_statement,
    match_pending_receipts,
    parse_queued_receipt,
    pending_parse_qs,
    save_receipt,
    window_days,
)

log = logging.getLogger("telegram_bot")

HELP = (
    "I can talk about your finances, summarise periods, and file receipts.\n"
    "Send a photo or PDF of a receipt — I'll parse line items, put it in your "
    "transactions list, and fill in the bank row when the statement arrives.\n"
    "Send a bank statement (.xls / .xlsx / .csv) and I'll import it. If more than "
    "one account fits, I'll ask which one (e.g. Monobank white vs black).\n"
    "Drop several receipt photos in one album — I'll file each and message as I go.\n"
    "Printed names stay as-is; set a custom title, tags (food vs household), "
    "barcode, or a product photo.\n"
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
                timeout = 5 if pending_parse_qs().exists() else 50
                updates = tg.get_updates(offset, timeout=timeout)
            except tg.TelegramError as exc:
                log.warning("getUpdates: %s", exc)
                time.sleep(3)
                continue
            groups: dict[str, list] = {}
            singles: list[dict] = []
            for update in updates:
                offset = update["update_id"] + 1
                _save_offset(offset)
                message = update.get("message") or {}
                gid = message.get("media_group_id")
                if gid:
                    groups.setdefault(gid, []).append(message)
                else:
                    singles.append(message)
            # Album items often arrive in two bursts; wait once for the rest.
            if groups:
                time.sleep(1.2)
                try:
                    more = tg.get_updates(offset, timeout=1)
                except tg.TelegramError as exc:
                    log.warning("getUpdates: %s", exc)
                    more = []
                for update in more:
                    offset = update["update_id"] + 1
                    _save_offset(offset)
                    message = update.get("message") or {}
                    gid = message.get("media_group_id")
                    if gid:
                        groups.setdefault(gid, []).append(message)
                    else:
                        singles.append(message)
            for message in singles:
                try:
                    _handle_message(message)
                except Exception:  # noqa: BLE001 - never die the poll loop
                    log.exception("update %s", message.get("message_id"))
                    chat = (message.get("chat") or {}).get("id")
                    if chat:
                        try:
                            tg.send_message(chat, "Something went wrong handling that. Try again.")
                        except tg.TelegramError:
                            pass
            for msgs in groups.values():
                try:
                    _handle_media_group(msgs)
                except Exception:  # noqa: BLE001
                    log.exception("media group")
                    chat = (msgs[0].get("chat") or {}).get("id") if msgs else None
                    if chat:
                        try:
                            tg.send_message(chat, "Something went wrong handling that album. Try again.")
                        except tg.TelegramError:
                            pass
            try:
                _try_parse_one()
            except Exception:  # noqa: BLE001
                log.exception("parse queue")


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
        _clear_pending_upload(link)
        link.save(update_fields=["messages", "pending_upload_id", "updated_at"])
        tg.send_message(chat_id, "Chat memory cleared.", reply_markup={"remove_keyboard": True})
        return

    attached = match_pending_receipts(owner)
    extra = ""
    file_id, filename, mime = _file_from_message(message)
    if file_id:
        _say(chat_id, f"Received {filename}")
        extra, wait = _ingest_file(link, owner, chat_id, message, text)
        if wait:
            return
        if extra.startswith("queued:"):
            rid = extra.split(":", 1)[1]
            n = pending_parse_qs(owner).count()
            _say(chat_id, f"Queued {_file_role(filename, mime)} #{rid} ({n} in parse queue)")
            return
        if extra.startswith("Saved "):
            _say(chat_id, extra)
            _note_history(link, text or f"(sent {filename})", extra)
            return
        if extra.startswith("[Imported"):
            _note_history(link, text or f"(sent {filename})", extra)
            return
        if not text:
            text = f"(sent file {filename})"
    elif link.pending_upload_id and text:
        extra = _resolve_pending_statement(link, owner, chat_id, text)
        if extra is None:
            return
        if extra.startswith("[Imported"):
            _note_history(link, text, extra)
            return
    elif attached:
        extra = f"[Auto-attached {attached} pending receipt(s) to bank transactions]"
        _say(chat_id, f"Attached {attached} pending receipt(s) to bank rows")

    _complete_turn(link, owner, chat_id, text, extra)


def _handle_media_group(messages: list[dict]) -> None:
    messages = [m for m in messages if m]
    if not messages:
        return
    if len(messages) == 1:
        _handle_message(messages[0])
        return
    first = messages[0]
    from_user = first.get("from") or {}
    user_id = from_user.get("id")
    chat_id = (first.get("chat") or {}).get("id")
    if user_id is None or chat_id is None:
        return
    allowed = settings.TELEGRAM_ALLOWED_USER_IDS
    if not allowed or user_id not in allowed:
        return
    owner = _owner()
    if owner is None:
        return
    link, _ = TelegramLink.objects.get_or_create(
        telegram_user_id=user_id,
        defaults={"owner": owner, "chat_id": chat_id, "messages": []},
    )
    match_pending_receipts(owner)
    caption = next(((m.get("caption") or "").strip() for m in messages if m.get("caption")), "")
    files = []
    seen = set()
    for message in messages:
        file_id, filename, mime = _file_from_message(message)
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        files.append((message, filename, mime))
    if not files:
        return
    _say(chat_id, f"Received {len(files)} files")
    loaded = []
    roles = {}
    for message, _filename, _mime in files:
        attachment = _download_attachment(message)
        role = _file_role(attachment[1], attachment[2], attachment[3])
        roles[role] = roles.get(role, 0) + 1
        loaded.append((message, attachment))
    identified = _identified_line(roles)
    if identified:
        _say(chat_id, identified)
    extras = []
    queued = 0
    for i, (message, attachment) in enumerate(loaded):
        extra, wait = _ingest_file(
            link,
            owner,
            chat_id,
            message,
            caption if i == 0 else "",
            loaded=attachment,
        )
        if extra.startswith("queued:"):
            queued += 1
        elif extra:
            extras.append(extra)
        if wait:
            break
    if queued:
        _say(chat_id, f"Queued {queued} for parsing — I'll message as each is done")
    imported = [e for e in extras if e.startswith("[Imported")]
    if imported:
        _note_history(link, caption or f"(sent {len(files)} files)", "\n\n".join(imported))
    other = [e for e in extras if not e.startswith("[Imported")]
    if other:
        for line in other:
            if line.startswith("Saved "):
                _say(chat_id, line)
        rest = [e for e in other if not e.startswith("Saved ")]
        if rest:
            _complete_turn(link, owner, chat_id, caption, "\n\n".join(rest))


def _say(chat_id, text: str, reply_markup: dict | None = None) -> None:
    tg.send_message(chat_id, text, reply_markup=reply_markup)


def _file_role(filename: str, mime: str = "", data: bytes = b"") -> str:
    if is_statement_file(filename, mime, data):
        return "statement"
    kind = classify_upload(filename)
    return {
        "invoice": "invoice",
        Document.KIND_TAX_DECLARATION: "declaration",
        Document.KIND_TAX_CERTIFICATE: "certificate",
        "other_document": "document",
    }.get(kind, "receipt")


def _identified_line(roles: dict) -> str:
    labels = (
        ("receipt", "receipts"),
        ("invoice", "invoices"),
        ("declaration", "declarations"),
        ("certificate", "certificates"),
        ("document", "documents"),
        ("statement", "statements"),
    )
    bits = [f"{label}: {roles[key]}" for key, label in labels if roles.get(key)]
    return "Identified " + ", ".join(bits) if bits else ""


def _download_attachment(message: dict) -> tuple[str, str, str, bytes]:
    file_id, filename, mime = _file_from_message(message)
    data, default_name, dl_mime = tg.download_file(file_id)
    return file_id, filename or default_name, mime or dl_mime, data


def _note_history(link, text: str, extra: str) -> None:
    history = list(link.messages or [])
    history.append({"role": "user", "content": _compose_user(text, extra)})
    history.append({"role": "assistant", "content": extra or "ok"})
    link.messages = _trim(history)
    link.save(update_fields=["messages", "updated_at"])


def _compose_user(text: str, extra: str) -> str:
    if extra and text:
        return f"{text}\n\n{extra}"
    return extra or text


def _ingest_file(
    link, owner, chat_id, message: dict, caption: str, loaded=None
) -> tuple[str, bool]:
    """Save one incoming file. Returns (extra, waiting_for_account)."""
    if loaded is None:
        file_id, filename, mime, data = _download_attachment(message)
    else:
        file_id, filename, mime, data = loaded
    if is_statement_file(filename, mime, data):
        extra = _handle_statement(link, owner, chat_id, data, filename, caption)
        return extra or "", extra is None
    kind = classify_upload(filename)
    if kind in (
        Document.KIND_TAX_DECLARATION,
        Document.KIND_TAX_CERTIFICATE,
        "other_document",
    ):
        doc_kind = (
            Document.KIND_OTHER if kind == "other_document" else kind
        )
        doc = save_personal_document(owner, data, filename, doc_kind)
        return f"Saved {doc.get_kind_display()}: {doc.title}", False
    if link.pending_item_id and (message.get("photo") or []):
        item = PurchaseItem.objects.filter(
            id=link.pending_item_id, receipt__owner=owner
        ).first()
        link.pending_item_id = None
        link.save(update_fields=["pending_item_id", "updated_at"])
        if item:
            item.telegram_photo_file_id = file_id
            item.save(update_fields=["telegram_photo_file_id"])
            return (
                f"[Stored product photo on item #{item.id} {item.label} "
                f"(Telegram file_id only, not downloaded)]",
                False,
            )
        return "[No matching pending item; photo ignored]", False
    receipt = save_receipt(
        owner,
        data=data,
        filename=filename,
        mime_type=mime,
        caption=caption,
        telegram_file_id=file_id,
        extract=False,
    )
    if kind == "invoice":
        receipt.kind = Receipt.KIND_INVOICE
        receipt.document_date = receipt.document_date or pdf_creation_date(data)
        receipt.save(update_fields=["kind", "document_date"])
    return f"queued:{receipt.id}", False


_announced_parse: set[int] = set()


def _try_parse_one() -> None:
    receipt = pending_parse_qs().first()
    if receipt is None:
        return
    link = TelegramLink.objects.filter(owner=receipt.owner).order_by("id").first()
    if link and receipt.id not in _announced_parse:
        _announced_parse.add(receipt.id)
        _say(link.chat_id, f"Parsing {receipt.get_kind_display().lower()} #{receipt.id}…")
    try:
        ok = parse_queued_receipt(receipt)
    except Exception:  # noqa: BLE001
        log.exception("parse receipt %s", receipt.id)
        receipt.needs_parse = False
        receipt.save(update_fields=["needs_parse"])
        _announced_parse.discard(receipt.id)
        return
    if not ok:
        log.info("parse queue waiting, %s left", pending_parse_qs().count())
        return
    _announced_parse.discard(receipt.id)
    left = pending_parse_qs(receipt.owner).count()
    merchant = receipt.merchant or receipt.original_filename or f"#{receipt.id}"
    money = (
        f"{receipt.amount} {receipt.currency}"
        if receipt.amount is not None
        else "no total"
    )
    n_items = receipt.items.count()
    if receipt.transaction_id and receipt.transaction and receipt.transaction.upload_id:
        status = f"attached to tx #{receipt.transaction_id}"
    elif receipt.transaction_id:
        status = f"pending tx #{receipt.transaction_id}"
    else:
        status = "unmatched"
    line = f"{receipt.get_kind_display()} #{receipt.id}: {merchant} · {money}"
    if n_items:
        line += f" · {n_items} items"
    line += f" · {status}"
    if left:
        line += f" ({left} still queued)"
    link = TelegramLink.objects.filter(owner=receipt.owner).order_by("id").first()
    if link:
        _say(link.chat_id, line)


def _complete_turn(link, owner, chat_id, text: str, extra: str) -> None:
    if not text and not extra:
        return
    if extra.startswith("[Imported"):
        _note_history(link, text, extra)
        return
    history = list(link.messages or [])
    try:
        answer = agent.reply(owner, history, extra_user_text=_compose_user(text, extra))
    except (AiNotConfigured, AiUnavailable) as exc:
        note = extra or str(exc)
        if extra:
            note = f"{extra}\n\n{exc}"
        _say(chat_id, note, reply_markup={"remove_keyboard": True})
        return
    except Exception as exc:  # noqa: BLE001
        if extra:
            _say(chat_id, extra, reply_markup={"remove_keyboard": True})
            return
        _say(chat_id, f"AI is not available: {exc}")
        return
    history.append({"role": "user", "content": _compose_user(text, extra)})
    history.append({"role": "assistant", "content": answer})
    link.messages = _trim(history)
    link.save(update_fields=["messages", "updated_at"])
    _say(chat_id, answer, reply_markup={"remove_keyboard": True})


def _bank_accounts(owner):
    return list(Account.objects.filter(owner=owner, kind=Account.KIND_BANK))


def _account_keyboard(accounts) -> dict:
    return {
        "keyboard": [[{"text": a.name}] for a in accounts],
        "one_time_keyboard": True,
        "resize_keyboard": True,
    }


def _clear_pending_upload(link: TelegramLink) -> None:
    if link.pending_upload_id:
        Upload.objects.filter(
            id=link.pending_upload_id, imported_count=0, owner=link.owner
        ).delete()
    link.pending_upload_id = None


def _statement_clues(filename: str, meta: dict, row_count: int) -> str:
    bits = [filename, f"{row_count} rows"]
    if meta.get("currency"):
        bits.append(meta["currency"])
    if meta.get("account_iban"):
        bits.append(meta["account_iban"])
    if meta.get("account_name"):
        bits.append(meta["account_name"])
    if meta.get("account_holder"):
        bits.append(meta["account_holder"])
    return " · ".join(str(b) for b in bits if b)


def _ask_account(chat_id: int, accounts, clues: str) -> None:
    lines = [
        "This looks like a bank statement, but more than one account fits:",
        clues,
        "",
        *[f"{i}. {a.name}" for i, a in enumerate(accounts, 1)],
        "",
        "Which account is it?",
    ]
    tg.send_message(chat_id, "\n".join(lines), reply_markup=_account_keyboard(accounts))


def _commit_statement(link, owner, chat_id, upload: Upload, account: Account, result: dict) -> str:
    extra = ingest_statement(owner, upload, account, result)
    link.pending_upload_id = None
    link.save(update_fields=["pending_upload_id", "updated_at"])
    _say(chat_id, f"Imported {extra['imported']} new, {extra['skipped']} duplicates")
    if extra["receipts_enriched"]:
        _say(chat_id, f"Filled {extra['receipts_enriched']} pending receipt row(s)")
    if extra["receipts_attached"]:
        _say(chat_id, f"Attached {extra['receipts_attached']} receipt(s) to bank rows")
    if extra["rule_assignments"]:
        _say(chat_id, f"Applied {extra['rule_assignments']} rule tag(s)")
    return (
        f"[Imported statement #{upload.id} into {account.name}: "
        f"{extra['imported']} new, {extra['skipped']} duplicates, "
        f"{extra['receipts_enriched']} receipt rows filled, "
        f"{extra['receipts_attached']} receipts attached]"
    )


def _handle_statement(link, owner, chat_id, data: bytes, filename: str, caption: str):
    _clear_pending_upload(link)
    accounts = _bank_accounts(owner)
    if not accounts:
        _say(chat_id, "Create a bank account in the app first, then resend the statement.")
        return None
    _say(chat_id, "Parsing statement…")
    upload = Upload(owner=owner, original_filename=filename)
    upload.file.save(Path(filename).name or "statement.csv", ContentFile(data), save=True)
    try:
        result = parse_statement(upload.file.path, filename)
    except (UnsupportedFormat, ParseError) as exc:
        upload.delete()
        _say(chat_id, f"Couldn't parse that statement: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001
        upload.delete()
        _say(chat_id, f"Couldn't parse that statement: {exc}")
        return None

    meta = result["meta"]
    n_rows = len(result["rows"])
    _say(chat_id, f"Parsed {n_rows} rows")
    clues = _statement_clues(filename, meta, n_rows)
    hits = match_accounts(accounts, meta, filename)
    if caption:
        picked = pick_account(hits, caption) or pick_account(accounts, caption)
        if picked:
            hits = [picked]
    if len(hits) == 1:
        account = hits[0]
        _say(chat_id, f"Statement identified: {account.name}")
        unmatched = Receipt.objects.filter(owner=owner, amount__isnull=False).filter(
            Q(transaction__isnull=True) | Q(transaction__upload__isnull=True)
        ).count()
        if unmatched:
            _say(chat_id, f"Found {unmatched} unmatched receipt(s)")
        return _commit_statement(link, owner, chat_id, upload, account, result)
    label = (hits[0].bank or hits[0].name) if hits else "unknown bank"
    _say(chat_id, f"Statement identified: {label} ({len(hits or accounts)} accounts fit)")
    upload.account_name = meta.get("account_name", "")
    upload.account_iban = meta.get("account_iban", "")
    upload.account_holder = meta.get("account_holder", "")
    upload.currency = meta.get("currency", "EUR")
    upload.row_count = n_rows
    upload.save()
    link.pending_upload_id = upload.id
    link.save(update_fields=["pending_upload_id", "updated_at"])
    _ask_account(chat_id, hits or accounts, clues)
    return None


def _resolve_pending_statement(link, owner, chat_id, text: str):
    upload = Upload.objects.filter(id=link.pending_upload_id, owner=owner).first()
    if upload is None:
        link.pending_upload_id = None
        link.save(update_fields=["pending_upload_id", "updated_at"])
        return "[Pending statement expired; send the file again.]"
    accounts = _bank_accounts(owner)
    meta = {
        "account_iban": upload.account_iban,
        "account_name": upload.account_name,
        "account_holder": upload.account_holder,
        "currency": upload.currency,
    }
    hits = match_accounts(accounts, meta, upload.original_filename)
    account = pick_account(hits, text) or pick_account(accounts, text)
    if account is None:
        _ask_account(
            chat_id,
            hits or accounts,
            _statement_clues(upload.original_filename, meta, upload.row_count),
        )
        return None
    try:
        result = parse_statement(upload.file.path, upload.original_filename)
        _say(chat_id, f"Importing into {account.name}…")
        return _commit_statement(link, owner, chat_id, upload, account, result)
    except (UnsupportedFormat, ParseError) as exc:
        _clear_pending_upload(link)
        link.save(update_fields=["pending_upload_id", "updated_at"])
        tg.send_message(chat_id, f"Couldn't parse that statement: {exc}")
        return None


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
    items = list(receipt.items.prefetch_related("tags")[:25])
    if items:
        lines = [
            f"- #{it.id} {it.label}"
            + (f" [{it.name}]" if it.title else "")
            + (f" barcode={it.barcode}" if it.barcode else "")
            + (
                f" tags={','.join(t.name for t in it.tags.all())}"
                if it.tags.all()
                else ""
            )
            + f" x{it.quantity} = {it.amount or '?'} ({it.category or '?'})"
            for it in items
        ]
        parts.append("items:\n" + "\n".join(lines))
    else:
        parts.append("items: none parsed")
    if receipt.transaction_id:
        tx = receipt.transaction
        if tx.upload_id is None:
            parts.append(
                f"pending transaction #{tx.id} (in the ledger until a statement arrives)"
            )
        else:
            parts.append(f"auto-attached to transaction #{tx.id}")
        return "\n".join(parts)
    hits = list(
        candidate_transactions(
            receipt.owner,
            receipt.amount,
            receipt.document_date,
            receipt.currency,
            days=window_days(receipt),
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
