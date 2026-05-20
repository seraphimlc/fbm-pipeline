"""Shared Amazon Search Terms normalization helpers."""

from __future__ import annotations

import re
from typing import Any

SEARCH_TERMS_MAX_KEYWORDS = 20
SEARCH_TERMS_SEPARATOR = ", "


def _split_terms(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item or "") for item in value]

    text = str(value or "").strip()
    if not text:
        return []

    if re.search(r"[,，;\n]", text):
        return re.split(r"[,，;\n]+", text)
    return text.split()


def _clean_term(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9 -]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text.lower()


def _term_words(term: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", term.lower()) if len(word) > 1]


def _format_terms(terms: list[str]) -> str:
    return SEARCH_TERMS_SEPARATOR.join(terms)


def normalize_search_terms(
    value: Any,
    *,
    visible_copy: str = "",
    max_bytes: int = 250,
    max_keywords: int = SEARCH_TERMS_MAX_KEYWORDS,
) -> tuple[str, bool, int]:
    """Normalize search terms as comma-separated keyword phrases.

    Returns the normalized text, whether it changed, and the final keyword count.
    """
    visible_words = set(_term_words(visible_copy))
    kept: list[str] = []
    seen_terms: set[str] = set()
    seen_words: set[str] = set()
    changed = False

    for raw in _split_terms(value):
        term = _clean_term(raw)
        words = _term_words(term)
        if not term or not words:
            changed = True
            continue

        term_key = "".join(words)
        if term_key in seen_terms or all(word in visible_words or word in seen_words for word in words):
            changed = True
            continue

        candidate_terms = [*kept, term]
        if len(candidate_terms) > max_keywords or len(_format_terms(candidate_terms).encode("utf-8")) > max_bytes:
            changed = True
            continue

        kept.append(term)
        seen_terms.add(term_key)
        seen_words.update(words)

    normalized = _format_terms(kept)
    original = str(value or "").strip()
    return normalized, changed or normalized != original, len(kept)
