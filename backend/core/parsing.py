"""Bank statement parsing.

A thin dispatcher picks a reader by file extension. Every reader returns a
uniform matrix of rows (list[list[cell]]) where cells are native Python values
(str / float / datetime.date). The shared normalizer then locates the header
row, maps columns, extracts account metadata and yields normalized transaction
dicts.

Adding a new bank/format = add one reader that returns a matrix. Nothing else
changes.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
from decimal import Decimal, InvalidOperation

CURRENCIES = {
    "EUR", "USD", "GBP", "CHF", "PLN", "SEK", "NOK", "DKK", "JPY",
    "UAH", "AUD", "CAD", "CNY", "CZK", "HUF", "RON", "TRY", "BGN",
}
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{10,30})\b")

# Header detection: a row is the header if it matches at least two of these.
# Includes BBVA (ES), Monobank (EN/UA), and generic English.
HEADER_TOKENS = (
    "fecha", "concepto", "importe", "saldo",
    "date", "amount", "balance", "description",
    "дата", "опис", "описание", "сума", "сумма", "залишок", "баланс",
)

# Leading transaction-type words to strip when guessing the counterparty.
_TYPE_PREFIXES = (
    "recibo", "transferencia", "transf", "traspaso", "bizum", "pago", "pagos",
    "adeudo", "adeudos", "compra", "cargo", "abono", "ingreso", "nomina",
    "liquidacion", "comision", "devolucion", "domiciliacion",
)
# Connectors after a type word ("Transferencia de Juan", "Bizum a Maria").
_CONNECTORS = ("a favor de ", "de ", "a ", "para ", "from ", "to ")
# Spanish company legal-form suffix; the name usually ends here.
_LEGAL_SUFFIX_RE = re.compile(
    r"\bS\.?\s?(?:L\.?\s?U?|A|C|L\.?\s?L|Coop)\.?", re.IGNORECASE
)
# Markers that signal the start of reference/detail noise.
_MARKER_RE = re.compile(
    r"\bN[\u00ba\u00b0o]\s*Recibo\b|\bRef\.?\b|\bMandato\b|\bConcepto\b", re.IGNORECASE
)


def extract_counterparty(concept: str) -> str:
    """Best-effort merchant/payer name from a free-text bank concept.

    Tuned for the BBVA layout (e.g. "Recibo Colegio Alfinach, S.l. ... Nº Recibo
    ... Ref. Mandato ...") but degrades gracefully for transfers and unknown
    formats. Not exact; refined over time and overridable by rules/AI.
    """
    if not concept:
        return ""
    text = re.sub(r"\s+", " ", str(concept)).strip()
    low = text.lower()

    for prefix in _TYPE_PREFIXES:
        if low.startswith(prefix + " ") or low == prefix:
            text = text[len(prefix):].strip()
            low = text.lower()
            break

    for conn in _CONNECTORS:
        if low.startswith(conn):
            text = text[len(conn):].strip()
            break

    suffix = _LEGAL_SUFFIX_RE.search(text)
    if suffix:
        candidate = text[: suffix.end()]
    else:
        marker = _MARKER_RE.search(text)
        candidate = text[: marker.start()] if marker else text
        digits = re.search(r"\d{4,}", candidate)
        if digits:
            candidate = candidate[: digits.start()]
        candidate = " ".join(candidate.split()[:6])

    candidate = candidate.strip(" ,.-\t").strip()
    # Monobank/merchant codes often append a numeric suffix (e.g. SUBSCRIBESTAR202753808).
    candidate = re.sub(r"(?<=[A-Za-z])\d{6,}$", "", candidate).strip()
    return candidate[:255]


class UnsupportedFormat(Exception):
    pass


class ParseError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Format readers -> matrix of native cell values
# --------------------------------------------------------------------------- #
def _read_xls(path: str) -> list[list]:
    import xlrd  # only needed for legacy .xls

    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_index(0)
    matrix = []
    for r in range(sheet.nrows):
        row = []
        for c in range(sheet.ncols):
            ctype = sheet.cell_type(r, c)
            value = sheet.cell_value(r, c)
            if ctype == xlrd.XL_CELL_DATE:
                value = xlrd.xldate.xldate_as_datetime(value, book.datemode).date()
            row.append(value)
        matrix.append(row)
    return matrix


def _read_xlsx(path: str) -> list[list]:
    from openpyxl import load_workbook

    # Pass a binary handle (not the path) so openpyxl validates the archive by
    # content instead of the file extension. Some banks (e.g. Monobank) export
    # real OOXML but name the file ".xls".
    with open(path, "rb") as fh:
        wb = load_workbook(fh, read_only=True, data_only=True)
        try:
            ws = wb.active
            matrix = [
                [
                    v.date() if isinstance(v, dt.datetime) else ("" if v is None else v)
                    for v in row
                ]
                for row in ws.iter_rows(values_only=True)
            ]
        finally:
            wb.close()
    return matrix


def _read_csv(path: str) -> list[list]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
        return [list(row) for row in csv.reader(fh, dialect)]


READERS = {
    "xls": _read_xls,
    "xlsx": _read_xlsx,
    "csv": _read_csv,
}

# Magic-byte signatures so we pick the right reader even when the extension
# lies about the real format (Monobank exports OOXML as ".xls").
_ZIP_SIG = b"PK\x03\x04"  # .xlsx (zip container)
_OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .xls (OLE2)


def _select_reader(path: str, ext: str):
    """Choose a reader by file content first, falling back to the extension."""
    if ext == "csv":
        return _read_csv
    try:
        with open(path, "rb") as fh:
            sig = fh.read(8)
    except OSError:
        sig = b""
    if sig.startswith(_ZIP_SIG):
        return _read_xlsx
    if sig.startswith(_OLE_SIG):
        return _read_xls
    return READERS.get(ext)


# --------------------------------------------------------------------------- #
# Value coercion helpers
# --------------------------------------------------------------------------- #
def parse_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = re.sub(r"[^\d,.\-]", "", str(value).strip())
    if not s or s in ("-", ".", ","):
        return None
    if "," in s and "." in s:
        # The rightmost separator is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if value is None or value == "":
        return None
    s = str(value).strip()
    # Some exports append a time: "23/06/2026 | 13:21:08"
    s = s.split("|")[0].split(" ")[0].strip()
    for fmt in (
        "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%m/%d/%Y",
        "%d.%m.%Y", "%d.%m.%y",
    ):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _cell_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value).strip()


# --------------------------------------------------------------------------- #
# Header + column mapping
# --------------------------------------------------------------------------- #
def _find_header_row(matrix: list[list]) -> int:
    for i, row in enumerate(matrix):
        joined = " ".join(_cell_str(c).lower() for c in row)
        hits = sum(1 for tok in HEADER_TOKENS if tok in joined)
        if hits >= 2:
            return i
    raise ParseError("Could not locate a header row (expected columns like "
                     "FECHA / CONCEPTO / IMPORTE / SALDO).")


def _map_columns(header: list[str]) -> dict:
    """Map header labels to logical fields.

    Monobank ships both a card-currency amount (what hits the balance) and a
    foreign "operation amount". Prefer the card-currency column when present.
    """
    cols = {}
    for idx, raw in enumerate(header):
        h = raw.lower()
        if not h:
            continue
        if "valor" in h or "value date" in h:
            cols.setdefault("value_date", idx)
        elif (
            "fecha" in h
            or "date and time" in h
            or "date" in h
            or "дата" in h
        ):
            cols.setdefault("operation_date", idx)
        if (
            "concepto" in h
            or "concept" in h
            or "descrip" in h
            or h in ("опис", "описание")
            or h.startswith("опис")
            or h.startswith("описание")
        ):
            cols.setdefault("concept", idx)
        # Card / account currency amount (Monobank) beats foreign op amount.
        if (
            "card currency amount" in h
            or "валюті картки" in h
            or "валюте карты" in h
            or "у валюті рахунку" in h
        ):
            cols["amount"] = idx
        elif (
            "importe" in h
            or ("amount" in h and "operation" not in h and "cashback" not in h
                and "commission" not in h)
            or ("сума" in h and "операц" not in h and "кешбек" not in h
                and "коміс" not in h)
            or ("сумма" in h and "операц" not in h)
        ):
            cols.setdefault("amount", idx)
        if "saldo" in h or "balance" in h or "залишок" in h or "баланс" in h:
            cols.setdefault("balance", idx)
        if h in ("mcc",) or h.startswith("mcc"):
            cols.setdefault("mcc", idx)
        if "operation currency" in h or "валюта операц" in h:
            cols.setdefault("operation_currency", idx)
        if (
            "operation amount" in h
            or "сума операц" in h
            or "сумма операц" in h
        ):
            cols.setdefault("operation_amount", idx)
        if "commission" in h or "коміс" in h or "комис" in h:
            cols.setdefault("commission", idx)
        if "cashback" in h or "кешбек" in h or "кэшбек" in h:
            cols.setdefault("cashback", idx)
    # Last-resort amount: accept a lone "operation amount" if nothing else matched.
    if "amount" not in cols:
        for idx, raw in enumerate(header):
            h = raw.lower()
            if "operation amount" in h or "сума операц" in h or "сумма операц" in h:
                cols["amount"] = idx
                break
    missing = {"operation_date", "concept", "amount"} - cols.keys()
    if missing:
        raise ParseError(f"Missing required columns: {', '.join(sorted(missing))}")
    return cols


def _detect_currency(matrix: list[list], header: list[str]) -> str:
    for cell in header:
        for token in _cell_str(cell).upper().split():
            if token in CURRENCIES:
                return token
    for row in matrix:
        for cell in row:
            for token in _cell_str(cell).upper().replace(",", " ").split():
                if token in CURRENCIES:
                    return token
    return "EUR"


def _extract_meta(matrix: list[list], header_row: int, header: list[str]) -> dict:
    meta = {"account_name": "", "account_iban": "", "account_holder": "",
            "currency": _detect_currency(matrix, header)}
    pre = matrix[:header_row]
    for r, row in enumerate(pre):
        for c, cell in enumerate(row):
            text = _cell_str(cell)
            if not text:
                continue
            m = IBAN_RE.search(text.replace(" ", ""))
            if m and not meta["account_iban"]:
                meta["account_iban"] = m.group(1)
            low = text.lower()
            if not meta["account_name"] and (
                "cuenta" in low
                or low.startswith("card number")
                or low.startswith("номер карт")
                or low.startswith("card:")
            ):
                # "Card number: 5358 **** **** 1026, ..." -> keep a short label.
                if ":" in text:
                    meta["account_name"] = text.split(":", 1)[1].strip()
                else:
                    meta["account_name"] = text
            # Monobank/other inline "Label: value" holder lines.
            if not meta["account_holder"] and (
                low.startswith("client:")
                or low.startswith("holder:")
                or low.startswith("клієнт:")
                or low.startswith("клиент:")
            ):
                meta["account_holder"] = text.split(":", 1)[1].strip()
            # A label cell like "Titular" sits directly above the holder value.
            if low in ("titular", "holder", "titular:") and r + 1 < len(pre):
                below = _cell_str(pre[r + 1][c]) if c < len(pre[r + 1]) else ""
                if below:
                    meta["account_holder"] = below
    return meta


def dedupe_hash(operation_date, amount, concept, balance) -> str:
    key = f"{operation_date}|{amount}|{concept}|{balance}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def parse(path: str, filename: str) -> dict:
    """Parse a statement file into {"meta": {...}, "rows": [ {...}, ... ]}."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    reader = _select_reader(path, ext)
    if reader is None:
        raise UnsupportedFormat(
            f"Unsupported file type '.{ext}'. Supported: {', '.join(READERS)}."
        )

    matrix = reader(path)
    if not matrix:
        raise ParseError("The file appears to be empty.")

    header_row = _find_header_row(matrix)
    header = [_cell_str(c) for c in matrix[header_row]]
    cols = _map_columns(header)
    meta = _extract_meta(matrix, header_row, header)

    rows = []
    for raw in matrix[header_row + 1:]:
        def col(name):
            idx = cols.get(name)
            return raw[idx] if idx is not None and idx < len(raw) else None

        op_date = parse_date(col("operation_date"))
        amount = parse_decimal(col("amount"))
        concept = _cell_str(col("concept"))
        # Skip blank/separator/total rows.
        if op_date is None or amount is None:
            continue
        balance = parse_decimal(col("balance"))
        value_date = parse_date(col("value_date"))

        # Optional enrichment columns (Monobank and similar).
        extras = {}
        mcc = _cell_str(col("mcc"))
        if mcc and mcc not in ("—", "-"):
            extras["mcc"] = mcc
        op_cur = _cell_str(col("operation_currency")).upper()
        if op_cur and op_cur not in ("—", "-", meta["currency"]):
            extras["operation_currency"] = op_cur
            op_amt = parse_decimal(col("operation_amount"))
            if op_amt is not None:
                extras["operation_amount"] = str(op_amt)
        commission = parse_decimal(col("commission"))
        if commission:
            extras["commission"] = str(commission)
        cashback = parse_decimal(col("cashback"))
        if cashback:
            extras["cashback"] = str(cashback)

        rows.append(
            {
                "operation_date": op_date,
                "value_date": value_date,
                "concept": concept,
                "counterparty": extract_counterparty(concept),
                "amount": amount,
                "balance": balance,
                "currency": meta["currency"],
                "metadata": extras,
                "dedupe_hash": dedupe_hash(op_date, amount, concept, balance),
            }
        )

    if not rows:
        raise ParseError("No transaction rows were found below the header.")
    return {"meta": meta, "rows": rows}
