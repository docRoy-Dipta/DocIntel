"""Turn a RawInvoice into scored, grounded results with bounding boxes."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.ai.grounding import is_field_grounded, is_line_grounded
from app.ai.schemas import FIELD_NAMES, REQUIRED_FIELDS, PageText, RawField, RawInvoice
from app.domain.dates import parse_date
from app.domain.money import parse_amount
from app.processors.layout import locate

_TEXT_LAYER_CONF = 0.97
_AMOUNT_FIELDS = {"subtotal", "tax", "total_amount"}


@dataclass
class FieldResult:
    name: str
    value: str | None
    raw_text: str | None
    page: int | None
    bbox: Any
    source: str
    confidence: float
    grounded: bool
    rejected_value: str | None = None  # value dropped because it could not be grounded


@dataclass
class LineResult:
    position: int
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    page: int | None
    raw_text: str | None
    bbox: Any
    confidence: float


@dataclass
class ScoredInvoice:
    fields: dict[str, FieldResult]
    line_items: list[LineResult]
    rejected_lines: list[dict[str, object]] = field(default_factory=list)
    overall_confidence: float = 0.0


def _format_ok(name: str, value: str) -> bool:
    if name in _AMOUNT_FIELDS or name == "tax_rate":
        return parse_amount(value) is not None
    if name == "invoice_date":
        return parse_date(value).value is not None
    return bool(value.strip())


def score_extraction(raw: RawInvoice, pages: list[PageText]) -> ScoredInvoice:
    by_number = {p.page_number: p for p in pages}
    texts = {p.page_number: p.text for p in pages}
    results: dict[str, FieldResult] = {}

    for name in FIELD_NAMES:
        rf: RawField = getattr(raw, name)
        if rf.value is None:
            results[name] = FieldResult(name, None, None, None, None, "extracted", 0.0, True)
            continue
        grounded = is_field_grounded(name, rf, texts)
        page = by_number.get(rf.page) if rf.page else None
        bbox: list[float] | None = None
        ocr_conf: float | None = None
        snippet = rf.raw_text or rf.value
        if page is not None and page.words and snippet:
            hit = locate(page.words, snippet)
            if hit:
                bbox, ocr_conf = hit
        if ocr_conf is None and page is not None and page.method == "ocr":
            ocr_conf = page.ocr_confidence
        base = (
            _TEXT_LAYER_CONF if (page is None or page.method != "ocr") else (ocr_conf if ocr_conf is not None else 0.8)
        )
        conf = base * (1.0 if _format_ok(name, rf.value) else 0.5) * (1.0 if grounded else 0.3)
        if rf.source == "inferred":
            conf = min(conf, 0.6)
        if not grounded:
            # Never keep a value that is not in the document.
            results[name] = FieldResult(name, None, None, rf.page, None, rf.source, 0.0, False, rejected_value=rf.value)
            continue
        results[name] = FieldResult(name, rf.value, rf.raw_text, rf.page, bbox, rf.source, round(conf, 3), True)

    lines: list[LineResult] = []
    rejected: list[dict[str, object]] = []
    for item in raw.line_items:
        if not is_line_grounded(item, texts):
            rejected.append(item.model_dump())
            continue
        page = by_number.get(item.page) if item.page else None
        bbox, ocr_conf = (None, None)
        if page is not None and page.words and item.raw_text:
            hit = locate(page.words, item.raw_text)
            if hit:
                bbox, ocr_conf = hit
        if ocr_conf is None and page is not None and page.method == "ocr":
            ocr_conf = page.ocr_confidence
        base = (
            _TEXT_LAYER_CONF if (page is None or page.method != "ocr") else (ocr_conf if ocr_conf is not None else 0.8)
        )
        lines.append(
            LineResult(
                position=len(lines) + 1,
                description=item.description,
                quantity=parse_amount(item.quantity),
                unit_price=parse_amount(item.unit_price),
                amount=parse_amount(item.amount),
                page=item.page,
                raw_text=item.raw_text,
                bbox=bbox,
                confidence=round(base, 3),
            )
        )

    req = [results[n].confidence for n in REQUIRED_FIELDS]
    overall = round(sum(req) / len(req), 3)
    return ScoredInvoice(results, lines, rejected, overall)
