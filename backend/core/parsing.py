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
    "liquidacion", "comision", "devolucion", "domiciliacion", "payment",
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
    # Santander's English xlsx uses U+2212 MINUS SIGN, which is not ASCII '-'.
    s = re.sub(r"[^\d,.\-]", "", str(value).strip().replace("\u2212", "-"))
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
        if "valor" in h or "value date" in h or "completed date" in h:
            cols.setdefault("value_date", idx)
        elif (
            "fecha" in h
            or "started date" in h
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
        if "commission" in h or h == "fee" or "коміс" in h or "комис" in h:
            cols.setdefault("commission", idx)
        if h == "type":
            cols.setdefault("type", idx)
        if h in ("state", "status"):
            cols.setdefault("state", idx)
        if h == "currency":
            cols.setdefault("currency", idx)
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


def _card_last4(text: str) -> str:
    """Last 4 of a PAN sitting in its own cell. Never keep the full number."""
    compact = text.replace(" ", "")
    if compact.isdigit() and 13 <= len(compact) <= 19:
        return compact[-4:]
    return ""


def _append_meta_name(meta: dict, piece: str) -> None:
    piece = (piece or "").strip()
    if not piece or piece.lower() in meta["account_name"].lower():
        return
    meta["account_name"] = (meta["account_name"] + " " + piece).strip()


def _extract_meta(matrix: list[list], header_row: int, header: list[str]) -> dict:
    meta = {"account_name": "", "account_iban": "", "account_holder": "",
            "currency": _detect_currency(matrix, header)}
    pre = matrix[:header_row]
    for r, row in enumerate(pre):
        for c, cell in enumerate(row):
            text = _cell_str(cell)
            if not text:
                continue
            last4 = _card_last4(text)
            if last4:
                _append_meta_name(meta, f"****{last4}")
                continue
            m = IBAN_RE.search(text.replace(" ", ""))
            if m and not meta["account_iban"]:
                meta["account_iban"] = m.group(1)
            low = text.lower()
            if (
                "cuenta" in low
                or "credito" in low
                or "crédito" in low
                or "credit" in low
                or "tarjeta" in low
                or low.startswith("card number")
                or low.startswith("номер карт")
                or low.startswith("card:")
            ):
                # "Card number: 5358 **** **** 1026, ..." / "CREDITO SANTANDER"
                label = text.split(":", 1)[1].strip() if ":" in text else text
                _append_meta_name(meta, label)
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


STATEMENT_EXTS = {"xls", "xlsx", "csv"}
STATEMENT_MIMES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def is_statement_file(filename: str, mime: str = "", data: bytes = b"") -> bool:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext in STATEMENT_EXTS:
        return True
    mime = (mime or "").split(";")[0].strip().lower()
    if mime in STATEMENT_MIMES:
        return True
    return bool(data) and data[:8] == _OLE_SIG


def _norm_iban(value: str) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def match_accounts(accounts, meta: dict, filename: str = "") -> list:
    """Narrow accounts using IBAN, card digits, bank name, currency.

    Returns one account when unique, otherwise the remaining candidates to ask.
    """
    accounts = list(accounts)
    if not accounts:
        return []
    meta = meta or {}
    iban = _norm_iban(meta.get("account_iban") or "")
    currency = (meta.get("currency") or "").upper()
    blob = f"{filename or ''} {meta.get('account_name') or ''} {meta.get('account_holder') or ''}".lower()
    last4s = re.findall(r"\d{4}", meta.get("account_name") or "")

    pool = accounts
    by_iban = [a for a in pool if iban and _norm_iban(a.iban) == iban]
    if len(by_iban) == 1:
        return by_iban
    if by_iban:
        pool = by_iban

    unmatched_card = False
    if last4s:
        by_card = [
            a for a in pool if any(d in f"{a.name} {a.bank} {a.iban}" for d in last4s)
        ]
        if len(by_card) == 1:
            return by_card
        if by_card:
            pool = by_card
        else:
            unmatched_card = True

    # Card / Revolut exports have no IBAN. Drop checking accounts before a
    # bank-name hit can unique-match e.g. "Santander" current account.
    if not iban:
        no_iban = [a for a in pool if not _norm_iban(a.iban)]
        if no_iban:
            pool = no_iban

    named = []
    for a in pool:
        for label in (a.name, a.bank):
            if label and len(label) >= 3 and label.lower() in blob:
                named.append(a)
                break
    if len(named) == 1:
        return named
    if named:
        pool = named

    if currency:
        by_cur = [a for a in pool if (a.currency or "").upper() == currency]
        if by_cur:
            pool = by_cur

    # Card last4 present but on no account: ask instead of dumping onto Revolut.
    if unmatched_card and len(pool) == 1:
        return list(accounts)
    return pool


def pick_account(accounts, text: str):
    """Map a user reply ('2', 'white', 'Monobank white') to one account."""
    t = (text or "").strip().lower()
    if not t:
        return None
    accounts = list(accounts)
    if t.isdigit():
        idx = int(t) - 1
        if 0 <= idx < len(accounts):
            return accounts[idx]
    exact = [a for a in accounts if a.name.lower() == t]
    if len(exact) == 1:
        return exact[0]
    partial = [a for a in accounts if t in a.name.lower()]
    if len(partial) == 1:
        return partial[0]
    return None


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
        state = _cell_str(col("state")).upper()
        if state in {
            "DECLINED",
            "FAILED",
            "REVERTED",
            "REVERSED",
            "CANCELLED",
            "CANCELED",
        }:
            continue
        balance = parse_decimal(col("balance"))
        value_date = parse_date(col("value_date"))

        # Optional enrichment columns (Monobank, Revolut, and similar).
        extras = {}
        tx_type = _cell_str(col("type"))
        if tx_type:
            extras["type"] = tx_type
        row_cur = _cell_str(col("currency")).upper()
        currency = row_cur if row_cur in CURRENCIES else meta["currency"]
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
            # Revolut Fee is extra to Amount and hits the balance. Monobank
            # "commission" sits beside an already-net card-currency amount.
            fee_header = ""
            idx = cols.get("commission")
            if idx is not None and idx < len(header):
                fee_header = header[idx].lower()
            if fee_header == "fee":
                amount = amount - commission
                extras["fee_in_amount"] = True
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
                "currency": currency,
                "metadata": extras,
                "dedupe_hash": dedupe_hash(op_date, amount, concept, balance),
            }
        )

    if not rows:
        raise ParseError("No transaction rows were found below the header.")
    return {"meta": meta, "rows": rows}


def _self_check():
    from types import SimpleNamespace as N

    accs = [
        N(name="Revolut", bank="Revolut", iban="", currency="EUR"),
        N(name="Santander", bank="Santander", iban="ES8700493328862814076200", currency="EUR"),
        N(name="Santander credit", bank="Santander", iban="", currency="EUR"),
        N(name="Monobank white", bank="Monobank", iban="UA493220010000026202305133293", currency="UAH"),
        N(name="Monobank black", bank="Monobank", iban="UA493220010000026202305133293", currency="UAH"),
    ]
    assert [a.name for a in match_accounts(accs, {"account_iban": "ES8700493328862814076200", "currency": "EUR"})] == ["Santander"]
    assert {a.name for a in match_accounts(accs, {"account_iban": "UA493220010000026202305133293", "account_name": "5358 **** **** 1026", "currency": "UAH"})} == {
        "Monobank white",
        "Monobank black",
    }
    named = list(accs)
    named[3] = N(name="Monobank white 1026", bank="Monobank", iban="UA493220010000026202305133293", currency="UAH")
    assert [a.name for a in match_accounts(named, {"account_iban": "UA493220010000026202305133293", "account_name": "5358 **** **** 1026", "currency": "UAH"})] == ["Monobank white 1026"]
    assert {a.name for a in match_accounts(accs, {"account_iban": "", "currency": "EUR"})} == {
        "Revolut",
        "Santander credit",
    }
    credit_meta = {
        "account_iban": "",
        "account_name": "CREDITO SANTANDER ****4883",
        "currency": "EUR",
    }
    assert [a.name for a in match_accounts(accs, credit_meta)] == ["Santander credit"]
    with_last4 = list(accs)
    with_last4[2] = N(name="Santander credit 4883", bank="Santander", iban="", currency="EUR")
    assert [a.name for a in match_accounts(with_last4, credit_meta)] == ["Santander credit 4883"]
    no_credit = [a for a in accs if a.name != "Santander credit"]
    assert {a.name for a in match_accounts(no_credit, credit_meta)} == {a.name for a in no_credit}
    assert pick_account(accs, "white").name == "Monobank white"
    assert pick_account(accs, "2").name == "Santander"
    matrix = [
        ["", "", "CREDITO SANTANDER", "Date"],
        ["", "", "4000000000004883", "20/08/2026 | 12:32:15"],
        ["", "", "Holder"],
        ["", "", "ZELENYUK OLEKSIY"],
        [],
        ["Transactions"],
        ["Transaction date", "Description", "Amount", "Currency"],
        ["18/08/2026", "SHOP", "\u22124,05", "EUR"],
    ]
    header_row = _find_header_row(matrix)
    header = [_cell_str(c) for c in matrix[header_row]]
    meta = _extract_meta(matrix, header_row, header)
    assert "4883" in meta["account_name"]
    assert "santander" in meta["account_name"].lower()
    assert "4000000000004883" not in meta["account_name"]
    assert "ZELENYUK" in meta["account_holder"].upper()
    assert not meta["account_iban"]
    assert parse_decimal(matrix[7][2]) == Decimal("-4.05")
    assert is_statement_file("report.xls")
    assert not is_statement_file("photo.jpg", "image/jpeg")
    assert parse_decimal("\u2212146,99") == Decimal("-146.99")
    assert parse_decimal("-146,99") == Decimal("-146.99")
    print("ok")


if __name__ == "__main__":
    _self_check()
