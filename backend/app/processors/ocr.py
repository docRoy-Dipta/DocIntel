"""OCR engines behind one interface, so Tesseract can be compared with others later."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image

from app.core.config import Settings
from app.core.errors import PermanentProcessingError, TransientProcessingError
from app.processors.imaging import preprocess, unrotate_point
from app.processors.layout import Word, words_to_text


@dataclass(frozen=True)
class OCRResult:
    words: list[Word]  # coordinates in the units of the image passed to recognize()
    mean_confidence: float | None  # 0..1
    text: str = ""  # reading-order text (built from straightened coordinates)


class OCREngine(Protocol):
    name: str

    def recognize(self, image: Image.Image) -> OCRResult: ...


class TesseractEngine:
    name = "tesseract"

    def __init__(self, lang: str = "eng", psm: int = 6, timeout: int = 120) -> None:
        self.lang, self.psm, self.timeout = lang, psm, timeout

    def recognize(self, image: Image.Image) -> OCRResult:
        import pytesseract

        try:
            data = pytesseract.image_to_data(
                image,
                lang=self.lang,
                config=f"--oem 1 --psm {self.psm}",
                output_type=pytesseract.Output.DICT,
                timeout=self.timeout,
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise PermanentProcessingError("Tesseract OCR is not installed on this worker.") from exc
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            raise TransientProcessingError(f"OCR timed out: {exc}") from exc
        words: list[Word] = []
        for i, text in enumerate(data["text"]):
            conf = float(data["conf"][i])
            if not text.strip() or conf < 0:
                continue
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            words.append(Word(x, y, x + w, y + h, text.strip(), conf / 100.0))
        confs = [w.conf for w in words if w.conf is not None]
        return OCRResult(words, sum(confs) / len(confs) if confs else None)


def get_engine(settings: Settings) -> OCREngine:
    if settings.ocr_engine == "tesseract":
        return TesseractEngine(lang=settings.ocr_lang)
    raise PermanentProcessingError(f"Unknown OCR engine '{settings.ocr_engine}'")


def ocr_page_image(
    image: Image.Image, settings: Settings, engine: OCREngine | None = None, scale: float = 1.0
) -> OCRResult:
    """Preprocess, run OCR, and return words mapped back to the ORIGINAL image geometry.

    `scale` converts image pixels to page units (e.g. 72/dpi for PDF points).
    """
    engine = engine or get_engine(settings)
    pre = preprocess(image, settings)
    result = engine.recognize(pre.image)
    # Build the text from the STRAIGHTENED coordinates; only the boxes are mapped back for evidence.
    text = words_to_text(result.words)
    width, height = image.size
    words: list[Word] = []
    for w in result.words:
        if pre.skew_degrees:
            x0, y0 = unrotate_point(w.x0, w.y0, width, height, pre.skew_degrees)
            x1, y1 = unrotate_point(w.x1, w.y1, width, height, pre.skew_degrees)
            x0, x1 = sorted((x0, x1))
            y0, y1 = sorted((y0, y1))
        else:
            x0, y0, x1, y1 = w.x0, w.y0, w.x1, w.y1
        words.append(Word(x0 * scale, y0 * scale, x1 * scale, y1 * scale, w.text, w.conf))
    return OCRResult(words, result.mean_confidence, text)
