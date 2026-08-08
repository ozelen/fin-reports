from rest_framework import serializers

from .models import Account, Folder, Rule, Tag, Transaction, TransactionTag, Upload


class OwnerScopedPKField(serializers.PrimaryKeyRelatedField):
    """PrimaryKeyRelatedField whose queryset is limited to the request user."""

    def __init__(self, model, **kwargs):
        self._model = model
        super().__init__(queryset=model.objects.none(), **kwargs)

    def get_queryset(self):
        request = self.context.get("request")
        qs = self._model.objects.all()
        if request is not None and request.user.is_authenticated:
            qs = qs.filter(owner=request.user)
        return qs


class AccountSerializer(serializers.ModelSerializer):
    transaction_count = serializers.IntegerField(
        source="transactions.count", read_only=True
    )

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "bank",
            "iban",
            "currency",
            "is_default",
            "transaction_count",
            "created_at",
        ]
        read_only_fields = ["id", "transaction_count", "created_at"]


class UploadSerializer(serializers.ModelSerializer):
    account_label = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = Upload
        fields = [
            "id",
            "original_filename",
            "account",
            "account_label",
            "account_name",
            "account_iban",
            "account_holder",
            "currency",
            "row_count",
            "imported_count",
            "parsed_at",
            "created_at",
        ]
        read_only_fields = fields


class TagSerializer(serializers.ModelSerializer):
    transaction_count = serializers.IntegerField(
        source="transactions.count", read_only=True
    )

    class Meta:
        model = Tag
        fields = ["id", "name", "color", "description", "transaction_count", "created_at"]
        read_only_fields = ["id", "transaction_count", "created_at"]


class TransactionTagSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="tag.id", read_only=True)
    name = serializers.CharField(source="tag.name", read_only=True)
    color = serializers.CharField(source="tag.color", read_only=True)

    class Meta:
        model = TransactionTag
        fields = ["id", "name", "color", "source", "confidence"]


class TransactionSerializer(serializers.ModelSerializer):
    kind = serializers.CharField(read_only=True)
    tags = TransactionTagSerializer(source="tag_links", many=True, read_only=True)
    account_label = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "operation_date",
            "value_date",
            "concept",
            "counterparty",
            "amount",
            "balance",
            "currency",
            "kind",
            "tags",
            "metadata",
            "upload",
            "account",
            "account_label",
            "created_at",
        ]
        read_only_fields = fields


class RuleSerializer(serializers.ModelSerializer):
    tags = OwnerScopedPKField(model=Tag, many=True, required=False)

    class Meta:
        model = Rule
        fields = [
            "id",
            "name",
            "order",
            "is_active",
            "criteria",
            "regex",
            "stop_processing",
            "tags",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FolderSerializer(serializers.ModelSerializer):
    parent = OwnerScopedPKField(
        model=Folder, required=False, allow_null=True
    )
    tags = OwnerScopedPKField(model=Tag, many=True, required=False)
    transaction_count = serializers.SerializerMethodField()

    class Meta:
        model = Folder
        fields = [
            "id",
            "name",
            "parent",
            "tags",
            "tag_match",
            "criteria",
            "transaction_count",
            "created_at",
        ]
        read_only_fields = ["id", "transaction_count", "created_at"]

    def get_transaction_count(self, obj):
        from .folders import folder_transaction_ids

        return len(folder_transaction_ids(obj, recursive=True))


class FolderTransactionsSerializer(serializers.Serializer):
    add = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    remove = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)


class BulkTagSerializer(serializers.Serializer):
    transaction_ids = serializers.ListField(child=serializers.IntegerField())
    add = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    remove = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)


class AiClassifySerializer(serializers.Serializer):
    scope = serializers.CharField(required=False, default="untagged")
    transaction_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200)


class AiApplySerializer(serializers.Serializer):
    class _Item(serializers.Serializer):
        transaction_id = serializers.IntegerField()
        tag_ids = serializers.ListField(
            child=serializers.IntegerField(), required=False, default=list
        )
        new_tags = serializers.ListField(
            child=serializers.CharField(), required=False, default=list
        )
        confidence = serializers.FloatField(required=False, allow_null=True, default=None)

    items = _Item(many=True)
