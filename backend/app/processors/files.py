"""File-type detection by content (magic bytes) and integrity checks. Never trust the filename."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.core.errors import FileRejectedError

_EXT_RULES: dict[str, tuple[str, str]] = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".tif": ("image", "image/tiff"),
    ".tiff": ("image", "image/tiff"),
    ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".xls": ("xls", "application/vnd.ms-excel"),
    ".csv": ("csv", "text/csv"),
}
ALLOWED_EXTENSIONS = tuple(_EXT_RULES)
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def decode_text_bytes(raw: bytes) -> tuple[str, str] | None:
    """Decode CSV bytes. UTF-16 is only trusted with a byte-order mark: legacy 8-bit text can
    accidentally be valid UTF-16 and would turn into garbage."""
    if raw.startswith(_UTF16_BOMS):
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            return None
    if b"\x00" in raw:
        return None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), ("utf-8" if enc == "utf-8-sig" else enc)
        except UnicodeDecodeError:
            continue
    return None


@dataclass(frozen=True)
class FileKind:
    kind: str  # pdf|image|xlsx|xls|csv
    mime: str


@dataclass(frozen=True)
class IntegrityInfo:
    page_count: int
    warnings: tuple[str, ...] = ()


def _head(path: Path, n: int = 8192) -> bytes:
    with path.open("rb") as fh:
        return fh.read(n)


def _signature(head: bytes) -> str | None:
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    return None


def _looks_like_text(head: bytes) -> bool:
    # A UTF-8 character may be cut in half at the end of the sample: ignore up to 3 trailing bytes.
    return any(decode_text_bytes(head[: len(head) - cut]) is not None for cut in (0, 1, 2, 3))


def check_zip_safety(path: Path, settings: Settings) -> list[str]:
    """Return the member names of an XLSX, rejecting zip bombs and macro-enabled files."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            names = [i.filename for i in infos]
            total = sum(i.file_size for i in infos)
            if total > settings.max_zip_uncompressed_mb * 1024 * 1024:
                raise FileRejectedError("Spreadsheet expands to an unreasonable size (possible zip bomb).")
            comp = sum(i.compress_size for i in infos) or 1
            if total / comp > 200 and total > 50 * 1024 * 1024:
                raise FileRejectedError("Spreadsheet compression ratio is suspicious (possible zip bomb).")
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise FileRejectedError("Macro-enabled spreadsheets are not accepted.")
            if any(n.startswith("/") or ".." in Path(n).parts for n in names):
                raise FileRejectedError("Spreadsheet archive contains unsafe paths.")
            return names
    except zipfile.BadZipFile as exc:
        raise FileRejectedError("File is corrupted (invalid ZIP structure).") from exc


def detect_kind(path: Path, filename: str, settings: Settings) -> FileKind:
    """Decide what a file really is. The extension and the content must agree."""
    ext = Path(filename).suffix.lower()
    if ext not in _EXT_RULES:
        raise FileRejectedError(f"Unsupported file type '{ext or '(none)'}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}.")
    kind, mime = _EXT_RULES[ext]
    if path.stat().st_size == 0:
        raise FileRejectedError("File is empty.")
    head = _head(path)
    sig = _signature(head)

    expected = {
        ".pdf": {"pdf"},
        ".png": {"png"},
        ".jpg": {"jpeg"},
        ".jpeg": {"jpeg"},
        ".tif": {"tiff"},
        ".tiff": {"tiff"},
        ".xlsx": {"zip"},
        ".xls": {"ole"},
    }
    if ext == ".csv":
        if sig is not None or not _looks_like_text(head):
            raise FileRejectedError("File content does not look like CSV text.")
    elif sig not in expected[ext]:
        raise FileRejectedError(f"File content does not match its '{ext}' extension.")

    if ext == ".xlsx":
        names = check_zip_safety(path, settings)
        if "xl/workbook.xml" not in names:
            raise FileRejectedError("File is a ZIP archive but not an Excel workbook.")
    return FileKind(kind, mime)


def validate_integrity(path: Path, kind: str, settings: Settings) -> IntegrityInfo:
    """Open the file with the real parser to detect corruption, encryption and absurd sizes."""
    try:
        if kind == "pdf":
            return _check_pdf(path, settings)
        if kind == "image":
            return _check_image(path, settings)
        if kind == "xlsx":
            return _check_xlsx(path)
        if kind == "xls":
            return _check_xls(path)
        if kind == "csv":
            return IntegrityInfo(page_count=1)
    except FileRejectedError:
        raise
    except Exception as exc:  # parser-specific errors all mean "corrupted"
        raise FileRejectedError(f"File is corrupted or unreadable: {type(exc).__name__}") from exc
    raise FileRejectedError(f"Unsupported kind '{kind}'.")


def _check_pdf(path: Path, settings: Settings) -> IntegrityInfo:
    import pymupdf

    doc = pymupdf.open(path)
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise FileRejectedError("PDF is password-protected.")
        n = doc.page_count
        if n < 1:
            raise FileRejectedError("PDF has no pages.")
        if n > settings.max_pages_per_document:
            raise FileRejectedError(f"PDF has {n} pages; the limit is {settings.max_pages_per_document}.")
        doc.load_page(0)
        doc.load_page(n - 1)  # a truncated file usually fails here
        warnings = ("PDF structure was damaged and repaired automatically.",) if doc.is_repaired else ()
        return IntegrityInfo(n, warnings)
    finally:
        doc.close()


def _check_image(path: Path, settings: Settings) -> IntegrityInfo:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels * 2
    with Image.open(path) as img:
        frames = getattr(img, "n_frames", 1)
        if frames > settings.max_pages_per_document:
            raise FileRejectedError(f"Image has {frames} frames; the limit is {settings.max_pages_per_document}.")
        if img.width * img.height > settings.max_image_pixels:
            raise FileRejectedError("Image dimensions are too large.")
    with Image.open(path) as img2:
        img2.verify()
    with Image.open(path) as img3:
        img3.seek(frames - 1)
        img3.load()  # forces a full decode of the last frame
    return IntegrityInfo(frames)


def _check_xlsx(path: Path) -> IntegrityInfo:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        n = len(wb.sheetnames)
    finally:
        wb.close()
    if n < 1:
        raise FileRejectedError("Workbook has no sheets.")
    return IntegrityInfo(n)


def _check_xls(path: Path) -> IntegrityInfo:
    import xlrd

    book = xlrd.open_workbook(path, on_demand=True)
    try:
        n = book.nsheets
    finally:
        book.release_resources()
    if n < 1:
        raise FileRejectedError("Workbook has no sheets.")
    return IntegrityInfo(n)
