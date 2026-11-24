"""Extractor selection, page chunking and merging of per-chunk results."""

from __future__ import annotations

from typing import Protocol

from app.ai.gemini import GeminiExtractor
from app.ai.heuristic import HeuristicExtractor
from app.ai.schemas import IDENTITY_FIELDS, TOTAL_FIELDS, PageText, RawField, RawInvoice
from app.core.config import Settings
from app.core.ratelimit import MemoryRateLimiter, RateLimiter


class Extractor(Protocol):
    name: str
    model: str | None
    max_pages_per_call: int

    def extract(self, pages: list[PageText], doc_type: str = "invoice") -> tuple[RawInvoice, dict[str, int]]: ...


_memory_limiter = MemoryRateLimiter()


def get_extractor(settings: Settings, limiter: RateLimiter | None = None) -> Extractor:
    if settings.llm_provider == "gemini":
        lim = limiter or _memory_limiter
        assert settings.gemini_api_key
        return GeminiExtractor(
            settings.gemini_api_key,
            settings.gemini_model,
            timeout=settings.llm_timeout_seconds,
            pages_per_call=settings.llm_pages_per_call,
            rate_limit=lambda: lim.hit("llm", settings.llm_requests_per_minute),
        )
    return HeuristicExtractor()


def merge_raw(chunks: list[RawInvoice]) -> RawInvoice:
    """Combine per-chunk results: identity fields from the first chunk that has them, totals from the last."""
    if len(chunks) == 1:
        return chunks[0]
    merged = RawInvoice()
    for name in IDENTITY_FIELDS:
        for chunk in chunks:
            f: RawField = getattr(chunk, name)
            if f.value is not None:
                setattr(merged, name, f)
                break
    for name in TOTAL_FIELDS:
        for chunk in reversed(chunks):
            f = getattr(chunk, name)
            if f.value is not None:
                setattr(merged, name, f)
                break
    seen: set[tuple[object, ...]] = set()
    for chunk in chunks:
        for item in chunk.line_items:
            key = (item.page, item.description, item.quantity, item.amount)
            if key not in seen:
                seen.add(key)
                merged.line_items.append(item)
    return merged


def extract_document(extractor: Extractor, pages: list[PageText], doc_type: str) -> tuple[RawInvoice, dict[str, int]]:
    """Run the extractor over page chunks and merge."""
    size = max(1, extractor.max_pages_per_call)
    chunks: list[RawInvoice] = []
    usage_total: dict[str, int] = {}
    for i in range(0, len(pages), size):
        raw, usage = extractor.extract(pages[i : i + size], doc_type)
        chunks.append(raw)
        for k, v in usage.items():
            usage_total[k] = usage_total.get(k, 0) + v
    if not chunks:
        return RawInvoice(), usage_total
    return merge_raw(chunks), usage_total
