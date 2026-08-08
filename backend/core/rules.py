"""Rule engine: assign tags to transactions from ordered, criteria-based rules.

Rules are re-runnable and idempotent. A rule assigns its tags to every matching
transaction as a `TransactionTag(source='rule')`. Manual tags are never modified
(get_or_create leaves an existing assignment untouched). `stop_processing` makes
a matched transaction skip all later rules.
"""
from __future__ import annotations

import re

from .criteria import apply_criteria
from .models import Rule, Transaction, TransactionTag


def _compile(pattern: str):
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def apply_rules(user, queryset=None) -> dict:
    """Apply all active rules for `user` to `queryset` (default: all their tx)."""
    if queryset is None:
        queryset = Transaction.objects.filter(owner=user)

    rules = (
        Rule.objects.filter(owner=user, is_active=True)
        .prefetch_related("tags")
        .order_by("order", "id")
    )

    stopped: set[int] = set()
    created = 0
    matched_tx: set[int] = set()

    for rule in rules:
        matches = apply_criteria(queryset, rule.criteria)

        if rule.regex:
            pattern = _compile(rule.regex)
            if pattern is not None:
                keep = [
                    t.id
                    for t in matches.only("id", "concept")
                    if pattern.search(t.concept or "")
                ]
                matches = queryset.filter(id__in=keep)

        rule_tags = list(rule.tags.all())
        if not rule_tags:
            continue

        for tx_id in matches.exclude(id__in=stopped).values_list("id", flat=True):
            matched_tx.add(tx_id)
            for tag in rule_tags:
                _, was_created = TransactionTag.objects.get_or_create(
                    transaction_id=tx_id,
                    tag_id=tag.id,
                    defaults={"source": TransactionTag.SOURCE_RULE, "rule": rule},
                )
                if was_created:
                    created += 1
            if rule.stop_processing:
                stopped.add(tx_id)

    return {"assignments_created": created, "transactions_matched": len(matched_tx)}
