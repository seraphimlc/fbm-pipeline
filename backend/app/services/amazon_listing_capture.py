import json
import re
import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AmazonListingCapture, AmazonStyleSnapCandidate
from app.pipeline.chrome_ctrl import chrome_execute_js, chrome_navigate, chrome_workflow


SOURCE_PLATFORM = "AMAZON_LISTING"


CAPTURE_JS = r"""(function() {
  function text(el) {
    return el ? String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : null;
  }
  function firstText(selectors) {
    for (var i = 0; i < selectors.length; i++) {
      var value = text(document.querySelector(selectors[i]));
      if (value) return value;
    }
    return null;
  }
  function metaContent(selectors) {
    for (var i = 0; i < selectors.length; i++) {
      var el = document.querySelector(selectors[i]);
      var value = el ? String(el.getAttribute('content') || '').replace(/\s+/g, ' ').trim() : null;
      if (value) return value;
    }
    return null;
  }
  function amazonTitleFromPageTitle(value) {
    var title = String(value || '').replace(/\s+/g, ' ').trim();
    if (!title || !/^Amazon\.com\s*:/i.test(title)) return null;
    title = title.replace(/^Amazon\.com\s*:\s*/i, '');
    title = title.replace(/\s*:\s*Amazon\.com\s*$/i, '');
    title = title.replace(/\s*:\s*[^:]{2,80}\s*$/, '');
    return title.trim() || null;
  }
  function cleanList(items) {
    var seen = {};
    return items.map(function(item) {
      return String(item || '').replace(/\s+/g, ' ').trim();
    }).filter(function(item) {
      if (!item || seen[item]) return false;
      seen[item] = true;
      return true;
    });
  }
  function detailRows(rootSelector) {
    var rows = {};
    document.querySelectorAll(rootSelector).forEach(function(row) {
      var key = null;
      var value = null;
      var th = row.querySelector('th');
      var td = row.querySelector('td');
      if (th && td) {
        key = text(th);
        value = text(td);
      } else {
        var label = row.querySelector('.a-text-bold');
        if (label) {
          key = text(label);
          value = text(row).replace(key || '', '').replace(/^[:\s]+/, '').trim();
        }
      }
      if (key && value) {
        key = key.replace(/[:\s]+$/, '').trim();
        rows[key] = value;
      }
    });
    return rows;
  }
  function dynamicImages() {
    var urls = [];
    var landing = document.querySelector('#landingImage, #imgTagWrapperId img, #main-image-container img');
    if (landing) {
      var dyn = landing.getAttribute('data-a-dynamic-image');
      if (dyn) {
        try {
          Object.keys(JSON.parse(dyn)).forEach(function(url) { urls.push(url); });
        } catch (e) {}
      }
      if (landing.src) urls.push(landing.src);
    }
    document.querySelectorAll('#altImages img, #imageBlock img, img[data-old-hires]').forEach(function(img) {
      var url = img.getAttribute('data-old-hires') || img.src;
      if (url) urls.push(url.replace(/\._[A-Z0-9_,]+_\./, '.'));
    });
    return cleanList(urls).filter(function(url) { return /^https?:\/\//.test(url); });
  }
  function breadcrumbs() {
    var values = [];
    document.querySelectorAll('#wayfinding-breadcrumbs_container a, #wayfinding-breadcrumbs_feature_div a').forEach(function(a) {
      var value = text(a);
      if (value && !/^back to/i.test(value)) values.push(value);
    });
    return cleanList(values);
  }
  function bestSellerRank() {
    var texts = [];
    [
      '#detailBulletsWrapper_feature_div',
      '#detailBullets_feature_div',
      '#productDetails_detailBullets_sections1',
      '#prodDetails',
      '#productDetails_techSpec_section_1'
    ].forEach(function(sel) {
      var value = text(document.querySelector(sel));
      if (value) texts.push(value);
    });
    var joined = texts.join(' ');
    var match = joined.match(/Best Sellers Rank\s*[:#\s]*([\s\S]{0,700}?)(?=(?:Date First Available|Manufacturer|Customer Reviews|ASIN|$))/i);
    return match ? match[1].replace(/\s+/g, ' ').trim() : null;
  }
  var details = Object.assign(
    {},
    detailRows('#productDetails_techSpec_section_1 tr'),
    detailRows('#productDetails_detailBullets_sections1 tr'),
    detailRows('#detailBullets_feature_div li')
  );
  var images = dynamicImages();
  var bullets = [];
  document.querySelectorAll('#feature-bullets li span, #featurebullets_feature_div li span').forEach(function(el) {
    var value = text(el);
    if (value && !/Make sure this fits/i.test(value)) bullets.push(value);
  });
  var bodyText = text(document.body) || '';
  var blocked = /captcha|Enter the characters you see below|Sorry, we just need to make sure/i.test(bodyText);
  var unavailable = /Page Not Found|Sorry! We couldn't find that page|Looking for something\\?/i.test(document.title || bodyText);
  var domTitle = firstText(['#productTitle', 'h1#title']);
  var metaTitle = metaContent(['meta[property="og:title"]', 'meta[name="title"]']);
  return JSON.stringify({
    url: location.href,
    page_title: document.title || null,
    page_body_length: bodyText.length,
    blocked: blocked,
    unavailable: unavailable,
    title: domTitle || amazonTitleFromPageTitle(metaTitle) || amazonTitleFromPageTitle(document.title),
    brand: firstText(['#bylineInfo', 'a#bylineInfo', '#brand', 'tr.po-brand td.a-span9 span']),
    seller: firstText(['#sellerProfileTriggerId', '#merchant-info a', '#merchant-info']),
    price: firstText(['#corePriceDisplay_desktop_feature_div .a-price .a-offscreen', '#corePrice_feature_div .a-offscreen', '.a-price .a-offscreen']),
    rating: firstText(['#acrPopover .a-icon-alt', '.reviewCountTextLinkedHistogram .a-icon-alt']),
    review_count: firstText(['#acrCustomerReviewText', '#reviewsMedley .totalReviewCount']),
    availability: firstText(['#availability', '#outOfStock', '#availabilityInsideBuyBox_feature_div']),
    categories: breadcrumbs(),
    category_rank: bestSellerRank(),
    bullets: cleanList(bullets),
    description: firstText(['#productDescription', '#bookDescription_feature_div', '#productDescription_feature_div']),
    product_details: details,
    aplus_text: (firstText(['#aplus', '#aplus_feature_div']) || '').slice(0, 12000),
    main_image_url: images[0] || null,
    image_urls: images.slice(0, 20)
  });
})()"""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _listing_url(candidate: AmazonStyleSnapCandidate) -> str:
    return candidate.url or f"https://www.amazon.com/dp/{candidate.asin}"


def _leaf_category(categories: list[Any], category_rank: str | None) -> str | None:
    cleaned = [str(item).strip() for item in categories if str(item).strip()]
    if cleaned:
        return cleaned[-1]
    if category_rank:
        matches = re.findall(r"#?[\d,]+\s+in\s+([^#()]+)", category_rank)
        cleaned_matches = [re.sub(r"\s+", " ", item).strip(" >›-") for item in matches if item.strip()]
        if cleaned_matches:
            return cleaned_matches[-1]
    return None


async def _existing_capture(db: AsyncSession, candidate_id: int) -> AmazonListingCapture | None:
    result = await db.execute(
        select(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id == candidate_id)
    )
    return result.scalar_one_or_none()


async def capture_listing_for_candidate(
    db: AsyncSession,
    candidate: AmazonStyleSnapCandidate,
    *,
    force: bool = False,
) -> AmazonListingCapture:
    existing = await _existing_capture(db, candidate.id)
    if existing and not force:
        return existing

    now = datetime.now()
    capture = existing or AmazonListingCapture(
        selected_candidate_id=candidate.id,
        batch_id=candidate.batch_id,
        site=candidate.site,
        item_code=candidate.item_code,
        sku_code=candidate.sku_code,
        asin=candidate.asin,
        created_at=now,
    )
    if not existing:
        db.add(capture)

    url = _listing_url(candidate)
    raw_data: dict[str, Any] = {}
    status = "captured"
    error: str | None = None
    capture.capture_status = "running"
    capture.capture_error = None
    capture.url = url
    capture.updated_at = now
    capture.captured_at = None
    await db.commit()
    try:
        async with chrome_workflow(f"amazon_listing_capture asin={candidate.asin}"):
            ok = await chrome_navigate(url, wait=4.0)
            if not ok:
                raise RuntimeError("Chrome 导航到 Amazon 失败")
            raw = None
            for attempt in range(3):
                raw = await chrome_execute_js(CAPTURE_JS, timeout=30)
                raw_data = _safe_json_loads(raw)
                if raw_data.get("blocked") or raw_data.get("unavailable") or raw_data.get("title"):
                    break
                if attempt < 2:
                    await asyncio.sleep(2)
        if not raw:
            status = "failed"
            error = "Amazon listing 页面脚本未返回数据，请确认 Chrome worker tab 可执行脚本后重试"
        elif raw_data.get("blocked"):
            status = "failed"
            error = "Amazon 页面疑似 CAPTCHA/风控拦截，请在 Chrome 人工处理后重试"
        elif raw_data.get("unavailable"):
            status = "failed"
            error = "Amazon 商品页不存在或不可访问，请切换其它竞品"
        elif not raw_data.get("title"):
            status = "failed"
            error = "Amazon listing 页面未提取到标题"
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"

    categories = raw_data.get("categories") if isinstance(raw_data.get("categories"), list) else []
    category_rank = raw_data.get("category_rank") or candidate.category_rank
    capture.url = url
    capture.title = raw_data.get("title")
    capture.brand = raw_data.get("brand") or candidate.brand
    capture.seller = raw_data.get("seller") or candidate.seller
    capture.price = raw_data.get("price") or candidate.price
    capture.rating = raw_data.get("rating") or candidate.rating
    capture.review_count = raw_data.get("review_count")
    capture.availability = raw_data.get("availability")
    capture.categories = _json_dumps(categories) if categories else None
    capture.leaf_category = _leaf_category(categories, category_rank)
    capture.category_rank = category_rank
    capture.bullets_json = _json_dumps(raw_data.get("bullets") or [])
    capture.description = raw_data.get("description")
    capture.product_details_json = _json_dumps(raw_data.get("product_details") or {})
    capture.aplus_text = raw_data.get("aplus_text")
    capture.main_image_url = raw_data.get("main_image_url") or candidate.amazon_image_url
    capture.image_urls_json = _json_dumps(raw_data.get("image_urls") or [])
    capture.raw_json = _json_dumps(raw_data) if raw_data else None
    capture.page_url = raw_data.get("url")
    capture.page_title = raw_data.get("page_title")
    capture.page_body_length = raw_data.get("page_body_length")
    capture.capture_status = status
    capture.capture_error = error
    capture.source_platform = SOURCE_PLATFORM
    capture.captured_at = now
    capture.updated_at = now

    await db.commit()
    await db.refresh(capture)
    return capture
