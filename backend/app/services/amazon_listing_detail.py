from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any, Protocol

from app.config import settings
from app.pipeline import chrome_ctrl


AMAZON_LISTING_DETAIL_ADAPTER_UNCONFIGURED = "unconfigured"
AMAZON_LISTING_DETAIL_ADAPTER_CHROME = "chrome"

logger = logging.getLogger(__name__)


class AmazonListingDetailError(RuntimeError):
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True)
class AmazonListingDetail:
    asin: str
    url: str | None
    title: str | None
    brand: str | None
    seller: str | None
    price: str | None
    rating: str | None
    review_count: str | None
    category_rank: str | None
    leaf_category: str | None
    main_image_url: str | None
    bullets: list[str]
    description: str | None
    product_details: dict[str, str]
    aplus_text: str | None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class AmazonListingDetailEvidenceContext:
    task_run_id: int | None = None
    task_step_id: int | None = None
    product_id: int | None = None
    candidate_id: int | None = None
    visual_rank: int | None = None


class AmazonListingDetailAdapter(Protocol):
    async def fetch(
        self,
        asin: str,
        *,
        url: str | None = None,
        marketplace: str = "US",
        evidence_context: AmazonListingDetailEvidenceContext | None = None,
    ) -> AmazonListingDetail:
        ...


class UnconfiguredAmazonListingDetailAdapter:
    async def fetch(
        self,
        asin: str,
        *,
        url: str | None = None,
        marketplace: str = "US",
        evidence_context: AmazonListingDetailEvidenceContext | None = None,
    ) -> AmazonListingDetail:
        raise AmazonListingDetailError(
            "adapter_not_configured",
            "Amazon listing detail adapter is not configured; real Amazon detail capture requires explicit authorization",
        )


class FixtureAmazonListingDetailAdapter:
    def __init__(self, html_by_asin: dict[str, str] | None = None):
        self.html_by_asin = {str(key).upper(): value for key, value in (html_by_asin or {}).items()}

    async def fetch(
        self,
        asin: str,
        *,
        url: str | None = None,
        marketplace: str = "US",
        evidence_context: AmazonListingDetailEvidenceContext | None = None,
    ) -> AmazonListingDetail:
        normalized_asin = str(asin or "").strip().upper()
        html = self.html_by_asin.get(normalized_asin)
        if html is None:
            raise AmazonListingDetailError("fixture_missing", f"No fixture HTML for ASIN: {normalized_asin}")
        return parse_amazon_listing_detail_html(html, asin=normalized_asin, url=url, marketplace=marketplace)


class ChromeAmazonListingDetailAdapter:
    """Read real Amazon detail pages through the dedicated local Chrome worker tab."""

    def __init__(self):
        self._last_fetch_started_at: datetime | None = None
        self.last_detail_evidence: dict[str, Any] | None = None

    async def fetch(
        self,
        asin: str,
        *,
        url: str | None = None,
        marketplace: str = "US",
        evidence_context: AmazonListingDetailEvidenceContext | None = None,
    ) -> AmazonListingDetail:
        normalized_asin = str(asin or "").strip().upper()
        if not _valid_asin(normalized_asin):
            raise AmazonListingDetailError("invalid_asin", f"Invalid Amazon ASIN: {normalized_asin or '<empty>'}")
        context = evidence_context or AmazonListingDetailEvidenceContext()
        target_url = _canonical_listing_url(normalized_asin, marketplace=marketplace)
        await self._apply_rate_limit()
        started_at = datetime.utcnow()
        evidence: dict[str, Any] = {
            "adapter": self.__class__.__name__,
            "asin": normalized_asin,
            "marketplace": marketplace,
            "requested_url": url,
            "target_url": target_url,
            "started_at": started_at.isoformat(),
            "task_run_id": context.task_run_id,
            "task_step_id": context.task_step_id,
            "product_id": context.product_id,
            "candidate_id": context.candidate_id,
            "visual_rank": context.visual_rank,
            "config": {
                "after_load_wait_seconds": settings.AMAZON_LISTING_DETAIL_AFTER_LOAD_WAIT_SECONDS,
                "between_candidate_delay_seconds": settings.AMAZON_LISTING_DETAIL_BETWEEN_CANDIDATE_DELAY_SECONDS,
            },
        }
        self.last_detail_evidence = None
        try:
            async with chrome_ctrl.chrome_workflow(f"amazon_listing_detail asin={normalized_asin}"):
                navigated = await chrome_ctrl.chrome_navigate(
                    target_url,
                    wait=settings.AMAZON_LISTING_DETAIL_AFTER_LOAD_WAIT_SECONDS,
                )
                if not navigated:
                    error_type = _chrome_error_type(chrome_ctrl.chrome_last_error())
                    message = f"Chrome navigation failed for Amazon detail: {chrome_ctrl.chrome_last_error() or 'unknown error'}"
                    evidence.update({"error_type": error_type, "error_message": message})
                    self._write_evidence(evidence)
                    raise AmazonListingDetailError(error_type, message)

                await _load_detail_sections()
                page = await _read_current_detail_page()
                if not page:
                    message = "Chrome did not return Amazon listing detail DOM"
                    evidence.update({"error_type": "browser_unavailable", "error_message": message})
                    self._write_evidence(evidence)
                    raise AmazonListingDetailError("browser_unavailable", message)

                html = str(page.get("html") or "")
                body_text = str(page.get("body_text") or "")
                classification = classify_amazon_listing_detail_page(html or body_text)
                evidence.update({
                    "page_url": page.get("url"),
                    "page_title": page.get("title"),
                    "classification": classification,
                    "dom_summary": _amazon_detail_dom_summary(html, body_text),
                })
                if classification:
                    message = f"Amazon listing detail page blocked or unsupported: {classification}"
                    evidence.update({"error_type": classification, "error_message": message})
                    self._write_evidence(evidence)
                    raise AmazonListingDetailError(classification, message)

                detail = parse_amazon_listing_detail_html(
                    html,
                    asin=normalized_asin,
                    url=str(page.get("url") or target_url),
                    marketplace=marketplace,
                )
                detail_payload = listing_detail_to_dict(detail)
                detail_payload["raw"] = None
                evidence.update({
                    "finished_at": datetime.utcnow().isoformat(),
                    "detail": detail_payload,
                    "quality": {
                        "has_title": bool(detail.title),
                        "bullet_count": len(detail.bullets),
                        "has_main_image": bool(detail.main_image_url),
                        "product_detail_count": len(detail.product_details),
                    },
                })
                evidence_path = self._write_evidence(evidence)
                return replace(detail, raw={
                    "adapter": self.__class__.__name__,
                    "parser": "amazon_detail_html_v2",
                    "evidence_path": evidence_path,
                    "page_url": page.get("url"),
                    "page_title": page.get("title"),
                })
        except AmazonListingDetailError:
            raise
        except TimeoutError as exc:
            message = f"Amazon listing detail navigation timed out: {exc}"
            evidence.update({"error_type": "timeout", "error_message": message})
            self._write_evidence(evidence)
            raise AmazonListingDetailError("timeout", message) from exc
        except Exception as exc:
            logger.exception("[AmazonListingDetail] Chrome adapter failed")
            message = f"Amazon listing detail adapter failed: {type(exc).__name__}: {exc}"
            evidence.update({"error_type": "parse_error", "error_message": message})
            self._write_evidence(evidence)
            raise AmazonListingDetailError("parse_error", message) from exc

    async def _apply_rate_limit(self) -> None:
        delay = max(0.0, float(settings.AMAZON_LISTING_DETAIL_BETWEEN_CANDIDATE_DELAY_SECONDS or 0))
        if not self._last_fetch_started_at or delay <= 0:
            self._last_fetch_started_at = datetime.utcnow()
            return
        elapsed = (datetime.utcnow() - self._last_fetch_started_at).total_seconds()
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._last_fetch_started_at = datetime.utcnow()

    def _write_evidence(self, evidence: dict[str, Any]) -> str:
        path = _evidence_path(
            task_run_id=evidence.get("task_run_id"),
            task_step_id=evidence.get("task_step_id"),
            visual_rank=evidence.get("visual_rank"),
            asin=evidence.get("asin"),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        evidence_path = str(path)
        self.last_detail_evidence = {
            "evidence_path": evidence_path,
            "asin": evidence.get("asin"),
            "classification": evidence.get("classification"),
            "error_type": evidence.get("error_type"),
            "has_title": bool((evidence.get("quality") or {}).get("has_title")),
            "bullet_count": int((evidence.get("quality") or {}).get("bullet_count") or 0),
        }
        return evidence_path


def get_amazon_listing_detail_adapter() -> AmazonListingDetailAdapter:
    adapter_name = (
        settings.AMAZON_LISTING_DETAIL_ADAPTER or AMAZON_LISTING_DETAIL_ADAPTER_UNCONFIGURED
    ).strip().lower()
    if adapter_name == AMAZON_LISTING_DETAIL_ADAPTER_CHROME:
        if not settings.AMAZON_LISTING_DETAIL_ENABLE_REAL_BROWSER:
            return UnconfiguredAmazonListingDetailAdapter()
        return ChromeAmazonListingDetailAdapter()
    return UnconfiguredAmazonListingDetailAdapter()


def listing_detail_to_dict(detail: AmazonListingDetail) -> dict[str, Any]:
    return asdict(detail)


def parse_amazon_listing_detail_html(
    html: str,
    *,
    asin: str,
    url: str | None = None,
    marketplace: str = "US",
) -> AmazonListingDetail:
    error_type = classify_amazon_listing_detail_page(html)
    if error_type:
        raise AmazonListingDetailError(error_type, f"Amazon listing detail page blocked or unsupported: {error_type}")

    title = _clean_text(_extract_first(html, [
        r'<span[^>]+id="productTitle"[^>]*>(.*?)</span>',
        r'<h1[^>]*>(.*?)</h1>',
    ]))
    brand = _clean_text(_extract_first(html, [
        r'id="bylineInfo"[^>]*>(.*?)</a>',
        r'Brand\s*[:：]\s*</span>\s*<span[^>]*>(.*?)</span>',
    ]))
    seller = _clean_text(_extract_first(html, [
        r'id="sellerProfileTriggerId"[^>]*>(.*?)</a>',
        r'Sold by\s*</span>\s*<span[^>]*>(.*?)</span>',
    ]))
    price = _clean_text(_extract_first(html, [
        r'<span[^>]+class="[^"]*a-price[^"]*"[^>]*>.*?<span[^>]+class="[^"]*a-offscreen[^"]*"[^>]*>(.*?)</span>.*?</span>',
    ]))
    rating = _clean_text(_extract_first(html, [r'<span[^>]+class="[^"]*a-icon-alt[^"]*"[^>]*>(.*?)</span>']))
    review_count = _clean_text(_extract_first(html, [
        r'id="acrCustomerReviewText"[^>]*>(.*?)</span>',
        r'([\d,]+)\s+ratings',
    ]))
    main_image_url = _extract_attr(_extract_first(html, [
        r'<img[^>]+id="landingImage"[^>]*>',
        r'<img[^>]+data-old-hires="[^"]*"[^>]*>',
    ]), "src") or _extract_attr(_extract_first(html, [r'<img[^>]+data-old-hires="[^"]*"[^>]*>']), "data-old-hires")
    bullets = _extract_feature_bullets(html)
    description = _clean_text(_extract_first(html, [
        r'id="productDescription"[^>]*>.*?<span[^>]*>(.*?)</span>',
        r'id="feature-bullets"[^>]*>(.*?)</div>',
    ]))
    product_details = _extract_product_details(html)
    category_rank = product_details.get("Best Sellers Rank") or _clean_text(_extract_first(html, [
        r'Best Sellers Rank.*?</span>\s*<span[^>]*>(.*?)</span>',
    ]))
    leaf_category = _leaf_category_from_rank(category_rank)
    aplus_text = _clean_text(_extract_first(html, [
        r'id="aplus"[^>]*>(.*?)</div>\s*</div>',
        r'id="aplus_feature_div"[^>]*>(.*?)</div>',
    ]))

    return AmazonListingDetail(
        asin=str(asin or "").strip().upper(),
        url=url,
        title=title,
        brand=brand,
        seller=seller,
        price=price,
        rating=rating,
        review_count=review_count,
        category_rank=category_rank,
        leaf_category=leaf_category,
        main_image_url=main_image_url,
        bullets=bullets,
        description=description,
        product_details=product_details,
        aplus_text=aplus_text,
        raw={"asin": asin, "marketplace": marketplace, "parser": "fixture_html_v1"},
    )


def classify_amazon_listing_detail_page(html: str) -> str | None:
    lower = html.lower()
    if "enter the characters you see below" in lower or "captcha" in lower:
        return "captcha"
    if "robot check" in lower or "automated access" in lower:
        return "bot_check"
    if "too many requests" in lower or "request was throttled" in lower:
        return "rate_limited"
    if "sign in" in lower and "ap_signin" in lower:
        return "login_required"
    if "deliver to" in lower and "choose your location" in lower and "producttitle" not in lower:
        return "region_page"
    if "currently unavailable" in lower and "producttitle" not in lower:
        return "not_found"
    if "id=\"producttitle\"" not in lower and "id='producttitle'" not in lower and "data-asin" not in lower:
        return "unsupported_page_structure"
    return None


def _extract_product_details(html: str) -> dict[str, str]:
    details: dict[str, str] = {}
    sections = _detail_sections(html)
    for section in sections:
        for key, value in re.findall(
            r'<tr[^>]*>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*</tr>',
            section,
            re.I | re.S,
        ):
            clean_key = _clean_text(key)
            clean_value = _clean_text(value)
            if clean_key and clean_value and len(clean_key) <= 200 and len(clean_value) <= 2000:
                details[clean_key] = clean_value
        for key, value in re.findall(
            r'<span[^>]+class=["\'][^"\']*a-text-bold[^"\']*["\'][^>]*>(.*?)</span>\s*<span[^>]*>(.*?)</span>',
            section,
            re.I | re.S,
        ):
            clean_key = (_clean_text(key) or "").rstrip(":：")
            clean_value = _clean_text(value)
            if clean_key and clean_value and len(clean_key) <= 200 and len(clean_value) <= 2000:
                details.setdefault(clean_key, clean_value)
    return details


def _detail_sections(html: str) -> list[str]:
    sections: list[str] = []
    for pattern in (
        r'<table[^>]+id=["\']productDetails_[^"\']+["\'][^>]*>.*?</table>',
        r'<div[^>]+id=["\']productOverview_feature_div["\'][^>]*>.*?</table>',
        r'<div[^>]+id=["\']detailBullets_feature_div["\'][^>]*>.*?</ul>',
    ):
        sections.extend(re.findall(pattern, html, re.I | re.S))
    return sections


def _extract_feature_bullets(html: str) -> list[str]:
    """Read only the product's About This Item list, not every page list item."""
    feature_section = _extract_first(html, [
        r'<div[^>]+id=["\']feature-bullets["\'][^>]*>(.*?</ul>)',
        r'<div[^>]+id=["\']featurebullets_feature_div["\'][^>]*>(.*?</ul>)',
    ])
    if not feature_section:
        return []
    bullets = [
        _clean_text(item)
        for item in re.findall(
            r'<li[^>]*>\s*<span[^>]*class=["\'][^"\']*a-list-item[^"\']*["\'][^>]*>(.*?)</span>\s*</li>',
            feature_section,
            re.I | re.S,
        )
    ]
    return [item for item in bullets if item and item not in {"›", "|"}]


def _leaf_category_from_rank(rank: str | None) -> str | None:
    if not rank:
        return None
    parts = [part.strip() for part in re.split(r">\s*| in ", rank) if part.strip()]
    return parts[-1] if parts else None


def _extract_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return match.group(1) if match.lastindex else match.group(0)
    return None


def _extract_attr(tag: str | None, attr: str) -> str | None:
    if not tag:
        return None
    match = re.search(rf'{attr}=["\']([^"\']+)["\']', tag, re.I)
    return unescape(match.group(1).strip()) if match else None


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _valid_asin(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[A-Z0-9]{10}", value.strip().upper()))


def _canonical_listing_url(asin: str, *, marketplace: str) -> str:
    base = (settings.AMAZON_SEARCH_BASE_URL or "https://www.amazon.com").strip().rstrip("/")
    return f"{base}/dp/{asin}?language=en_US"


async def _load_detail_sections() -> None:
    js = r'''(function() {
  const targets = [
    document.getElementById('feature-bullets'),
    document.getElementById('productDetails_feature_div'),
    document.getElementById('detailBullets_feature_div'),
    document.getElementById('aplus_feature_div')
  ].filter(Boolean);
  for (const target of targets) {
    try { target.scrollIntoView({block: 'center'}); } catch (err) {}
  }
  window.scrollTo(0, Math.min(document.body ? document.body.scrollHeight : 0, 1800));
  return 'ok';
})()'''
    await chrome_ctrl.chrome_execute_js(js, timeout=5)
    await asyncio.sleep(1.5)


async def _read_current_detail_page() -> dict[str, Any] | None:
    js = r'''(function() {
  try {
    return JSON.stringify({
      url: location.href,
      title: document.title,
      html: document.documentElement ? document.documentElement.outerHTML : "",
      body_text: document.body && document.body.innerText ? document.body.innerText : ""
    });
  } catch (err) {
    return JSON.stringify({url: location.href, title: document.title, html: "", body_text: "", error: String(err)});
  }
})()'''
    raw = await chrome_ctrl.chrome_execute_js(
        js,
        timeout=max(5, int(settings.AMAZON_LISTING_DETAIL_NAV_TIMEOUT_SECONDS)),
    )
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
        return "timeout"
    return "browser_unavailable"


def _amazon_detail_dom_summary(html: str, body_text: str) -> dict[str, Any]:
    return {
        "html_length": len(html),
        "body_text_sample": body_text[:1200],
        "has_product_title": bool(re.search(r'id=["\']productTitle["\']', html, re.I)),
        "bullet_hint": len(re.findall(r'class=["\'][^"\']*a-list-item', html, re.I)),
        "has_landing_image": bool(re.search(r'id=["\']landingImage["\']', html, re.I)),
        "has_aplus": "aplus_feature_div" in html or 'id="aplus"' in html,
    }


def _evidence_path(*, task_run_id: Any, task_step_id: Any, visual_rank: Any, asin: Any) -> Path:
    run_part = f"run-{task_run_id}" if task_run_id else "run-unknown"
    step_part = f"step-{task_step_id}" if task_step_id else "step-unknown"
    rank_part = f"rank-{int(visual_rank):02d}" if visual_rank else "rank-unknown"
    asin_part = str(asin or "unknown").strip().upper()
    root = settings.AMAZON_LISTING_DETAIL_EVIDENCE_DIR or (
        settings.DATA_DIR / "task_evidence" / "amazon_listing_detail"
    )
    return Path(root) / run_part / step_part / f"{rank_part}-{asin_part}.json"
