import datetime as dt
from collections import defaultdict

from django.core import serializers as dj_serializers
from django.core.management.color import no_style
from django.db import connection, transaction as db_transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import (
    TruncDay,
    TruncMonth,
    TruncQuarter,
    TruncWeek,
    TruncYear,
)
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import ai, parsing
from .criteria import apply_criteria
from .export import build_workbook
from .filters import TransactionFilter
from .folders import descendants, folder_transaction_ids, own_transaction_ids, subtree
from .models import Account, Folder, Rule, Tag, Transaction, TransactionTag, Upload
from .rules import apply_rules
from .serializers import (
    AccountSerializer,
    AiApplySerializer,
    AiClassifySerializer,
    BulkTagSerializer,
    FolderSerializer,
    FolderTransactionsSerializer,
    RuleSerializer,
    TagSerializer,
    TransactionSerializer,
    UploadSerializer,
)


class UploadViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = UploadSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return Upload.objects.filter(owner=self.request.user)

    def _resolve_account(self, request):
        """Pick the account for this upload: the requested one, else the user's
        default, else their first account (or None if they have none yet)."""
        accounts = Account.objects.filter(owner=request.user)
        account_id = request.data.get("account")
        if account_id:
            account = accounts.filter(id=account_id).first()
            if account is not None:
                return account
        return (
            accounts.filter(is_default=True).first()
            or accounts.order_by("id").first()
        )

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "No file provided (expected form field 'file')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        account = self._resolve_account(request)

        upload = Upload.objects.create(
            owner=request.user,
            account=account,
            original_filename=file_obj.name,
            file=file_obj,
        )

        try:
            result = parsing.parse(upload.file.path, upload.original_filename)
        except (parsing.UnsupportedFormat, parsing.ParseError) as exc:
            upload.delete()
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - surface parser issues to the client
            upload.delete()
            return Response(
                {"detail": f"Failed to parse file: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        meta = result["meta"]
        rows = result["rows"]

        upload.account_name = meta.get("account_name", "")
        upload.account_iban = meta.get("account_iban", "")
        upload.account_holder = meta.get("account_holder", "")
        upload.currency = meta.get("currency", "EUR")
        upload.row_count = len(rows)
        upload.parsed_at = timezone.now()

        objects = [
            Transaction(owner=request.user, upload=upload, account=account, **row)
            for row in rows
        ]
        Transaction.objects.bulk_create(objects, ignore_conflicts=True)
        # ignore_conflicts makes counting unreliable across backends; recount.
        upload.imported_count = Transaction.objects.filter(upload=upload).count()
        upload.save()

        rule_result = apply_rules(
            request.user, Transaction.objects.filter(upload=upload)
        )

        serializer = self.get_serializer(upload)
        data = serializer.data
        data["skipped_duplicates"] = upload.row_count - upload.imported_count
        data["rule_assignments"] = rule_result["assignments_created"]
        return Response(data, status=status.HTTP_201_CREATED)


class TransactionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = TransactionSerializer
    filterset_class = TransactionFilter
    search_fields = ["concept", "counterparty"]
    ordering_fields = [
        "operation_date",
        "value_date",
        "amount",
        "balance",
        "concept",
        "counterparty",
    ]
    ordering = ["-operation_date", "-id"]

    def get_queryset(self):
        return (
            Transaction.objects.filter(owner=self.request.user)
            .prefetch_related("tag_links__tag")
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        by_currency = list(
            qs.values("currency")
            .annotate(
                count=Count("id"),
                income=Sum("amount", filter=Q(amount__gte=0)),
                expense=Sum("amount", filter=Q(amount__lt=0)),
            )
            .order_by("currency")
        )
        currencies = [
            {
                "currency": row["currency"] or "EUR",
                "count": row["count"] or 0,
                "income": row["income"] or 0,
                "expense": row["expense"] or 0,
                "net": (row["income"] or 0) + (row["expense"] or 0),
            }
            for row in by_currency
        ]
        # Single-currency totals stay on the top-level fields for the UI.
        # Mixed currencies must not be summed (UAH + EUR is meaningless).
        if len(currencies) == 1:
            only = currencies[0]
            return Response({**only, "currencies": currencies, "mixed": False})
        return Response(
            {
                "count": sum(c["count"] for c in currencies),
                "income": None,
                "expense": None,
                "net": None,
                "currency": None,
                "currencies": currencies,
                "mixed": True,
            }
        )

    @action(detail=False, methods=["post"])
    def tag(self, request):
        serializer = BulkTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        owned_tx = list(
            Transaction.objects.filter(
                owner=request.user, id__in=data["transaction_ids"]
            )
        )
        add_tags = Tag.objects.filter(owner=request.user, id__in=data["add"])
        created = 0
        for tx in owned_tx:
            for tag in add_tags:
                _, was_created = TransactionTag.objects.get_or_create(
                    transaction=tx,
                    tag=tag,
                    defaults={"source": TransactionTag.SOURCE_MANUAL},
                )
                if was_created:
                    created += 1
        if data["remove"]:
            TransactionTag.objects.filter(
                transaction__in=owned_tx, tag_id__in=data["remove"]
            ).delete()

        return Response({"updated": len(owned_tx), "created": created})

    @action(detail=False, methods=["get"])
    def by_tag(self, request):
        """Aggregate the filtered transactions per tag for dashboard charts."""
        qs = self.filter_queryset(self.get_queryset())
        currency_codes = sorted(
            {c for c in qs.values_list("currency", flat=True).distinct() if c}
        )
        mixed = len(currency_codes) > 1
        display_currency = None if mixed else (currency_codes[0] if currency_codes else "EUR")

        rows = (
            TransactionTag.objects.filter(transaction__in=qs)
            .values("tag_id", "tag__name", "tag__color")
            .annotate(
                count=Count("transaction_id", distinct=True),
                income=Sum("transaction__amount", filter=Q(transaction__amount__gte=0)),
                expense=Sum("transaction__amount", filter=Q(transaction__amount__lt=0)),
            )
            .order_by()
        )

        def money(value):
            return float(value or 0)

        tags = [
            {
                "id": r["tag_id"],
                "name": r["tag__name"],
                "color": r["tag__color"],
                "count": r["count"],
                "income": money(r["income"]),
                "expense": money(r["expense"]),
                "net": money(r["income"]) + money(r["expense"]),
            }
            for r in rows
        ]
        tags.sort(key=lambda t: abs(t["net"]), reverse=True)

        untagged_qs = qs.filter(tag_links__isnull=True)
        u = untagged_qs.aggregate(
            count=Count("id"),
            income=Sum("amount", filter=Q(amount__gte=0)),
            expense=Sum("amount", filter=Q(amount__lt=0)),
        )
        untagged = {
            "count": u["count"] or 0,
            "income": money(u["income"]),
            "expense": money(u["expense"]),
            "net": money(u["income"]) + money(u["expense"]),
        }

        t = qs.aggregate(
            count=Count("id"),
            income=Sum("amount", filter=Q(amount__gte=0)),
            expense=Sum("amount", filter=Q(amount__lt=0)),
        )
        totals = {
            "count": t["count"] or 0,
            "income": None if mixed else money(t["income"]),
            "expense": None if mixed else money(t["expense"]),
            "net": None if mixed else money(t["income"]) + money(t["expense"]),
            "currency": display_currency,
        }

        return Response(
            {
                "tags": tags,
                "untagged": untagged,
                "totals": totals,
                "mixed": mixed,
                "currencies": currency_codes,
            }
        )

    @action(detail=False, methods=["get"])
    def over_time(self, request):
        """Income/expense/net per time bucket for the dashboard line chart.

        ``granularity`` may be day/week/month/quarter/year.
        Refuses to series-sum when the filter spans multiple currencies.
        """
        qs = self.filter_queryset(self.get_queryset())
        currency_codes = sorted(
            {c for c in qs.values_list("currency", flat=True).distinct() if c}
        )
        mixed = len(currency_codes) > 1
        if mixed:
            return Response(
                {
                    "granularity": request.query_params.get("granularity") or "month",
                    "series": [],
                    "mixed": True,
                    "currencies": currency_codes,
                }
            )

        granularity = (request.query_params.get("granularity") or "month").lower()
        trunc = {
            "day": TruncDay,
            "week": TruncWeek,
            "month": TruncMonth,
            "quarter": TruncQuarter,
            "year": TruncYear,
        }.get(granularity, TruncMonth)

        rows = (
            qs.annotate(period=trunc("operation_date"))
            .values("period")
            .annotate(
                income=Sum("amount", filter=Q(amount__gte=0)),
                expense=Sum("amount", filter=Q(amount__lt=0)),
                count=Count("id"),
            )
            .order_by("period")
        )

        def money(value):
            return float(value or 0)

        series = [
            {
                "period": r["period"].isoformat() if r["period"] else None,
                "income": money(r["income"]),
                "expense": money(r["expense"]),
                "net": money(r["income"]) + money(r["expense"]),
                "count": r["count"],
            }
            for r in rows
            if r["period"] is not None
        ]
        return Response(
            {
                "granularity": granularity,
                "series": series,
                "mixed": False,
                "currencies": currency_codes,
            }
        )


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer

    def get_queryset(self):
        return Account.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        account = serializer.save(owner=self.request.user)
        self._sync_default(account)

    def perform_update(self, serializer):
        account = serializer.save()
        self._sync_default(account)

    def _sync_default(self, account):
        """Keep at most one default account per owner."""
        if account.is_default:
            Account.objects.filter(owner=account.owner).exclude(
                id=account.id
            ).update(is_default=False)


class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer

    def get_queryset(self):
        return Tag.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        tag = self.get_object()
        qs = tag.transactions.all().order_by("-operation_date", "-id")
        page = self.paginate_queryset(qs)
        serializer = TransactionSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class RuleViewSet(viewsets.ModelViewSet):
    serializer_class = RuleSerializer

    def get_queryset(self):
        return Rule.objects.filter(owner=self.request.user).prefetch_related("tags")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["post"])
    def apply(self, request):
        ids = request.data.get("transaction_ids")
        qs = Transaction.objects.filter(owner=request.user)
        if ids:
            qs = qs.filter(id__in=ids)
        result = apply_rules(request.user, qs)
        return Response(result)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        rule = self.get_object()
        base = Transaction.objects.filter(owner=request.user)
        matches = apply_criteria(base, rule.criteria)
        if rule.regex:
            import re

            try:
                pattern = re.compile(rule.regex, re.IGNORECASE)
                keep = [
                    t.id
                    for t in matches.only("id", "concept")
                    if pattern.search(t.concept or "")
                ]
                matches = base.filter(id__in=keep)
            except re.error:
                return Response(
                    {"detail": "Invalid regex."}, status=status.HTTP_400_BAD_REQUEST
                )
        sample = matches.order_by("-operation_date")[:10]
        return Response(
            {
                "match_count": matches.count(),
                "sample": TransactionSerializer(sample, many=True).data,
            }
        )


class FolderViewSet(viewsets.ModelViewSet):
    serializer_class = FolderSerializer

    def get_queryset(self):
        return Folder.objects.filter(owner=self.request.user).prefetch_related(
            "tags", "children"
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        parent = serializer.validated_data.get("parent", serializer.instance.parent)
        self._guard_cycle(serializer.instance, parent)
        serializer.save()

    def _guard_cycle(self, folder, parent):
        if parent is None:
            return
        if parent.id == folder.id:
            raise ValidationError("A folder cannot be its own parent.")
        descendant_ids = {d.id for d in descendants(folder)}
        if parent.id in descendant_ids:
            raise ValidationError("Cannot move a folder into its own descendant.")

    @action(detail=False, methods=["get"])
    def tree(self, request):
        folders = list(self.get_queryset())
        by_parent = defaultdict(list)
        for f in folders:
            by_parent[f.parent_id].append(f)

        context = self.get_serializer_context()

        def build(node):
            data = FolderSerializer(node, context=context).data
            data["children"] = [build(child) for child in by_parent.get(node.id, [])]
            return data

        return Response([build(root) for root in by_parent.get(None, [])])

    @action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        folder = self.get_object()
        recursive = request.query_params.get("recursive", "true").lower() != "false"
        ids = folder_transaction_ids(folder, recursive=recursive)
        qs = (
            Transaction.objects.filter(id__in=ids)
            .prefetch_related("tag_links__tag")
            .order_by("-operation_date", "-id")
        )
        page = self.paginate_queryset(qs)
        serializer = TransactionSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="update-transactions")
    def update_transactions(self, request, pk=None):
        folder = self.get_object()
        serializer = FolderTransactionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        add_ids = serializer.validated_data["add"]
        remove_ids = serializer.validated_data["remove"]

        owned = Transaction.objects.filter(owner=request.user)
        if add_ids:
            to_add = list(owned.filter(id__in=add_ids))
            folder.included_transactions.add(*to_add)
            folder.excluded_transactions.remove(*to_add)
        if remove_ids:
            to_remove = list(owned.filter(id__in=remove_ids))
            folder.excluded_transactions.add(*to_remove)
            folder.included_transactions.remove(*to_remove)

        return Response(
            {
                "id": folder.id,
                "transaction_count": len(folder_transaction_ids(folder, recursive=True)),
            }
        )

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        folder = self.get_object()
        totals = request.query_params.get("totals", "both")
        if totals not in ("income", "expense", "both"):
            totals = "both"
        recursive = request.query_params.get("recursive", "true").lower() != "false"

        def sheet_for(f):
            qs = Transaction.objects.filter(id__in=own_transaction_ids(f)).order_by(
                "operation_date", "id"
            )
            return (f.name, qs)

        if recursive:
            # One sheet per folder in the subtree (parent + descendants) that has
            # its own transactions, so child folders export as separate sheets.
            sheets = [sheet_for(f) for f in subtree(folder) if own_transaction_ids(f)]
            if not sheets:
                sheets = [(folder.name, Transaction.objects.none())]
        else:
            sheets = [sheet_for(folder)]

        buffer = build_workbook(sheets, totals=totals)
        safe_name = "".join(
            c for c in folder.name if c.isalnum() or c in (" ", "-", "_")
        ).strip().replace(" ", "_") or "folder"
        stamp = dt.date.today().isoformat()
        filename = f"{safe_name}_{stamp}.xlsx"
        response = FileResponse(
            buffer,
            as_attachment=True,
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return response


class AiViewSet(viewsets.ViewSet):
    @action(detail=False, methods=["post"])
    def classify(self, request):
        serializer = AiClassifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        qs = Transaction.objects.filter(owner=request.user).prefetch_related(
            "tag_links"
        )
        if data["transaction_ids"]:
            qs = qs.filter(id__in=data["transaction_ids"])
        elif data["scope"] == "untagged":
            qs = qs.filter(tag_links__isnull=True)
        qs = qs.order_by("-operation_date", "-id")[: data["limit"]]

        transactions = list(qs)
        if not transactions:
            return Response({"suggestions": []})

        try:
            raw = ai.classify(request.user, transactions)
        except ai.AiNotConfigured as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - surface provider errors
            return Response(
                {"detail": f"AI classification failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        tag_names = dict(
            Tag.objects.filter(owner=request.user).values_list("id", "name")
        )
        tx_by_id = {tx.id: tx for tx in transactions}
        suggestions = []
        for item in raw:
            tx = tx_by_id.get(item.get("transaction_id"))
            if tx is None:
                continue
            valid_tag_ids = [t for t in item.get("tag_ids", []) if t in tag_names]
            suggestions.append(
                {
                    "transaction_id": tx.id,
                    "concept": tx.concept,
                    "counterparty": tx.counterparty,
                    "amount": tx.amount,
                    "tag_ids": valid_tag_ids,
                    "tag_names": [tag_names[t] for t in valid_tag_ids],
                    "new_tags": item.get("new_tags", []),
                    "confidence": item.get("confidence"),
                }
            )
        return Response({"suggestions": suggestions})

    @action(detail=False, methods=["post"])
    def apply(self, request):
        serializer = AiApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]

        owned_tx = set(
            Transaction.objects.filter(owner=request.user).values_list("id", flat=True)
        )
        created = 0
        new_tags_created = 0
        for item in items:
            tx_id = item["transaction_id"]
            if tx_id not in owned_tx:
                continue
            tag_ids = list(item["tag_ids"])
            for name in item["new_tags"]:
                name = name.strip()
                if not name:
                    continue
                tag, was_new = Tag.objects.get_or_create(
                    owner=request.user, name=name
                )
                if was_new:
                    new_tags_created += 1
                tag_ids.append(tag.id)

            valid_tags = Tag.objects.filter(owner=request.user, id__in=tag_ids)
            for tag in valid_tags:
                _, was_created = TransactionTag.objects.get_or_create(
                    transaction_id=tx_id,
                    tag=tag,
                    defaults={
                        "source": TransactionTag.SOURCE_AI,
                        "confidence": item.get("confidence"),
                    },
                )
                if was_created:
                    created += 1

        return Response(
            {"assignments_created": created, "new_tags_created": new_tags_created}
        )


# Models included in a backup, in dependency order for restore.
BACKUP_MODELS = [Account, Tag, Rule, Upload, Transaction, TransactionTag, Folder]


class BackupExportView(APIView):
    """Download all of the current user's data as a Django fixture JSON."""

    def get(self, request):
        user = request.user
        querysets = [
            Account.objects.filter(owner=user),
            Tag.objects.filter(owner=user),
            Rule.objects.filter(owner=user),
            Upload.objects.filter(owner=user),
            Transaction.objects.filter(owner=user),
            TransactionTag.objects.filter(transaction__owner=user),
            Folder.objects.filter(owner=user),
        ]
        objects = [obj for qs in querysets for obj in qs]
        data = dj_serializers.serialize("json", objects, indent=2)

        stamp = dt.date.today().isoformat()
        response = HttpResponse(data, content_type="application/json")
        response["Content-Disposition"] = (
            f'attachment; filename="income-share-backup-{stamp}.json"'
        )
        return response


class BackupImportView(APIView):
    """Restore a backup, replacing all of the current user's data."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response(
                {"detail": "No file provided (expected form field 'file')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            payload = file_obj.read().decode("utf-8")
            objects = list(dj_serializers.deserialize("json", payload, ignorenonexistent=True))
        except Exception as exc:  # noqa: BLE001 - surface parse errors to the client
            return Response(
                {"detail": f"Invalid backup file: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        try:
            with db_transaction.atomic():
                # Deleting transactions/uploads cascades their tag links.
                Folder.objects.filter(owner=user).delete()
                Rule.objects.filter(owner=user).delete()
                Transaction.objects.filter(owner=user).delete()
                Upload.objects.filter(owner=user).delete()
                Tag.objects.filter(owner=user).delete()
                Account.objects.filter(owner=user).delete()

                counts = defaultdict(int)
                for obj in objects:
                    instance = obj.object
                    if hasattr(instance, "owner_id"):
                        instance.owner_id = user.id
                    obj.save()
                    counts[instance._meta.model_name] += 1

            sql = connection.ops.sequence_reset_sql(no_style(), BACKUP_MODELS)
            if sql:
                with connection.cursor() as cursor:
                    for statement in sql:
                        cursor.execute(statement)
        except Exception as exc:  # noqa: BLE001 - restore is all-or-nothing
            return Response(
                {"detail": f"Restore failed: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"restored": dict(counts)})
