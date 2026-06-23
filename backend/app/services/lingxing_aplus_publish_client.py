from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

import httpx

from app.config import settings
from app.pipeline.chrome_ctrl import chrome_execute_js, chrome_get_cookie_for_domain, chrome_navigate, chrome_workflow
from app.services.lingxing_aplus_publish_policy import AplusPublishAsset


LINGXING_APLUS_URL = "https://erp.lingxing.com/erp/aplusList"
UPLOAD_DESTINATION_URL = "https://gw.lingxingerp.com/amz/amz-data-transfer/amazon/aplus/uploadDestination"
APLUS_ADD_URL = "https://gw.lingxingerp.com/amz/amz-data-transfer/amazon/aplus/add"


class LingxingAplusDraftSaveClientError(RuntimeError):
    def __init__(self, code: str, message: str, *, auth_required: bool = False):
        super().__init__(message)
        self.code = code
        self.auth_required = auth_required


@dataclass(frozen=True)
class LingxingAplusDraftSaveRequest:
    asin: str
    seller_sku: str
    document_name: str
    store_id: str
    site: str
    assets: list[AplusPublishAsset]
    product_id: int
    product_aplus_id: int
    content_fingerprint: str


@dataclass(frozen=True)
class LingxingAplusDraftSaveResult:
    id_hash: str | None = None
    record_key: str | None = None
    status_text: str | None = None
    uploaded_images: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _clean(value: str | int | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_cookie(cookie: str) -> dict[str, str]:
    parsed = {}
    for part in cookie.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            parsed[key.strip()] = unquote(value.strip())
    return parsed


def _headers(auth: dict[str, Any]) -> dict[str, str]:
    headers = dict(auth["headers"])
    headers["Content-Type"] = "application/json"
    return headers


def _safe_response_summary(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    return {
        "code": data.get("code"),
        "success": data.get("success"),
        "message": data.get("msg") or data.get("message"),
        "idHash": payload.get("idHash") or payload.get("id_hash"),
        "statusName": payload.get("statusName") or payload.get("status_name"),
    }


async def _get_lingxing_aplus_auth(*, store_id: str) -> dict[str, Any]:
    async with chrome_workflow("lingxing_aplus_publish_auth"):
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
    return {"ok": True, "headers": headers, "store_id": store_id}


class LingxingAplusDraftSaveClient:
    async def save_draft(self, request: LingxingAplusDraftSaveRequest) -> LingxingAplusDraftSaveResult:
        if not settings.LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS:
            raise LingxingAplusDraftSaveClientError(
                "real_external_calls_disabled",
                "Lingxing A+ draft save real external calls are disabled by config",
            )
        if settings.LINGXING_APLUS_SUBMIT_FOR_APPROVAL:
            raise LingxingAplusDraftSaveClientError(
                "submit_not_supported_in_t3",
                "T3 draft save does not support submit for approval",
            )
        store_id = _clean(request.store_id)
        if not store_id:
            raise LingxingAplusDraftSaveClientError(
                "store_config_required",
                "Lingxing A+ draft save requires explicit store_id when real external calls are enabled",
            )
        auth = await _get_lingxing_aplus_auth(store_id=store_id)
        if not auth.get("ok"):
            raise LingxingAplusDraftSaveClientError(
                "auth_required",
                auth.get("error") or "领星登录态失效，无法保存 A+ 草稿",
                auth_required=True,
            )

        try:
            async with httpx.AsyncClient(timeout=30, verify=settings.external_http_verify) as client:
                uploaded = [await self._upload_image(client, auth, asset) for asset in request.assets]
                response = await self._save_draft(client, auth, request, uploaded)
        except LingxingAplusDraftSaveClientError:
            raise
        except Exception as exc:
            raise LingxingAplusDraftSaveClientError(
                "request_failed",
                f"领星 A+ 保存草稿请求失败: {type(exc).__name__}: {exc}",
            ) from exc

        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        id_hash = data.get("idHash") or data.get("id_hash")
        status_text = data.get("statusName") or data.get("status_name") or "草稿"
        return LingxingAplusDraftSaveResult(
            id_hash=id_hash,
            record_key=id_hash,
            status_text=status_text,
            uploaded_images=uploaded,
            evidence={
                "endpoint_family": "lingxing_aplus_add",
                "submitFlag": 0,
                "idHash": id_hash,
                "status_text": status_text,
                "response": _safe_response_summary(response),
                "uploaded_image_count": len(uploaded),
            },
        )

    async def _upload_image(
        self,
        client: httpx.AsyncClient,
        auth: dict[str, Any],
        asset: AplusPublishAsset,
    ) -> dict[str, Any]:
        content = asset.path.read_bytes()
        response = await client.post(
            UPLOAD_DESTINATION_URL,
            headers=_headers(auth),
            json={
                "contentType": asset.content_type,
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
            raise LingxingAplusDraftSaveClientError(
                "upload_destination_missing",
                "领星未返回 A+ 图片上传地址",
            )
        parsed = urlparse(url)
        form_fields = dict(parse_qsl(parsed.query, keep_blank_values=True))
        upload_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        files = {"file": (asset.path.name, content, asset.content_type)}
        upload_response = await client.post(upload_url, data=form_fields, files=files)
        if upload_response.status_code not in (200, 201, 204):
            raise LingxingAplusDraftSaveClientError(
                "object_upload_failed",
                f"领星 A+ 图片对象上传失败: {upload_response.status_code}",
            )
        return {
            "position": asset.position,
            "file_name": asset.path.name,
            "uploadDestinationId": upload_id,
            "altText": asset.alt_text,
            "contentType": asset.content_type,
            "width": asset.width,
            "height": asset.height,
            "size": asset.size,
        }

    async def _save_draft(
        self,
        client: httpx.AsyncClient,
        auth: dict[str, Any],
        request: LingxingAplusDraftSaveRequest,
        uploaded: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "storeId": auth["store_id"],
            "asinList": [request.asin],
            "contentDocument": {
                "contentType": "EBC",
                "locale": "en-US",
                "name": request.document_name,
                "contentModuleList": [_module_payload(item, index) for index, item in enumerate(uploaded, start=1)],
            },
            "submitFlag": 0,
        }
        response = await client.post(APLUS_ADD_URL, headers=_headers(auth), json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("code") not in (1, 200, "1") and data.get("success") is not True:
            raise LingxingAplusDraftSaveClientError(
                "api_failed",
                data.get("msg") or data.get("message") or "领星 A+ 保存草稿失败",
            )
        return data


def _module_payload(image: dict[str, Any], position: int) -> dict[str, Any]:
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
