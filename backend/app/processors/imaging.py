"""Image loading and OCR preprocessing (Pillow + numpy)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from app.core.config import Settings
from app.core.errors import PermanentProcessingError


@dataclass(frozen=True)
class PreprocessResult:
    image: Image.Image
    skew_degrees: float  # rotation applied (positive = counter-clockwise)


def load_image_frame(path: Path, frame: int, settings: Settings) -> Image.Image:
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels * 2
    try:
        with Image.open(path) as img:
            if img.width * img.height > settings.max_image_pixels:
                raise PermanentProcessingError("Image dimensions are too large to process safely.")
            img.seek(frame)
            img.load()
            return ImageOps.exif_transpose(img.convert("RGB"))
    except PermanentProcessingError:
        raise
    except (OSError, ValueError, EOFError, Image.DecompressionBombError) as exc:
        raise PermanentProcessingError(f"Image could not be decoded: {exc}") from exc


def estimate_skew(gray: Image.Image, max_angle: float = 5.0, step: float = 0.5) -> float:
    """Projection-profile method: the right angle makes text rows sharpest."""
    small = gray.copy()
    small.thumbnail((700, 700))
    arr0 = np.asarray(small, dtype=np.uint8)
    thresh = arr0.mean() - 0.5 * arr0.std()
    best_angle, best_score = 0.0, -1.0
    angle = -max_angle
    while angle <= max_angle + 1e-9:
        rotated = small.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=255)
        dark = (np.asarray(rotated, dtype=np.uint8) < thresh).sum(axis=1).astype(np.float64)
        score = float(np.var(dark))
        if score > best_score:
            best_angle, best_score = angle, score
        angle += step
    return best_angle


def _otsu(arr: np.ndarray) -> int:
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    total = arr.size
    sum_all = float(np.dot(np.arange(256), hist))
    sum_b, w_b, best, thr = 0.0, 0.0, 0.0, 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > best:
            best, thr = between, t
    return thr


def preprocess(img: Image.Image, settings: Settings) -> PreprocessResult:
    gray = ImageOps.autocontrast(img.convert("L"), cutoff=1)
    angle = 0.0
    if settings.ocr_deskew:
        angle = estimate_skew(gray)
        if abs(angle) >= 0.5:
            gray = gray.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)
        else:
            angle = 0.0
    if settings.ocr_denoise:
        gray = gray.filter(ImageFilter.MedianFilter(3))
    if settings.ocr_binarize:
        arr = np.asarray(gray, dtype=np.uint8)
        gray = Image.fromarray(((arr > _otsu(arr)) * 255).astype(np.uint8))
    return PreprocessResult(gray, angle)


def unrotate_point(x: float, y: float, width: int, height: int, angle_degrees: float) -> tuple[float, float]:
    """Map a point from the deskewed image back to the original image (rotation about the centre)."""
    if not angle_degrees:
        return x, y
    cx, cy = width / 2, height / 2
    theta = math.radians(angle_degrees)  # PIL rotates counter-clockwise by +angle
    dx, dy = x - cx, y - cy
    # undo a counter-clockwise rotation (in image coordinates y points down)
    ox = dx * math.cos(theta) - dy * math.sin(theta)
    oy = dx * math.sin(theta) + dy * math.cos(theta)
    return cx + ox, cy + oy
