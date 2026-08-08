"""OpenAI-based classification of untagged transactions.

Given the user's existing tag taxonomy, the model suggests, per transaction, zero
or more existing tags (by id) and optionally proposes new tag names. Nothing is
persisted here - suggestions are returned for review and written only via the
apply endpoint.
"""
from __future__ import annotations

import json

from django.conf import settings

from .models import Tag

SYSTEM_PROMPT = (
    "You are a bookkeeping assistant that classifies bank transactions for a "
    "small business. You are given the user's existing tags and a list of "
    "transactions (Spanish bank concepts). For each transaction, choose the "
    "existing tag ids that best apply. If none fit well and a clear category is "
    "warranted, propose a concise new tag name (lowercase, 1-3 words) in "
    "new_tags. Prefer existing tags. Return a confidence in [0,1]. Do not invent "
    "transaction ids; only classify the ones provided."
)

RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "classification",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "transaction_id": {"type": "integer"},
                            "tag_ids": {"type": "array", "items": {"type": "integer"}},
                            "new_tags": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "transaction_id",
                            "tag_ids",
                            "new_tags",
                            "confidence",
                        ],
                    },
                }
            },
            "required": ["items"],
        },
    },
}


class AiNotConfigured(Exception):
    pass


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def classify(user, transactions, batch_size: int = 20) -> list[dict]:
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise AiNotConfigured(
            "OPENAI_API_KEY is not set. Add it to the environment to enable AI "
            "classification."
        )

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    tags = list(Tag.objects.filter(owner=user).values("id", "name", "description"))
    transactions = list(transactions)

    suggestions: list[dict] = []
    for batch in _chunks(transactions, batch_size):
        payload = {
            "tags": tags,
            "transactions": [
                {
                    "id": tx.id,
                    "concept": tx.concept,
                    "counterparty": tx.counterparty,
                    "amount": str(tx.amount),
                    "kind": tx.kind,
                }
                for tx in batch
            ],
        }
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format=RESPONSE_SCHEMA,
        )
        data = json.loads(response.choices[0].message.content)
        suggestions.extend(data.get("items", []))

    return suggestions
