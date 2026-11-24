"""Rule-based invoice extractor. Works offline, free, and is deterministic.

It is the baseline the AI extractor is compared against, and the fallback when no API key is set.
Every value it returns is copied from the document text, so it is grounded by construction.
"""

from __future__ import annotations

import re

from app.ai.schemas import PageText, RawField, RawInvoice, RawLineItem
from app.domain.dates import parse_date
from app.domain.money import detect_currency, parse_amount

_NUM = r"[-(]?(?:[A-Z]{3}\s?)?[^\w\s.,()\-]?\s?\d(?:[\d.,]*\d)?\)?"  # noqa: E501 - any single currency glyph is tolerated (OCR, odd fonts)
_MONEY_TOKEN = re.compile(_NUM)

_INVOICE_NO = re.compile(
    r"(?:invoice|inv)\s*(?:no\.?|number|num|#|id)\s*[:#\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/_.]*[A-Za-z0-9]|[A-Za-z0-9])",
    re.I,
)
_DATE_LABEL = re.compile(r"(?:invoice\s*date|date\s*of\s*issue|issue\s*date|date)\s*[:\-]?\s*(.+)$", re.I)
_PARTY_LABELS = {
    "supplier_name": re.compile(r"^\s*(?:from|supplier|vendor|seller|issued\s+by)\s*[:\-]\s*(.*)$", re.I),
    "customer_name": re.compile(r"^\s*(?:bill(?:ed)?\s+to|customer|client|sold\s+to)\s*[:\-]?\s*(.*)$", re.I),
}
_SUBTOTAL = re.compile(r"^\s*(?:sub\s*-?\s*total|net\s+(?:amount|total))\b", re.I)
_TAX = re.compile(r"^\s*(?:sales\s+tax|vat|gst|tax)\b", re.I)
_TOTAL = re.compile(r"^\s*(?:grand\s+total|total\s+(?:amount|due|payable)|amount\s+due|balance\s+due|total)\b", re.I)
_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_TABLE_HEADER = re.compile(r"\bdescription\b.*\b(?:amount|total|price|qty|quantity)\b", re.I)
_TITLE_WORDS = re.compile(r"^\s*(?:tax\s+)?(?:invoice|receipt|bill|statement)\b", re.I)
_LINE_A = re.compile(rf"^(?P<desc>[A-Za-z].*?)\s+(?P<qty>\d+(?:\.\d+)?)\s+(?P<unit>{_NUM})\s+(?P<amt>{_NUM})\s*$")
_LINE_B = re.compile(rf"^(?P<desc>[A-Za-z][^\d\n]*?)\s{{2,}}(?P<amt>{_NUM})\s*$")
_ADDRESSISH = re.compile(r"\b(street|st\.|road|rd\.|avenue|ave|floor|suite|p\.?o\.? box|tel|phone|email|@|www\.)", re.I)


def _last_amount(line: str) -> tuple[str, str] | None:
    """The amount at the end of a totals line (ignoring percentages). Returns (raw token, normalised)."""
    cleaned = _RATE.sub("", line)
    tokens = [m.group(0).strip() for m in _MONEY_TOKEN.finditer(cleaned)]
    tokens = [t for t in tokens if parse_amount(t) is not None]
    if not tokens:
        return None
    tok = tokens[-1]
    val = parse_amount(tok)
    return (tok, format(val, "f")) if val is not None else None


class HeuristicExtractor:
    name = "heuristic"
    model: str | None = None
    max_pages_per_call = 10**6

    def extract(self, pages: list[PageText], doc_type: str = "invoice") -> tuple[RawInvoice, dict[str, int]]:
        out = RawInvoice()
        lines: list[tuple[int, str]] = [
            (p.page_number, ln.strip()) for p in pages for ln in p.text.splitlines() if ln.strip()
        ]
        self._invoice_number(out, lines)
        self._date(out, lines)
        self._parties(out, lines, doc_type)
        self._amounts(out, lines)
        self._currency(out, lines)
        self._line_items(out, lines)
        return out, {}

    # --------------------------------------------------------------------- fields
    def _invoice_number(self, out: RawInvoice, lines: list[tuple[int, str]]) -> None:
        pattern = (
            _INVOICE_NO
            if _INVOICE_NO.search("\n".join(t for _, t in lines))
            else re.compile(
                r"(?:receipt)\s*(?:no\.?|number|num|#|id)\s*[:#\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/_.]*)",
                re.I,
            )
        )
        for page, text in lines:
            if m := pattern.search(text):
                out.invoice_number = RawField(value=m.group(1).strip(".,;"), raw_text=m.group(0).strip(), page=page)
                return

    def _date(self, out: RawInvoice, lines: list[tuple[int, str]]) -> None:
        for page, text in lines:
            if re.search(r"\b(due|payment)\s+date\b|\bdue\b", text, re.I):
                continue
            if m := _DATE_LABEL.search(text):
                parsed = parse_date(m.group(1))
                if parsed.value:
                    out.invoice_date = RawField(value=parsed.value.isoformat(), raw_text=m.group(0).strip(), page=page)
                    if parsed.ambiguous:
                        out.invoice_date.source = "inferred"  # day/month order was guessed
                    return

    def _parties(self, out: RawInvoice, lines: list[tuple[int, str]], doc_type: str) -> None:
        for name, pattern in _PARTY_LABELS.items():
            for idx, (page, text) in enumerate(lines):
                m = pattern.match(text)
                if not m:
                    continue
                value = m.group(1).strip()
                raw = text
                if not value and idx + 1 < len(lines):
                    page, value = lines[idx + 1]
                    raw = value
                value = re.split(r"\s{2,}", value)[0].strip()
                if value:
                    setattr(
                        out,
                        name,
                        RawField(value=value, raw_text=raw.strip() if raw != value else value, page=page),
                    )
                    break
        if out.supplier_name.value is None:
            for page, text in lines[:8]:
                if _TITLE_WORDS.match(text) or _ADDRESSISH.search(text) or not re.search(r"[A-Za-z]{3}", text):
                    continue
                if _INVOICE_NO.search(text) or _DATE_LABEL.search(text) or _PARTY_LABELS["customer_name"].match(text):
                    continue
                value = re.split(r"\s{2,}", text)[0].strip()
                out.supplier_name = RawField(value=value, raw_text=value, page=page)
                break

    def _amounts(self, out: RawInvoice, lines: list[tuple[int, str]]) -> None:
        for page, text in lines:
            for name, pattern in (("subtotal", _SUBTOTAL), ("tax", _TAX), ("total_amount", _TOTAL)):
                if pattern.match(text) and (amt := _last_amount(text)):
                    # Totals sit at the bottom of the document: the LAST match wins.
                    setattr(out, name, RawField(value=amt[1], raw_text=text, page=page))
                    if name == "tax" and (r := _RATE.search(text)):
                        out.tax_rate = RawField(value=r.group(1), raw_text=r.group(0), page=page)

    def _currency(self, out: RawInvoice, lines: list[tuple[int, str]]) -> None:
        for page, text in lines:
            if m := re.match(r"^\s*currency\s*[:\-]?\s*([A-Z]{3})\b", text, re.I):
                out.currency = RawField(value=m.group(1).upper(), raw_text=text, page=page)
                return
        preferred = [t for _, t in lines if _TOTAL.match(t)] + [t for _, t in lines]
        for text in preferred:
            code, source = detect_currency(text)
            if code:
                page = next(p for p, t in lines if t == text)
                snippet = next((s for s in (code, "$", "€", "£", "¥", "₹", "৳", "₩", "₫") if s in text), code)
                out.currency = RawField(
                    value=code,
                    raw_text=snippet,
                    page=page,
                    source="extracted" if source == "extracted" else "inferred",
                )
                return

    def _line_items(self, out: RawInvoice, lines: list[tuple[int, str]]) -> None:
        in_table = False
        for page, text in lines:
            if _TABLE_HEADER.search(text):
                in_table = True
                continue
            if _SUBTOTAL.match(text) or _TAX.match(text) or _TOTAL.match(text):
                in_table = False
                continue
            m = _LINE_A.match(text)
            if m:
                out.line_items.append(
                    RawLineItem(
                        description=m["desc"].strip(),
                        quantity=format(parse_amount(m["qty"]), "f") if parse_amount(m["qty"]) is not None else None,
                        unit_price=_fmt(m["unit"]),
                        amount=_fmt(m["amt"]),
                        raw_text=text,
                        page=page,
                    )
                )
                continue
            m = _LINE_B.match(text)
            if m and in_table:
                out.line_items.append(
                    RawLineItem(
                        description=m["desc"].strip(),
                        amount=_fmt(m["amt"]),
                        raw_text=text,
                        page=page,
                    )
                )


def _fmt(token: str) -> str | None:
    v = parse_amount(token)
    return format(v, "f") if v is not None else None
