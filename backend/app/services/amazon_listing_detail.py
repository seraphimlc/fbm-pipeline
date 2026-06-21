from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from html import unescape
from typing import Any, Protocol


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


class AmazonListingDetailAdapter(Protocol):
    async def fetch(self, asin: str, *, url: str | None = None, marketplace: str = "US") -> AmazonListingDetail:
        ...


class UnconfiguredAmazonListingDetailAdapter:
    async def fetch(self, asin: str, *, url: str | None = None, marketplace: str = "US") -> AmazonListingDetail:
        raise AmazonListingDetailError(
            "adapter_not_configured",
            "Amazon listing detail adapter is not configured; real Amazon detail capture requires explicit authorization",
        )


class FixtureAmazonListingDetailAdapter:
    def __init__(self, html_by_asin: dict[str, str] | None = None):
        self.html_by_asin = {str(key).upper(): value for key, value in (html_by_asin or {}).items()}

    async def fetch(self, asin: str, *, url: str | None = None, marketplace: str = "US") -> AmazonListingDetail:
        normalized_asin = str(asin or "").strip().upper()
        html = self.html_by_asin.get(normalized_asin)
        if html is None:
            raise AmazonListingDetailError("fixture_missing", f"No fixture HTML for ASIN: {normalized_asin}")
        return parse_amazon_listing_detail_html(html, asin=normalized_asin, url=url, marketplace=marketplace)


def get_amazon_listing_detail_adapter() -> AmazonListingDetailAdapter:
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
    bullets = [
        _clean_text(item)
        for item in re.findall(r'<li[^>]*>\s*<span[^>]*class="[^"]*a-list-item[^"]*"[^>]*>(.*?)</span>\s*</li>', html, re.I | re.S)
    ]
    bullets = [item for item in bullets if item]
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
    if "sign in" in lower and "ap_signin" in lower:
        return "login_required"
    if "currently unavailable" in lower and "producttitle" not in lower:
        return "not_found"
    if "id=\"producttitle\"" not in lower and "id='producttitle'" not in lower and "data-asin" not in lower:
        return "unsupported_page_structure"
    return None


def _extract_product_details(html: str) -> dict[str, str]:
    details: dict[str, str] = {}
    for key, value in re.findall(r'<tr[^>]*>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*</tr>', html, re.I | re.S):
        clean_key = _clean_text(key)
        clean_value = _clean_text(value)
        if clean_key and clean_value:
            details[clean_key] = clean_value
    for key, value in re.findall(r'<span[^>]+class="[^"]*a-text-bold[^"]*"[^>]*>(.*?)</span>\s*<span[^>]*>(.*?)</span>', html, re.I | re.S):
        clean_key = _clean_text(key).rstrip(":：")
        clean_value = _clean_text(value)
        if clean_key and clean_value:
            details.setdefault(clean_key, clean_value)
    return details


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
