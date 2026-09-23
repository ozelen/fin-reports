"""Attach salary inflows to clients via match_text."""
from __future__ import annotations

from .models import Client, Transaction
from .receipts import merchant_overlap


def attach_client(tx: Transaction, client: Client) -> bool:
    changed = tx.client_id != client.id
    if changed:
        tx.client = client
        tx.save(update_fields=["client"])
    return changed


def match_client(clients: list[Client], tx: Transaction) -> Client | None:
    if tx.amount <= 0:
        return None
    hits = [
        c
        for c in clients
        if (c.match_text or "").strip() and merchant_overlap(c.match_text, tx)
    ]
    if not hits:
        return None
    hits.sort(key=lambda c: -len((c.match_text or "").strip()))
    return hits[0]


def attach_new_clients(user, queryset) -> int:
    clients = list(
        Client.objects.filter(owner=user).exclude(match_text="").exclude(match_text__isnull=True)
    )
    if not clients:
        return 0
    attached = 0
    for tx in queryset.filter(amount__gt=0):
        hit = match_client(clients, tx)
        if hit is None:
            continue
        if attach_client(tx, hit):
            attached += 1
    return attached


def backfill(user) -> int:
    return attach_new_clients(
        user, Transaction.objects.filter(owner=user, amount__gt=0)
    )
