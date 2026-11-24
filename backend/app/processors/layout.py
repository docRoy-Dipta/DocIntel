"""Word boxes -> text lines, and locating a text snippet on a page."""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from typing import Any


@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float | None = None  # 0..1, OCR only

    def as_list(self) -> list[Any]:
        return [
            round(self.x0, 1),
            round(self.y0, 1),
            round(self.x1, 1),
            round(self.y1, 1),
            self.text,
            None if self.conf is None else round(self.conf, 3),
        ]

    @classmethod
    def from_list(cls, row: list[Any]) -> Word:
        conf = row[5] if len(row) > 5 else None
        return cls(
            float(row[0]),
            float(row[1]),
            float(row[2]),
            float(row[3]),
            str(row[4]),
            None if conf is None else float(conf),
        )


def words_to_text(words: list[Word]) -> str:
    """Rebuild reading-order text. Large horizontal gaps become two spaces (table columns)."""
    words = [w for w in words if w.text.strip()]
    if not words:
        return ""
    heights = [max(w.y1 - w.y0, 1.0) for w in words]
    med_h = median(heights)
    ordered = sorted(words, key=lambda w: ((w.y0 + w.y1) / 2, w.x0))
    lines: list[list[Word]] = []
    centers: list[float] = []
    for w in ordered:
        cy = (w.y0 + w.y1) / 2
        if lines and abs(cy - centers[-1]) <= 0.6 * med_h:
            lines[-1].append(w)
            centers[-1] = sum((x.y0 + x.y1) / 2 for x in lines[-1]) / len(lines[-1])
        else:
            lines.append([w])
            centers.append(cy)
    out: list[str] = []
    char_w = median([(w.x1 - w.x0) / max(len(w.text), 1) for w in words]) or 1.0
    for line in lines:
        line.sort(key=lambda w: w.x0)
        parts = [line[0].text]
        for prev, cur in zip(line, line[1:], strict=False):
            gap = cur.x0 - prev.x1
            parts.append("  " if gap > 2.5 * char_w else " ")
            parts.append(cur.text)
        out.append("".join(parts))
    return "\n".join(out)


def _norm(token: str) -> str:
    return re.sub(r"\W+", "", token.lower())


def locate(words: list[Word], snippet: str) -> tuple[list[float], float | None] | None:
    """Find a consecutive run of words equal to the snippet. Returns (bbox, mean OCR confidence)."""
    tokens = [t for t in (_norm(x) for x in snippet.split()) if t]
    if not tokens:
        return None
    norm_words = [_norm(w.text) for w in words]
    n = len(tokens)
    for i in range(len(words) - n + 1):
        if norm_words[i : i + n] == tokens:
            run = words[i : i + n]
            bbox = [
                min(w.x0 for w in run),
                min(w.y0 for w in run),
                max(w.x1 for w in run),
                max(w.y1 for w in run),
            ]
            confs = [w.conf for w in run if w.conf is not None]
            return [round(v, 1) for v in bbox], (sum(confs) / len(confs) if confs else None)
    return None
