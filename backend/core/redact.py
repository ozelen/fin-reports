"""Redact bank details and amounts from uploaded PDFs for sharing."""
from __future__ import annotations

import html
import io
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.colors import black
from reportlab.pdfgen import canvas

from decimal import Decimal, InvalidOperation

from .models import Account, Client, Invoice

_SMALL = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)

_WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
    re.I | re.S,
)
_PAGE_RE = re.compile(
    r'<page[^>]*width="([\d.]+)"[^>]*height="([\d.]+)"[^>]*>(.*?)</page>',
    re.I | re.S,
)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
_MIN_NEEDLE = 6


class RedactError(ValueError):
    pass


@dataclass(frozen=True)
class _Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _int_words(n: int) -> str:
    if n < 0 or n > 999999:
        return ""
    if n < 20:
        return _SMALL[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f" {_SMALL[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_SMALL[hundreds]} hundred" + (f" and {_int_words(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    head = f"{_int_words(thousands)} thousand"
    return head + (f" {_int_words(rest)}" if rest else "")


def known_amounts(user) -> set[Decimal]:
    vals: set[Decimal] = set()
    for client in Client.objects.filter(owner=user):
        if client.default_unit_price:
            vals.add(Decimal(client.default_unit_price))
    for inv in Invoice.objects.filter(owner=user):
        for raw in (inv.unit_price, inv.net_amount, inv.total_amount, inv.vat_amount):
            if raw:
                vals.add(Decimal(raw))
    return {v for v in vals if v > 0}


def _parse_money_token(text: str) -> Decimal | None:
    raw = re.sub(r"(?i)(€|eur(o)?)", "", text).strip().replace(" ", "")
    if not raw:
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d{2}", raw):
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+\.\d{2}", raw):
        raw = raw.replace(",", "")
    elif re.fullmatch(r"\d+,\d{2}", raw):
        raw = raw.replace(",", ".")
    elif not re.fullmatch(r"\d+(\.\d{1,2})?", raw):
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _word_is_amount(idx: int, words: list[_Word], amounts: set[Decimal]) -> bool:
    if not amounts:
        return False
    value = _parse_money_token(words[idx].text)
    if value is None:
        return False
    ints = {int(a) for a in amounts}
    if value not in amounts and int(value) not in ints:
        return False
    token = words[idx].text
    if "€" in token or re.search(r"eur", token, re.I):
        return True
    if value >= 100:
        return True
    neighbors = []
    if idx:
        neighbors.append(words[idx - 1].text)
    if idx + 1 < len(words):
        neighbors.append(words[idx + 1].text)
    blob = " ".join(neighbors).lower()
    return any(key in blob for key in ("€", "eur", "euro", "day", "hour", "día", "hora"))


def secret_phrases(user) -> list[str]:
    phrases: list[str] = []
    for acc in Account.objects.filter(owner=user):
        for raw in (acc.iban, acc.bic, acc.correspondent_bic):
            if raw:
                phrases.append(raw)
                phrases.append(re.sub(r"\s+", "", raw))
    for amount in known_amounts(user):
        n = int(amount)
        phrases.append(f"{amount:.2f}")
        phrases.append(f"{amount:.2f}".replace(".", ","))
        phrases.append(f"€{n}")
        phrases.append(f"{n} EUR")
        phrases.append(f"{n} euro")
        if n >= 100:
            words = _int_words(n)
            if words:
                phrases.append(words)
                phrases.append(f"{words} euro")
    out = []
    seen = set()
    for phrase in phrases:
        needle = _alnum(phrase)
        if len(needle) < _MIN_NEEDLE or needle in seen:
            continue
        seen.add(needle)
        out.append(phrase)
    return out


def _needles(phrases: list[str], extra_text: str = "") -> list[str]:
    found = list(phrases)
    found.extend(_IBAN_RE.findall(extra_text or ""))
    out, seen = [], set()
    for phrase in found:
        needle = _alnum(phrase)
        if len(needle) < _MIN_NEEDLE or needle in seen:
            continue
        seen.add(needle)
        out.append(needle)
    return out


def _pdf_pages_bbox(pdf_path: Path) -> list[tuple[float, float, list[_Word]]]:
    try:
        html_out = subprocess.check_output(
            ["pdftotext", "-bbox", str(pdf_path), "-"],
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RedactError("Could not read PDF text for redaction.") from exc
    markup = html_out.decode("utf-8", errors="replace")
    pages = []
    for width, height, body in _PAGE_RE.findall(markup):
        words = [
            _Word(html.unescape(text), float(x0), float(y0), float(x1), float(y1))
            for x0, y0, x1, y1, text in _WORD_RE.findall(body)
        ]
        pages.append((float(width), float(height), words))
    if not pages:
        raise RedactError(
            "This PDF has no text layer, so it cannot be auto-redacted. "
            "Use a shareable copy or a text PDF."
        )
    return pages


def _hit_indexes(
    words: list[_Word], needles: list[str], amounts: set[Decimal] | None = None
) -> set[int]:
    chars: list[int] = []
    hay_parts: list[str] = []
    for i, word in enumerate(words):
        token = _alnum(word.text)
        hay_parts.append(token)
        chars.extend([i] * len(token))
    hay = "".join(hay_parts)
    hits: set[int] = set()
    for needle in needles:
        start = 0
        while True:
            pos = hay.find(needle, start)
            if pos < 0:
                break
            hits.update(chars[pos : pos + len(needle)])
            start = pos + 1
    if amounts:
        for i, _word in enumerate(words):
            if _word_is_amount(i, words, amounts):
                hits.add(i)
    return hits


def _render_page(image: Path, width: float, height: float, boxes: list[_Word]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    if image.is_file():
        c.drawImage(str(image), 0, 0, width=width, height=height)
    c.setFillColor(black)
    for word in boxes:
        x = word.x0 - 1
        y = height - word.y1 - 1
        c.rect(x, y, (word.x1 - word.x0) + 2, (word.y1 - word.y0) + 2, fill=1, stroke=0)
    c.showPage()
    c.save()
    return buf.getvalue()


def _merge_pdfs(parts: list[bytes]) -> bytes:
    if len(parts) == 1:
        return parts[0]
    # reportlab files are concatenated with pdfinfo/pdftk-less join via pypdf-free
    # trick: keep one canvas and replay — we already emit one file per page, so
    # stitch with poppler pdfunite when available.
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        paths = []
        for i, data in enumerate(parts, start=1):
            path = folder / f"p{i:04d}.pdf"
            path.write_bytes(data)
            paths.append(path)
        out = folder / "out.pdf"
        try:
            subprocess.check_call(
                ["pdfunite", *[str(p) for p in paths], str(out)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RedactError("Could not assemble the redacted PDF.") from exc
        return out.read_bytes()


def redact_pdf(
    data: bytes, phrases: list[str], amounts: set[Decimal] | None = None
) -> bytes:
    if not data.startswith(b"%PDF"):
        raise RedactError("Redaction is only available for PDFs.")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        src = folder / "src.pdf"
        src.write_bytes(data)
        pages = _pdf_pages_bbox(src)
        raw_text = " ".join(w.text for _, _, words in pages for w in words)
        needles = _needles(phrases, raw_text)
        if not needles and not amounts:
            raise RedactError("No bank details or amounts found to redact.")
        hits_any = False
        for _, _, words in pages:
            if _hit_indexes(words, needles, amounts):
                hits_any = True
                break
        if not hits_any:
            raise RedactError(
                "This PDF has no IBAN, BIC, or amounts from your profile. "
                "The original download is already safe for those fields."
            )
        try:
            subprocess.check_call(
                ["pdftoppm", "-png", "-r", "110", str(src), str(folder / "page")],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RedactError("Could not rasterize PDF for redaction.") from exc
        images = sorted(folder.glob("page*.png"))
        rendered = []
        for i, (width, height, words) in enumerate(pages):
            boxes = [words[j] for j in sorted(_hit_indexes(words, needles, amounts))]
            image = images[i] if i < len(images) else folder / "missing.png"
            rendered.append(_render_page(image, width, height, boxes))
        return _merge_pdfs(rendered)


def redact_name(filename: str) -> str:
    path = Path(filename or "document.pdf")
    return f"{path.stem}-redacted{path.suffix or '.pdf'}"
