"""Gemini-based classification of untagged transactions (OpenAI-compatible API).

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
    "transaction ids; only classify the ones provided. Reply with JSON: "
    '{"items": [{"transaction_id": int, "tag_ids": [int], "new_tags": [str], '
    '"confidence": number}]}.'
)


class AiNotConfigured(Exception):
    pass


class AiUnavailable(Exception):
    """Key is set but the provider rejected the call (quota, rate limit, etc.)."""


def get_client():
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise AiNotConfigured(
            "GEMINI_API_KEY is not set. Add it to the environment to enable AI."
        )
    from openai import OpenAI

    return OpenAI(api_key=api_key, base_url=settings.GEMINI_OPENAI_BASE)


def user_message_for_ai_error(exc) -> str:
    text = str(exc)
    low = text.lower()
    if "429" in text or "resource_exhausted" in low or "rate limit" in low:
        return "Gemini is rate-limiting right now. Try again in a minute."
    if "api key" in low or "unauthenticated" in low or "401" in text:
        return "Gemini API key was rejected. Check GEMINI_API_KEY."
    return f"Gemini error: {exc}"


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def classify(user, transactions, batch_size: int = 20) -> list[dict]:
    client = get_client()
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
            model=settings.GEMINI_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        suggestions.extend(data.get("items", []))

    return suggestions
