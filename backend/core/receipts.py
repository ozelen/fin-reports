"""Save receipts, extract fields via vision, and match them to bank transactions."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q
from django.db.models.functions import Abs
from django.utils import timezone

from .models import PurchaseItem, Receipt, Tag, Transaction, TransactionTag

log = logging.getLogger(__name__)

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
DATE_WINDOW_DAYS = 5
INVOICE_DATE_WINDOW_DAYS = 45
AMOUNT_TOLERANCE = Decimal("0.02")

EXTRACT_PROMPT = (
    "Extract fields from this receipt or vendor invoice. "
    "Return JSON only with keys: merchant (string), date (YYYY-MM-DD or null), "
    "time (HH:MM if printed, else empty), location (store address or city if printed, else empty), "
    "payment_method (cash, card, or empty), card_last4 (last 4 digits if a card was used, else empty), "
    "amount (number, the total paid, or null), currency (3-letter code, default EUR), "
    "kind (receipt, invoice, or other), notes (short string), "
    "items (array of line items). Each item: name (printed text), "
    "title (plain-language custom label; keep name as the printed OCR text), "
    "barcode (digits if visible, else empty string), quantity (number, default 1), "
    "unit_price (number or null), amount (line total, number or null), "
    "category (short lowercase tag for THIS line only: groceries, household, dining, fuel, "
    "electronics, pharmacy, clothing, transport, services, other — a grocery receipt may mix "
    "groceries and household). "
    "Skip tax/total/change rows. Prefer the printed line total for amount."
)


def amounts_match(a, b, tol=AMOUNT_TOLERANCE) -> bool:
    try:
        return abs(abs(Decimal(str(a))) - abs(Decimal(str(b)))) <= tol
    except (InvalidOperation, TypeError):
        return False


def date_close(a: dt.date | None, b: dt.date | None, days: int = DATE_WINDOW_DAYS) -> bool:
    if a is None or b is None:
        return False
    return abs((a - b).days) <= days


def window_days(receipt: Receipt | None) -> int:
    if receipt is not None and receipt.kind == Receipt.KIND_INVOICE:
        return INVOICE_DATE_WINDOW_DAYS
    return DATE_WINDOW_DAYS


def parse_amount(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def parse_date(value) -> dt.date | None:
    if not value:
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _norm(text: str) -> str:
    return "".join(ch.lower() for ch in (text or "") if ch.isalnum() or ch.isspace()).strip()


def merchant_overlap(merchant: str, tx: Transaction) -> bool:
    needle = _norm(merchant)
    if len(needle) < 3:
        return False
    hay = _norm(f"{tx.counterparty} {tx.concept}")
    if needle in hay or (hay and hay in needle):
        return True
    return any(tok in hay for tok in needle.split() if len(tok) >= 4)


def candidate_transactions(
    user,
    amount,
    document_date,
    currency: str = "",
    limit: int = 8,
    days: int = DATE_WINDOW_DAYS,
):
    """Bank txs that could belong to this receipt. Amount is required to match."""
    amount = parse_amount(amount)
    if amount is None:
        return Transaction.objects.none()
    qs = Transaction.objects.filter(owner=user, upload__isnull=False).select_related(
        "account"
    )
    if currency:
        qs = qs.filter(Q(currency__iexact=currency) | Q(currency=""))
    qs = qs.annotate(abs_amount=Abs("amount")).filter(
        abs_amount__gte=amount - AMOUNT_TOLERANCE,
        abs_amount__lte=amount + AMOUNT_TOLERANCE,
    )
    document_date = parse_date(document_date)
    if document_date:
        start = document_date - dt.timedelta(days=days)
        end = document_date + dt.timedelta(days=days)
        qs = qs.filter(operation_date__gte=start, operation_date__lte=end)
    else:
        qs = qs.filter(operation_date__gte=dt.date.today() - dt.timedelta(days=90))
    return qs.order_by("-operation_date", "-id")[:limit]


def unique_auto_match(
    user,
    amount,
    document_date,
    currency: str = "",
    merchant: str = "",
    days: int = DATE_WINDOW_DAYS,
):
    """Single obvious tx, or None. Date+amount unique, else amount+merchant unique."""
    if parse_amount(amount) is None:
        return None
    matches = list(
        candidate_transactions(
            user, amount, document_date, currency, limit=12, days=days
        )
    )
    if parse_date(document_date) is not None and len(matches) == 1:
        return matches[0]
    named = [tx for tx in matches if merchant_overlap(merchant, tx)]
    if len(named) == 1:
        return named[0]
    return None


def try_match_receipt(receipt: Receipt) -> Receipt:
    """Link a unique bank tx, or hang a placeholder until one lands."""
    tx = receipt.transaction
    if tx is not None and tx.upload_id:
        return receipt
    if receipt.amount is None:
        return receipt
    match = unique_auto_match(
        receipt.owner,
        receipt.amount,
        receipt.document_date,
        receipt.currency,
        merchant=receipt.merchant,
        days=window_days(receipt),
    )
    if match is not None:
        link_receipt(receipt, match)
    else:
        ensure_placeholder(receipt)
    return receipt


def match_pending_receipts(user) -> int:
    """Attach unmatched receipts that now have exactly one obvious bank tx."""
    attached = 0
    pending = Receipt.objects.filter(owner=user, amount__isnull=False).filter(
        Q(transaction__isnull=True) | Q(transaction__upload__isnull=True)
    )
    for receipt in pending.select_related("transaction"):
        try_match_receipt(receipt)
        receipt.refresh_from_db()
        if receipt.transaction_id and receipt.transaction.upload_id:
            attached += 1
    return attached


def attach_new_transactions(user, transactions) -> int:
    """After a statement import, attach unmatched receipts that now have exactly one hit."""
    attached = 0
    pending = Receipt.objects.filter(owner=user, amount__isnull=False).filter(
        Q(transaction__isnull=True) | Q(transaction__upload__isnull=True)
    )
    txs = list(transactions)
    if not txs:
        return 0
    for receipt in pending.select_related("transaction"):
        hits = []
        for tx in txs:
            if not amounts_match(receipt.amount, tx.amount):
                continue
            if receipt.currency and receipt.currency.upper() != (tx.currency or "").upper():
                continue
            if receipt.document_date:
                if not date_close(
                    receipt.document_date, tx.operation_date, window_days(receipt)
                ):
                    continue
            elif not merchant_overlap(receipt.merchant, tx):
                continue
            hits.append(tx)
        if len(hits) > 1:
            named = [tx for tx in hits if merchant_overlap(receipt.merchant, tx)]
            if len(named) == 1:
                hits = named
        if len(hits) == 1:
            link_receipt(receipt, hits[0])
            attached += 1
    return attached


def _drop_other_receipts(tx: Transaction, keep: Receipt) -> None:
    """One receipt photo per bank row — a resubmit replaces the previous parse."""
    Receipt.objects.filter(transaction=tx).exclude(pk=keep.pk).delete()


def _existing_purchase(receipt: Receipt) -> Receipt | None:
    if receipt.amount is None:
        return None
    qs = Receipt.objects.filter(
        owner=receipt.owner, amount=receipt.amount
    ).exclude(pk=receipt.pk)
    merch = (receipt.merchant or "").strip()
    if merch:
        qs = qs.filter(merchant__iexact=merch)
    if receipt.document_date:
        qs = qs.filter(
            Q(document_date=receipt.document_date) | Q(document_date__isnull=True)
        )
    return qs.filter(transaction__isnull=False).order_by("id").first()


def link_receipt(receipt: Receipt, tx: Transaction) -> None:
    pending = receipt.transaction
    if (
        pending is not None
        and pending.upload_id is None
        and pending.id != tx.id
        and tx.upload_id is not None
    ):
        tx = absorb_bank_into_pending(pending, tx)
    _drop_other_receipts(tx, keep=receipt)
    receipt.transaction = tx
    receipt.save(update_fields=["transaction"])
    receipt.items.update(transaction=tx)
    sync_tx_tags_from_items(tx)


def ensure_placeholder(receipt: Receipt) -> Transaction | None:
    """Show an unmatched receipt in the transactions list until a statement lands."""
    if receipt.transaction_id:
        return receipt.transaction
    if receipt.amount is None:
        return None
    twin = _existing_purchase(receipt)
    if twin is not None:
        tx = twin.transaction
        _drop_other_receipts(tx, keep=receipt)
        receipt.transaction = tx
        receipt.save(update_fields=["transaction"])
        receipt.items.update(transaction=tx)
        return tx
    date = receipt.document_date or dt.date.today()
    amount = -abs(receipt.amount)
    merchant = (receipt.merchant or "").strip()
    tx = Transaction.objects.create(
        owner=receipt.owner,
        upload=None,
        account=None,
        operation_date=date,
        concept=merchant or receipt.original_filename or "Receipt",
        counterparty=merchant,
        amount=amount,
        currency=receipt.currency or "EUR",
        dedupe_hash=hashlib.sha256(f"receipt:{receipt.id}".encode()).hexdigest(),
        metadata={"receipt_id": receipt.id},
    )
    receipt.transaction = tx
    receipt.save(update_fields=["transaction"])
    receipt.items.update(transaction=tx)
    return tx


def enrich_transaction(tx: Transaction, row: dict, upload, account) -> None:
    tx.upload = upload
    tx.account = account
    tx.operation_date = row["operation_date"]
    tx.value_date = row.get("value_date")
    tx.concept = row.get("concept") or tx.concept
    tx.counterparty = row.get("counterparty") or tx.counterparty
    tx.amount = row["amount"]
    tx.balance = row.get("balance")
    tx.currency = row.get("currency") or tx.currency
    tx.dedupe_hash = row["dedupe_hash"]
    meta = dict(tx.metadata or {})
    if row.get("metadata"):
        meta.update(row["metadata"])
    tx.metadata = meta
    tx.save()


def absorb_bank_into_pending(pending: Transaction, bank: Transaction) -> Transaction:
    """Keep the receipt's transaction id; copy bank fields; drop the duplicate row."""
    if pending.id == bank.id:
        return pending
    row = {
        "operation_date": bank.operation_date,
        "value_date": bank.value_date,
        "concept": bank.concept,
        "counterparty": bank.counterparty,
        "amount": bank.amount,
        "balance": bank.balance,
        "currency": bank.currency,
        "dedupe_hash": bank.dedupe_hash,
        "metadata": bank.metadata,
    }
    upload, account = bank.upload, bank.account
    bank.delete()
    enrich_transaction(pending, row, upload, account)
    return pending


def absorb_statement_rows(user, rows, upload, account) -> tuple[list, int]:
    """Fold matching statement rows into receipt placeholders. Return (to_create, enriched)."""
    pending = list(
        Transaction.objects.filter(owner=user, upload__isnull=True, account__isnull=True)
        .prefetch_related("receipts")
    )
    used: set[int] = set()
    to_create = []
    enriched = 0
    for row in rows:
        hit = _pick_pending(pending, used, row)
        if hit is None and account is not None:
            # Revolut PENDING → COMPLETED (same date/amount/concept, balance filled).
            hit = (
                Transaction.objects.filter(
                    owner=user,
                    account=account,
                    operation_date=row["operation_date"],
                    amount=row["amount"],
                    concept=row["concept"],
                    balance__isnull=True,
                )
                .exclude(id__in=used)
                .exclude(metadata__has_key="transfer")
                .first()
            )
        if hit is None:
            to_create.append(
                Transaction(owner=user, upload=upload, account=account, **row)
            )
            continue
        enrich_transaction(hit, row, upload, account)
        used.add(hit.id)
        enriched += 1
    return to_create, enriched


def ingest_statement(user, upload, account, result: dict) -> dict:
    """Commit a parsed statement onto `upload` for `account` (web + Telegram)."""
    from .rules import apply_rules

    meta = result["meta"]
    rows = result["rows"]
    account_ccy = (getattr(account, "currency", None) or "").upper()
    for row in rows:
        if row.pop("_currency_explicit", False):
            continue
        if account_ccy:
            row["currency"] = account_ccy
    upload.account = account
    upload.account_name = meta.get("account_name", "")
    upload.account_iban = meta.get("account_iban", "")
    upload.account_holder = meta.get("account_holder", "")
    upload.currency = meta.get("currency", "EUR")
    upload.row_count = len(rows)
    upload.parsed_at = timezone.now()
    objects, receipts_enriched = absorb_statement_rows(user, rows, upload, account)
    Transaction.objects.bulk_create(objects, ignore_conflicts=True)
    upload.imported_count = Transaction.objects.filter(upload=upload).count()
    upload.save()
    rule_result = apply_rules(user, Transaction.objects.filter(upload=upload))
    receipts_attached = attach_new_transactions(
        user, Transaction.objects.filter(upload=upload)
    )
    from .accounts import apply_statement_balance

    from .recurrences import attach_new_recurrences

    recurrences_attached = attach_new_recurrences(
        user, Transaction.objects.filter(upload=upload)
    )
    from .clients import attach_new_clients

    clients_attached = attach_new_clients(
        user, Transaction.objects.filter(upload=upload)
    )
    apply_statement_balance(account, rows)
    return {
        "imported": upload.imported_count,
        "skipped": max(upload.row_count - upload.imported_count, 0),
        "rule_assignments": rule_result["assignments_created"],
        "receipts_attached": receipts_attached,
        "receipts_enriched": receipts_enriched,
        "recurrences_attached": recurrences_attached,
        "clients_attached": clients_attached,
    }


def _pick_pending(pending, used, row):
    amount = row.get("amount")
    date = row.get("operation_date")
    currency = (row.get("currency") or "").upper()
    merchant = row.get("counterparty") or row.get("concept") or ""
    hits = []
    for tx in pending:
        if tx.id in used:
            continue
        if not amounts_match(tx.amount, amount):
            continue
        if currency and tx.currency and currency != (tx.currency or "").upper():
            continue
        rec = next(iter(tx.receipts.all()), None)
        if not date_close(tx.operation_date, date, window_days(rec)):
            continue
        hits.append(tx)
    if len(hits) == 1:
        return hits[0]
    named = [tx for tx in hits if merchant_overlap(merchant, tx)]
    if len(named) == 1:
        return named[0]
    return None


def set_item_tags(item: PurchaseItem, tags) -> None:
    item.tags.set(tags)
    if item.transaction_id:
        sync_tx_tags_from_items(item.transaction)


def name_tokens(name: str) -> list[str]:
    """Letter runs of 3+ chars. Drops 'M', '1000G', punctuation."""
    return [t.casefold() for t in re.findall(r"[^\W\d_]{3,}", name or "", flags=re.UNICODE)]


def filter_by_name_tokens(qs, keyword: str):
    """AND-match tokens so 'BURGER VACUN' hits 'BURGER M VACUN 1000G'."""
    tokens = name_tokens(keyword)
    if not tokens:
        needle = (keyword or "").strip()
        if not needle:
            return qs
        return qs.filter(
            Q(name__icontains=needle) | Q(title__icontains=needle) | Q(barcode__icontains=needle)
        )
    for token in tokens[:4]:
        qs = qs.filter(Q(name__icontains=token) | Q(title__icontains=token))
    return qs


def lookup_similar_items(user, name: str, *, exclude_id=None, limit: int = 8):
    """Past purchase lines with a similar printed name. Newest first."""
    qs = (
        PurchaseItem.objects.filter(receipt__owner=user)
        .select_related("receipt")
        .prefetch_related("tags")
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    hits = filter_by_name_tokens(qs, name)
    if not hits.exists():
        tokens = sorted(name_tokens(name), key=len, reverse=True)[:2]
        if len(tokens) >= 2:
            hits = qs
            for token in tokens:
                hits = hits.filter(name__icontains=token)
    return list(hits.order_by("-id")[:limit])


def apply_item_history(item: PurchaseItem) -> bool:
    """Copy title/tags/barcode from the latest similar line. Never touches name."""
    similar = lookup_similar_items(
        item.receipt.owner, item.name, exclude_id=item.id, limit=8
    )
    prior = next((s for s in similar if s.title or s.tags.exists()), None)
    if prior is None:
        return False
    fields = []
    if prior.title and not item.title:
        item.title = prior.title
        fields.append("title")
    if prior.barcode and not item.barcode:
        item.barcode = prior.barcode
        fields.append("barcode")
    if fields:
        item.save(update_fields=fields)
    prior_tags = list(prior.tags.all())
    if prior_tags and not item.tags.exists():
        item.tags.set(prior_tags)
    return True


def apply_receipt_history(receipt: Receipt) -> None:
    for item in receipt.items.all():
        apply_item_history(item)
    if receipt.transaction_id:
        sync_tx_tags_from_items(receipt.transaction)


def tag_items_from_categories(receipt: Receipt) -> None:
    for item in receipt.items.all():
        if item.tags.exists():
            continue
        if item.category:
            item.tags.add(*Tag.resolve(receipt.owner, [item.category]))
    if receipt.transaction_id:
        sync_tx_tags_from_items(receipt.transaction)


def sync_tx_tags_from_items(tx: Transaction) -> None:
    names = []
    for item in tx.purchase_items.prefetch_related("tags"):
        names.extend(t.name for t in item.tags.all())
        if item.category:
            names.append(item.category)
    for tag in Tag.resolve(tx.owner, names):
        TransactionTag.objects.get_or_create(
            transaction=tx,
            tag=tag,
            defaults={"source": TransactionTag.SOURCE_AI},
        )


def extract_from_image(image_bytes: bytes, mime: str, caption: str = "") -> dict:
    """Vision pass on a photo or PDF. Returns {} if Gemini is not configured."""
    from .ai import AiNotConfigured, AiUnavailable, get_client, user_message_for_ai_error

    parts: list[tuple[str, bytes]] = []
    if _looks_like_pdf(image_bytes, mime):
        parts = [("image/png", png) for png in _pdf_page_pngs(image_bytes)]
    else:
        if mime not in IMAGE_MIMES:
            if image_bytes[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
        if mime in IMAGE_MIMES:
            parts = [(mime, image_bytes)]
    if not parts:
        return {}
    try:
        client = get_client()
    except AiNotConfigured:
        return {}

    import base64

    user_text = EXTRACT_PROMPT
    if caption:
        user_text += f" User caption: {caption}"
    content = [{"type": "text", "text": user_text}]
    for part_mime, blob in parts:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{part_mime};base64,{base64.b64encode(blob).decode('ascii')}"
                },
            }
        )
    try:
        response = client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:  # noqa: BLE001 - turn provider errors into a chat reply
        raise AiUnavailable(user_message_for_ai_error(exc)) from exc
    try:
        return json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {}


def apply_extracted(receipt: Receipt, extracted: dict, caption: str = "") -> None:
    if not extracted:
        if caption and not receipt.notes:
            receipt.notes = caption
        return
    receipt.extracted = extracted
    merchant = (extracted.get("merchant") or "").strip()
    if merchant:
        receipt.merchant = merchant[:255]
    amount = parse_amount(extracted.get("amount"))
    if amount is not None:
        receipt.amount = amount
    currency = (extracted.get("currency") or "").strip()
    if currency:
        receipt.currency = currency[:8]
    date = parse_date(extracted.get("date"))
    if date:
        receipt.document_date = date
    kind = extracted.get("kind") or ""
    if receipt.kind != Receipt.KIND_INVOICE and kind in {
        Receipt.KIND_RECEIPT,
        Receipt.KIND_INVOICE,
        Receipt.KIND_OTHER,
    }:
        receipt.kind = kind
    notes = extracted.get("notes") or ""
    if caption:
        notes = f"{caption}\n{notes}".strip()
    if notes:
        receipt.notes = notes


def line_from_raw(raw: dict) -> dict | None:
    name = (raw.get("name") or "").strip()[:255]
    if not name:
        return None
    qty = parse_amount(raw.get("quantity")) or Decimal("1")
    unit = parse_amount(raw.get("unit_price"))
    amount = parse_amount(raw.get("amount"))
    if amount is None and unit is not None:
        amount = (qty * unit).quantize(Decimal("0.01"))
    return {
        "name": name,
        "title": (raw.get("title") or "").strip()[:255],
        "barcode": "".join(ch for ch in str(raw.get("barcode") or "") if ch.isalnum())[:64],
        "quantity": qty,
        "unit_price": unit,
        "amount": amount,
        "category": (raw.get("category") or "").strip().lower()[:80],
    }


def replace_items(receipt: Receipt, items_raw) -> int:
    receipt.items.all().delete()
    rows = []
    for raw in items_raw or []:
        if not isinstance(raw, dict):
            continue
        parsed = line_from_raw(raw)
        if parsed:
            rows.append(
                PurchaseItem(
                    receipt=receipt,
                    transaction=receipt.transaction,
                    **parsed,
                )
            )
    if rows:
        PurchaseItem.objects.bulk_create(rows)
    return len(rows)


def save_receipt(
    user,
    *,
    data: bytes,
    filename: str,
    mime_type: str = "",
    caption: str = "",
    source: str = Receipt.SOURCE_TELEGRAM,
    telegram_file_id: str = "",
    extract: bool = True,
) -> Receipt:
    mime_type = mime_type or _guess_mime(filename)
    receipt = Receipt(
        owner=user,
        original_filename=filename,
        mime_type=mime_type,
        source=source,
        telegram_file_id=telegram_file_id,
        notes=caption,
    )
    receipt.save()
    if data:
        receipt.file.save(
            Path(filename).name or "receipt.bin", ContentFile(data), save=True
        )
    if not extract and _can_parse(data, mime_type):
        receipt.needs_parse = True
        receipt.save(update_fields=["needs_parse"])
        return receipt
    if extract:
        from .ai import AiUnavailable

        try:
            extracted = extract_from_image(data, mime_type, caption)
        except AiUnavailable:
            receipt.needs_parse = True
            receipt.save(update_fields=["needs_parse"])
            return receipt
    else:
        extracted = {}
    return _finish_parse(receipt, extracted, caption)


def pending_parse_qs(user=None):
    qs = Receipt.objects.filter(needs_parse=True)
    if user is not None:
        qs = qs.filter(owner=user)
    return qs.order_by("id")


def parse_queued_receipt(receipt: Receipt) -> bool:
    """Run vision on a queued receipt. False means rate-limited — try again later."""
    from . import telegram as tg
    from .ai import AiUnavailable

    data = b""
    mime = receipt.mime_type
    if receipt.file:
        with receipt.file.open("rb") as fh:
            data = fh.read()
    if not data and receipt.telegram_file_id:
        data, _, dl_mime = tg.download_file(receipt.telegram_file_id)
        mime = mime or dl_mime
        if data and not receipt.file:
            receipt.file.save(
                receipt.original_filename or "receipt.bin",
                ContentFile(data),
                save=True,
            )
    if not _can_parse(data, mime):
        receipt.needs_parse = False
        receipt.save(update_fields=["needs_parse"])
        return True
    try:
        extracted = extract_from_image(data, mime, receipt.notes)
    except AiUnavailable:
        return False
    _finish_parse(receipt, extracted, receipt.notes)
    return True


def _looks_like_pdf(data: bytes, mime: str) -> bool:
    mime = (mime or "").lower()
    if mime in {"application/pdf", "application/x-pdf"} or mime.endswith("/pdf"):
        return True
    return (data or b"")[:5] == b"%PDF-"


def _can_parse(data: bytes, mime: str) -> bool:
    return _looks_like_image(data, mime) or _looks_like_pdf(data, mime)


def _pdf_page_pngs(data: bytes, max_pages: int = 3) -> list[bytes]:
    """Rasterize invoice/receipt PDF pages for the same vision path as photos."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.pdf"
        src.write_bytes(data)
        prefix = Path(tmp) / "page"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    "150",
                    "-f",
                    "1",
                    "-l",
                    str(max_pages),
                    str(src),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            log.warning("pdftoppm failed: %s", exc)
            return []
        return [p.read_bytes() for p in sorted(Path(tmp).glob("page*.png"))]


def _looks_like_image(data: bytes, mime: str) -> bool:
    mime = mime or ""
    if mime in IMAGE_MIMES:
        return True
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    return False


def _finish_parse(receipt: Receipt, extracted: dict, caption: str = "") -> Receipt:
    apply_extracted(receipt, extracted, caption)
    receipt.needs_parse = False
    receipt.save()
    try_match_receipt(receipt)
    replace_items(receipt, extracted.get("items") if extracted else None)
    apply_receipt_history(receipt)
    tag_items_from_categories(receipt)
    fill_missing_titles(receipt)
    return receipt


def reparse_receipt(receipt: Receipt) -> Receipt:
    """Re-run vision on the stored file / Telegram file and replace line items."""
    from .ai import AiUnavailable

    receipt.needs_parse = True
    receipt.save(update_fields=["needs_parse"])
    if parse_queued_receipt(receipt):
        return receipt
    raise AiUnavailable("Gemini is rate-limiting right now. Receipt is queued.")


def fill_missing_titles(receipt: Receipt) -> int:
    """Text pass: cryptic OCR names -> human titles. Barcodes stay as parsed."""
    items = [it for it in receipt.items.all() if not it.title]
    if not items:
        return 0
    from .ai import AiNotConfigured, get_client

    try:
        client = get_client()
    except AiNotConfigured:
        return 0
    payload = [
        {"name": it.name, "amount": str(it.amount) if it.amount is not None else None}
        for it in items
    ]
    try:
        response = client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Label these supermarket receipt lines. Return JSON "
                        '{"items": [{"name": str, "title": str}]}. '
                        "title is a short plain-language product "
                        "(e.g. BURGER M VACUN 1000G -> Beef mince 1kg). "
                        "Keep every name. One object per input line.\n"
                        + json.dumps(payload, ensure_ascii=False)
                    ),
                }
            ],
        )
        data = json.loads(response.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001 - titles are optional
        import logging

        logging.getLogger(__name__).warning("fill_missing_titles: %s", exc)
        return 0
    by_name = {}
    for raw in data.get("items") or []:
        if isinstance(raw, dict) and raw.get("name") and raw.get("title"):
            by_name.setdefault(str(raw["name"]).strip(), str(raw["title"]).strip()[:255])
    updated = 0
    for it in items:
        title = by_name.get(it.name)
        if title:
            it.title = title
            it.save(update_fields=["title"])
            updated += 1
    return updated


def _guess_mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".pdf": "application/pdf",
    }.get(ext, "")


def _self_check():
    assert amounts_match("10.00", "-10")
    assert amounts_match(Decimal("23.45"), Decimal("-23.45"))
    assert not amounts_match("10.00", "10.50")
    assert date_close(dt.date(2026, 8, 10), dt.date(2026, 8, 12))
    assert not date_close(dt.date(2026, 8, 10), dt.date(2026, 8, 20))
    assert not date_close(dt.date(2026, 8, 10), None)
    assert parse_amount("12,34") is None
    assert parse_amount("12.34") == Decimal("12.34")
    line = line_from_raw(
        {"name": "Milk", "quantity": 2, "unit_price": "1.20", "category": "Groceries"}
    )
    assert line["amount"] == Decimal("2.40")
    assert line["category"] == "groceries"
    assert line["title"] == ""
    line2 = line_from_raw(
        {"name": "BURGER M VACUN 1000G", "title": "Beef mince 1kg", "barcode": "841123"}
    )
    assert line2["title"] == "Beef mince 1kg"
    assert line2["barcode"] == "841123"
    assert name_tokens("BURGER M VACUN 1000G") == ["burger", "vacun"]
    assert name_tokens("SANDIA BAJA SEMILLAS") == ["sandia", "baja", "semillas"]
    assert line_from_raw({"name": "  "}) is None
    print("ok")


if __name__ == "__main__":
    _self_check()
