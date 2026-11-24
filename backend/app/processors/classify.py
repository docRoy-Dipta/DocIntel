"""Rule-based page classification and bundle splitting.

Rules first (fast, free, explainable). An LLM can be added later for pages the rules are unsure about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PAGE_OF = re.compile(r"\bpage\s+(\d+)\s*(?:of|/)\s*(\d+)\b", re.I)
_MONEY = re.compile(r"\d[\d,]*\.\d{2}\b")
_INVOICE_NO = re.compile(r"\binvoice\s*(?:no\.?|number|num|#|id)\b|\binv\s*(?:no\.?|#)", re.I)
_RECEIPT_NO = re.compile(r"\breceipt\s*(?:no\.?|number|num|#|id)\b", re.I)
_TOTAL_WORDS = re.compile(r"\b(sub\s*total|total|amount due|balance due|vat|tax|gst)\b", re.I)


@dataclass(frozen=True)
class PageClass:
    doc_type: str  # invoice|receipt|other
    score: float
    is_start: bool
    page_of: tuple[int, int] | None
    looks_like_continuation: bool


def classify_page(text: str) -> PageClass:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    head = " ".join(lines[:6]).lower()
    body = text.lower()
    page_of_match = _PAGE_OF.search(text)
    page_of = (int(page_of_match[1]), int(page_of_match[2])) if page_of_match else None

    inv = 0.0
    rec = 0.0
    if re.search(r"\b(tax\s+)?invoice\b", head):
        inv += 3
    if re.search(r"\breceipt\b", head):
        rec += 3
    if _INVOICE_NO.search(text):
        inv += 2
    if _RECEIPT_NO.search(text):
        rec += 2
    inv += 1.0 * sum(k in body for k in ("bill to", "amount due", "invoice date", "due date", "balance due"))
    rec += 1.0 * sum(
        k in body
        for k in (
            "payment received",
            "amount paid",
            "paid in full",
            "thank you for your payment",
            "payment method",
        )
    )

    if max(inv, rec) < 2:
        doc_type, score = "other", max(inv, rec)
    elif rec > inv:
        doc_type, score = "receipt", rec
    else:
        doc_type, score = "invoice", inv

    title = bool(re.search(r"\b(tax\s+)?(invoice|receipt)\b", head))
    has_id = bool(_INVOICE_NO.search(text) or _RECEIPT_NO.search(text))
    continuation_page = page_of is not None and page_of[0] > 1
    is_start = doc_type != "other" and title and has_id and not continuation_page

    looks_cont = continuation_page or (len(_MONEY.findall(text)) >= 3 and bool(_TOTAL_WORDS.search(text)) and not title)
    return PageClass(doc_type, score, is_start, page_of, looks_cont)


@dataclass
class Span:
    doc_type: str
    start_page: int
    end_page: int
    score: float


def split_pages(pages: list[tuple[int, str]]) -> list[Span]:
    """Group consecutive pages into logical documents (an invoice may span pages; a file may hold many)."""
    spans: list[Span] = []
    current: Span | None = None
    for number, text in pages:
        pc = classify_page(text)
        if pc.is_start:
            current = Span(pc.doc_type, number, number, pc.score)
            spans.append(current)
        elif current is not None and current.doc_type != "other" and pc.looks_like_continuation:
            current.end_page = number
        elif pc.doc_type != "other":  # invoice-like page without a clear title: its own document
            current = Span(pc.doc_type, number, number, pc.score)
            spans.append(current)
        else:
            if current is not None and current.doc_type == "other" and current.end_page == number - 1:
                current.end_page = number
            else:
                current = Span("other", number, number, pc.score)
                spans.append(current)
    return spans
