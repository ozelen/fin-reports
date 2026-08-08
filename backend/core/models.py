from django.conf import settings
from django.db import models


class Account(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts"
    )
    name = models.CharField(max_length=120)
    bank = models.CharField(max_length=120, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    bic = models.CharField(max_length=20, blank=True)
    correspondent_bic = models.CharField(max_length=20, blank=True)
    bank_address = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=8, default="EUR")
    is_default = models.BooleanField(default=False)
    is_invoice_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_owner_account")
        ]

    def __str__(self):
        return self.name

    def invoice_snapshot(self) -> dict:
        """Bank requisites copied onto an invoice at issue time."""
        return {
            "account_name": self.name,
            "bank_name": self.bank,
            "iban": self.iban,
            "bic": self.bic,
            "correspondent_bic": self.correspondent_bic,
            "bank_address": self.bank_address,
            "currency": self.currency,
        }


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


class IssuerProfile(models.Model):
    """Seller details used when issuing invoices (one per owner)."""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="issuer_profile",
    )
    legal_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, blank=True)
    vat_number = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True, default="Spain")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    legal_form = models.CharField(
        max_length=120, blank=True, default="Private Entrepreneur | Autónomo"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.legal_name

    def invoice_snapshot(self) -> dict:
        return {
            "issuer_name": self.legal_name,
            "issuer_trade_name": self.trade_name,
            "issuer_vat_number": self.vat_number,
            "issuer_address": self.address,
            "issuer_city": self.city,
            "issuer_country": self.country,
            "issuer_phone": self.phone,
            "issuer_email": self.email,
            "issuer_legal_form": self.legal_form,
        }


class Client(models.Model):
    VAT_REVERSE_CHARGE = "reverse_charge"
    VAT_STANDARD = "standard"
    VAT_EXEMPT = "exempt"
    VAT_MODE_CHOICES = [
        (VAT_REVERSE_CHARGE, "Reverse charge (NP)"),
        (VAT_STANDARD, "Standard VAT"),
        (VAT_EXEMPT, "Exempt (ZW)"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clients"
    )
    name = models.CharField(max_length=200)
    tax_id = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    vat_mode = models.CharField(
        max_length=20, choices=VAT_MODE_CHOICES, default=VAT_REVERSE_CHARGE
    )
    default_vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    default_description = models.CharField(max_length=255, blank=True)
    default_unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    currency = models.CharField(max_length=8, default="EUR")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_owner_client")
        ]

    def __str__(self):
        return self.name

    def invoice_snapshot(self) -> dict:
        return {
            "client_name": self.name,
            "client_tax_id": self.tax_id,
            "client_address": self.address,
            "vat_mode": self.vat_mode,
        }


class Invoice(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ISSUED = "issued"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ISSUED, "Issued"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="invoices"
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    number = models.CharField(max_length=40, blank=True)

    client = models.ForeignKey(
        Client, on_delete=models.PROTECT, related_name="invoices"
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )

    service_year = models.PositiveIntegerField()
    service_month = models.PositiveSmallIntegerField()
    issue_date = models.DateField()
    sale_date = models.DateField()
    due_date = models.DateField()

    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="EUR")
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    vat_label = models.CharField(max_length=20, blank=True, default="NP")
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    # Snapshots (refreshed while draft; frozen once issued)
    issuer_name = models.CharField(max_length=200, blank=True)
    issuer_trade_name = models.CharField(max_length=200, blank=True)
    issuer_vat_number = models.CharField(max_length=40, blank=True)
    issuer_address = models.TextField(blank=True)
    issuer_city = models.CharField(max_length=120, blank=True)
    issuer_country = models.CharField(max_length=120, blank=True)
    issuer_phone = models.CharField(max_length=40, blank=True)
    issuer_email = models.EmailField(blank=True)
    issuer_legal_form = models.CharField(max_length=120, blank=True)

    client_name = models.CharField(max_length=200, blank=True)
    client_tax_id = models.CharField(max_length=40, blank=True)
    client_address = models.TextField(blank=True)
    vat_mode = models.CharField(max_length=20, blank=True)

    account_name = models.CharField(max_length=120, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    bic = models.CharField(max_length=20, blank=True)
    correspondent_bic = models.CharField(max_length=20, blank=True)
    bank_address = models.CharField(max_length=255, blank=True)

    xlsx_file = models.FileField(upload_to="invoices/", blank=True)
    pdf_file = models.FileField(upload_to="invoices/", blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-issue_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "number"], name="uniq_owner_invoice_number"
            )
        ]
        indexes = [
            models.Index(fields=["owner", "service_year", "service_month"]),
            models.Index(fields=["owner", "status"]),
        ]

    def __str__(self):
        return f"{self.number} ({self.status})"

    @property
    def is_issued(self) -> bool:
        return self.status == self.STATUS_ISSUED

    def recalculate_amounts(self) -> None:
        from decimal import Decimal, ROUND_HALF_UP

        q = Decimal(self.quantity or 0)
        p = Decimal(self.unit_price or 0)
        rate = Decimal(self.vat_rate or 0)
        net = (q * p).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        vat = (net * rate / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        self.net_amount = net
        self.vat_amount = vat
        self.total_amount = net + vat
