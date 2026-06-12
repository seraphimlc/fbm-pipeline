import asyncio
import base64
import json
import mimetypes
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AmazonStyleSnapCandidate
from app.pipeline.chrome_ctrl import chrome_execute_js, chrome_get_page_info, chrome_navigate, chrome_workflow
from app.services.seller_sprite_openapi import SellerSpriteOpenApiError, competitor_lookup


SOURCE_PLATFORM = "AMAZON_STYLESNAP"
TMP_UPLOAD_IMAGE = Path("/tmp/fbm-stylesnap-upload.jpg")


@dataclass
class AmazonStyleSnapSearchInput:
    batch_id: str
    site: str
    item_code: str
    sku_code: str
    product_name: str | None
    source_image_path: str
    source_image_url: str | None = None


@dataclass
class AmazonStyleSnapSearchResult:
    candidates: list[AmazonStyleSnapCandidate] = field(default_factory=list)
    count: int = 0
    page: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


EXTRACT_JS = r"""
(() => {
  function clean(s) { return String(s || '').replace(/\u200c/g, '').replace(/\s+/g, ' ').trim(); }
  function imageUrlForBlock(block, asin) {
    const links = Array.from(document.querySelectorAll(`a[href*="${asin}"], a[href*="/dp/${asin}"]`));
    for (const link of links) {
      const root = link.closest('[data-asin], div, li') || link;
      const img = root.querySelector('img');
      if (img && img.src && /^https?:\/\//.test(img.src)) return img.src;
    }
    return '';
  }
  const body = document.body && document.body.innerText || '';
  const loading = document.body && document.body.getAttribute('data-codex-stylesnap-loading') === '1';
  const has_detail_fields = body.includes('品牌:') && body.includes('卖家:');
  const start = body.indexOf('SIMILAR PRODUCTS');
  const txt = start >= 0 ? body.slice(start) : body;
  const asinRe = /\bASIN:([A-Z0-9]{10})\b/g;
  const positions = [];
  let m;
  while ((m = asinRe.exec(txt))) positions.push({ asin: m[1], index: m.index });
  const out = [];
  const seen = new Set();
  for (let i = 0; i < positions.length && out.length < 10; i++) {
    const asin = positions[i].asin;
    if (seen.has(asin)) continue;
    seen.add(asin);
    const block = txt.slice(positions[i].index, positions[i + 1] ? positions[i + 1].index : positions[i].index + 1800);
    const before = txt.slice(Math.max(0, positions[i].index - 180), positions[i].index);
    const price = (block.match(/价格:\s*\$?([0-9]+(?:\.[0-9]{2})?)/) || before.match(/\$([0-9]+)\s*([0-9]{2})/) || [])[1] || '';
    const cents = (before.match(/\$([0-9]+)\s*([0-9]{2})/) || [])[2] || '';
    const rating = (block.match(/评分\(评分数\):\s*([0-9.]+)\(([^)]*)\)/) || []);
    const rank1 = (block.match(/#([0-9,]+)\s+in\s+([^\n#]+?)(?=\s+#|\s+近30天|\s+FBA|\s+毛利率|\s+变体数|$)/) || []);
    const brand = (block.match(/品牌:\s*([^\n]+?)\s+卖家:/) || [])[1] || '';
    const seller = (block.match(/卖家:([^\n]+?)\s+配送:/) || [])[1] || '';
    const delivery = (block.match(/配送:\s*([^\n]+?)\s+加入产品库/) || [])[1] || '';
    const color = (block.match(/Color:\s*([^\n]+?)(?=\s+(Style:|Size:|全部流量词|自然搜索词|广告流量词|$))/) || [])[1] || '';
    const size = (block.match(/Size:\s*([^\n]+?)(?=\s+(Style:|Color:|全部流量词|自然搜索词|广告流量词|$))/) || [])[1] || '';
    const style = (block.match(/Style:\s*([^\n]+?)(?=\s+(Color:|Size:|全部流量词|自然搜索词|广告流量词|$))/) || [])[1] || '';
    out.push({
      rank: out.length + 1,
      asin,
      url: `https://www.amazon.com/dp/${asin}`,
      brand: clean(brand),
      seller: clean(seller),
      delivery: clean(delivery),
      price: price ? `$${price}${cents && price.indexOf('.') < 0 ? '.' + cents : ''}` : '',
      rating: rating[1] ? `${rating[1]}(${rating[2] || ''})` : '',
      category_rank: rank1[1] ? `#${rank1[1]} in ${clean(rank1[2])}` : '',
      color: clean(color),
      size: clean(size),
      style: clean(style),
      amazon_image_url: imageUrlForBlock(block, asin),
      raw: clean(block).slice(0, 900)
    });
  }
  return JSON.stringify({
    href: location.href,
    title: document.title,
    loading,
    has_detail_fields,
    body_length: body.length,
    count: out.length,
    items: out
  });
})()
"""

DIRECT_UPLOAD_POLL_JS = r"""(() => JSON.stringify(window.__fbmDirectStyleSnap || null))()"""
STYLESNAP_TOKEN_READY_JS = r"""
(() => {
  const tokenEl = document.getElementsByName('stylesnap')[0];
  return tokenEl && tokenEl.value ? 'ready' : 'missing';
})()
"""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _is_remote_url(value: str | None) -> bool:
    return bool(value and str(value).strip().lower().startswith(("http://", "https://")))


def _image_ext_from_url(url: str, content_type: str | None = None) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}:
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    return guessed if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"} else ".jpg"


async def _download_remote_upload_image(url: str) -> str:
    digest = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")[:24]
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=30, write=20, pool=20),
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type")
        content = response.content
    target = Path(f"/tmp/fbm-stylesnap-source-{digest}{_image_ext_from_url(url, content_type)}")
    target.write_bytes(content)
    return str(target)


def _make_upload_data_url(image_path: str) -> str:
    path = Path(image_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"主图文件不存在: {path}")
    upload_path = path
    if path.stat().st_size > 800_000:
        subprocess.run(
            ["/usr/bin/sips", "-s", "format", "jpeg", "-Z", "900", str(path), "--out", str(TMP_UPLOAD_IMAGE)],
            text=True,
            capture_output=True,
            check=True,
        )
        upload_path = TMP_UPLOAD_IMAGE
    mime = mimetypes.guess_type(str(upload_path))[0] or "image/jpeg"
    encoded = base64.b64encode(upload_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _direct_upload_start_js(data_url: str) -> str:
    return f"""
(() => {{
  window.__fbmDirectStyleSnap = {{status:'starting', startedAt: Date.now()}};
  const dataUrl = {json.dumps(data_url)};
  const tokenEl = document.getElementsByName('stylesnap')[0];
  const token = tokenEl && tokenEl.value;
  if (!token) {{
    window.__fbmDirectStyleSnap = {{
      status:'failed',
      error:'stylesnap token not found',
      href: location.href,
      title: document.title
    }};
    return 'no-token';
  }}
  function dataUrlToFile(dataUrl, filename) {{
    const parts = dataUrl.split(',');
    const mime = (parts[0].match(/data:([^;]+)/) || [,'image/jpeg'])[1];
    const bin = atob(parts[1]);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], filename, {{type: mime}});
  }}
  const file = dataUrlToFile(dataUrl, 'fbm-stylesnap.jpg');
  const form = new FormData();
  form.append(file.name, file);
  const url = 'stylesnap/upload?stylesnapToken=' + encodeURIComponent(token);
  window.__fbmDirectStyleSnap = {{
    status:'running',
    url,
    href: location.href,
    title: document.title,
    startedAt: Date.now(),
    fileSize: file.size,
    fileType: file.type
  }};
  fetch(url, {{method:'POST', body: form, credentials:'include'}})
    .then(res => res.text().then(text => {{
      let parsed = null;
      try {{ parsed = JSON.parse(text); }} catch(e) {{}}
      window.__fbmDirectStyleSnap = {{
        status:'done',
        ok: res.ok,
        httpStatus: res.status,
        statusText: res.statusText,
        url,
        href: location.href,
        title: document.title,
        contentType: res.headers.get('content-type'),
        elapsedMs: Date.now() - window.__fbmDirectStyleSnap.startedAt,
        response: parsed,
        textPreview: text.slice(0, 1000)
      }};
    }}))
    .catch(e => {{
      window.__fbmDirectStyleSnap = {{
        status:'failed',
        error:String(e),
        url,
        href: location.href,
        title: document.title,
        elapsedMs: Date.now() - window.__fbmDirectStyleSnap.startedAt
      }};
    }});
  return 'started';
}})()
"""


async def _direct_stylesnap_upload(data_url: str, timeout: int = 60) -> dict[str, Any]:
    started = await chrome_execute_js(_direct_upload_start_js(data_url), timeout=30)
    if started == "no-token":
        raise RuntimeError("StyleSnap token not found")
    if started not in {"started", None, ""}:
        raise RuntimeError(f"StyleSnap 接口提交失败: {started}")
    last: dict[str, Any] = {}
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(2)
        raw = await chrome_execute_js(DIRECT_UPLOAD_POLL_JS, timeout=15)
        try:
            parsed = json.loads(raw or "{}")
        except Exception:
            parsed = {"status": "unknown", "raw": str(raw or "")[:1000]}
        last = parsed if isinstance(parsed, dict) else {}
        if last.get("status") in {"done", "failed"}:
            break
    if started in {None, ""} and not last:
        raise RuntimeError("StyleSnap 接口提交失败：Chrome 未返回 JS 启动状态")
    if last.get("status") != "done" or not last.get("ok"):
        raise RuntimeError(last.get("error") or last.get("statusText") or "StyleSnap 接口返回失败")
    response = last.get("response")
    if not isinstance(response, dict):
        raise RuntimeError("StyleSnap 接口未返回 JSON")
    return {
        "href": last.get("href"),
        "title": last.get("title"),
        "upload_url": last.get("url"),
        "elapsed_ms": last.get("elapsedMs"),
        "response": response,
    }


async def _wait_for_stylesnap_token(timeout: int = 20) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        result = await chrome_execute_js(STYLESNAP_TOKEN_READY_JS, timeout=10)
        if result == "ready":
            return True
        await asyncio.sleep(1)
    return False


async def _ensure_stylesnap_upload_page() -> bool:
    page = await chrome_get_page_info()
    url = str((page or {}).get("url") or "")
    if "amazon.com/stylesnap" in url and await _wait_for_stylesnap_token(timeout=3):
        return True
    ok = await chrome_navigate("https://www.amazon.com/stylesnap#fbm-pipeline-worker", wait=3.0)
    if not ok:
        return False
    return await _wait_for_stylesnap_token()


def _extract_direct_candidates(upload_result: dict[str, Any]) -> list[dict[str, Any]]:
    response = upload_result.get("response") if isinstance(upload_result.get("response"), dict) else {}
    search_results = response.get("searchResults") if isinstance(response.get("searchResults"), list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(asin: Any, source: str, payload: dict[str, Any] | None = None) -> None:
        normalized = _clean_text(asin)
        if not normalized:
            return
        normalized = normalized.upper()
        if normalized in seen or len(out) >= 10:
            return
        seen.add(normalized)
        properties = payload.get("properties") if isinstance(payload, dict) and isinstance(payload.get("properties"), dict) else {}
        out.append({
            "rank": len(out) + 1,
            "asin": normalized,
            "url": f"https://www.amazon.com/dp/{normalized}",
            "score": properties.get("score"),
            "glcode": properties.get("glcode"),
            "match_source": source,
            "raw": payload or {"asin": normalized, "source": source},
        })

    for result in search_results:
        if not isinstance(result, dict):
            continue
        for item in result.get("subContent") or []:
            if isinstance(item, dict) and item.get("contentType") == "ASIN":
                add(item.get("content"), item.get("dataSource") or item.get("source") or "imagematch", item)
        for item in result.get("bbxAsinMetadataList") or []:
            if isinstance(item, dict):
                add(item.get("asin") or item.get("ASIN") or item.get("content"), "bbxAsinMetadataList", item)
        for asin in result.get("bbxAsinList") or []:
            add(asin, "bbxAsinList", {"asin": asin})
    return out


async def _extract_results(timeout: int = 60) -> dict[str, Any]:
    last: dict[str, Any] = {}
    started = asyncio.get_running_loop().time()
    await asyncio.sleep(10)
    while asyncio.get_running_loop().time() - started < timeout:
        raw = await chrome_execute_js(EXTRACT_JS, timeout=30)
        try:
            parsed = json.loads(raw or "{}")
        except Exception:
            parsed = {"count": 0, "raw": str(raw or "")[:1000]}
        last = parsed
        if parsed.get("loading"):
            await asyncio.sleep(2)
            continue
        if parsed.get("count", 0) >= 10 and (parsed.get("has_detail_fields") or asyncio.get_running_loop().time() - started > 32):
            return parsed
        await asyncio.sleep(2)
    return last


def _money(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return _clean_text(value)


def _rating(value: Any, count: Any) -> str | None:
    if value in (None, ""):
        return None
    if count not in (None, ""):
        return f"{value}({count})"
    return _clean_text(value)


def _category_rank(item: dict[str, Any]) -> str | None:
    label = _clean_text(item.get("nodeLabelPath"))
    bsr = item.get("bsr")
    if bsr and label:
        leaf = label.split(":")[-1].strip()
        return f"#{bsr:,} in {leaf}" if isinstance(bsr, int) else f"#{bsr} in {leaf}"
    subcategories = item.get("subcategories") if isinstance(item.get("subcategories"), list) else []
    if subcategories:
        first = subcategories[0]
        if isinstance(first, dict) and first.get("rank") and first.get("label"):
            return f"#{first.get('rank')} in {first.get('label')}"
    return label


def _raw_snippet(asin: str, seller_item: dict[str, Any] | None, direct: dict[str, Any]) -> str:
    if not seller_item:
        score = direct.get("score")
        return f"ASIN:{asin} 图片匹配分数:{score}" if score else f"ASIN:{asin}"
    parts = [
        f"ASIN:{asin}",
        f"品牌:{seller_item.get('brand')}" if seller_item.get("brand") else None,
        f"卖家:{seller_item.get('sellerName')}" if seller_item.get("sellerName") else None,
        f"配送:{seller_item.get('fulfillment')}" if seller_item.get("fulfillment") else None,
        f"价格:{_money(seller_item.get('price'))}" if seller_item.get("price") is not None else None,
        f"评分:{seller_item.get('rating')}({seller_item.get('ratings')})" if seller_item.get("rating") is not None else None,
        f"月销量(父体):{seller_item.get('units')}" if seller_item.get("units") is not None else None,
        f"子体近30日销量:{seller_item.get('amzUnit')}" if seller_item.get("amzUnit") is not None else None,
        f"销售额:{_money(seller_item.get('revenue'))}" if seller_item.get("revenue") is not None else None,
        f"变体数:{seller_item.get('variations')}" if seller_item.get("variations") is not None else None,
        f"类目:{seller_item.get('nodeLabelPath')}" if seller_item.get("nodeLabelPath") else None,
        f"商品重量:{seller_item.get('weight')}" if seller_item.get("weight") else None,
        f"商品尺寸:{seller_item.get('dimension')}" if seller_item.get("dimension") else None,
        f"包装重量:{seller_item.get('pkgWeight')}" if seller_item.get("pkgWeight") else None,
        f"包装尺寸:{seller_item.get('pkgDimensions')}" if seller_item.get("pkgDimensions") else None,
        f"变体:{seller_item.get('sku')}" if seller_item.get("sku") else None,
    ]
    return " ".join(str(part) for part in parts if part)[:1800]


def _variant_parts(sku: str | None) -> dict[str, str | None]:
    result = {"color": None, "size": None, "style": None}
    if not sku:
        return result
    for part in str(sku).split("|"):
        if ":" not in part:
            continue
        key, value = [item.strip() for item in part.split(":", 1)]
        lower = key.lower()
        if lower == "color":
            result["color"] = value
        elif lower == "size":
            result["size"] = value
        elif lower == "style":
            result["style"] = value
    return result


async def _existing_candidate(
    db: AsyncSession,
    batch_id: str,
    site: str,
    item_code: str,
    sku_code: str,
    rank: int,
    asin: str,
) -> AmazonStyleSnapCandidate | None:
    result = await db.execute(
        select(AmazonStyleSnapCandidate).where(
            AmazonStyleSnapCandidate.batch_id == batch_id,
            AmazonStyleSnapCandidate.site == site,
            AmazonStyleSnapCandidate.item_code == item_code,
            AmazonStyleSnapCandidate.sku_code == sku_code,
            AmazonStyleSnapCandidate.rank == rank,
            AmazonStyleSnapCandidate.asin == asin,
        )
    )
    return result.scalar_one_or_none()


async def search_and_store_stylesnap_candidates(
    db: AsyncSession,
    options: AmazonStyleSnapSearchInput,
) -> AmazonStyleSnapSearchResult:
    site = options.site.strip().upper()
    upload_source_path = options.source_image_path
    source_image_url = options.source_image_url or (options.source_image_path if _is_remote_url(options.source_image_path) else None)
    if _is_remote_url(upload_source_path):
        upload_source_path = await _download_remote_upload_image(upload_source_path)
    data_url = await asyncio.to_thread(_make_upload_data_url, upload_source_path)

    async with chrome_workflow(f"amazon_stylesnap_search item={options.item_code} sku={options.sku_code}"):
        ok = await _ensure_stylesnap_upload_page()
        if not ok:
            raise RuntimeError("Chrome 导航到 Amazon StyleSnap 失败")
        try:
            upload_result = await _direct_stylesnap_upload(data_url)
            candidates = _extract_direct_candidates(upload_result)
            parsed = {
                "href": upload_result.get("href"),
                "title": upload_result.get("title"),
                "body_length": None,
                "count": len(candidates),
                "has_detail_fields": False,
                "source": "amazon_stylesnap_upload_api",
                "query_id": (upload_result.get("response") or {}).get("queryId"),
                "items": candidates,
            }
        except Exception as exc:
            submit_js = (
                "(() => {"
                "document.body.innerText='Codex StyleSnap upload pending...';"
                "document.body.setAttribute('data-codex-stylesnap-loading','1');"
                f"localStorage.setItem('uploadedImage', {json.dumps(data_url)});"
                "location.href='https://www.amazon.com/stylesnap?q=local';"
                "return 'ok';"
                "})()"
            )
            submitted = await chrome_execute_js(submit_js, timeout=30)
            if submitted != "ok":
                raise RuntimeError(f"StyleSnap 接口直调失败且页面提交失败: {exc}")
            parsed = await _extract_results()

    candidates = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    asins = [_clean_text(candidate.get("asin")) for candidate in candidates if isinstance(candidate, dict)]
    asins = [asin for asin in asins if asin]
    seller_data: dict[str, dict[str, Any]] = {}
    if asins:
        try:
            seller_data = await competitor_lookup(asins, marketplace=site, size=max(len(asins), 10))
            missing_asins = [asin for asin in asins if asin not in seller_data]
            for asin in missing_asins:
                try:
                    single_data = await competitor_lookup([asin], marketplace=site, size=1)
                except (SellerSpriteOpenApiError, httpx.HTTPError, json.JSONDecodeError, ValueError):
                    continue
                if single_data.get(asin):
                    seller_data[asin] = single_data[asin]
        except (SellerSpriteOpenApiError, httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            seller_data = {}
            parsed["sellersprite_error"] = str(exc)

    now = datetime.now()
    page = {
        key: parsed.get(key)
        for key in ("href", "title", "body_length", "count", "has_detail_fields", "source", "query_id", "sellersprite_error")
    }
    saved: list[AmazonStyleSnapCandidate] = []
    max_rank_result = await db.execute(
        select(func.max(AmazonStyleSnapCandidate.rank)).where(
            AmazonStyleSnapCandidate.batch_id == options.batch_id,
            AmazonStyleSnapCandidate.site == site,
            AmazonStyleSnapCandidate.item_code == options.item_code,
            AmazonStyleSnapCandidate.sku_code == options.sku_code,
        )
    )
    rank_offset = int(max_rank_result.scalar_one_or_none() or 0)

    for index, candidate in enumerate(candidates[:10], start=1):
        if not isinstance(candidate, dict):
            continue
        asin = _clean_text(candidate.get("asin"))
        if not asin:
            continue
        asin = asin.upper()
        seller_item = seller_data.get(asin)
        variants = _variant_parts(_clean_text(seller_item.get("sku")) if seller_item else None)
        rank = rank_offset + index
        record = await _existing_candidate(db, options.batch_id, site, options.item_code, options.sku_code, rank, asin)
        if not record:
            record = AmazonStyleSnapCandidate(
                batch_id=options.batch_id,
                site=site,
                item_code=options.item_code,
                sku_code=options.sku_code,
                rank=rank,
                asin=asin,
                imported_at=now,
            )
            db.add(record)
        record.product_name = _clean_text(options.product_name)
        record.source_image_url = _clean_text(source_image_url)
        record.source_image_path = options.source_image_path
        record.title = _clean_text(seller_item.get("title") if seller_item else None) or _clean_text(candidate.get("title"))
        record.url = _clean_text(candidate.get("url")) or f"https://www.amazon.com/dp/{asin}"
        record.brand = _clean_text(seller_item.get("brand") if seller_item else None) or _clean_text(candidate.get("brand"))
        record.seller = _clean_text(seller_item.get("sellerName") if seller_item else None) or _clean_text(candidate.get("seller"))
        record.delivery = _clean_text(seller_item.get("fulfillment") if seller_item else None) or _clean_text(candidate.get("delivery"))
        record.price = _money(seller_item.get("price") if seller_item else None) or _clean_text(candidate.get("price"))
        record.rating = _rating(seller_item.get("rating"), seller_item.get("ratings")) if seller_item else _clean_text(candidate.get("rating"))
        record.category_rank = _category_rank(seller_item) if seller_item else _clean_text(candidate.get("category_rank"))
        record.color = variants.get("color") or _clean_text(candidate.get("color"))
        record.size = variants.get("size") or _clean_text(candidate.get("size"))
        record.style = variants.get("style") or _clean_text(candidate.get("style"))
        record.amazon_image_url = _clean_text(seller_item.get("imageUrl") if seller_item else None) or _clean_text(candidate.get("amazon_image_url"))
        record.amazon_image_path = None
        record.raw_snippet = _clean_text(_raw_snippet(asin, seller_item, candidate) or candidate.get("raw") or candidate.get("raw_snippet"))
        record.raw_candidate_json = _json_dumps({
            "stylesnap": candidate,
            "sellersprite": seller_item,
        })
        record.raw_capture_json = _json_dumps({"page": page, "candidates": candidates[:10]})
        record.page_href = _clean_text(page.get("href"))
        record.page_title = _clean_text(page.get("title"))
        record.page_body_length = int(page["body_length"]) if page.get("body_length") else None
        record.capture_error = None
        record.source_platform = SOURCE_PLATFORM
        record.captured_at = now
        record.updated_at = now
        saved.append(record)

    if not saved:
        error = _clean_text(parsed.get("raw")) or "StyleSnap 未提取到候选 ASIN"
        return AmazonStyleSnapSearchResult(count=0, page=page, error=error)

    await db.commit()
    for record in saved:
        await db.refresh(record)
    return AmazonStyleSnapSearchResult(candidates=saved, count=len(saved), page=page)
