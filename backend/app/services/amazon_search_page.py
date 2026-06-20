from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from html import unescape
from typing import Any, Protocol
from urllib.parse import urljoin


AMAZON_SEARCH_SOURCE = "amazon_search_page"


class AmazonSearchPageError(RuntimeError):
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class AmazonSearchPageCandidate:
    asin: str
    url: str | None
    title: str | None
    image_url: str | None
    price: str | None
    rating: str | None
    review_count: str | None
    sponsored: bool
    search_query: str
    search_rank: int
    source: str = AMAZON_SEARCH_SOURCE
    raw_candidate: dict[str, Any] | None = None


@dataclass(frozen=True)
class AmazonSearchPageResult:
    query: str
    query_intent: str | None
    query_index: int
    captured_at: datetime
    candidates: list[AmazonSearchPageCandidate]
    raw_search_page: dict[str, Any]


class AmazonSearchPageAdapter(Protocol):
    async def search(self, query: str, *, marketplace: str = "US", limit: int = 12) -> list[AmazonSearchPageCandidate]:
        ...


class UnconfiguredAmazonSearchPageAdapter:
    async def search(self, query: str, *, marketplace: str = "US", limit: int = 12) -> list[AmazonSearchPageCandidate]:
        raise AmazonSearchPageError(
            "adapter_not_configured",
            "Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization",
        )


class FixtureAmazonSearchPageAdapter:
    def __init__(self, html_by_query: dict[str, str] | None = None):
        self.html_by_query = html_by_query or {}

    async def search(self, query: str, *, marketplace: str = "US", limit: int = 12) -> list[AmazonSearchPageCandidate]:
        html = self.html_by_query.get(query)
        if html is None:
            raise AmazonSearchPageError("fixture_missing", f"No fixture HTML for query: {query}")
        return parse_amazon_search_results_html(html, query=query, marketplace=marketplace, limit=limit)


def get_amazon_search_page_adapter() -> AmazonSearchPageAdapter:
    return UnconfiguredAmazonSearchPageAdapter()


async def run_amazon_search_queries(
    queries: list[dict[str, Any]],
    *,
    marketplace: str = "US",
    per_query_limit: int = 12,
    adapter: AmazonSearchPageAdapter | None = None,
) -> list[AmazonSearchPageResult]:
    client = adapter or get_amazon_search_page_adapter()
    results: list[AmazonSearchPageResult] = []
    for index, query_spec in enumerate(queries, start=1):
        query = str(query_spec.get("query") or "").strip()
        if not query:
            continue
        candidates = await client.search(query, marketplace=marketplace, limit=per_query_limit)
        results.append(AmazonSearchPageResult(
            query=query,
            query_intent=str(query_spec.get("intent") or ""),
            query_index=index,
            captured_at=datetime.utcnow(),
            candidates=candidates[:per_query_limit],
            raw_search_page={
                "query": query,
                "intent": query_spec.get("intent"),
                "candidate_count": len(candidates[:per_query_limit]),
                "adapter": client.__class__.__name__,
            },
        ))
    return results


def parse_amazon_search_results_html(
    html: str,
    *,
    query: str,
    marketplace: str = "US",
    limit: int = 12,
) -> list[AmazonSearchPageCandidate]:
    error_type = classify_amazon_search_page(html)
    if error_type:
        raise AmazonSearchPageError(error_type, f"Amazon search page blocked or unsupported: {error_type}")

    candidates: list[AmazonSearchPageCandidate] = []
    for block in _result_blocks(html):
        asin = _extract_attr(block, "data-asin")
        if not asin:
            continue
        title = _clean_text(_extract_first(block, [
            r'<h2[^>]*>.*?<span[^>]*>(.*?)</span>.*?</h2>',
            r'<span[^>]+class="[^"]*a-text-normal[^"]*"[^>]*>(.*?)</span>',
        ]))
        url = _extract_attr(_extract_first(block, [r'<a[^>]+class="[^"]*a-link-normal[^"]*"[^>]*>']), "href")
        image_url = _extract_attr(_extract_first(block, [r'<img[^>]+class="[^"]*s-image[^"]*"[^>]*>']), "src")
        price = _clean_text(_extract_first(block, [
            r'<span[^>]+class="[^"]*a-price[^"]*"[^>]*>.*?<span[^>]+class="[^"]*a-offscreen[^"]*"[^>]*>(.*?)</span>.*?</span>',
        ]))
        rating = _clean_text(_extract_first(block, [r'<span[^>]+class="[^"]*a-icon-alt[^"]*"[^>]*>(.*?)</span>']))
        review_count = _clean_text(_extract_first(block, [
            r'<span[^>]+class="[^"]*a-size-base[^"]*s-underline-text[^"]*"[^>]*>(.*?)</span>',
            r'aria-label="([\d,]+)"',
        ]))
        sponsored = bool(re.search(r"\bSponsored\b", _strip_tags(block), re.I))
        candidates.append(AmazonSearchPageCandidate(
            asin=asin.strip().upper(),
            url=_absolute_amazon_url(url, marketplace),
            title=title,
            image_url=image_url,
            price=price,
            rating=rating,
            review_count=review_count,
            sponsored=sponsored,
            search_query=query,
            search_rank=len(candidates) + 1,
            raw_candidate={"asin": asin, "marketplace": marketplace},
        ))
        if len(candidates) >= limit:
            break
    if not candidates:
        raise AmazonSearchPageError("empty_results", "Amazon search returned no recognizable natural results")
    return candidates


def classify_amazon_search_page(html: str) -> str | None:
    lower = html.lower()
    if "enter the characters you see below" in lower or "captcha" in lower:
        return "captcha"
    if "robot check" in lower or "automated access" in lower:
        return "bot_check"
    if "sign in" in lower and "ap_signin" in lower:
        return "login_required"
    if "deliver to" in lower and "choose your location" in lower:
        return "region_page"
    if "data-component-type=\"s-search-result\"" not in lower and "data-asin=" not in lower:
        return "unsupported_page_structure"
    return None


def candidate_to_dict(candidate: AmazonSearchPageCandidate) -> dict[str, Any]:
    return asdict(candidate)


def _result_blocks(html: str) -> list[str]:
    blocks: list[str] = []
    pattern = re.compile(r'<div[^>]+data-component-type="s-search-result"[^>]*data-asin="[^"]+"[^>]*>', re.I)
    matches = list(pattern.finditer(html))
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        blocks.append(html[start:end])
    return blocks


def _extract_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return match.group(1) if match.lastindex else match.group(0)
    return None


def _extract_attr(text: str | None, attr: str) -> str | None:
    if not text:
        return None
    match = re.search(rf'{re.escape(attr)}="([^"]*)"', text, re.I)
    return unescape(match.group(1)).strip() if match else None


def _strip_tags(value: str | None) -> str:
    return re.sub(r"<[^>]+>", " ", value or "")


def _clean_text(value: str | None) -> str | None:
    text = unescape(_strip_tags(value)).strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def _absolute_amazon_url(url: str | None, marketplace: str) -> str | None:
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    domain = "https://www.amazon.com"
    if marketplace.upper() not in {"US", "USA"}:
        domain = "https://www.amazon.com"
    return urljoin(domain, url)
