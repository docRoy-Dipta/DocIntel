"""Date parsing that admits when a date is ambiguous."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))


@dataclass(frozen=True)
class ParsedDate:
    value: date | None
    ambiguous: bool = False


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str | None) -> ParsedDate:
    """Parse common invoice date formats. Numeric dd/mm vs mm/dd that cannot be resolved are flagged."""
    if not text:
        return ParsedDate(None)
    s = text.strip().strip(".,;")

    if m := re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", s):  # ISO-like
        return ParsedDate(_safe(int(m[1]), int(m[2]), int(m[3])))
    if m := re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-./]+({_MONTH_RE})[a-z]*\.?,?[\s\-./]+(\d{{4}})\b",
        s,
        re.I,
    ):
        return ParsedDate(_safe(int(m[3]), _MONTHS[m[2].lower()], int(m[1])))
    if m := re.search(rf"\b({_MONTH_RE})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", s, re.I):
        return ParsedDate(_safe(int(m[3]), _MONTHS[m[1].lower()], int(m[2])))
    if m := re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", s):  # dd.mm.yyyy (European)
        return ParsedDate(_safe(int(m[3]), int(m[2]), int(m[1])))
    if m := re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", s):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12 >= b:
            return ParsedDate(_safe(y, b, a))
        if b > 12 >= a:
            return ParsedDate(_safe(y, a, b))
        if a == b:
            return ParsedDate(_safe(y, a, b))
        return ParsedDate(_safe(y, b, a), ambiguous=True)  # assume day-first, but flag it
    return ParsedDate(None)
