"""Finance agent: Gemini tool-calling over the owner's books."""
from __future__ import annotations

import datetime as dt
import json

from django.conf import settings
from django.db.models import Count, Q, Sum

from .criteria import apply_criteria
from .fx import exclude_ignored, summarize_eur
from .models import Account, Invoice, PurchaseItem, Receipt, Tag, Transaction, TransactionTag
from .receipts import (
    candidate_transactions,
    filter_by_name_tokens,
    link_receipt,
    lookup_similar_items,
    name_tokens,
    parse_amount,
    reparse_receipt,
    set_item_tags,
    window_days,
)

SYSTEM_PROMPT = """You are a personal finance assistant for Income Share, a bookkeeping app.
You help the owner understand bank transactions, income vs expenses, issued invoices,
incoming receipts, and purchase line-items parsed from those receipts.

Rules:
- Be concise. Totals in EUR use NBU daily rates when the owner has mixed or non-EUR currencies; always also report the native per-currency breakdown.
- Never invent transaction, receipt, or invoice ids. Only use ids returned by tools.
- Receipts often arrive before the bank statement. If there is no bank match,
  a pending transaction is created automatically and shows up in the ledger.
  Do not tell the user it is missing. When a statement is imported later, that
  pending row is enriched (same id, tags and items kept).
- After saving a receipt, always try suggest_matches / attach_receipt.
- If a receipt was parsed before titles/barcodes existed, call reparse_receipt.
- Line items have `name` (printed OCR — never change it; it is how products are
  found and classified) and `title` (custom human label, e.g. 'beef mince 1kg'
  for BURGER M VACUN 1000G). Set title with update_item.
- Before guessing a title or tags for an item or transaction, call
  lookup_similar_items (and search_transactions for the merchant). If a past
  line matches (BURGER * VACUN *G), reuse its title and tags. Only guess when
  lookup returns nothing, and then ask before creating a new tag.
- Tag each item (food vs household chemicals on the same check). Prefer existing
  tags from list_tags; create a tag only when none fit. Then tag the parent
  transaction with the union of item tags (tag_transaction).
- To attach a product photo to an item, call await_item_photo then tell the user to send it.
- Today is {today}.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_transactions",
            "description": "Search bank transactions by text, dates, amount, kind, account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                    "kind": {"type": "string", "enum": ["income", "expense", "all"]},
                    "min_amount": {"type": "number"},
                    "max_amount": {"type": "number"},
                    "account_id": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_transactions",
            "description": "Income, expense, net, and count for a period.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "quarter": {
                        "type": "string",
                        "description": "this, prev, Q1, Q2, Q3, Q4",
                    },
                    "year": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["income", "expense", "all"]},
                    "account_id": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_receipts",
            "description": "List saved receipts/invoices, optionally only unattached ones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unattached_only": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_matches",
            "description": "Find bank transactions that could match a receipt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "receipt_id": {"type": "integer"},
                },
                "required": ["receipt_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "attach_receipt",
            "description": "Link a receipt and its line items to a bank transaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "receipt_id": {"type": "integer"},
                    "transaction_id": {"type": "integer"},
                },
                "required": ["receipt_id", "transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reparse_receipt",
            "description": "Re-read a Telegram receipt image for titles, barcodes, and items.",
            "parameters": {
                "type": "object",
                "properties": {"receipt_id": {"type": "integer"}},
                "required": ["receipt_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_invoices",
            "description": "List invoices issued by the owner.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["draft", "issued", "all"]},
                    "year": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_purchases",
            "description": "Search purchase lines. Keyword is fuzzy (BURGER VACUN matches BURGER M VACUN 1000G).",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "category": {"type": "string"},
                    "merchant": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_similar_items",
            "description": "Fuzzy-search past purchase lines by printed name. Call before guessing title or tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Printed OCR name, e.g. BURGER M VACUN 1000G"},
                    "limit": {"type": "integer"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_purchases",
            "description": "Spend totals grouped by purchase category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "category": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_item",
            "description": "Set custom title, barcode, tags. Never changes the printed name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer"},
                    "title": {"type": "string", "description": "Custom label. Does not replace printed name."},
                    "barcode": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tag names for this line (food, household, ...).",
                    },
                    "category": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "amount": {"type": "number"},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "await_item_photo",
            "description": "Next photo the user sends is stored as this item's product picture.",
            "parameters": {
                "type": "object",
                "properties": {"item_id": {"type": "integer"}},
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tags",
            "description": "List the owner's tags (use these names before creating new ones).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tag_item",
            "description": "Set tags on a purchase line. Does not change the printed name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["item_id", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tag_transaction",
            "description": "Add tags to a bank/pending transaction (does not remove existing).",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["transaction_id", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_accounts",
            "description": "List accounts (bank, cash wallets, debts) with balances.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _tx_row(tx: Transaction) -> dict:
    return {
        "id": tx.id,
        "date": tx.operation_date.isoformat(),
        "amount": str(tx.amount),
        "currency": tx.currency,
        "kind": tx.kind,
        "pending": tx.pending,
        "counterparty": tx.counterparty,
        "concept": (tx.concept or "")[:180],
        "account": tx.account.name if tx.account_id else None,
        "tags": [t.name for t in tx.tags.all()],
    }


def _item_row(it: PurchaseItem) -> dict:
    return {
        "id": it.id,
        "name": it.name,
        "title": it.title,
        "label": it.label,
        "barcode": it.barcode,
        "qty": str(it.quantity),
        "amount": str(it.amount) if it.amount is not None else None,
        "category": it.category,
        "tags": [t.name for t in it.tags.all()],
        "receipt_id": it.receipt_id,
        "transaction_id": it.transaction_id,
        "has_photo": bool(it.telegram_photo_file_id),
        "merchant": it.receipt.merchant if it.receipt_id else None,
        "currency": it.receipt.currency if it.receipt_id else None,
        "date": (
            it.receipt.document_date.isoformat()
            if it.receipt_id and it.receipt.document_date
            else None
        ),
    }


def _receipt_row(r: Receipt) -> dict:
    items = [_item_row(it) for it in r.items.all()[:40]]
    return {
        "id": r.id,
        "kind": r.kind,
        "merchant": r.merchant,
        "amount": str(r.amount) if r.amount is not None else None,
        "currency": r.currency,
        "date": r.document_date.isoformat() if r.document_date else None,
        "transaction_id": r.transaction_id,
        "telegram_file_id": r.telegram_file_id,
        "filename": r.original_filename,
        "notes": (r.notes or "")[:200],
        "items": items,
    }


def _run_tool(user, name: str, args: dict) -> dict:
    limit = min(int(args.get("limit") or 15), 40)

    if name == "search_transactions":
        criteria = {
            "date_from": args.get("date_from"),
            "date_to": args.get("date_to"),
            "kind": args.get("kind") if args.get("kind") not in (None, "all") else None,
            "min_amount": args.get("min_amount"),
            "max_amount": args.get("max_amount"),
            "account": args.get("account_id"),
        }
        qs = apply_criteria(
            Transaction.objects.filter(owner=user).select_related("account").prefetch_related("tags"),
            criteria,
        )
        kw = (args.get("keyword") or "").strip()
        if kw:
            tokens = name_tokens(kw) or [kw]
            for token in tokens[:4]:
                qs = qs.filter(Q(concept__icontains=token) | Q(counterparty__icontains=token))
        rows = [_tx_row(tx) for tx in qs.order_by("-operation_date", "-id")[:limit]]
        return {"count": qs.count(), "transactions": rows}

    if name == "summarize_transactions":
        criteria = {
            "date_from": args.get("date_from"),
            "date_to": args.get("date_to"),
            "quarter": args.get("quarter"),
            "year": args.get("year"),
            "kind": args.get("kind") if args.get("kind") not in (None, "all") else None,
            "account": args.get("account_id"),
        }
        qs = exclude_ignored(apply_criteria(Transaction.objects.filter(owner=user), criteria))
        summary = summarize_eur(qs)
        native = [
            {
                "currency": row["currency"] or "EUR",
                "count": row["count"] or 0,
                "income": str(row["income"] or 0),
                "expense": str(row["expense"] or 0),
                "net": str(row["net"] or 0),
            }
            for row in summary["currencies"]
        ]
        return {
            "currency": summary["currency"],
            "converted": summary["converted"],
            "count": summary["count"],
            "income": None if summary["income"] is None else str(summary["income"]),
            "expense": None if summary["expense"] is None else str(summary["expense"]),
            "net": None if summary["net"] is None else str(summary["net"]),
            "currencies": native,
        }

    if name == "list_receipts":
        qs = Receipt.objects.filter(owner=user).prefetch_related("items__tags")
        if args.get("unattached_only"):
            qs = qs.filter(transaction__isnull=True)
        rows = [_receipt_row(r) for r in qs.order_by("-created_at")[:limit]]
        return {"receipts": rows}

    if name == "search_purchases":
        qs = PurchaseItem.objects.filter(receipt__owner=user).select_related("receipt").prefetch_related("tags")
        kw = (args.get("keyword") or "").strip()
        if kw:
            named = filter_by_name_tokens(qs, kw)
            tagged = qs.filter(
                Q(tags__name__icontains=kw)
                | Q(category__icontains=kw)
                | Q(barcode__icontains=kw)
            )
            qs = (named | tagged).distinct()
        if args.get("category"):
            qs = qs.filter(category__iexact=args["category"])
        if args.get("merchant"):
            qs = qs.filter(receipt__merchant__icontains=args["merchant"])
        if args.get("date_from"):
            qs = qs.filter(receipt__document_date__gte=args["date_from"])
        if args.get("date_to"):
            qs = qs.filter(receipt__document_date__lte=args["date_to"])
        rows = [_item_row(it) for it in qs.select_related("receipt").order_by("-receipt__document_date", "-id")[:limit]]
        return {"items": rows}

    if name == "lookup_similar_items":
        printed = (args.get("name") or "").strip()
        if not printed:
            return {"error": "name required"}
        hits = lookup_similar_items(
            user, printed, limit=min(int(args.get("limit") or 8), 20)
        )
        suggested_title = next((h.title for h in hits if h.title), None)
        suggested_tags = []
        seen = set()
        for h in hits:
            for tag in h.tags.all():
                key = tag.name.casefold()
                if key not in seen:
                    seen.add(key)
                    suggested_tags.append(tag.name)
        return {
            "query": printed,
            "tokens": name_tokens(printed),
            "matches": [_item_row(h) for h in hits],
            "suggested_title": suggested_title,
            "suggested_tags": suggested_tags,
        }

    if name == "update_item":
        item = (
            PurchaseItem.objects.filter(id=args["item_id"], receipt__owner=user)
            .select_related("receipt")
            .first()
        )
        if item is None:
            return {"error": "item not found"}
        if "title" in args and args["title"] is not None:
            item.title = str(args["title"]).strip()[:255]
        if "barcode" in args and args["barcode"] is not None:
            item.barcode = "".join(ch for ch in str(args["barcode"]) if ch.isalnum())[:64]
        if "category" in args and args["category"] is not None:
            item.category = str(args["category"]).strip().lower()[:80]
        if "quantity" in args and args["quantity"] is not None:
            item.quantity = parse_amount(args["quantity"]) or item.quantity
        if "unit_price" in args and args["unit_price"] is not None:
            item.unit_price = parse_amount(args["unit_price"])
        if "amount" in args and args["amount"] is not None:
            item.amount = parse_amount(args["amount"])
        item.save()
        if "tags" in args and args["tags"] is not None:
            set_item_tags(item, Tag.resolve(user, args["tags"]))
        elif "category" in args and item.category:
            set_item_tags(item, Tag.resolve(user, [item.category]))
        item = PurchaseItem.objects.prefetch_related("tags").get(pk=item.pk)
        return {"ok": True, "item": _item_row(item)}

    if name == "await_item_photo":
        item = PurchaseItem.objects.filter(
            id=args["item_id"], receipt__owner=user
        ).first()
        if item is None:
            return {"error": "item not found"}
        from .models import TelegramLink

        TelegramLink.objects.filter(owner=user).update(pending_item_id=item.id)
        return {
            "ok": True,
            "item": _item_row(item),
            "hint": "Send a photo next; it will be stored as this item's picture (Telegram file_id only).",
        }

    if name == "summarize_purchases":
        qs = PurchaseItem.objects.filter(receipt__owner=user)
        if args.get("date_from"):
            qs = qs.filter(receipt__document_date__gte=args["date_from"])
        if args.get("date_to"):
            qs = qs.filter(receipt__document_date__lte=args["date_to"])
        if args.get("category"):
            qs = qs.filter(category__iexact=args["category"])
        rows = list(
            qs.values("category", "receipt__currency")
            .annotate(count=Count("id"), total=Sum("amount"))
            .order_by("receipt__currency", "category")
        )
        return {
            "by_category": [
                {
                    "category": row["category"] or "uncategorized",
                    "currency": row["receipt__currency"] or "EUR",
                    "count": row["count"],
                    "total": str(row["total"] or 0),
                }
                for row in rows
            ]
        }

    if name == "suggest_matches":
        receipt = (
            Receipt.objects.filter(owner=user, id=args["receipt_id"])
            .prefetch_related("items")
            .first()
        )
        if receipt is None:
            return {"error": "receipt not found"}
        hits = candidate_transactions(
            user,
            receipt.amount,
            receipt.document_date,
            receipt.currency,
            days=window_days(receipt),
        )
        return {"receipt": _receipt_row(receipt), "candidates": [_tx_row(tx) for tx in hits]}

    if name == "attach_receipt":
        receipt = (
            Receipt.objects.filter(owner=user, id=args["receipt_id"])
            .prefetch_related("items")
            .first()
        )
        tx = Transaction.objects.filter(owner=user, id=args["transaction_id"]).first()
        if receipt is None:
            return {"error": "receipt not found"}
        if tx is None:
            return {"error": "transaction not found"}
        link_receipt(receipt, tx)
        receipt.refresh_from_db()
        return {"ok": True, "receipt": _receipt_row(receipt), "transaction": _tx_row(tx)}

    if name == "reparse_receipt":
        receipt = (
            Receipt.objects.filter(owner=user, id=args["receipt_id"])
            .prefetch_related("items")
            .first()
        )
        if receipt is None:
            return {"error": "receipt not found"}
        try:
            receipt = reparse_receipt(receipt)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        return {"ok": True, "receipt": _receipt_row(receipt)}

    if name == "list_invoices":
        qs = Invoice.objects.filter(owner=user)
        status = args.get("status") or "all"
        if status in ("draft", "issued"):
            qs = qs.filter(status=status)
        if args.get("year"):
            qs = qs.filter(service_year=args["year"])
        rows = [
            {
                "id": inv.id,
                "number": inv.number,
                "status": inv.status,
                "client": inv.client_name or (inv.client.name if inv.client_id else ""),
                "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
                "total": str(inv.total_amount),
                "currency": inv.currency,
            }
            for inv in qs.order_by("-issue_date", "-id")[:limit]
        ]
        return {"invoices": rows}

    if name == "list_tags":
        rows = list(
            Tag.objects.filter(owner=user).values("id", "name", "description", "color")
        )
        return {"tags": rows}

    if name == "tag_item":
        item = PurchaseItem.objects.filter(
            id=args["item_id"], receipt__owner=user
        ).first()
        if item is None:
            return {"error": "item not found"}
        set_item_tags(item, Tag.resolve(user, args.get("tags") or []))
        item = PurchaseItem.objects.prefetch_related("tags").get(pk=item.pk)
        return {"ok": True, "item": _item_row(item)}

    if name == "tag_transaction":
        tx = Transaction.objects.filter(owner=user, id=args["transaction_id"]).first()
        if tx is None:
            return {"error": "transaction not found"}
        for tag in Tag.resolve(user, args.get("tags") or []):
            TransactionTag.objects.get_or_create(
                transaction=tx,
                tag=tag,
                defaults={"source": TransactionTag.SOURCE_AI},
            )
        tx = Transaction.objects.prefetch_related("tags").get(pk=tx.pk)
        return {"ok": True, "transaction": _tx_row(tx)}

    if name == "list_accounts":
        rows = list(
            Account.objects.filter(owner=user).values(
                "id",
                "name",
                "kind",
                "bank",
                "currency",
                "group",
                "iban",
                "balance",
                "credit_limit",
            )
        )
        return {"accounts": rows}

    return {"error": f"unknown tool {name}"}


def _thought_extra(tc) -> dict | None:
    extra = getattr(tc, "extra_content", None)
    if isinstance(extra, dict) and extra:
        return extra
    dumped = tc.model_dump(exclude_none=True) if hasattr(tc, "model_dump") else {}
    if dumped.get("extra_content"):
        return dumped["extra_content"]
    more = getattr(tc, "model_extra", None) or {}
    if more.get("extra_content"):
        return more["extra_content"]
    sig = dumped.get("thought_signature") or more.get("thought_signature")
    if sig:
        return {"google": {"thought_signature": sig}}
    return None


def _assistant_tool_message(msg) -> dict:
    """Echo tool_calls including Gemini thought_signature, or skip-validator."""
    tool_calls = []
    for tc in msg.tool_calls:
        entry = {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        }
        extra = _thought_extra(tc)
        entry["extra_content"] = extra or {
            "google": {"thought_signature": "skip_thought_signature_validator"}
        }
        tool_calls.append(entry)
    return {"role": "assistant", "content": msg.content, "tool_calls": tool_calls}


def reply(user, history: list[dict], extra_user_text: str = "") -> str:
    """One agent turn. `history` is user/assistant dicts; extra_user_text is appended."""
    from .ai import AiUnavailable, get_client, user_message_for_ai_error

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(today=dt.date.today().isoformat())},
        *history,
    ]
    if extra_user_text:
        messages.append({"role": "user", "content": extra_user_text})

    client = get_client()
    for _ in range(8):
        try:
            response = client.chat.completions.create(
                model=settings.GEMINI_MODEL,
                temperature=0.2,
                messages=messages,
                tools=TOOLS,
            )
        except Exception as exc:  # noqa: BLE001
            raise AiUnavailable(user_message_for_ai_error(exc)) from exc
        msg = response.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip() or "Done."

        messages.append(_assistant_tool_message(msg))
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool(user, tc.function.name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )
    return "I got stuck calling tools. Try a shorter question."
