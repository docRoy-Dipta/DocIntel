"""Grounding: a value is only accepted if it can be found in the source text.

This is the main defence against hallucination: an extractor (especially an LLM) may only return
what the document actually says.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.ai.schemas import RawField, RawLineItem
from app.domain.dates import parse_date
from app.domain.money import parse_amount

_AMOUNT_FIELDS = {"subtotal", "tax", "total_amount"}
_NUMBER_TOKEN = re.compile(r"\d[\d.,]*\d|\d")


def squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def amount_from_raw(raw: str) -> Decimal | None:
    """The amount in a quoted snippet such as 'Tax (10%)  $2.55': ignore percentages, take the last number."""
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*%", "", raw)
    tokens = _NUMBER_TOKEN.findall(cleaned)
    return parse_amount(tokens[-1]) if tokens else None


def _amount_in_text(value: str, text: str) -> bool:
    try:
        target = Decimal(value)
    except InvalidOperation:
        return False
    return any(parse_amount(tok) == target for tok in _NUMBER_TOKEN.findall(text))


def _date_in_text(value: str, text: str) -> bool:
    for line in text.splitlines():
        parsed = parse_date(line)
        if parsed.value and parsed.value.isoformat() == value:
            return True
    return False


def is_field_grounded(name: str, field: RawField, page_texts: dict[int, str]) -> bool:
    """True if the field's value is supported by the page text."""
    if field.value is None:
        return True
    if field.source == "inferred":
        return True  # inferred values are not in the text by definition; they are flagged instead
    haystack = page_texts.get(field.page) if field.page in page_texts else "\n".join(page_texts.values())
    haystack = haystack or ""
    if field.raw_text:
        if squash(field.raw_text) not in squash(haystack):
            return False
        # The normalised value must agree with the quoted text.
        if name in _AMOUNT_FIELDS:
            return amount_from_raw(field.raw_text) == Decimal(field.value) if _is_decimal(field.value) else False
        if name == "invoice_date":
            parsed = parse_date(field.raw_text)
            return parsed.value is not None and parsed.value.isoformat() == field.value
        if name == "tax_rate":
            return field.value in field.raw_text
        return squash(field.value) in squash(field.raw_text)
    if name in _AMOUNT_FIELDS:
        return _amount_in_text(field.value, haystack)
    if name == "invoice_date":
        return _date_in_text(field.value, haystack)
    return squash(field.value) in squash(haystack)


def _is_decimal(v: str) -> bool:
    try:
        Decimal(v)
        return True
    except InvalidOperation:
        return False


def is_line_grounded(item: RawLineItem, page_texts: dict[int, str]) -> bool:
    haystack = page_texts.get(item.page) if item.page in page_texts else "\n".join(page_texts.values())
    haystack = haystack or ""
    if item.raw_text:
        return squash(item.raw_text) in squash(haystack)
    ok = True
    if item.description:
        ok = ok and squash(item.description) in squash(haystack)
    if item.amount:
        ok = ok and _amount_in_text(item.amount, haystack)
    return ok and bool(item.description or item.amount)
