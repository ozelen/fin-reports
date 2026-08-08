"""Smart-folder membership resolution.

Effective members of a folder = (criteria/tag matches) plus manual includes,
minus manual excludes. Totals/export can roll up all descendant folders.
"""
from __future__ import annotations

from .criteria import apply_criteria


def own_transaction_ids(folder) -> set[int]:
    from .models import Transaction

    base = Transaction.objects.filter(owner_id=folder.owner_id)

    data = dict(folder.criteria or {})
    tag_ids = list(folder.tags.values_list("id", flat=True))
    if tag_ids:
        data["tags"] = tag_ids
        data["tag_match"] = folder.tag_match

    if data:
        match_ids = set(apply_criteria(base, data).values_list("id", flat=True))
    else:
        match_ids = set()

    included = set(folder.included_transactions.values_list("id", flat=True))
    excluded = set(folder.excluded_transactions.values_list("id", flat=True))
    return (match_ids | included) - excluded


def descendants(folder) -> list:
    result = []
    seen = {folder.id}
    stack = list(folder.children.all())
    while stack:
        child = stack.pop()
        if child.id in seen:
            continue
        seen.add(child.id)
        result.append(child)
        stack.extend(child.children.all())
    return result


def subtree(folder) -> list:
    """The folder followed by all descendants, depth-first, children by name."""
    result = []
    seen = set()

    def visit(node):
        if node.id in seen:
            return
        seen.add(node.id)
        result.append(node)
        for child in node.children.all().order_by("name"):
            visit(child)

    visit(folder)
    return result


def folder_transaction_ids(folder, recursive: bool = True) -> set[int]:
    ids = set(own_transaction_ids(folder))
    if recursive:
        for child in descendants(folder):
            ids |= own_transaction_ids(child)
    return ids
