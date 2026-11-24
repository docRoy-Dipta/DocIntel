"""Cross-document comparison: normalisation, record matching and field-by-field verdicts.

Everything here is deterministic and works on plain Python objects, so it is easy to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from app.domain.money import amounts_equal

MATCH, MISMATCH, UNCERTAIN = "match", "mismatch", "uncertain"
NOT_COMPARABLE = "not_comparable"  # nothing on one side/both sides to compare: reported, never a discrepancy
MISSING_LEFT, MISSING_RIGHT = "missing_in_left", "missing_in_right"

_COMPANY_SUFFIXES = {
    "ltd",
    "limited",
    "inc",
    "incorporated",
    "llc",
    "llp",
    "corp",
    "corporation",
    "co",
    "company",
    "plc",
    "gmbh",
    "sa",
    "ag",
    "pvt",
    "pte",
    "bv",
    "srl",
    "sas",
    "pty",
    "the",
}

HEADER_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total_amount",
    "currency",
)
NAME_FIELDS = {"supplier_name", "customer_name"}
AMOUNT_FIELDS = {"subtotal", "tax", "total_amount"}


@dataclass
class FieldValue:
    value: Any  # str | Decimal | date | None
    source: dict[str, Any] = field(default_factory=dict)  # document, page/sheet, cell, bbox...


@dataclass
class Record:
    """One invoice/receipt/spreadsheet row, ready to be compared."""

    ref: dict[str, Any]  # {"logical_id":..,"document_id":..,"filename":..,"pages":[a,b]}
    fields: dict[str, FieldValue] = field(default_factory=dict)
    line_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class FieldComparison:
    field: str
    verdict: str
    left_value: str | None
    right_value: str | None
    left_source: dict[str, Any]
    right_source: dict[str, Any]
    rule: str


@dataclass
class RecordPair:
    left: Record | None
    right: Record | None
    matched_by: str
    comparisons: list[FieldComparison] = field(default_factory=list)


def normalize_invoice_number(value: str | None) -> str:
    if not value:
        return ""
    s = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    stripped = s.lstrip("0")
    return stripped or s


def normalize_company(value: str | None) -> str:
    if not value:
        return ""
    s = re.sub(r"[^\w\s]", " ", value.lower())
    tokens = [t for t in s.split() if t not in _COMPANY_SUFFIXES]
    return " ".join(tokens)


def name_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_company(a), normalize_company(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / len(ta | tb)
    return max(seq, jacc)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def compare_field(
    name: str,
    left: FieldValue | None,
    right: FieldValue | None,
    *,
    amount_tolerance: Decimal = Decimal("0.01"),
    date_tolerance_days: int = 0,
    name_match: float = 0.85,
    name_uncertain: float = 0.6,
) -> FieldComparison:
    lv = left.value if left else None
    rv = right.value if right else None
    ls = left.source if left else {}
    rs = right.source if right else {}

    def result(verdict: str, rule: str) -> FieldComparison:
        return FieldComparison(name, verdict, _text(lv), _text(rv), ls, rs, rule)

    if lv in (None, "") and rv in (None, ""):
        return result(NOT_COMPARABLE, "Neither document has this field.")
    if lv in (None, ""):
        return result(MISSING_LEFT, "Present only on the right.")
    if rv in (None, ""):
        return result(MISSING_RIGHT, "Present only on the left.")

    if name == "invoice_number":
        ok = normalize_invoice_number(str(lv)) == normalize_invoice_number(str(rv))
        return result(MATCH if ok else MISMATCH, "Equal after removing punctuation, case and leading zeros.")
    if name in AMOUNT_FIELDS:
        ok = amounts_equal(Decimal(lv), Decimal(rv), amount_tolerance)
        return result(MATCH if ok else MISMATCH, f"Equal within {amount_tolerance}.")
    if name == "invoice_date":
        diff = abs((lv - rv).days)
        return result(
            MATCH if diff <= date_tolerance_days else MISMATCH,
            f"Dates within {date_tolerance_days} day(s).",
        )
    if name == "currency":
        return result(MATCH if str(lv).upper() == str(rv).upper() else MISMATCH, "Exact (case-insensitive).")
    if name in NAME_FIELDS:
        sim = name_similarity(str(lv), str(rv))
        rule = f"Name similarity {sim:.2f} (match >= {name_match}, uncertain >= {name_uncertain})."
        if sim >= name_match:
            return result(MATCH, rule)
        return result(UNCERTAIN if sim >= name_uncertain else MISMATCH, rule)
    return result(MATCH if str(lv) == str(rv) else MISMATCH, "Exact.")


def compare_line_items(
    left: list[dict[str, Any]], right: list[dict[str, Any]], tolerance: Decimal = Decimal("0.01")
) -> FieldComparison:
    """Greedy matching of line items by amount, then description similarity."""
    if not left or not right:
        return FieldComparison(
            "line_items",
            NOT_COMPARABLE,
            f"{len(left)} item(s)" if left else None,
            f"{len(right)} item(s)" if right else None,
            {},
            {},
            "At least one document has no line items (summary-level document), so they cannot be compared.",
        )
    unmatched = list(range(len(right)))
    matched = 0
    for li in left:
        best, best_score = None, 0.0
        for idx in unmatched:
            ri = right[idx]
            la, ra = li.get("amount"), ri.get("amount")
            if la is None or ra is None or not amounts_equal(la, ra, tolerance):
                continue
            score = SequenceMatcher(
                None, (li.get("description") or "").lower(), (ri.get("description") or "").lower()
            ).ratio()
            if score > best_score or best is None:
                best, best_score = idx, score
        if best is not None:
            unmatched.remove(best)
            matched += 1
    total = max(len(left), len(right))
    verdict = MATCH if matched == len(left) == len(right) else MISMATCH
    return FieldComparison(
        "line_items",
        verdict,
        f"{len(left)} item(s)",
        f"{len(right)} item(s)",
        {},
        {},
        f"{matched} of {total} line items matched by amount.",
    )


def compare_records(left: Record | None, right: Record | None, **kw: Any) -> list[FieldComparison]:
    out: list[FieldComparison] = []
    for name in HEADER_FIELDS:
        out.append(
            compare_field(
                name,
                (left.fields.get(name) if left else None),
                (right.fields.get(name) if right else None),
                **kw,
            )
        )
    if left and right:
        out.append(compare_line_items(left.line_items, right.line_items))
    return out


def match_records(left: list[Record], right: list[Record]) -> list[RecordPair]:
    """Pair up records. 1) normalised invoice number, 2) supplier similarity + equal total (+ date)."""
    pairs: list[RecordPair] = []
    free_right = list(range(len(right)))
    unmatched_left: list[int] = []

    def num(r: Record) -> str:
        fv = r.fields.get("invoice_number")
        return normalize_invoice_number(str(fv.value)) if fv and fv.value else ""

    for li, lrec in enumerate(left):
        key = num(lrec)
        hit = next((ri for ri in free_right if key and num(right[ri]) == key), None)
        if hit is None:
            unmatched_left.append(li)
            continue
        free_right.remove(hit)
        pairs.append(RecordPair(lrec, right[hit], "invoice_number"))

    for li in unmatched_left:
        lrec = left[li]
        lt = lrec.fields.get("total_amount")
        ls = lrec.fields.get("supplier_name")
        best, best_score = None, 0.0
        for ri in free_right:
            rt = right[ri].fields.get("total_amount")
            rs = right[ri].fields.get("supplier_name")
            if not (lt and rt and lt.value is not None and rt.value is not None):
                continue
            if not amounts_equal(lt.value, rt.value):
                continue
            sim = name_similarity(ls.value if ls else None, rs.value if rs else None)
            if sim >= 0.6 and sim > best_score:
                best, best_score = ri, sim
        if best is not None:
            free_right.remove(best)
            pairs.append(RecordPair(lrec, right[best], "supplier+total"))
        else:
            pairs.append(RecordPair(lrec, None, "unmatched"))
    pairs.extend(RecordPair(None, right[ri], "unmatched") for ri in free_right)

    for pair in pairs:
        pair.comparisons = compare_records(pair.left, pair.right)
    return pairs
