from django.conf import settings
from django.db import models


class Account(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts"
    )
    name = models.CharField(max_length=120)
    bank = models.CharField(max_length=120, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    currency = models.CharField(max_length=8, default="EUR")
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_owner_account")
        ]

    def __str__(self):
        return self.name


class Upload(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="uploads"
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploads",
    )
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to="uploads/")
    account_name = models.CharField(max_length=255, blank=True)
    account_iban = models.CharField(max_length=34, blank=True)
    account_holder = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=8, default="EUR")
    row_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    parsed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.created_at:%Y-%m-%d})"


class Tag(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags"
    )
    name = models.CharField(max_length=80)
    color = models.CharField(max_length=9, default="#1f4e78")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_owner_tag")
        ]

    def __str__(self):
        return self.name


class Rule(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rules"
    )
    name = models.CharField(max_length=120)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    # Same shape as the transaction filter params (kind, search, counterparty,
    # date_from/date_to, quarter/year, min_amount/max_amount, tags/tag_match).
    criteria = models.JSONField(default=dict, blank=True)
    # Optional regex applied to the concept (case-insensitive).
    regex = models.CharField(max_length=255, blank=True)
    stop_processing = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, related_name="rules", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class Transaction(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions"
    )
    upload = models.ForeignKey(
        Upload, on_delete=models.CASCADE, related_name="transactions"
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    operation_date = models.DateField()
    value_date = models.DateField(null=True, blank=True)
    concept = models.TextField()
    counterparty = models.CharField(max_length=255, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(max_length=8, default="EUR")
    tags = models.ManyToManyField(
        Tag, through="TransactionTag", related_name="transactions", blank=True
    )
    # Enrichment seam (Amazon exports, etc.) without future migrations on data.
    metadata = models.JSONField(default=dict, blank=True)
    dedupe_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-operation_date", "-id"]
        indexes = [models.Index(fields=["owner", "operation_date"])]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "dedupe_hash"], name="uniq_owner_tx"
            )
        ]

    @property
    def kind(self):
        return "income" if self.amount >= 0 else "expense"

    def __str__(self):
        return f"{self.operation_date} {self.amount} {self.concept[:40]}"


class TransactionTag(models.Model):
    SOURCE_MANUAL = "manual"
    SOURCE_RULE = "rule"
    SOURCE_AI = "ai"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_RULE, "Rule"),
        (SOURCE_AI, "AI"),
    ]

    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="tag_links"
    )
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, related_name="transaction_links"
    )
    source = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, default=SOURCE_MANUAL
    )
    rule = models.ForeignKey(
        Rule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
    )
    confidence = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transaction", "tag"], name="uniq_transaction_tag"
            )
        ]

    def __str__(self):
        return f"{self.transaction_id}:{self.tag_id} ({self.source})"


class Folder(models.Model):
    TAG_MATCH_ANY = "any"
    TAG_MATCH_ALL = "all"
    TAG_MATCH_CHOICES = [(TAG_MATCH_ANY, "Any"), (TAG_MATCH_ALL, "All")]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="folders"
    )
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    # Manual overrides on top of the smart criteria.
    included_transactions = models.ManyToManyField(
        Transaction, related_name="included_in_folders", blank=True
    )
    excluded_transactions = models.ManyToManyField(
        Transaction, related_name="excluded_from_folders", blank=True
    )
    # Smart criteria: tags to match plus a filter dict (same shape as the API filter).
    tags = models.ManyToManyField(Tag, related_name="folders", blank=True)
    tag_match = models.CharField(
        max_length=3, choices=TAG_MATCH_CHOICES, default=TAG_MATCH_ANY
    )
    criteria = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "parent", "name"], name="uniq_owner_parent_folder"
            )
        ]

    def __str__(self):
        return self.name
