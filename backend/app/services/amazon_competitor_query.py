from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from app.models import Product


RULE_VERSION = "amazon_competitor_query_v1"

STOPWORDS = {
    "and",
    "with",
    "for",
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "by",
    "new",
    "hot",
    "sale",
    "giga",
    "gigab2b",
    "vindhvisk",
}

NOISE_PATTERNS = (
    re.compile(r"\bsku[:#-]?\s*[a-z0-9_-]+\b", re.I),
    re.compile(r"\bitem[:#-]?\s*[a-z0-9_-]+\b", re.I),
    re.compile(r"\bmodel[:#-]?\s*[a-z0-9_-]+\b", re.I),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:cm|mm|kg|g|lb|lbs)\b", re.I),
)

CORE_PRODUCT_TERMS = (
    "sofa",
    "loveseat",
    "chair",
    "table",
    "cabinet",
    "shelf",
    "rack",
    "bed",
    "mattress",
    "desk",
    "dresser",
    "nightstand",
    "bench",
    "stool",
    "cart",
    "organizer",
    "basket",
    "lamp",
    "mirror",
    "dog bed",
    "cat tree",
    "patio umbrella",
    "fire pit",
    "storage box",
)

ATTRIBUTE_TERMS = (
    "modular",
    "foldable",
    "reclining",
    "adjustable",
    "convertible",
    "portable",
    "rechargeable",
    "waterproof",
    "outdoor",
    "indoor",
    "sectional",
    "tufted",
    "upholstered",
    "freestanding",
    "wall mounted",
    "4 tier",
    "3 tier",
    "2 pack",
)

USE_CASE_TERMS = (
    "living room",
    "bedroom",
    "kitchen",
    "garage",
    "bathroom",
    "office",
    "patio",
    "garden",
    "camping",
    "entryway",
)

EXCLUDED_TERMS = ("replacement part", "cover only", "accessory")


class CompetitorQueryError(ValueError):
    """Raised when product facts cannot produce a trustworthy Amazon query."""


@dataclass(frozen=True)
class AmazonCompetitorQuery:
    query: str
    intent: str
    included_terms: list[str]
    excluded_terms: list[str]
    reason: str
    source_facts: list[str]
    rule_version: str = RULE_VERSION


def build_amazon_competitor_queries(product: Product) -> dict[str, Any]:
    facts = _product_facts(product)
    fact_text = " ".join(str(value) for value in facts.values() if value)
    normalized_text = _normalize_text(fact_text)
    core_terms = _terms_in_text(normalized_text, CORE_PRODUCT_TERMS)
    attribute_terms = _terms_in_text(normalized_text, ATTRIBUTE_TERMS)
    use_case_terms = _terms_in_text(normalized_text, USE_CASE_TERMS)
    material_terms = _split_terms(facts.get("material"), max_terms=2)
    dimension_terms = _dimension_terms(product)

    if not core_terms:
        fallback = _fallback_core_terms(facts.get("title"))
        core_terms.extend(fallback[:1])
    if not core_terms:
        raise CompetitorQueryError("insufficient_product_facts_for_competitor_search: missing reliable product type")

    queries: list[AmazonCompetitorQuery] = []
    core = _query_terms([core_terms[0], *attribute_terms[:2], *material_terms[:1], *use_case_terms[:1]])
    queries.append(AmazonCompetitorQuery(
        query=" ".join(core),
        intent="core_product",
        included_terms=core,
        excluded_terms=list(EXCLUDED_TERMS),
        reason="Core product type and strongest visible attributes from product facts",
        source_facts=_source_fact_names(facts, ("title", "features", "material", "description")),
    ))

    material_size = _query_terms([core_terms[0], *material_terms[:2], *dimension_terms[:2], *attribute_terms[:1]])
    if len(material_size) >= 3 and material_size != core:
        queries.append(AmazonCompetitorQuery(
            query=" ".join(material_size),
            intent="material_or_size",
            included_terms=material_size,
            excluded_terms=list(EXCLUDED_TERMS),
            reason="Material and size facts can improve Amazon recall",
            source_facts=_source_fact_names(facts, ("title", "material", "dimensions", "packages")),
        ))

    use_case = _query_terms([core_terms[0], *use_case_terms[:2], *attribute_terms[:2], *material_terms[:1]])
    if len(use_case) >= 3 and use_case not in (core, material_size):
        queries.append(AmazonCompetitorQuery(
            query=" ".join(use_case),
            intent="use_case",
            included_terms=use_case,
            excluded_terms=list(EXCLUDED_TERMS),
            reason="Use-case language is present in source facts",
            source_facts=_source_fact_names(facts, ("title", "features", "description")),
        ))

    cleaned: list[AmazonCompetitorQuery] = []
    seen: set[str] = set()
    for item in queries:
        terms = _query_terms(item.included_terms)
        if len(terms) < 3:
            continue
        query = " ".join(terms[:7])
        if query in seen:
            continue
        seen.add(query)
        cleaned.append(AmazonCompetitorQuery(
            query=query,
            intent=item.intent,
            included_terms=terms[:7],
            excluded_terms=item.excluded_terms,
            reason=item.reason,
            source_facts=item.source_facts,
        ))
        if len(cleaned) >= 3:
            break

    if not cleaned:
        raise CompetitorQueryError("insufficient_product_facts_for_competitor_search: generated query is too weak")

    return {
        "queries": [asdict(item) for item in cleaned],
        "source_facts": facts,
        "rule_version": RULE_VERSION,
    }


def _product_facts(product: Product) -> dict[str, Any]:
    data = product.data
    images = product.images
    features = _json_value(getattr(data, "features", None), default=[]) if data else []
    variants = _json_value(getattr(data, "variants", None), default=[]) if data else []
    packages = _json_value(getattr(data, "packages", None), default=[]) if data else []
    image_selection = _json_value(getattr(images, "image_selection_analysis", None), default={}) if images else {}
    dimensions = ""
    if data:
        dims = [data.dimension_length, data.dimension_width, data.dimension_height]
        if any(value is not None for value in dims):
            dimensions = " x ".join(str(value) for value in dims if value is not None)
    return {
        "title": getattr(data, "title", None) if data else None,
        "description": getattr(data, "description", None) if data else None,
        "features": features,
        "material": getattr(data, "material", None) if data else None,
        "dimensions": dimensions,
        "packages": packages,
        "variants": variants,
        "main_image_path": getattr(images, "main_image_path", None) if images else None,
        "main_image_source": getattr(images, "main_image_source", None) if images else None,
        "image_selection_analysis": image_selection,
    }


def _json_value(value: str | None, *, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except Exception:
        return value
    return parsed if parsed is not None else default


def _normalize_text(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    for pattern in NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(r"[^a-zA-Z0-9\s-]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _terms_in_text(text: str, terms: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    padded = f" {text} "
    for term in terms:
        needle = f" {term.lower()} "
        if needle in padded and term not in found:
            found.append(term)
    return found


def _split_terms(value: Any, *, max_terms: int) -> list[str]:
    text = _normalize_text(value)
    terms: list[str] = []
    for token in text.split():
        if token in STOPWORDS or token.isdigit() or len(token) < 3:
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= max_terms:
            break
    return terms


def _fallback_core_terms(title: Any) -> list[str]:
    tokens = _split_terms(title, max_terms=5)
    if len(tokens) >= 2:
        return [" ".join(tokens[:2])]
    return tokens


def _dimension_terms(product: Product) -> list[str]:
    data = product.data
    if not data:
        return []
    terms: list[str] = []
    for value in (data.dimension_length, data.dimension_width, data.dimension_height):
        if value and value >= 12:
            terms.append(f"{int(round(value))} inch")
            break
    packages = _normalize_text(data.packages)
    for token in ("2 pack", "3 pack", "4 pack"):
        if token in packages and token not in terms:
            terms.append(token)
    return terms


def _query_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    for value in values:
        for term in str(value or "").lower().split(","):
            term = re.sub(r"\s+", " ", term).strip()
            if not term or term in STOPWORDS:
                continue
            if term not in terms:
                terms.append(term)
    return terms[:7]


def _source_fact_names(facts: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    return [name for name in names if facts.get(name)]
