"""Pure-logic tests: money, dates, financial validation, matching. No database needed."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.domain import matching as m
from app.domain.dates import parse_date
from app.domain.money import (
    amounts_equal,
    currencies_consistent,
    currency_mentions,
    detect_currency,
    parse_amount,
    quantize_money,
)
from app.domain.validation import InvoiceData, LineItemData, validate_invoice

TODAY = date(2026, 1, 1)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("(45.00)", "-45.00"),
        ("12,50", "12.50"),
        ("1,234", "1234"),
        ("Rs. 1,000", "1000"),
        ("-3.5", "-3.5"),
        ("1 234,56 EUR", "1234.56"),
        ("৳ 2,50,000.00", "250000.00"),
        ("€ 0.99", "0.99"),
        ("1.234.567", "1234567"),
        ("USD 99", "99"),
        ("\u22125.00", "-5.00"),
    ],
)
def test_parse_amount(text: str, expected: str) -> None:
    assert parse_amount(text) == D(expected)


@pytest.mark.parametrize("text", [None, "", "abc", "   ", "--", "$"])
def test_parse_amount_returns_none_when_unreadable(text: str | None) -> None:
    assert parse_amount(text) is None


def test_money_never_uses_float_arithmetic() -> None:
    a, b = parse_amount("0.1"), parse_amount("0.2")
    assert a is not None and b is not None and a + b == D("0.3")
    assert quantize_money(D("2.675")) == D("2.68")  # half-up, unlike float rounding
    assert amounts_equal(D("10.00"), D("10.01")) and not amounts_equal(D("10.00"), D("10.02"))
    assert not amounts_equal(None, D("1"))


def test_currency_detection_distinguishes_extracted_from_inferred() -> None:
    assert detect_currency("Total USD 100") == ("USD", "extracted")
    assert detect_currency("Total € 5") == ("EUR", "extracted")
    assert detect_currency("Total $5") == ("USD", "inferred")  # "$" is ambiguous
    assert detect_currency("no currency here") == (None, "extracted")
    assert currencies_consistent(currency_mentions("USD 5 and $6")) is True
    assert currencies_consistent(currency_mentions("USD 5 and EUR 6")) is False
    assert currencies_consistent(currency_mentions("CAD 5 and $6")) is True
    assert currencies_consistent(currency_mentions("EUR 5 and $6")) is False


@pytest.mark.parametrize(
    "text,iso,ambiguous",
    [
        ("2025-03-12", "2025-03-12", False),
        ("12 March 2025", "2025-03-12", False),
        ("March 12, 2025", "2025-03-12", False),
        ("12-Mar-2025", "2025-03-12", False),
        ("13/03/2025", "2025-03-13", False),
        ("03/13/2025", "2025-03-13", False),
        ("12.03.2025", "2025-03-12", False),
        ("03/04/2025", "2025-04-03", True),
        ("5th Jan 2024", "2024-01-05", False),
        ("Date: 07/07/2025", "2025-07-07", False),
    ],
)
def test_parse_date(text: str, iso: str, ambiguous: bool) -> None:
    parsed = parse_date(text)
    assert parsed.value is not None and parsed.value.isoformat() == iso and parsed.ambiguous is ambiguous


@pytest.mark.parametrize("text", [None, "", "not a date", "31/02/2025", "2025-13-40"])
def test_parse_date_rejects_invalid(text: str | None) -> None:
    assert parse_date(text).value is None


def good_invoice(**over: object) -> InvoiceData:
    base: dict[str, object] = dict(  # noqa: C408
        invoice_number="INV-1",
        invoice_date=date(2025, 3, 1),
        supplier_name="Acme",
        customer_name="Globex",
        subtotal=D("100.00"),
        tax=D("10.00"),
        total_amount=D("110.00"),
        currency="USD",
        tax_rate=D("10"),
        line_items=[
            LineItemData(1, "A", D("2"), D("30.00"), D("60.00")),
            LineItemData(2, "B", D("1"), D("40.00"), D("40.00")),
        ],
    )
    base.update(over)
    return InvoiceData(**base)  # type: ignore[arg-type]


def codes(data: InvoiceData) -> dict[str, str]:
    return {i.code: i.severity for i in validate_invoice(data, today=TODAY).issues}


def test_valid_invoice_has_no_issues() -> None:
    report = validate_invoice(good_invoice(), today=TODAY)
    assert report.issues == [] and report.status == "valid" and not report.needs_review


@pytest.mark.parametrize(
    "override,code,severity",
    [
        ({"invoice_number": None}, "REQUIRED_FIELD_MISSING", "error"),
        ({"invoice_date": None}, "REQUIRED_FIELD_MISSING", "error"),
        ({"supplier_name": ""}, "REQUIRED_FIELD_MISSING", "error"),
        ({"currency": None}, "REQUIRED_FIELD_MISSING", "error"),
        ({"customer_name": None}, "FIELD_MISSING", "warning"),
        ({"tax": None, "total_amount": D("100.00")}, "FIELD_MISSING", "warning"),
        ({"line_items": []}, "LINE_ITEMS_MISSING", "warning"),
        ({"total_amount": D("111.00")}, "TOTAL_MISMATCH", "error"),
        ({"subtotal": D("99.00"), "total_amount": D("109.00")}, "SUBTOTAL_MISMATCH", "error"),
        ({"tax": D("12.00"), "total_amount": D("112.00")}, "TAX_RATE_MISMATCH", "error"),
        (
            {"tax": D("150.00"), "total_amount": D("250.00"), "tax_rate": None},
            "TAX_EXCEEDS_SUBTOTAL",
            "warning",
        ),
        (
            {
                "total_amount": D("-110.00"),
                "subtotal": D("-100"),
                "tax": D("-10"),
                "line_items": [],
            },
            "NEGATIVE_AMOUNT",
            "warning",
        ),
        ({"currency": "XXX"}, "CURRENCY_UNKNOWN", "warning"),
        ({"currency_mentions": {"USD", "EUR"}}, "CURRENCY_INCONSISTENT", "error"),
        ({"invoice_date": date(2027, 1, 1)}, "DATE_IN_FUTURE", "warning"),
        ({"invoice_date": date(1980, 1, 1)}, "DATE_IMPLAUSIBLE", "warning"),
        ({"ambiguous_date": True}, "DATE_AMBIGUOUS", "warning"),
        ({"inferred_fields": {"currency"}}, "FIELD_INFERRED", "warning"),
        ({"ungrounded_fields": {"supplier_name"}}, "FIELD_UNGROUNDED", "warning"),
        ({"low_confidence_fields": {"total_amount"}}, "FIELD_LOW_CONFIDENCE", "warning"),
    ],
)
def test_each_validation_rule_fires(override: dict[str, object], code: str, severity: str) -> None:
    assert codes(good_invoice(**override)).get(code) == severity


def test_line_amount_mismatch_reports_expected_vs_actual() -> None:
    data = good_invoice(
        line_items=[
            LineItemData(1, "A", D("2"), D("30.00"), D("61.00")),
            LineItemData(2, "B", D("1"), D("40.00"), D("40.00")),
        ],
        subtotal=D("101.00"),
        total_amount=D("111.10"),
        tax=D("10.10"),
        tax_rate=None,
    )
    issue = next(i for i in validate_invoice(data, today=TODAY).issues if i.code == "LINE_AMOUNT_MISMATCH")
    assert (issue.expected, issue.actual) == ("60", "61")


def test_rounding_tolerance_is_exact_to_one_cent() -> None:
    assert "TOTAL_MISMATCH" not in codes(good_invoice(total_amount=D("110.01")))
    assert "TOTAL_MISMATCH" in codes(good_invoice(total_amount=D("110.02")))
    strict = validate_invoice(good_invoice(total_amount=D("110.01")), tolerance=D("0"), today=TODAY)
    assert any(i.code == "TOTAL_MISMATCH" for i in strict.issues)


def test_missing_tax_with_higher_total_is_unverifiable_not_an_error() -> None:
    c = codes(good_invoice(tax=None, tax_rate=None, total_amount=D("110.00")))
    assert c["TOTAL_UNVERIFIED_TAX_MISSING"] == "warning" and "TOTAL_MISMATCH" not in c
    assert codes(good_invoice(tax=None, tax_rate=None, total_amount=D("90.00")))["TOTAL_MISMATCH"] == "error"


def test_totals_can_be_verified_from_lines_when_subtotal_is_missing() -> None:
    assert "TOTAL_MISMATCH" in codes(good_invoice(subtotal=None, total_amount=D("999.00")))
    assert "TOTAL_MISMATCH" not in codes(good_invoice(subtotal=None))


# ----------------------------------------------------------------------------- matching


def test_normalisation_rules() -> None:
    assert m.normalize_invoice_number("inv-000123") == m.normalize_invoice_number("INV 000123") == "INV000123"
    assert m.normalize_invoice_number("000123") == "123"
    assert (
        m.normalize_company("The ACME Widgets, Ltd.") == m.normalize_company("Acme Widgets Limited") == "acme widgets"
    )
    assert m.name_similarity("Acme Widgets Ltd", "ACME Widget Ltd") > 0.85
    assert m.name_similarity("Acme", "Globex") < 0.5 and m.name_similarity(None, "x") == 0.0


def fv(v: object) -> m.FieldValue:
    return m.FieldValue(v, {"page": 1})


@pytest.mark.parametrize(
    "name,left,right,verdict",
    [
        ("total_amount", D("10.00"), D("10.005"), m.MATCH),
        ("total_amount", D("10.00"), D("10.50"), m.MISMATCH),
        ("invoice_date", date(2025, 1, 1), date(2025, 1, 1), m.MATCH),
        ("invoice_date", date(2025, 1, 1), date(2025, 1, 2), m.MISMATCH),
        ("currency", "usd", "USD", m.MATCH),
        ("currency", "USD", "EUR", m.MISMATCH),
        ("supplier_name", "Acme Ltd", "Acme Limited", m.MATCH),
        ("supplier_name", "Acme Ltd", "Globex", m.MISMATCH),
        ("invoice_number", "INV-001", "inv001", m.MATCH),
        ("invoice_number", "INV-001", "INV-002", m.MISMATCH),
    ],
)
def test_field_comparison_verdicts(name: str, left: object, right: object, verdict: str) -> None:
    assert m.compare_field(name, fv(left), fv(right)).verdict == verdict


def test_missing_sides_are_distinguished() -> None:
    assert m.compare_field("tax", None, fv(D(1))).verdict == m.MISSING_LEFT
    assert m.compare_field("tax", fv(D(1)), None).verdict == m.MISSING_RIGHT
    assert m.compare_field("tax", None, None).verdict == m.NOT_COMPARABLE


def rec(num: str | None, supplier: str, total: str, **ref: object) -> m.Record:
    fields = {"supplier_name": fv(supplier), "total_amount": fv(D(total))}
    if num:
        fields["invoice_number"] = fv(num)
    return m.Record(ref=dict(ref), fields=fields)


def test_record_matching_by_number_then_by_supplier_and_total() -> None:
    left = [
        rec("A-1", "Acme Ltd", "10"),
        rec(None, "Globex Corp", "99.00"),
        rec("Z-9", "Lonely", "5"),
    ]
    right = [
        rec("a1", "Acme", "10"),
        rec("QQ", "Globex Corporation", "99"),
        rec("N-1", "Other", "7"),
    ]
    pairs = m.match_records(left, right)
    by = {(p.matched_by, p.left is not None, p.right is not None) for p in pairs}
    assert ("invoice_number", True, True) in by and ("supplier+total", True, True) in by
    assert ("unmatched", True, False) in by and ("unmatched", False, True) in by
    assert len(pairs) == 4


def test_line_item_comparison() -> None:
    a = [{"description": "Widget", "amount": D("10")}, {"description": "Gadget", "amount": D("5")}]
    assert m.compare_line_items(a, list(reversed(a))).verdict == m.MATCH
    assert m.compare_line_items(a, a[:1]).verdict == m.MISMATCH
    assert m.compare_line_items(a, []).verdict == m.NOT_COMPARABLE


def test_summary_level_data_does_not_expect_line_items() -> None:
    assert "LINE_ITEMS_MISSING" in codes(good_invoice(line_items=[]))
    assert "LINE_ITEMS_MISSING" not in codes(good_invoice(line_items=[], expect_line_items=False))
