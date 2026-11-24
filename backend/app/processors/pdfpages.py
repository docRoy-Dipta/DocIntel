"""Page-level reading of PDFs and images. One page at a time keeps memory flat."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.core.config import Settings
from app.core.errors import PermanentProcessingError
from app.processors.imaging import load_image_frame
from app.processors.layout import Word, words_to_text
from app.processors.ocr import OCREngine, ocr_page_image


@dataclass
class PageResult:
    text: str
    words: list[Word]
    method: str  # text_layer|ocr|empty
    width: float
    height: float
    ocr_confidence: float | None = None
    notes: list[str] = field(default_factory=list)


def read_pdf_text_layer(path: Path, page_number: int, settings: Settings) -> PageResult | None:
    """Extract the text layer. Returns None when the page looks scanned (needs OCR)."""
    import pymupdf

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PermanentProcessingError(f"PDF could not be opened: {exc}") from exc
    try:
        try:
            page = doc.load_page(page_number - 1)
            raw = page.get_text("words")
            rect = page.rect
        except Exception as exc:
            raise PermanentProcessingError(f"PDF page {page_number} is unreadable: {exc}") from exc
        words = [Word(w[0], w[1], w[2], w[3], w[4]) for w in raw if str(w[4]).strip()]
        text = words_to_text(words)
        if len(text.strip()) >= settings.scanned_text_threshold:
            return PageResult(text, words, "text_layer", rect.width, rect.height)
        return None
    finally:
        doc.close()


def render_pdf_page(path: Path, page_number: int, dpi: int) -> tuple[Image.Image, float, float]:
    """Render a PDF page to a PIL image. Returns (image, width_pt, height_pt)."""
    import pymupdf

    doc = pymupdf.open(path)
    try:
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img, page.rect.width, page.rect.height
    except Exception as exc:
        raise PermanentProcessingError(f"PDF page {page_number} could not be rendered: {exc}") from exc
    finally:
        doc.close()


def ocr_pdf_page(path: Path, page_number: int, settings: Settings, engine: OCREngine | None = None) -> PageResult:
    img, wpt, hpt = render_pdf_page(path, page_number, settings.ocr_dpi)
    result = ocr_page_image(img, settings, engine, scale=72.0 / settings.ocr_dpi)
    text = result.text
    method = "ocr" if text.strip() else "empty"
    return PageResult(text, result.words, method, wpt, hpt, result.mean_confidence)


def ocr_image_frame(path: Path, frame: int, settings: Settings, engine: OCREngine | None = None) -> PageResult:
    img = load_image_frame(path, frame, settings)
    result = ocr_page_image(img, settings, engine, scale=1.0)
    text = result.text
    method = "ocr" if text.strip() else "empty"
    return PageResult(text, result.words, method, float(img.width), float(img.height), result.mean_confidence)


def render_page_png(
    path: Path, kind: str, page_number: int, dpi: int, settings: Settings, max_side: int = 1800
) -> bytes:
    """PNG bytes for the UI preview."""
    import io

    if kind == "pdf":
        img, _, _ = render_pdf_page(path, page_number, dpi)
    else:
        img = load_image_frame(path, page_number - 1, settings)
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
