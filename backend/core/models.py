import datetime as dt

from django.conf import settings
from django.db import models


def date_in_force(start, end, on: dt.date) -> bool:
    if start and start > on:
        return False
    if end and end < on:
        return False
    return True


class Account(models.Model):
    GROUP_FAMILY = "family"
    GROUP_PERSONAL = "personal"
    GROUP_CHOICES = [
        (GROUP_FAMILY, "Family"),
        (GROUP_PERSONAL, "Personal"),
    ]
    KIND_BANK = "bank"
    KIND_CASH = "cash"
    KIND_DEBT = "debt"
    KIND_CHOICES = [
        (KIND_BANK, "Bank"),
        (KIND_CASH, "Cash"),
        (KIND_DEBT, "Debt"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts"
    )
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default=KIND_BANK)
    bank = models.CharField(max_length=120, blank=True)
    iban = models.CharField(max_length=34, blank=True)
    bic = models.CharField(max_length=20, blank=True)
    correspondent_bic = models.CharField(max_length=20, blank=True)
    bank_address = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=8, default="EUR")
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit_limit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="If set, stored balance is available credit; real = balance − limit.",
    )
    group = models.CharField(
        max_length=20, choices=GROUP_CHOICES, default=GROUP_FAMILY
    )
    is_default = models.BooleanField(default=False)
    is_invoice_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "group", "name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_owner_account")
        ]

    def __str__(self):
        return self.name

    @property
    def effective_balance(self):
        """Owed-as-negative when `credit_limit` is set (available credit on the statement)."""
        from decimal import Decimal

        bal = self.balance or Decimal("0")
        limit = self.credit_limit
        if limit in (None, Decimal("0")):
            return bal
        return bal - limit

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
    ignore_stats = models.BooleanField(
        default=False,
        help_text="Hide this tag from dashboard, budgets, and other totals (swap, cash in/out).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_owner_tag")
        ]

    def __str__(self):
        return self.name

    @classmethod
    def resolve(cls, user, names) -> list["Tag"]:
        """Existing tags by case-insensitive name, created if missing."""
        tags = []
        seen: set[str] = set()
        for raw in names or []:
            name = " ".join(str(raw).split())[:80]
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            tag = cls.objects.filter(owner=user, name__iexact=name).first()
            if tag is None:
                tag = cls.objects.create(owner=user, name=name)
            tags.append(tag)
        return tags


class Budget(models.Model):
    PERIOD_WEEK = "week"
    PERIOD_MONTH = "month"
    PERIOD_QUARTER = "quarter"
    PERIOD_YEAR = "year"
    PERIOD_CHOICES = [
        (PERIOD_WEEK, "Week"),
        (PERIOD_MONTH, "Month"),
        (PERIOD_QUARTER, "Quarter"),
        (PERIOD_YEAR, "Year"),
    ]
    KIND_SPEND = "spend"
    KIND_INCOME = "income"
    KIND_SAVE = "save"
    KIND_CHOICES = [
        (KIND_SPEND, "Spend"),
        (KIND_INCOME, "Income"),
        (KIND_SAVE, "Save"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budgets"
    )
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="budgets")
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="budgets",
    )
    period = models.CharField(
        max_length=8, choices=PERIOD_CHOICES, default=PERIOD_MONTH
    )
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default=KIND_SPEND)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "period", "id"]

    def __str__(self):
        return f"{self.kind} {self.tag} {self.period} {self.amount}"


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


class Recurrence(models.Model):
    FREQ_WEEK = "week"
    FREQ_MONTH = "month"
    FREQ_QUARTER = "quarter"
    FREQ_YEAR = "year"
    FREQ_CHOICES = [
        (FREQ_WEEK, "Weekly"),
        (FREQ_MONTH, "Monthly"),
        (FREQ_QUARTER, "Quarterly"),
        (FREQ_YEAR, "Yearly"),
    ]
    CAT_TAX = "tax"
    CAT_LOAN = "loan"
    CAT_SUBSCRIPTION = "subscription"
    CAT_INCOME = "income"
    CAT_OTHER = "other"
    CAT_CHOICES = [
        (CAT_TAX, "Tax"),
        (CAT_LOAN, "Loan"),
        (CAT_SUBSCRIPTION, "Subscription"),
        (CAT_INCOME, "Income"),
        (CAT_OTHER, "Other"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recurrences"
    )
    name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=8, default="EUR")
    frequency = models.CharField(
        max_length=8, choices=FREQ_CHOICES, default=FREQ_MONTH
    )
    due_day = models.SmallIntegerField(
        default=1,
        help_text="Weekday 0–6 (Mon–Sun) for weekly; day of month 1–31 otherwise.",
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recurrences",
    )
    match_text = models.CharField(max_length=255, blank=True)
    amount_tolerance_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=10
    )
    auto_match = models.BooleanField(default=True)
    category = models.CharField(
        max_length=16, choices=CAT_CHOICES, default=CAT_OTHER
    )
    is_active = models.BooleanField(default=True)
    tags = models.ManyToManyField(Tag, related_name="recurrences", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class TaxProfile(models.Model):
    METHOD_130 = "modelo_130"
    METHOD_CHOICES = [(METHOD_130, "Modelo 130")]
    INCOME_HOURS = "hours"
    INCOME_INVOICES = "invoices"
    INCOME_TAGS = "tags"
    INCOME_CHOICES = [
        (INCOME_HOURS, "Hourly × working days"),
        (INCOME_INVOICES, "Issued invoices"),
        (INCOME_TAGS, "Tagged bank income"),
    ]
    SS_TABLE = "table"
    SS_FIXED = "fixed"
    SS_CHOICES = [
        (SS_TABLE, "RETA tramos"),
        (SS_FIXED, "Fixed cuota"),
    ]

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tax_profile",
    )
    irpf_method = models.CharField(
        max_length=16, choices=METHOD_CHOICES, default=METHOD_130
    )
    withholding_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0
    )
    simplificada = models.BooleanField(default=True)
    income_from = models.CharField(
        max_length=12, choices=INCOME_CHOICES, default=INCOME_HOURS
    )
    hourly_rate = models.DecimalField(max_digits=12, decimal_places=2, default=30)
    hours_per_day = models.PositiveSmallIntegerField(default=8)
    # {"2026-08": 160} — hours for that calendar month; missing keys use invoice or Mon–Fri.
    hours_overrides = models.JSONField(default=dict, blank=True)
    ss_mode = models.CharField(max_length=8, choices=SS_CHOICES, default=SS_TABLE)
    ss_cuota_override = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    new_autonomo_start = models.DateField(null=True, blank=True)
    planned_income_override = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    deductible_tags = models.ManyToManyField(
        Tag, related_name="tax_profiles", blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"tax profile {self.owner_id}"


class Transaction(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions"
    )
    upload = models.ForeignKey(
        Upload,
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
        help_text="Null until a bank statement row is absorbed.",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    recurrence = models.ForeignKey(
        Recurrence,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="occurrences",
    )
    client = models.ForeignKey(
        "Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
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

    @property
    def pending(self):
        return self.upload_id is None and not (self.metadata or {}).get("transfer")

    def __str__(self):
        return f"{self.operation_date} {self.amount} {self.concept[:40]}"


class FxRate(models.Model):
    """NBU daily quote: UAH per 1 unit of `currency`. EUR is stored; UAH is not."""

    date = models.DateField(db_index=True)
    currency = models.CharField(max_length=8)
    uah_per_unit = models.DecimalField(max_digits=18, decimal_places=8)

    class Meta:
        ordering = ["-date", "currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["date", "currency"], name="uniq_fx_date_currency"
            )
        ]

    def __str__(self):
        return f"{self.date} {self.currency} {self.uah_per_unit}"


class TransactionTag(models.Model):
    SOURCE_MANUAL = "manual"
    SOURCE_RULE = "rule"
    SOURCE_AI = "ai"
    SOURCE_SCHEDULE = "schedule"
    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_RULE, "Rule"),
        (SOURCE_AI, "AI"),
        (SOURCE_SCHEDULE, "Schedule"),
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

    UNIT_HOUR = "hour"
    UNIT_DAY = "day"
    UNIT_CHOICES = [
        (UNIT_HOUR, "Hour"),
        (UNIT_DAY, "Day"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="clients"
    )
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=40, blank=True)
    tax_id = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    vat_mode = models.CharField(
        max_length=20, choices=VAT_MODE_CHOICES, default=VAT_REVERSE_CHARGE
    )
    default_vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    default_description = models.CharField(max_length=255, blank=True)
    billing_unit = models.CharField(
        max_length=8, choices=UNIT_CHOICES, default=UNIT_HOUR
    )
    default_unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    currency = models.CharField(max_length=8, default="EUR")
    match_text = models.CharField(
        max_length=255,
        blank=True,
        help_text="Bank counterparty/concept text used to attach salary payments.",
    )
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_owner_client")
        ]

    def __str__(self):
        return self.name

    def display_name(self) -> str:
        return self.short_name or self.name

    def is_active(self, on: dt.date | None = None) -> bool:
        """True if a contract is in force, else if the engagement window covers `on`."""
        on = on or dt.date.today()
        agreements = [d for d in self.documents.all() if d.kind == Document.KIND_AGREEMENT]
        dated = [d for d in agreements if d.starts_on or d.ends_on or d.document_date]
        if dated:
            return any(d.in_force(on) for d in dated)
        return date_in_force(self.active_from, self.active_to, on)

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
    unit = models.CharField(max_length=8, blank=True, default=Client.UNIT_HOUR)
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


class Document(models.Model):
    """File registry: per-client (agreements, orders) or personal (tax, certificates)."""

    KIND_AGREEMENT = "agreement"
    KIND_ORDER = "order"
    KIND_OFFER = "offer"
    KIND_TAX_DECLARATION = "tax_declaration"
    KIND_TAX_CERTIFICATE = "tax_certificate"
    KIND_OTHER = "other"
    KIND_CHOICES = [
        (KIND_AGREEMENT, "Agreement"),
        (KIND_ORDER, "Order"),
        (KIND_OFFER, "Offer"),
        (KIND_TAX_DECLARATION, "Tax declaration"),
        (KIND_TAX_CERTIFICATE, "Tax certificate"),
        (KIND_OTHER, "Other"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents"
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="documents",
        help_text="Leave empty for personal documents (tax, certificates, etc.).",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER)
    title = models.CharField(max_length=255)
    document_date = models.DateField(null=True, blank=True)
    starts_on = models.DateField(
        null=True,
        blank=True,
        help_text="Contract start date. Defaults to the signed date for agreements.",
    )
    ends_on = models.DateField(
        null=True,
        blank=True,
        help_text="Termination date. Empty means the contract is still open.",
    )
    notes = models.TextField(blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to="documents/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-document_date", "-created_at"]
        indexes = [
            models.Index(fields=["owner", "kind"]),
            models.Index(fields=["owner", "client"]),
        ]

    def __str__(self):
        scope = self.client.name if self.client_id else "Personal"
        return f"{scope}: {self.title}"

    def in_force(self, on: dt.date | None = None) -> bool:
        on = on or dt.date.today()
        return date_in_force(self.starts_on or self.document_date, self.ends_on, on)


class Receipt(models.Model):
    """Incoming receipt/invoice photo or PDF, optionally linked to a bank tx later."""

    KIND_RECEIPT = "receipt"
    KIND_INVOICE = "invoice"
    KIND_OTHER = "other"
    KIND_CHOICES = [
        (KIND_RECEIPT, "Receipt"),
        (KIND_INVOICE, "Invoice"),
        (KIND_OTHER, "Other"),
    ]

    SOURCE_TELEGRAM = "telegram"
    SOURCE_WEB = "web"
    SOURCE_CHOICES = [
        (SOURCE_TELEGRAM, "Telegram"),
        (SOURCE_WEB, "Web"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="receipts"
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="receipts",
        help_text="Set once the matching bank transaction is known.",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_RECEIPT)
    merchant = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default="EUR")
    document_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    file = models.FileField(upload_to="receipts/", blank=True)
    extracted = models.JSONField(default=dict, blank=True)
    needs_parse = models.BooleanField(
        default=False,
        help_text="Vision parse queued (rate limit or album). Bot retries until done.",
    )
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=SOURCE_TELEGRAM
    )
    telegram_file_id = models.CharField(
        max_length=128,
        blank=True,
        help_text="Telegram file_id. Bot API download URLs expire; this id does not.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "transaction"]),
            models.Index(fields=["owner", "document_date"]),
        ]

    def __str__(self):
        label = self.merchant or self.original_filename or f"Receipt {self.pk}"
        return label


class PurchaseItem(models.Model):
    """One line from a parsed receipt/invoice, for spend analysis."""

    receipt = models.ForeignKey(
        Receipt, on_delete=models.CASCADE, related_name="items"
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_items",
    )
    name = models.CharField(max_length=255, help_text="Printed OCR text.")
    title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human label, e.g. 'beef mince' instead of 'BURGER M VACUN'.",
    )
    barcode = models.CharField(max_length=64, blank=True, db_index=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit_price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    category = models.CharField(max_length=80, blank=True, db_index=True)
    tags = models.ManyToManyField(Tag, related_name="purchase_items", blank=True)
    telegram_photo_file_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.title or self.name

    @property
    def label(self) -> str:
        return self.title or self.name


class TelegramLink(models.Model):
    """Maps a Telegram user to the app owner and stores recent chat turns."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="telegram_links",
    )
    telegram_user_id = models.BigIntegerField(unique=True)
    chat_id = models.BigIntegerField()
    messages = models.JSONField(default=list, blank=True)
    pending_item_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Next Telegram photo is stored as this purchase item's picture.",
    )
    pending_upload_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Statement waiting for the user to pick an account.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["telegram_user_id"])]

    def __str__(self):
        return f"tg:{self.telegram_user_id} → {self.owner}"
