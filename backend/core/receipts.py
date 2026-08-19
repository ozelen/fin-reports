"""Save receipts, extract fields via vision, and match them to bank transactions."""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Q
from django.db.models.functions import Abs

from .models import PurchaseItem, Receipt, Transaction

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
DATE_WINDOW_DAYS = 5
AMOUNT_TOLERANCE = Decimal("0.02")

EXTRACT_PROMPT = (
    "Extract fields from this receipt or vendor invoice. "
    "Return JSON only with keys: merchant (string), date (YYYY-MM-DD or null), "
    "amount (number, the total paid, or null), currency (3-letter code, default EUR), "
    "kind (receipt, invoice, or other), notes (short string), "
    "items (array of line items). Each item: name (string), quantity (number, default 1), "
    "unit_price (number or null), amount (line total, number or null), "
    "category (short lowercase spend category: groceries, dining, fuel, household, "
    "electronics, pharmacy, clothing, transport, services, other). "
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


def candidate_transactions(user, amount, document_date, currency: str = "", limit: int = 8):
    """Bank txs that could belong to this receipt. Amount is required to match."""
    amount = parse_amount(amount)
    if amount is None:
        return Transaction.objects.none()
    qs = Transaction.objects.filter(owner=user).select_related("account")
    if currency:
        qs = qs.filter(Q(currency__iexact=currency) | Q(currency=""))
    qs = qs.annotate(abs_amount=Abs("amount")).filter(
        abs_amount__gte=amount - AMOUNT_TOLERANCE,
        abs_amount__lte=amount + AMOUNT_TOLERANCE,
    )
    document_date = parse_date(document_date)
    if document_date:
        start = document_date - dt.timedelta(days=DATE_WINDOW_DAYS)
        end = document_date + dt.timedelta(days=DATE_WINDOW_DAYS)
        qs = qs.filter(operation_date__gte=start, operation_date__lte=end)
    else:
        qs = qs.filter(operation_date__gte=dt.date.today() - dt.timedelta(days=90))
    return qs.order_by("-operation_date", "-id")[:limit]


def unique_auto_match(user, amount, document_date, currency: str = "", merchant: str = ""):
    """Single obvious tx, or None. Date+amount unique, else amount+merchant unique."""
    if parse_amount(amount) is None:
        return None
    matches = list(candidate_transactions(user, amount, document_date, currency, limit=12))
    if parse_date(document_date) is not None and len(matches) == 1:
        return matches[0]
    named = [tx for tx in matches if merchant_overlap(merchant, tx)]
    if len(named) == 1:
        return named[0]
    return None


def attach_new_transactions(user, transactions) -> int:
    """After a statement import, attach unmatched receipts that now have exactly one hit."""
    attached = 0
    pending = Receipt.objects.filter(
        owner=user, transaction__isnull=True, amount__isnull=False
    )
    txs = list(transactions)
    if not txs:
        return 0
    for receipt in pending:
        hits = []
        for tx in txs:
            if not amounts_match(receipt.amount, tx.amount):
                continue
            if receipt.currency and receipt.currency.upper() != (tx.currency or "").upper():
                continue
            if receipt.document_date:
                if not date_close(receipt.document_date, tx.operation_date):
                    continue
            elif not merchant_overlap(receipt.merchant, tx):
                continue
            hits.append(tx)
        if len(hits) > 1:
            named = [tx for tx in hits if merchant_overlap(receipt.merchant, tx)]
            if len(named) == 1:
                hits = named
        if len(hits) == 1:
            receipt.transaction = hits[0]
            receipt.save(update_fields=["transaction"])
            attached += 1
    return attached


def extract_from_image(image_bytes: bytes, mime: str, caption: str = "") -> dict:
    """Vision pass. Returns {} if Gemini is not configured or the file is not an image."""
    from .ai import AiNotConfigured, AiUnavailable, get_client, user_message_for_ai_error

    if mime not in IMAGE_MIMES:
        return {}
    try:
        client = get_client()
    except AiNotConfigured:
        return {}

    import base64

    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    user_text = EXTRACT_PROMPT
    if caption:
        user_text += f" User caption: {caption}"
    try:
        response = client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
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
    receipt.merchant = (extracted.get("merchant") or "")[:255]
    receipt.amount = parse_amount(extracted.get("amount"))
    receipt.currency = (extracted.get("currency") or receipt.currency or "EUR")[:8]
    receipt.document_date = parse_date(extracted.get("date"))
    kind = extracted.get("kind") or ""
    if kind in {Receipt.KIND_RECEIPT, Receipt.KIND_INVOICE, Receipt.KIND_OTHER}:
        receipt.kind = kind
    notes = extracted.get("notes") or ""
    if caption:
        notes = f"{caption}\n{notes}".strip()
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
            rows.append(PurchaseItem(receipt=receipt, **parsed))
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
    receipt.file.save(filename, ContentFile(data), save=False)
    receipt.save()
    extracted = {}
    if extract:
        from .ai import AiUnavailable

        try:
            extracted = extract_from_image(data, mime_type, caption)
        except AiUnavailable as exc:
            raise AiUnavailable(
                f"Saved as receipt #{receipt.id} (unparsed). {exc}"
            ) from exc
    apply_extracted(receipt, extracted, caption)
    match = unique_auto_match(
        user,
        receipt.amount,
        receipt.document_date,
        receipt.currency,
        merchant=receipt.merchant,
    )
    if match is not None:
        receipt.transaction = match
    receipt.save()
    replace_items(receipt, extracted.get("items") if extracted else None)
    return receipt


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
    assert line_from_raw({"name": "  "}) is None
    print("ok")


if __name__ == "__main__":
    _self_check()
