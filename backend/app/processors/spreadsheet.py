"""Excel (.xlsx/.xls) and CSV reading, header detection, and invoice-record mapping.

Spreadsheets have no standard layout, so we (1) find the header row, (2) map header names to
canonical invoice fields with a synonym table, (3) group rows into invoice records. Everything is
deterministic and every value keeps its cell reference (e.g. "Invoices!C5") as evidence.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl.utils import get_column_letter

from app.core.config import Settings
from app.core.errors import PermanentProcessingError
from app.domain.dates import parse_date
from app.domain.money import detect_currency, parse_amount
from app.processors.files import decode_text_bytes

_SYNONYMS: dict[str, list[str]] = {
    "invoice_number": [
        "invoice number",
        "invoice no",
        "invoice num",
        "invoice #",
        "invoice id",
        "inv no",
        "inv number",
        "inv #",
        "invoice",
        "bill number",
        "document number",
        "doc no",
    ],
    "invoice_date": [
        "invoice date",
        "date",
        "issue date",
        "issued",
        "bill date",
        "inv date",
        "document date",
    ],
    "supplier_name": [
        "supplier",
        "supplier name",
        "vendor",
        "vendor name",
        "seller",
        "from",
        "company",
    ],
    "customer_name": [
        "customer",
        "customer name",
        "client",
        "client name",
        "buyer",
        "bill to",
        "sold to",
    ],
    "subtotal": ["subtotal", "sub total", "net amount", "net total", "amount before tax", "net"],
    "tax": ["tax", "vat", "gst", "tax amount", "vat amount", "sales tax"],
    "total_amount": [
        "total",
        "total amount",
        "grand total",
        "amount due",
        "gross amount",
        "invoice total",
        "gross total",
    ],
    "currency": ["currency", "ccy", "curr"],
    "description": ["description", "item", "item description", "product", "details", "line item"],
    "quantity": ["quantity", "qty", "units"],
    "unit_price": ["unit price", "price", "rate", "unit cost", "price each"],
    "line_amount": ["line total", "line amount", "ext price", "extended price", "extended amount"],
}
_LOOKUP = {syn: canon for canon, syns in _SYNONYMS.items() for syn in syns}
_LOOKUP["amount"] = "amount_generic"  # resolved in map_header_row()
_LINE_COLS = {"description", "quantity", "unit_price", "line_amount"}


@dataclass
class SheetData:
    name: str
    rows: list[list[Any]]  # raw cell values; row i is sheet row i+1
    warnings: list[str] = field(default_factory=list)


@dataclass
class SheetCell:
    value: Any
    ref: str  # e.g. "Invoices!C5"


@dataclass
class SheetRecord:
    sheet: str
    first_row: int
    last_row: int
    fields: dict[str, SheetCell] = field(default_factory=dict)
    line_items: list[dict[str, Any]] = field(default_factory=list)
    has_line_columns: bool = False  # does this sheet's layout carry line items at all?


def _norm_header(value: Any) -> str:
    s = re.sub(r"[^a-z0-9# ]+", " ", str(value).lower()) if value is not None else ""
    return re.sub(r"\s+", " ", s).strip()


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time().isoformat() == "00:00:00" else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# ----------------------------------------------------------------------------- reading


def read_csv(path: Path, settings: Settings) -> SheetData:
    decoded = decode_text_bytes(path.read_bytes())
    if decoded is None:
        raise PermanentProcessingError("CSV encoding could not be determined.")
    text, used = decoded
    sample = text[:8192]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows: list[list[Any]] = []
    warnings = [f"CSV decoded as {used}."] if used != "utf-8" else []
    for i, row in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i >= settings.max_sheet_rows:
            warnings.append(f"CSV truncated to {settings.max_sheet_rows} rows.")
            break
        rows.append([c.strip() if c.strip() != "" else None for c in row])
    return SheetData("csv", rows, warnings)


def read_xlsx(path: Path, settings: Settings) -> list[SheetData]:
    import openpyxl

    sheets: list[SheetData] = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    wb_f = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        for name in wb.sheetnames:
            rows: list[list[Any]] = []
            warnings: list[str] = []
            uncached = 0
            for i, (vals, forms) in enumerate(
                zip(
                    wb[name].iter_rows(values_only=True),
                    wb_f[name].iter_rows(values_only=True),
                    strict=False,
                )
            ):
                if i >= settings.max_sheet_rows:
                    warnings.append(f"Sheet truncated to {settings.max_sheet_rows} rows.")
                    break
                rows.append(list(vals))
                uncached += sum(
                    1
                    for v, f in zip(vals, forms, strict=False)
                    if v is None and isinstance(f, str) and f.startswith("=")
                )
            if uncached:
                warnings.append(
                    f"{uncached} formula cell(s) have no cached value (file not saved by Excel?); values may be absent."
                )
            sheets.append(SheetData(name, rows, warnings))
    finally:
        wb.close()
        wb_f.close()
    return sheets


def read_xls(path: Path, settings: Settings) -> list[SheetData]:
    import xlrd

    book = xlrd.open_workbook(path)
    sheets: list[SheetData] = []
    try:
        for sh in book.sheets():
            rows: list[list[Any]] = []
            for r in range(min(sh.nrows, settings.max_sheet_rows)):
                row: list[Any] = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        dt = xlrd.xldate_as_datetime(cell.value, book.datemode)
                        row.append(dt)
                    elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        row.append(None)
                    else:
                        row.append(cell.value)
                rows.append(row)
            sheets.append(SheetData(sh.name, rows))
    finally:
        book.release_resources()
    return sheets


def read_workbook(path: Path, kind: str, settings: Settings) -> list[SheetData]:
    try:
        if kind == "csv":
            return [read_csv(path, settings)]
        if kind == "xlsx":
            return read_xlsx(path, settings)
        if kind == "xls":
            return read_xls(path, settings)
    except PermanentProcessingError:
        raise
    except Exception as exc:
        raise PermanentProcessingError(f"Spreadsheet could not be read: {exc}") from exc
    raise PermanentProcessingError(f"Not a spreadsheet kind: {kind}")


def sheet_to_text(sheet: SheetData, max_rows: int = 5000) -> str:
    lines = []
    for row in sheet.rows[:max_rows]:
        cells = [cell_text(c) for c in row]
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            lines.append("\t".join(cells))
    return "\n".join(lines)


# ----------------------------------------------------------------------------- mapping


def map_header_row(row: list[Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, value in enumerate(row):
        norm = _norm_header(value)
        if not norm:
            continue
        canon = _LOOKUP.get(norm)
        if canon is None:  # allow decorated headers such as "Invoice Date (DD/MM/YYYY)"
            for syn in sorted(_LOOKUP, key=len, reverse=True):
                if norm.startswith(syn + " "):
                    canon = _LOOKUP[syn]
                    break
        if canon and canon not in mapping:
            mapping[canon] = idx
    # "Amount" is ambiguous: a line amount in a line-item layout, otherwise the invoice total.
    if "amount_generic" in mapping:
        idx = mapping.pop("amount_generic")
        if "description" in mapping and "line_amount" not in mapping:
            mapping["line_amount"] = idx
        elif "total_amount" not in mapping:
            mapping["total_amount"] = idx
        elif "line_amount" not in mapping:
            mapping["line_amount"] = idx
    return mapping


def find_header(rows: list[list[Any]], scan_rows: int = 30) -> tuple[int, dict[str, int]] | None:
    best: tuple[int, dict[str, int]] | None = None
    for i, row in enumerate(rows[:scan_rows]):
        mapping = map_header_row(row)
        has_anchor = "invoice_number" in mapping or "total_amount" in mapping or "line_amount" in mapping
        if len(mapping) >= 3 and has_anchor and (best is None or len(mapping) > len(best[1])):
            best = (i, mapping)
    if best is None:
        return None
    return best


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return Decimal(str(value))
    return parse_amount(str(value))


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or value == "":
        return None
    return parse_date(str(value)).value


def extract_records(sheet: SheetData) -> list[SheetRecord]:
    found = find_header(sheet.rows)
    if found is None:
        return []
    header_idx, mapping = found
    records: list[SheetRecord] = []
    current: SheetRecord | None = None
    current_key: str | None = None
    has_line_layout = bool(_LINE_COLS & set(mapping)) and "description" in mapping

    def ref(col: int, row_idx: int) -> str:
        return f"{sheet.name}!{get_column_letter(col + 1)}{row_idx + 1}"

    for i in range(header_idx + 1, len(sheet.rows)):
        row = sheet.rows[i]
        if all(cell_text(c) == "" for c in row):
            continue
        get = lambda name, _row=row: _row[mapping[name]] if name in mapping and mapping[name] < len(_row) else None  # noqa: E731
        inv_no = cell_text(get("invoice_number"))
        first_text = next((cell_text(c) for c in row if cell_text(c)), "")
        if re.fullmatch(r"(grand\s+)?(sub)?total\s*:?", inv_no, re.I) or (
            not inv_no and re.match(r"^(grand\s+)?(sub)?total\b", first_text, re.I)
        ):
            continue  # a totals row, not a record

        key = inv_no.upper() if inv_no else None
        if has_line_layout:
            # Several rows share one invoice number; a new number starts a new invoice.
            if current is None or (key and key != current_key):
                current = SheetRecord(sheet.name, i + 1, i + 1, has_line_columns=True)
                current_key = key
                records.append(current)
        else:
            # One row per invoice.
            current = SheetRecord(sheet.name, i + 1, i + 1)
            current_key = key
            records.append(current)
        assert current is not None
        current.last_row = i + 1

        for name in (
            "invoice_number",
            "invoice_date",
            "supplier_name",
            "customer_name",
            "subtotal",
            "tax",
            "total_amount",
            "currency",
        ):
            if name in current.fields or name not in mapping:
                continue
            raw = get(name)
            if raw is None or cell_text(raw) == "":
                continue
            if name == "invoice_date":
                value: Any = _to_date(raw)
            elif name in ("subtotal", "tax", "total_amount"):
                value = _to_decimal(raw)
            elif name == "currency":
                value = (detect_currency(cell_text(raw))[0] or cell_text(raw)).upper()
            else:
                value = cell_text(raw)
            if value is not None:
                current.fields[name] = SheetCell(value, ref(mapping[name], i))

        if has_line_layout and (cell_text(get("description")) or get("line_amount") is not None):
            qty, unit = _to_decimal(get("quantity")), _to_decimal(get("unit_price"))
            amount = _to_decimal(get("line_amount"))
            current.line_items.append(
                {
                    "description": cell_text(get("description")) or None,
                    "quantity": qty,
                    "unit_price": unit,
                    "amount": amount,
                    "ref": ref(mapping.get("line_amount", mapping.get("description", 0)), i),
                }
            )
    return [r for r in records if r.fields]
