from django_filters import rest_framework as filters

from .criteria import quarter_range
from .models import Transaction


def _as_id_list(value):
    if value in (None, "", []):
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).split(",")
    ids = []
    for item in items:
        item = str(item).strip()
        if item.isdigit():
            ids.append(int(item))
    return ids


class TransactionFilter(filters.FilterSet):
    kind = filters.CharFilter(method="filter_kind")
    keyword = filters.CharFilter(method="filter_keyword")
    search = filters.CharFilter(method="filter_keyword")
    counterparty = filters.CharFilter(field_name="counterparty", lookup_expr="icontains")
    date_from = filters.DateFilter(field_name="operation_date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="operation_date", lookup_expr="lte")
    quarter = filters.CharFilter(method="filter_quarter")
    year = filters.NumberFilter(method="filter_noop")
    tags = filters.CharFilter(method="filter_tags")
    tag_match = filters.CharFilter(method="filter_noop")
    source = filters.CharFilter(method="filter_source")
    untagged = filters.BooleanFilter(method="filter_untagged")
    folder = filters.NumberFilter(method="filter_folder")
    recurrence = filters.NumberFilter(field_name="recurrence__id")
    upload = filters.NumberFilter(field_name="upload__id")
    account = filters.NumberFilter(field_name="account__id")
    min_amount = filters.NumberFilter(field_name="amount", lookup_expr="gte")
    max_amount = filters.NumberFilter(field_name="amount", lookup_expr="lte")

    class Meta:
        model = Transaction
        fields = [
            "kind",
            "date_from",
            "date_to",
            "folder",
            "recurrence",
            "upload",
            "account",
        ]

    def filter_noop(self, queryset, name, value):
        return queryset

    def filter_kind(self, queryset, name, value):
        value = (value or "").lower()
        if value == "income":
            return queryset.filter(amount__gte=0)
        if value == "expense":
            return queryset.filter(amount__lt=0)
        return queryset

    def filter_keyword(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(concept__icontains=value)

    def filter_quarter(self, queryset, name, value):
        rng = quarter_range(value, self.data.get("year"))
        if not rng:
            return queryset
        start, end = rng
        return queryset.filter(operation_date__gte=start, operation_date__lte=end)

    def filter_tags(self, queryset, name, value):
        ids = _as_id_list(value)
        if not ids:
            return queryset
        match = str(self.data.get("tag_match", "any")).lower()
        if match == "all":
            for tid in ids:
                queryset = queryset.filter(tags__id=tid)
            return queryset.distinct()
        return queryset.filter(tags__id__in=ids).distinct()

    def filter_source(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(tag_links__source=value).distinct()

    def filter_untagged(self, queryset, name, value):
        if value is True:
            return queryset.filter(tag_links__isnull=True)
        return queryset

    def filter_folder(self, queryset, name, value):
        from .folders import folder_transaction_ids
        from .models import Folder

        folder = Folder.objects.filter(id=value).first()
        if folder is None:
            return queryset.none()
        ids = folder_transaction_ids(folder, recursive=True)
        return queryset.filter(id__in=ids)
