"""Money parsing and comparison. Always Decimal, never float."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ISO_CURRENCIES = frozenset(
    [
        "USD",
        "EUR",
        "GBP",
        "BDT",
        "INR",
        "JPY",
        "CNY",
        "AUD",
        "CAD",
        "CHF",
        "SGD",
        "HKD",
        "NZD",
        "AED",
        "SAR",
        "PKR",
        "LKR",
        "NPR",
        "MYR",
        "THB",
        "IDR",
        "PHP",
        "KRW",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "RON",
        "TRY",
        "ZAR",
        "BRL",
        "MXN",
        "ARS",
        "CLP",
        "COP",
        "RUB",
        "UAH",
        "ILS",
        "EGP",
        "NGN",
        "KES",
        "QAR",
        "KWD",
        "OMR",
        "BHD",
        "VND",
        "TWD",
    ]  # noqa: E501
)
# Symbols that map to exactly one currency (reading them counts as "extracted").
_UNAMBIGUOUS_SYMBOLS = {"€": "EUR", "£": "GBP", "৳": "BDT", "₹": "INR", "₩": "KRW", "₫": "VND"}
# Symbols shared by several currencies (reading them is only "inferred").
_AMBIGUOUS_SYMBOLS = {"$": "USD", "¥": "JPY"}
_DOLLAR_FAMILY = {"USD", "CAD", "AUD", "NZD", "SGD", "HKD"}
_CODE_RE = re.compile(r"\b([A-Z]{3})\b")


def parse_amount(text: str | None) -> Decimal | None:
    """Parse '1,234.56', '1.234,56', '(45.00)', '$ 12', '12,50' ... into a Decimal.

    Returns None when no number can be read.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith(("-", "\u2212")) or re.match(r"^[^\d]*[-\u2212]\s*\d", s):
        negative = True
    if s.endswith("-"):
        negative = True
    s = re.sub(r"[^\d.,]", "", s)
    s = s.strip(".,")
    if not s or not re.search(r"\d", s):
        return None

    if "." in s and "," in s:
        decimal_sep = "." if s.rfind(".") > s.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in s:
        if s.count(",") > 1:
            s = s.replace(",", "")
        else:
            after = s.split(",")[1]
            s = s.replace(",", "") if len(after) == 3 else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


def quantize_money(value: Decimal, places: int = 2) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def amounts_equal(a: Decimal | None, b: Decimal | None, tolerance: Decimal = Decimal("0.01")) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tolerance


def detect_currency(text: str) -> tuple[str | None, str]:
    """Find the currency in a snippet. Returns (code, source) with source extracted|inferred."""
    for match in _CODE_RE.finditer(text.upper() if text.isupper() else text):
        if match.group(1) in ISO_CURRENCIES:
            return match.group(1), "extracted"
    for symbol, code in _UNAMBIGUOUS_SYMBOLS.items():
        if symbol in text:
            return code, "extracted"
    for symbol, code in _AMBIGUOUS_SYMBOLS.items():
        if symbol in text:
            return code, "inferred"
    return None, "extracted"


def currency_mentions(text: str) -> set[str]:
    """All currency codes/symbols mentioned in a text (for the consistency check)."""
    mentions = {m.group(1) for m in _CODE_RE.finditer(text) if m.group(1) in ISO_CURRENCIES}
    mentions |= {code for sym, code in _UNAMBIGUOUS_SYMBOLS.items() if sym in text}
    mentions |= {sym for sym in _AMBIGUOUS_SYMBOLS if sym in text}
    return mentions


def currencies_consistent(mentions: set[str]) -> bool:
    """True when all mentions can refer to one currency ($ is compatible with the dollar family)."""
    codes = {m for m in mentions if m in ISO_CURRENCIES}
    symbols = mentions - codes
    if len(codes) > 1:
        return False
    if "$" in symbols and codes and not (codes & _DOLLAR_FAMILY):
        return False
    if "¥" in symbols and codes and not (codes & {"JPY", "CNY"}):
        return False
    others = {s for s in symbols if s in ISO_CURRENCIES}
    return not (len(symbols - others) > 1 and {"$", "¥"} <= symbols)
