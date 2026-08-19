"""Finance agent: Gemini tool-calling over the owner's books."""
from __future__ import annotations

import datetime as dt
import json

from django.conf import settings
from django.db.models import Count, Q, Sum

from .criteria import apply_criteria
from .models import Account, Invoice, PurchaseItem, Receipt, Transaction
from .receipts import candidate_transactions

SYSTEM_PROMPT = """You are a personal finance assistant for Income Share, a bookkeeping app.
You help the owner understand bank transactions, income vs expenses, issued invoices,
incoming receipts, and purchase line-items parsed from those receipts.

Rules:
- Be concise. Use the owner's currencies as stored; never sum mixed currencies.
- Never invent transaction, receipt, or invoice ids. Only use ids returned by tools.
- Receipts may arrive before the bank transaction. If there is exactly one good match,
  attach it. If several, list them and ask. If none, say it will wait for a later import.
- When a receipt is saved, confirm the parsed items and spend category.
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
            "description": "Link a receipt to a bank transaction.",
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
            "description": "Search parsed purchase line-items (what was bought).",
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
            "name": "list_accounts",
            "description": "List bank accounts.",
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
        "counterparty": tx.counterparty,
        "concept": (tx.concept or "")[:180],
        "account": tx.account.name if tx.account_id else None,
    }


def _receipt_row(r: Receipt) -> dict:
    items = [
        {
            "name": it.name,
            "qty": str(it.quantity),
            "amount": str(it.amount) if it.amount is not None else None,
            "category": it.category,
        }
        for it in r.items.all()[:40]
    ]
    return {
        "id": r.id,
        "kind": r.kind,
        "merchant": r.merchant,
        "amount": str(r.amount) if r.amount is not None else None,
        "currency": r.currency,
        "date": r.document_date.isoformat() if r.document_date else None,
        "transaction_id": r.transaction_id,
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
            Transaction.objects.filter(owner=user).select_related("account"),
            criteria,
        )
        kw = (args.get("keyword") or "").strip()
        if kw:
            qs = qs.filter(Q(concept__icontains=kw) | Q(counterparty__icontains=kw))
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
        qs = apply_criteria(Transaction.objects.filter(owner=user), criteria)
        by_currency = list(
            qs.values("currency")
            .annotate(
                count=Count("id"),
                income=Sum("amount", filter=Q(amount__gte=0)),
                expense=Sum("amount", filter=Q(amount__lt=0)),
            )
            .order_by("currency")
        )
        return {
            "currencies": [
                {
                    "currency": row["currency"] or "EUR",
                    "count": row["count"] or 0,
                    "income": str(row["income"] or 0),
                    "expense": str(row["expense"] or 0),
                    "net": str((row["income"] or 0) + (row["expense"] or 0)),
                }
                for row in by_currency
            ]
        }

    if name == "list_receipts":
        qs = Receipt.objects.filter(owner=user).prefetch_related("items")
        if args.get("unattached_only"):
            qs = qs.filter(transaction__isnull=True)
        rows = [_receipt_row(r) for r in qs.order_by("-created_at")[:limit]]
        return {"receipts": rows}

    if name == "search_purchases":
        qs = PurchaseItem.objects.filter(receipt__owner=user).select_related("receipt")
        kw = (args.get("keyword") or "").strip()
        if kw:
            qs = qs.filter(Q(name__icontains=kw) | Q(category__icontains=kw))
        if args.get("category"):
            qs = qs.filter(category__iexact=args["category"])
        if args.get("merchant"):
            qs = qs.filter(receipt__merchant__icontains=args["merchant"])
        if args.get("date_from"):
            qs = qs.filter(receipt__document_date__gte=args["date_from"])
        if args.get("date_to"):
            qs = qs.filter(receipt__document_date__lte=args["date_to"])
        rows = [
            {
                "id": it.id,
                "name": it.name,
                "qty": str(it.quantity),
                "amount": str(it.amount) if it.amount is not None else None,
                "category": it.category,
                "merchant": it.receipt.merchant,
                "date": (
                    it.receipt.document_date.isoformat()
                    if it.receipt.document_date
                    else None
                ),
                "receipt_id": it.receipt_id,
                "currency": it.receipt.currency,
            }
            for it in qs.order_by("-receipt__document_date", "-id")[:limit]
        ]
        return {"items": rows}

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
            user, receipt.amount, receipt.document_date, receipt.currency
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
        receipt.transaction = tx
        receipt.save(update_fields=["transaction"])
        return {"ok": True, "receipt": _receipt_row(receipt), "transaction": _tx_row(tx)}

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

    if name == "list_accounts":
        rows = list(
            Account.objects.filter(owner=user).values(
                "id", "name", "bank", "currency", "group", "iban"
            )
        )
        return {"accounts": rows}

    return {"error": f"unknown tool {name}"}


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

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
        )
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
