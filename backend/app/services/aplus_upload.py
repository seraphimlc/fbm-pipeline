"""Lingxing A+ upload batches."""

import asyncio
import hashlib
import json
import logging
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import AplusUploadBatch, AplusUploadItem, CatalogProduct, Product
from app.pipeline.chrome_ctrl import chrome_execute_js, chrome_get_cookie_for_domain, chrome_navigate, chrome_workflow

logger = logging.getLogger(__name__)

DEFAULT_STORE = "Andy店-US"
DEFAULT_STORE_ID = 17983
LINGXING_APLUS_URL = "https://erp.lingxing.com/erp/aplusList"
UPLOAD_DESTINATION_URL = "https://gw.lingxingerp.com/amz/amz-data-transfer/amazon/aplus/uploadDestination"
APLUS_ADD_URL = "https://gw.lingxingerp.com/amz/amz-data-transfer/amazon/aplus/add"
APLUS_EDIT_URL = "https://gw.lingxingerp.com/amz/amz-data-transfer/amazon/aplus/edit"
_running_batches: dict[int, asyncio.Task] = {}
SELLABLE_STATUS_KEYWORDS = ("售卖", "在售", "可售", "active", "buyable", "正常")


def is_sellable_amazon_product_status(status: str | None) -> bool:
    normalized = str(status or "").strip().lower()
    return bool(normalized) and any(keyword in normalized for keyword in SELLABLE_STATUS_KEYWORDS)


def start_aplus_upload_batch(batch_id: int) -> bool:
    if batch_id in _running_batches:
        return False
    task = asyncio.create_task(_run_batch(batch_id))
    _running_batches[batch_id] = task
    return True


def build_upload_item(catalog: CatalogProduct) -> AplusUploadItem:
    product = catalog.source_product
    pd = product.data if product else None
    asin = (catalog.amazon_asin or (product.amazon_asin if product else None) or "").strip()
    item_code = (catalog.item_code or (pd.item_code if pd else None) or "").strip()
    document_name = f"{asin}_{item_code}_{catalog.source_product_id}" if asin and item_code else None
    amazon_status = catalog.amazon_product_status or (product.amazon_product_status if product else None)
    status = "pending"
    error_message = None
    if not asin:
        status = "skipped"
        error_message = "缺少真实 ASIN，请先同步 ASIN"
    elif not is_sellable_amazon_product_status(amazon_status):
        status = "skipped"
        error_message = f"亚马逊商品状态不是售卖：{amazon_status or '未同步'}"
    return AplusUploadItem(
        catalog_product_id=catalog.id,
        product_id=catalog.source_product_id,
        amazon_asin=asin or None,
        item_code=item_code or None,
        document_name=document_name,
        status=status,
        error_message=error_message,
    )


async def _set_aplus_upload_status(
    product_id: int,
    catalog_product_id: int,
    status: str,
    error: str | None = None,
    uploaded_at: datetime | None = None,
) -> None:
    async with async_session() as db:
        product = await db.get(Product, product_id)
        catalog = await db.get(CatalogProduct, catalog_product_id)
        for target in (product, catalog):
            if not target:
                continue
            target.aplus_upload_status = status
            target.aplus_upload_error = error
            if uploaded_at or status in {"submitted", "draft_saved", "failed", "skipped"}:
                target.aplus_uploaded_at = uploaded_at or datetime.now()
        await db.commit()


async def _run_batch(batch_id: int) -> None:
    try:
        async with async_session() as db:
            result = await db.execute(
                select(AplusUploadBatch)
                .options(selectinload(AplusUploadBatch.items))
                .where(AplusUploadBatch.id == batch_id)
            )
            batch = result.scalar_one_or_none()
            if not batch:
                return
            batch.status = "running"
            batch.started_at = datetime.now()
            await db.commit()
            item_ids = [item.id for item in batch.items if item.status == "pending"]
            submit = bool(batch.submit_for_approval)
            if not item_ids:
                await _update_batch_counts(db, batch)
                return

        auth = await _get_lingxing_auth()
        if not auth.get("ok"):
            await _fail_whole_batch(batch_id, auth.get("error") or "领星未登录，无法上传 A+")
            return

        for item_id in item_ids:
            await _run_item(item_id, auth, submit)

        async with async_session() as db:
            result = await db.execute(
                select(AplusUploadBatch)
                .options(selectinload(AplusUploadBatch.items))
                .where(AplusUploadBatch.id == batch_id)
            )
            batch = result.scalar_one_or_none()
            if batch:
                await _update_batch_counts(db, batch)
    except Exception as exc:
        logger.exception("[A+ Upload] Batch %s failed", batch_id)
        await _fail_whole_batch(batch_id, f"{type(exc).__name__}: {exc}")
    finally:
        _running_batches.pop(batch_id, None)


async def _update_batch_counts(db, batch: AplusUploadBatch) -> None:
    statuses = [item.status for item in batch.items]
    batch.success_count = statuses.count("success")
    batch.failed_count = statuses.count("failed")
    batch.skipped_count = statuses.count("skipped")
    done = batch.success_count + batch.failed_count + batch.skipped_count
    if done >= batch.total_count:
        batch.status = "completed" if batch.failed_count == 0 else "partial"
        batch.finished_at = datetime.now()
    await db.commit()


async def _fail_whole_batch(batch_id: int, error: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(AplusUploadBatch)
            .options(selectinload(AplusUploadBatch.items))
            .where(AplusUploadBatch.id == batch_id)
        )
        batch = result.scalar_one_or_none()
        if not batch:
            return
        batch.status = "failed"
        batch.error_message = error
        batch.finished_at = datetime.now()
        for item in batch.items:
            if item.status in {"pending", "running"}:
                item.status = "failed"
                item.error_message = error
                item.finished_at = datetime.now()
                product = await db.get(Product, item.product_id)
                catalog = await db.get(CatalogProduct, item.catalog_product_id)
                for target in (product, catalog):
                    if target:
                        target.aplus_upload_status = "failed"
                        target.aplus_upload_error = error
                        target.aplus_uploaded_at = datetime.now()
        await _update_batch_counts(db, batch)


async def _run_item(item_id: int, auth: dict, submit: bool) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(AplusUploadItem)
            .where(AplusUploadItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            return
        item.status = "running"
        item.started_at = datetime.now()
        await db.commit()
        product_id = item.product_id
        catalog_product_id = item.catalog_product_id

    await _set_aplus_upload_status(product_id, catalog_product_id, "running")

    try:
        async with async_session() as db:
            product = await db.get(Product, product_id, options=[selectinload(Product.data), selectinload(Product.aplus)])
            if not product:
                raise ValueError("商品不存在")
            image_paths, alt_texts = _collect_aplus_images(product)
            asin = product.amazon_asin
            item_code = product.data.item_code if product.data else None
            if not asin:
                raise ValueError("缺少真实 ASIN，请先同步 ASIN")
            if not item_code:
                raise ValueError("缺少商品Code")

        uploaded = []
        async with httpx.AsyncClient(timeout=120, verify=False) as client:
            for index, path in enumerate(image_paths, start=1):
                uploaded.append(await _upload_image(client, auth, path, alt_texts[index - 1]))
            response = await _save_aplus(client, auth, asin, item_code, product_id, uploaded, submit)

        await _finish_item(
            item_id,
            "success",
            catalog_status="submitted" if submit else "draft_saved",
            uploaded_images=json.dumps(uploaded, ensure_ascii=False),
            lingxing_response=json.dumps(response, ensure_ascii=False)[:4000],
        )
    except Exception as exc:
        await _finish_item(item_id, "failed", catalog_status="failed", error=f"{type(exc).__name__}: {exc}")


async def _finish_item(
    item_id: int,
    status: str,
    catalog_status: str | None = None,
    uploaded_images: str | None = None,
    lingxing_response: str | None = None,
    error: str | None = None,
) -> None:
    async with async_session() as db:
        item = await db.get(AplusUploadItem, item_id)
        if not item:
            return
        item.status = status
        item.uploaded_images = uploaded_images
        item.lingxing_response = lingxing_response
        item.error_message = error
        item.finished_at = datetime.now()
        product = await db.get(Product, item.product_id)
        catalog = await db.get(CatalogProduct, item.catalog_product_id)
        final_catalog_status = catalog_status or status
        for target in (product, catalog):
            if not target:
                continue
            target.aplus_upload_status = final_catalog_status
            target.aplus_upload_error = error
            if status in {"success", "failed", "skipped"}:
                target.aplus_uploaded_at = datetime.now()
        result = await db.execute(
            select(AplusUploadBatch)
            .options(selectinload(AplusUploadBatch.items))
            .where(AplusUploadBatch.id == item.batch_id)
        )
        batch = result.scalar_one_or_none()
        if batch:
            await _update_batch_counts(db, batch)
        else:
            await db.commit()


async def _get_lingxing_auth() -> dict:
    async with chrome_workflow("aplus_upload_auth"):
        opened = await chrome_navigate(LINGXING_APLUS_URL, wait=3)
        if not opened:
            return {"ok": False, "error": "无法打开领星 A+ 页面"}
        cookie = await chrome_get_cookie_for_domain("erp.lingxing.com")
        if not cookie:
            return {"ok": False, "error": "领星未登录，无法读取 Cookie"}
        js = """
(function() {
  const text = document.body ? document.body.innerText : '';
  if (/登录|login/i.test(text) && !/A\\+商品描述|产品|销售|超级管理员/.test(text)) {
    return JSON.stringify({ok:false, error:'领星未登录'});
  }
  return JSON.stringify({
    ok: true,
    language: localStorage.getItem('language') || 'zh',
    loginEnv: sessionStorage.getItem('loginEnv') || '1',
    origin: location.origin
  });
})()
"""
        raw = await chrome_execute_js(js, timeout=20)
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {"ok": False, "error": "无法读取领星页面状态"}
        if not data.get("ok"):
            return data
        cookies = _parse_cookie(cookie)
    headers = {
        "Cookie": cookie,
        "X-AK-Language": data.get("language") or "zh",
        "X-AK-Request-Source": "erp",
        "X-AK-Zid": cookies.get("zid", ""),
        "X-AK-Version": "3.8.3.3.0.141",
        "X-AK-ENV-KEY": cookies.get("envKey", ""),
        "X-AK-PLATFORM": data.get("loginEnv") or "1",
        "AK-Client-Type": "web",
        "auth-token": cookies.get("authToken", ""),
        "X-AK-Uid": cookies.get("uid", ""),
        "X-AK-Company-Id": cookies.get("company_id", ""),
        "AK-Origin": data.get("origin") or "https://erp.lingxing.com",
        "Origin": "https://erp.lingxing.com",
        "Referer": "https://erp.lingxing.com/",
    }
    return {"ok": True, "headers": headers, "store_id": DEFAULT_STORE_ID}


def _parse_cookie(cookie: str) -> dict[str, str]:
    parsed = {}
    for part in cookie.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            parsed[key.strip()] = unquote(value.strip())
    return parsed


def _collect_aplus_images(product: Product) -> tuple[list[Path], list[str]]:
    if not product.aplus or not product.aplus.aplus_images:
        raise ValueError("缺少 A+ 图片，请先完成 A+ 出图")
    images = json.loads(product.aplus.aplus_images)
    done = [item for item in images if item.get("status") == "done" and item.get("path")]
    done.sort(key=lambda item: item.get("position") or 0)
    if len(done) < 5:
        raise ValueError(f"A+ 图片不足 5 张：{len(done)}/5")
    paths = [Path(item["path"]).expanduser() for item in done[:5]]
    for path in paths:
        if not path.is_file():
            raise ValueError(f"A+ 图片不存在: {path}")
        with Image.open(path) as img:
            width, height = img.size
        if width < 970 or height < 600:
            raise ValueError(f"A+ 图片尺寸小于 970x600: {path.name} {width}x{height}")
    plan_modules = json.loads(product.aplus.aplus_plan or "{}").get("modules", [])
    alt_texts = []
    fallback = ((product.data.listing_title or product.data.title) if product.data else None) or product.amazon_asin
    for index in range(5):
        module = plan_modules[index] if index < len(plan_modules) else {}
        alt_texts.append((module.get("headline") or module.get("subheading") or module.get("key_message") or fallback or "Amazon A+ product image")[:100])
    return paths, alt_texts


async def _upload_image(client: httpx.AsyncClient, auth: dict, path: Path, alt_text: str) -> dict:
    content = path.read_bytes()
    content_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    headers = _headers(auth)
    response = await client.post(
        UPLOAD_DESTINATION_URL,
        headers=headers,
        json={
            "contentType": content_type,
            "contentMd5": hashlib.md5(content).hexdigest(),
            "storeId": auth["store_id"],
        },
    )
    response.raise_for_status()
    data = response.json()
    upload_data = data.get("data") or {}
    upload_id = upload_data.get("uploadDestinationId")
    url = upload_data.get("url")
    if not upload_id or not url:
        raise RuntimeError(f"领星未返回上传地址: {json.dumps(data, ensure_ascii=False)[:800]}")

    parsed = urlparse(url)
    form_fields = dict(parse_qsl(parsed.query, keep_blank_values=True))
    upload_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    files = {"file": (path.name, content, content_type)}
    upload_response = await client.post(upload_url, data=form_fields, files=files)
    if upload_response.status_code not in (200, 201, 204):
        raise RuntimeError(f"S3 上传失败 {upload_response.status_code}: {upload_response.text[:300]}")

    with Image.open(path) as img:
        width, height = img.size
    return {
        "path": str(path),
        "uploadDestinationId": upload_id,
        "altText": alt_text,
        "contentType": content_type,
        "width": width,
        "height": height,
    }


async def _save_aplus(
    client: httpx.AsyncClient,
    auth: dict,
    asin: str,
    item_code: str,
    product_id: int,
    uploaded: list[dict],
    submit: bool,
) -> dict:
    name = f"{asin}_{item_code}_{product_id}"
    payload = {
        "storeId": auth["store_id"],
        "asinList": [asin],
        "contentDocument": {
            "contentType": "EBC",
            "locale": "en-US",
            "name": name,
            "contentModuleList": [_module_payload(item, index) for index, item in enumerate(uploaded, start=1)],
        },
        "submitFlag": 1 if submit else 0,
    }
    response = await client.post(APLUS_ADD_URL, headers=_headers(auth), json=payload)
    response.raise_for_status()
    data = response.json()
    if data.get("code") not in (1, 200, "1") and data.get("success") is not True:
        raise RuntimeError(f"A+ 保存/提交失败: {json.dumps(data, ensure_ascii=False)[:1200]}")
    id_hash = (data.get("data") or {}).get("idHash")
    if submit and id_hash and (data.get("data") or {}).get("statusName") == "草稿":
        submit_response = await client.post(f"{APLUS_EDIT_URL}?idHash={id_hash}", headers=_headers(auth), json=payload)
        submit_response.raise_for_status()
        submit_data = submit_response.json()
        if submit_data.get("code") not in (1, 200, "1") and submit_data.get("success") is not True:
            raise RuntimeError(f"A+ 提交审批失败: {json.dumps(submit_data, ensure_ascii=False)[:1200]}")
        data["submit_response"] = submit_data
    return data


def _module_payload(image: dict, position: int) -> dict:
    image_data = {
        "uploadDestinationId": image["uploadDestinationId"],
        "altText": image["altText"],
        "imageCropSpecification": {
            "offset": {
                "x": {"units": "pixels", "value": 0},
                "y": {"units": "pixels", "value": 0},
            },
            "size": {
                "height": {"units": "pixels", "value": str(image["height"])},
                "width": {"units": "pixels", "value": str(image["width"])},
            },
        },
    }
    return {
        "contentModuleType": "STANDARD_HEADER_IMAGE_TEXT",
        "standardHeaderImageText": {
            "headline": {"value": ""},
            "block": {
                "image": image_data,
                "headline": {"value": ""},
                "body": {"textList": []},
            },
        },
        "position": position,
    }


def _headers(auth: dict) -> dict:
    headers = dict(auth["headers"])
    headers["Content-Type"] = "application/json"
    headers["X-AK-Request-Id"] = str(uuid.uuid4())
    return headers
