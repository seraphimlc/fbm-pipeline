from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode, urljoin

from app.config import settings
from app.pipeline import chrome_ctrl


AMAZON_SEARCH_SOURCE = "amazon_search_page"
AMAZON_SEARCH_ADAPTER_UNCONFIGURED = "unconfigured"
AMAZON_SEARCH_ADAPTER_CHROME = "chrome"

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class AmazonSearchEvidenceContext:
    task_run_id: int | None = None
    task_step_id: int | None = None
    product_id: int | None = None
    item_code: str | None = None
    query_index: int | None = None


class AmazonSearchPageAdapter(Protocol):
    async def search(
        self,
        query: str,
        *,
        marketplace: str = "US",
        limit: int = 12,
        evidence_context: AmazonSearchEvidenceContext | None = None,
    ) -> list[AmazonSearchPageCandidate]:
        ...


class UnconfiguredAmazonSearchPageAdapter:
    async def search(
        self,
        query: str,
        *,
        marketplace: str = "US",
        limit: int = 12,
        evidence_context: AmazonSearchEvidenceContext | None = None,
    ) -> list[AmazonSearchPageCandidate]:
        raise AmazonSearchPageError(
            "adapter_not_configured",
            "Amazon search page adapter is not configured; real Amazon search requires explicit browser authorization",
        )


class FixtureAmazonSearchPageAdapter:
    def __init__(self, html_by_query: dict[str, str] | None = None):
        self.html_by_query = html_by_query or {}

    async def search(
        self,
        query: str,
        *,
        marketplace: str = "US",
        limit: int = 12,
        evidence_context: AmazonSearchEvidenceContext | None = None,
    ) -> list[AmazonSearchPageCandidate]:
        html = self.html_by_query.get(query)
        if html is None:
            raise AmazonSearchPageError("fixture_missing", f"No fixture HTML for query: {query}")
        return parse_amazon_search_results_html(html, query=query, marketplace=marketplace, limit=limit)


class ChromeAmazonSearchPageAdapter:
    def __init__(self):
        self._last_query_started_at: datetime | None = None
        self.last_search_evidence: dict[str, Any] | None = None

    async def search(
        self,
        query: str,
        *,
        marketplace: str = "US",
        limit: int = 12,
        evidence_context: AmazonSearchEvidenceContext | None = None,
    ) -> list[AmazonSearchPageCandidate]:
        self.last_search_evidence = None
        marketplace = (marketplace or settings.AMAZON_SEARCH_MARKETPLACE or "US").strip().upper()
        url = build_amazon_search_url(query, marketplace=marketplace)
        context = evidence_context or AmazonSearchEvidenceContext()
        await self._apply_rate_limit()
        started_at = datetime.utcnow()
        evidence: dict[str, Any] = {
            "adapter": self.__class__.__name__,
            "query": query,
            "marketplace": marketplace,
            "url": url,
            "started_at": started_at.isoformat(),
            "task_run_id": context.task_run_id,
            "task_step_id": context.task_step_id,
            "product_id": context.product_id,
            "item_code": context.item_code,
            "query_index": context.query_index,
            "config": {
                "base_url": settings.AMAZON_SEARCH_BASE_URL,
                "limit": limit,
                "after_load_wait_seconds": settings.AMAZON_SEARCH_AFTER_LOAD_WAIT_SECONDS,
                "between_query_delay_seconds": settings.AMAZON_SEARCH_BETWEEN_QUERY_DELAY_SECONDS,
            },
        }
        try:
            async with chrome_ctrl.chrome_workflow(f"amazon_search query_index={context.query_index or 'unknown'}"):
                navigated = await chrome_ctrl.chrome_navigate(url, wait=settings.AMAZON_SEARCH_AFTER_LOAD_WAIT_SECONDS)
                if not navigated:
                    error_type = _chrome_error_type(chrome_ctrl.chrome_last_error())
                    message = f"Chrome navigation failed for Amazon search: {chrome_ctrl.chrome_last_error() or 'unknown error'}"
                    evidence.update({"error_type": error_type, "error_message": message})
                    self._write_evidence(evidence)
                    raise AmazonSearchPageError(error_type, message)

                await _mild_scroll()
                page = await _read_current_search_page()
                if not page:
                    message = "Chrome did not return Amazon search page DOM"
                    evidence.update({"error_type": "browser_unavailable", "error_message": message})
                    self._write_evidence(evidence)
                    raise AmazonSearchPageError("browser_unavailable", message)

                html = str(page.get("html") or "")
                body_text = str(page.get("body_text") or "")
                classification = classify_amazon_search_page(html or body_text)
                evidence.update({
                    "page_url": page.get("url"),
                    "page_title": page.get("title"),
                    "classification": classification,
                    "dom_summary": _amazon_dom_summary(html, body_text),
                })
                if classification:
                    message = f"Amazon search page blocked or unsupported: {classification}"
                    evidence.update({"error_type": classification, "error_message": message})
                    self._write_evidence(evidence)
                    raise AmazonSearchPageError(classification, message)
                try:
                    candidates = parse_amazon_search_results_html(html, query=query, marketplace=marketplace, limit=limit)
                except AmazonSearchPageError as exc:
                    evidence.update({
                        "finished_at": datetime.utcnow().isoformat(),
                        "candidate_count": 0,
                        "error_type": exc.error_type,
                        "error_message": str(exc),
                    })
                    self._write_evidence(evidence)
                    raise
                candidate_dicts = [candidate_to_dict(item) for item in candidates]
                evidence.update({
                    "finished_at": datetime.utcnow().isoformat(),
                    "candidate_count": len(candidates),
                    "candidates": candidate_dicts,
                })
                evidence_path = self._write_evidence(evidence)
                self.last_search_evidence = {
                    "evidence_path": evidence_path,
                    "page_url": page.get("url"),
                    "page_title": page.get("title"),
                    "classification": classification,
                    "candidate_count": len(candidates),
                }
                return candidates
        except AmazonSearchPageError:
            raise
        except TimeoutError as exc:
            message = f"Amazon search page navigation timed out: {exc}"
            evidence.update({"error_type": "navigation_timeout", "error_message": message})
            self._write_evidence(evidence)
            raise AmazonSearchPageError("navigation_timeout", message) from exc
        except Exception as exc:
            logger.exception("[AmazonSearchPage] Chrome adapter failed")
            message = f"Amazon search page adapter failed: {type(exc).__name__}: {exc}"
            evidence.update({"error_type": "parser_error", "error_message": message})
            self._write_evidence(evidence)
            raise AmazonSearchPageError("parser_error", message) from exc

    async def _apply_rate_limit(self) -> None:
        delay = max(0.0, float(settings.AMAZON_SEARCH_BETWEEN_QUERY_DELAY_SECONDS or 0))
        if not self._last_query_started_at or delay <= 0:
            self._last_query_started_at = datetime.utcnow()
            return
        elapsed = (datetime.utcnow() - self._last_query_started_at).total_seconds()
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._last_query_started_at = datetime.utcnow()

    def _write_evidence(self, evidence: dict[str, Any]) -> str:
        path = _evidence_path(
            task_run_id=evidence.get("task_run_id"),
            task_step_id=evidence.get("task_step_id"),
            query_index=evidence.get("query_index"),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        evidence_path = str(path)
        self.last_search_evidence = {
            "evidence_path": evidence_path,
            "classification": evidence.get("classification"),
            "error_type": evidence.get("error_type"),
            "candidate_count": evidence.get("candidate_count", 0),
        }
        return evidence_path


def get_amazon_search_page_adapter() -> AmazonSearchPageAdapter:
    adapter_name = (settings.AMAZON_SEARCH_PAGE_ADAPTER or AMAZON_SEARCH_ADAPTER_UNCONFIGURED).strip().lower()
    if adapter_name == AMAZON_SEARCH_ADAPTER_CHROME:
        if not settings.AMAZON_SEARCH_ENABLE_REAL_BROWSER:
            return UnconfiguredAmazonSearchPageAdapter()
        return ChromeAmazonSearchPageAdapter()
    return UnconfiguredAmazonSearchPageAdapter()


async def run_amazon_search_queries(
    queries: list[dict[str, Any]],
    *,
    marketplace: str = "US",
    per_query_limit: int = 12,
    adapter: AmazonSearchPageAdapter | None = None,
    product_id: int | None = None,
    item_code: str | None = None,
    task_run_id: int | None = None,
    task_step_id: int | None = None,
) -> list[AmazonSearchPageResult]:
    client = adapter or get_amazon_search_page_adapter()
    results: list[AmazonSearchPageResult] = []
    for index, query_spec in enumerate(queries, start=1):
        query = str(query_spec.get("query") or "").strip()
        if not query:
            continue
        evidence_context = AmazonSearchEvidenceContext(
            task_run_id=task_run_id,
            task_step_id=task_step_id,
            product_id=product_id,
            item_code=item_code,
            query_index=index,
        )
        candidates = await client.search(
            query,
            marketplace=marketplace,
            limit=per_query_limit,
            evidence_context=evidence_context,
        )
        adapter_evidence = getattr(client, "last_search_evidence", None)
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
                "evidence": adapter_evidence if isinstance(adapter_evidence, dict) else None,
            },
        ))
    return results


def build_amazon_search_url(query: str, *, marketplace: str = "US") -> str:
    base_url = _amazon_base_url(marketplace)
    params = urlencode({
        "k": query,
        "language": "en_US",
        "ref": "nb_sb_noss",
    })
    return f"{base_url.rstrip('/')}/s?{params}"


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
        block_without_scripts = _strip_script_like_blocks(block)
        result_tag = _opening_tag(block)
        asin = _extract_attr(result_tag, "data-asin")
        url = _extract_product_url(block_without_scripts, asin=asin, marketplace=marketplace)
        if not _valid_asin(asin):
            asin = _extract_asin_from_product_url(url)
        if not asin:
            continue
        title = _clean_text(_extract_first(block_without_scripts, [
            r'<h2[^>]*>.*?<span[^>]*>(.*?)</span>.*?</h2>',
            r'<h2[^>]*>.*?<a[^>]*>(.*?)</a>.*?</h2>',
            r'<a[^>]+href\s*=\s*["\'][^"\']*(?:/dp/|/gp/product/)[A-Z0-9]{10}[^"\']*["\'][^>]*>.*?<span[^>]*>(.*?)</span>.*?</a>',
            r'<span[^>]+class\s*=\s*["\'][^"\']*a-text-normal[^"\']*["\'][^>]*>(.*?)</span>',
        ]))
        image_url = _extract_attr(_extract_first(block_without_scripts, [r'<img[^>]+class\s*=\s*["\'][^"\']*s-image[^"\']*["\'][^>]*>']), "src")
        price = _clean_text(_extract_first(block_without_scripts, [
            r'<span[^>]+class\s*=\s*["\'][^"\']*a-price[^"\']*["\'][^>]*>.*?<span[^>]+class\s*=\s*["\'][^"\']*a-offscreen[^"\']*["\'][^>]*>(.*?)</span>.*?</span>',
        ]))
        rating = _clean_text(_extract_first(block_without_scripts, [r'<span[^>]+class\s*=\s*["\'][^"\']*a-icon-alt[^"\']*["\'][^>]*>(.*?)</span>']))
        review_count = _clean_text(_extract_first(block_without_scripts, [
            r'<span[^>]+class\s*=\s*["\'][^"\']*a-size-base[^"\']*s-underline-text[^"\']*["\'][^>]*>(.*?)</span>',
            r'aria-label\s*=\s*["\']([\d,]+)["\']',
        ]))
        sponsored = bool(re.search(r"\bSponsored\b", _strip_tags(block_without_scripts), re.I))
        candidates.append(AmazonSearchPageCandidate(
            asin=asin.strip().upper(),
            url=url,
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
    if "too many requests" in lower or "request was throttled" in lower:
        return "rate_limited"
    if "sign in" in lower and "ap_signin" in lower:
        return "login_required"
    if _has_search_result_structure(html):
        return None
    if "deliver to" in lower and "choose your location" in lower:
        return "region_page"
    if not _has_search_result_structure(html) and not _has_data_asin_attr(html):
        return "unsupported_page_structure"
    return None


def candidate_to_dict(candidate: AmazonSearchPageCandidate) -> dict[str, Any]:
    return asdict(candidate)


def _has_search_result_structure(html: str) -> bool:
    return bool(_result_blocks(html)) or bool(re.search(
        r'data-component-type\s*=\s*["\']s-search-result["\']',
        html,
        re.I,
    ))


def _has_data_asin_attr(html: str) -> bool:
    return bool(re.search(r'\bdata-asin\s*=', _strip_script_like_blocks(html), re.I))


def _result_blocks(html: str) -> list[str]:
    blocks: list[str] = []
    pattern = re.compile(
        r'<div\b(?=[^>]*\bdata-component-type\s*=\s*["\']s-search-result["\'])[^>]*>',
        re.I | re.S,
    )
    matches = list(pattern.finditer(html))
    for index, match in enumerate(matches):
        start = match.start()
        next_result_start = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        end = _balanced_div_end(html, match.end(), limit=next_result_start)
        blocks.append(html[start:end])
    return blocks


def _balanced_div_end(html: str, open_tag_end: int, *, limit: int) -> int:
    depth = 1
    for tag in re.finditer(r"</?div\b[^>]*>", html[open_tag_end:limit], re.I | re.S):
        tag_text = tag.group(0)
        if tag_text.startswith("</"):
            depth -= 1
            if depth == 0:
                return open_tag_end + tag.end()
        else:
            depth += 1
    return _fallback_result_fragment_end(html, open_tag_end, limit=limit)


def _fallback_result_fragment_end(html: str, open_tag_end: int, *, limit: int) -> int:
    fragment = html[open_tag_end:limit]
    outside_marker = re.search(r"<(?:nav|header|footer|main|aside)\b", fragment, re.I)
    if outside_marker:
        return open_tag_end + outside_marker.start()
    return min(limit, open_tag_end + 30000)


def _amazon_dom_summary(html: str, body_text: str) -> dict[str, Any]:
    result_blocks = _result_blocks(html)
    block_without_scripts = [_strip_script_like_blocks(block) for block in result_blocks]
    return {
        "html_length": len(html),
        "body_text_sample": body_text[:1200],
        "result_count_hint": len(result_blocks),
        "data_asin_hint": sum(1 for block in result_blocks if _valid_asin(_extract_attr(_opening_tag(block), "data-asin"))),
        "dp_link_hint": sum(1 for block in block_without_scripts if _extract_asin_from_product_url(_extract_product_url(block, asin=None, marketplace="US"))),
        "result_block_snippets": [_safe_dom_snippet(block) for block in result_blocks[:3]],
    }


def _opening_tag(html: str | None) -> str | None:
    if not html:
        return None
    match = re.match(r"\s*(<[^>]+>)", html, re.S)
    return match.group(1) if match else None


def _strip_script_like_blocks(html: str) -> str:
    without_scripts = re.sub(r"<script\b[^>]*>.*?</script\s*>", " ", html, flags=re.I | re.S)
    return re.sub(r"<style\b[^>]*>.*?</style\s*>", " ", without_scripts, flags=re.I | re.S)


def _safe_dom_snippet(html: str, *, limit: int = 900) -> str:
    snippet = _strip_script_like_blocks(html)
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet[:limit]


def _valid_asin(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[A-Z0-9]{10}", value.strip().upper()))


def _extract_product_url(block: str, *, asin: str | None, marketplace: str) -> str | None:
    expected_asin = asin.strip().upper() if _valid_asin(asin) else None
    fallback_url: str | None = None
    for anchor in re.finditer(r"<a\b[^>]*\bhref\s*=\s*([\"'])(.*?)\1[^>]*>", block, re.I | re.S):
        href = unescape(anchor.group(2)).strip()
        href_asin = _extract_asin_from_product_url(href)
        if not href_asin:
            continue
        absolute_url = _absolute_amazon_url(href, marketplace)
        if expected_asin:
            if href_asin == expected_asin:
                return absolute_url
            continue
        if fallback_url is None:
            fallback_url = absolute_url
    return fallback_url


def _extract_asin_from_product_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"(?:/dp/|/gp/product/)([A-Z0-9]{10})(?:[/?#]|$)", url, re.I)
    if not match:
        return None
    asin = match.group(1).upper()
    return asin if _valid_asin(asin) else None


def _extract_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return match.group(1) if match.lastindex else match.group(0)
    return None


def _extract_attr(text: str | None, attr: str) -> str | None:
    if not text:
        return None
    quoted = re.search(rf'\b{re.escape(attr)}\s*=\s*(["\'])(.*?)\1', text, re.I | re.S)
    if quoted:
        return unescape(quoted.group(2)).strip()
    unquoted = re.search(rf'\b{re.escape(attr)}\s*=\s*([^\s>]+)', text, re.I)
    return unescape(unquoted.group(1)).strip() if unquoted else None


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
    return urljoin(_amazon_base_url(marketplace), url)


def _amazon_base_url(marketplace: str) -> str:
    configured = (settings.AMAZON_SEARCH_BASE_URL or "").strip()
    if configured:
        return configured
    if marketplace.upper() in {"US", "USA"}:
        return "https://www.amazon.com"
    return "https://www.amazon.com"


async def _mild_scroll() -> None:
    await chrome_ctrl.chrome_execute_js(
        "(function(){ window.scrollTo(0, Math.min(document.body.scrollHeight || 0, 900)); return 'ok'; })()",
        timeout=5,
    )
    await asyncio.sleep(1.0)


async def _read_current_search_page() -> dict[str, Any] | None:
    js = r'''(function() {
  try {
    return JSON.stringify({
      url: location.href,
      title: document.title,
      html: document.documentElement ? document.documentElement.outerHTML : "",
      body_text: document.body && document.body.innerText ? document.body.innerText : ""
    });
  } catch (err) {
    return JSON.stringify({
      url: location.href,
      title: document.title,
      html: "",
      body_text: "",
      error: String(err && err.stack ? err.stack : err)
    });
  }
})()'''
    raw = await chrome_ctrl.chrome_execute_js(js, timeout=max(5, int(settings.AMAZON_SEARCH_NAV_TIMEOUT_SECONDS)))
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"url": None, "title": None, "html": raw, "body_text": raw}
    return parsed if isinstance(parsed, dict) else None


def _chrome_error_type(message: str | None) -> str:
    lower = (message or "").lower()
    if "not authorized" in lower or "not allowed" in lower or "not permitted" in lower or "permission" in lower:
        return "browser_permission_denied"
    if "timed out" in lower or "timeout" in lower:
        return "navigation_timeout"
    return "browser_unavailable"


def _evidence_path(*, task_run_id: Any, task_step_id: Any, query_index: Any) -> Path:
    run_part = f"run-{task_run_id}" if task_run_id else "run-unknown"
    step_part = f"step-{task_step_id}" if task_step_id else "step-unknown"
    query_part = f"query-{query_index or 'unknown'}"
    root = settings.AMAZON_SEARCH_EVIDENCE_DIR or (settings.DATA_DIR / "task_evidence" / "amazon_search_page")
    return Path(root) / run_part / step_part / f"{query_part}.json"
