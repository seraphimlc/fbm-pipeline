import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    AmazonStyleSnapCandidateGroupResponse,
    AmazonStyleSnapCandidateResponse,
    ProductResponse,
)
from app.database import async_session, get_db
from app.models import AmazonListingCapture, AmazonStyleSnapCandidate, CatalogProduct, Product
from app.services.amazon_listing_capture import (
    capture_listing_for_candidate,
)
from app.services.amazon_stylesnap_search import AmazonStyleSnapSearchInput, search_and_store_stylesnap_candidates
from app.services.seller_sprite_openapi import competitor_lookup
from app.services.stylesnap_product_tasks import (
    _category_path_from_candidate,
    _category_path_from_listing_capture,
    _json_dumps,
    _json_loads,
    _listing_capture_snapshot,
)
from app.pipeline.engine import is_running
from app.product_tasks.workflow import build_product_workflow, set_product_workflow
from app.task_planners.product_image_analysis import create_product_image_analysis_runs
from app.models.status import (
    CREATED,
    FAILED,
    STEP5_LISTING,
    STEP6_CURATING,
    WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_GET_STYLESNAP_TOKEN,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_NODE_SEARCH_COMPETITOR,
    WORKFLOW_NODE_SELECT_COMPETITOR,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_SUCCEEDED,
)


router = APIRouter(prefix="/api/amazon-stylesnap", tags=["amazon-stylesnap"])
COMPETITOR_SEARCHING = "competitor_searching"
COMPETITOR_SWITCH_BLOCKING_STATUSES = {
    COMPETITOR_SEARCHING,
    STEP5_LISTING,
    STEP6_CURATING,
}
LISTING_CAPTURE_ACTIVE_TTL = timedelta(minutes=5)
LISTING_CAPTURE_QUEUED_TTL = timedelta(seconds=30)
LISTING_PREFETCH_LIMIT = 10
LISTING_PREFETCH_CONCURRENCY = 1
_listing_prefetch_semaphore = asyncio.Semaphore(LISTING_PREFETCH_CONCURRENCY)

COMPETITOR_SEARCH_ALLOWED_WORKFLOWS = {
    (WORKFLOW_NODE_SEARCH_COMPETITOR, WORKFLOW_STATUS_PENDING),
    (WORKFLOW_NODE_SEARCH_COMPETITOR, WORKFLOW_STATUS_FAILED),
    (WORKFLOW_NODE_GET_STYLESNAP_TOKEN, WORKFLOW_STATUS_PENDING),
    (WORKFLOW_NODE_SELECT_COMPETITOR, WORKFLOW_STATUS_PENDING),
}
COMPETITOR_SELECT_ALLOWED_WORKFLOWS = {
    (WORKFLOW_NODE_SELECT_COMPETITOR, WORKFLOW_STATUS_PENDING),
    (WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL, WORKFLOW_STATUS_FAILED),
    (WORKFLOW_NODE_IMAGE_ANALYSIS, WORKFLOW_STATUS_PENDING),
    (WORKFLOW_NODE_IMAGE_ANALYSIS, WORKFLOW_STATUS_FAILED),
    (WORKFLOW_NODE_IMAGE_ANALYSIS, WORKFLOW_STATUS_SUCCEEDED),
    (WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_PENDING),
    (WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_FAILED),
    (WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_SUCCEEDED),
    (WORKFLOW_NODE_FLOW_DONE, WORKFLOW_STATUS_SUCCEEDED),
}
COMPETITOR_SELECT_RUNNING_WORKFLOWS = {
    (WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL, WORKFLOW_STATUS_PROCESSING),
    (WORKFLOW_NODE_IMAGE_ANALYSIS, WORKFLOW_STATUS_PROCESSING),
    (WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_PROCESSING),
}
COMPETITOR_DOWNSTREAM_RESELECT_WORKFLOWS = {
    (WORKFLOW_NODE_IMAGE_ANALYSIS, WORKFLOW_STATUS_PENDING),
    (WORKFLOW_NODE_IMAGE_ANALYSIS, WORKFLOW_STATUS_FAILED),
    (WORKFLOW_NODE_IMAGE_ANALYSIS, WORKFLOW_STATUS_SUCCEEDED),
    (WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_PENDING),
    (WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_FAILED),
    (WORKFLOW_NODE_LISTING_GENERATION, WORKFLOW_STATUS_SUCCEEDED),
    (WORKFLOW_NODE_FLOW_DONE, WORKFLOW_STATUS_SUCCEEDED),
}
SAFE_APLUS_UPLOAD_STATUSES = {None, "", "not_uploaded", "failed"}
SAFE_ASIN_SYNC_STATUSES = {None, "", "not_synced", "failed"}
STYLESNAP_TOKEN_BROWSER_ERROR_KEYWORDS = (
    "StyleSnap token not found",
    "未找到上传 token",
    "Chrome 导航到 Amazon StyleSnap 失败",
    "Chrome 未开启",
    "允许 Apple 事件中的 JavaScript",
    "Apple Events",
    "AppleScript",
    "Amazon StyleSnap 页面已打开，但未找到上传 token",
    "登录",
    "token",
)


async def _start_image_analysis_after_capture(db: AsyncSession, product_id: int) -> None:
    await create_product_image_analysis_runs(db, [product_id], created_by="competitor_selection")


def _candidate_response(
    candidate: AmazonStyleSnapCandidate,
    capture_by_candidate: dict[int, AmazonListingCapture] | None = None,
) -> AmazonStyleSnapCandidateResponse:
    data = AmazonStyleSnapCandidateResponse.model_validate(candidate)
    capture = (capture_by_candidate or {}).get(candidate.id)
    if capture:
        data.listing_capture_id = capture.id
        data.listing_capture_status = capture.capture_status
        data.listing_capture_error = capture.capture_error
        data.listing_capture_has_main_image = bool(capture.main_image_url)
        data.listing_captured_at = capture.captured_at
        data.url = capture.page_url or capture.url or data.url
        data.title = capture.title or data.title
        data.brand = capture.brand or data.brand
        data.seller = capture.seller or data.seller
        data.price = capture.price or data.price
        data.rating = capture.rating or data.rating
        data.review_count = capture.review_count
        data.leaf_category = capture.leaf_category
        data.category_rank = capture.category_rank or data.category_rank
        data.amazon_image_url = capture.main_image_url or data.amazon_image_url
        bullets = _json_loads(capture.bullets_json, [])
        if isinstance(bullets, list) and bullets:
            data.listing_summary = " / ".join(str(item).strip() for item in bullets[:3] if str(item).strip()) or None
        data.listing_summary = data.listing_summary or capture.description or data.raw_snippet
    return data


async def _captures_by_candidate(
    db: AsyncSession,
    candidate_ids: list[int],
) -> dict[int, AmazonListingCapture]:
    if not candidate_ids:
        return {}
    result = await db.execute(
        select(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id.in_(candidate_ids))
    )
    return {capture.selected_candidate_id: capture for capture in result.scalars().all()}


def _is_competitor_listing_capture_state(product: Product) -> bool:
    return (
        product.status == STEP5_LISTING
        and bool(product.error_message)
        and "竞品" in (product.error_message or "")
        and "抓取中" in (product.error_message or "")
    )


def _is_active_listing_capture(capture: AmazonListingCapture | None) -> bool:
    if not capture or capture.capture_status not in {"queued", "running"} or not capture.updated_at:
        return False
    ttl = LISTING_CAPTURE_QUEUED_TTL if capture.capture_status == "queued" else LISTING_CAPTURE_ACTIVE_TTL
    return datetime.now() - capture.updated_at < ttl


async def _selected_listing_capture_from_snapshot(
    db: AsyncSession,
    snapshot: dict,
) -> AmazonListingCapture | None:
    selected = snapshot.get("selected_stylesnap") if isinstance(snapshot.get("selected_stylesnap"), dict) else {}
    candidate_id = selected.get("candidate_id")
    if not candidate_id:
        return None
    result = await db.execute(
        select(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id == int(candidate_id))
    )
    return result.scalar_one_or_none()


async def _ensure_competitor_can_be_changed(
    db: AsyncSession,
    product: Product,
    snapshot: dict,
    *,
    action: str,
) -> None:
    if is_running(product.id):
        raise HTTPException(400, f"商品流程正在运行中，不能{action}竞品")
    if product.status not in COMPETITOR_SWITCH_BLOCKING_STATUSES:
        return
    if _is_competitor_listing_capture_state(product):
        capture = await _selected_listing_capture_from_snapshot(db, snapshot)
        if _is_active_listing_capture(capture):
            raise HTTPException(400, "竞品详情正在抓取中，请等待后台完成；如果长时间不动，5分钟后可重新抓取")
        return
    raise HTTPException(400, f"商品正在处理竞品或生成流程，不能{action}竞品")


def _build_group(
    candidates: list[AmazonStyleSnapCandidate],
    capture_by_candidate: dict[int, AmazonListingCapture] | None = None,
    product_by_item_code: dict[str, Product] | None = None,
) -> AmazonStyleSnapCandidateGroupResponse:
    first = candidates[0]
    sorted_candidates = sorted(candidates, key=lambda item: (item.rank, item.id))
    selected = next((item for item in sorted_candidates if item.is_selected), None)
    product = (product_by_item_code or {}).get(first.item_code)
    selected_capture = (capture_by_candidate or {}).get(selected.id) if selected else None
    if product:
        task_ready = False
        task_ready_reason = f"已创建任务 {product.id}"
    elif not selected:
        task_ready = False
        task_ready_reason = "未选择同款"
    elif not selected_capture:
        task_ready = False
        task_ready_reason = "未抓取 Amazon Listing"
    elif selected_capture.capture_status != "captured":
        task_ready = False
        task_ready_reason = selected_capture.capture_error or "Amazon Listing 抓取失败"
    else:
        task_ready = True
        task_ready_reason = "就绪"
    return AmazonStyleSnapCandidateGroupResponse(
        batch_id=first.batch_id,
        site=first.site,
        item_code=first.item_code,
        sku_code=first.sku_code,
        product_name=first.product_name,
        source_image_url=first.source_image_url,
        source_image_path=first.source_image_path,
        selected_candidate_id=selected.id if selected else None,
        product_task_id=product.id if product else None,
        product_task_status=product.status if product else None,
        task_ready=task_ready,
        task_ready_reason=task_ready_reason,
        candidates=[_candidate_response(item, capture_by_candidate) for item in sorted_candidates],
    )


async def _load_group(
    db: AsyncSession,
    batch_id: str,
    site: str,
    item_code: str,
    sku_code: str,
) -> AmazonStyleSnapCandidateGroupResponse:
    result = await db.execute(
        select(AmazonStyleSnapCandidate)
        .where(
            AmazonStyleSnapCandidate.batch_id == batch_id,
            AmazonStyleSnapCandidate.site == site,
            AmazonStyleSnapCandidate.item_code == item_code,
            AmazonStyleSnapCandidate.sku_code == sku_code,
        )
        .order_by(AmazonStyleSnapCandidate.rank.asc(), AmazonStyleSnapCandidate.id.asc())
    )
    candidates = result.scalars().all()
    if not candidates:
        raise HTTPException(404, "StyleSnap candidates not found")
    captures = await _captures_by_candidate(db, [candidate.id for candidate in candidates])
    return _build_group(candidates, captures)


async def _load_product_for_competitor_selection(
    db: AsyncSession,
    product_id: int,
) -> tuple[Product, dict]:
    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.data),
            selectinload(Product.images),
            selectinload(Product.aplus),
            selectinload(Product.catalog_item),
        )
        .where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product or not product.data:
        raise HTTPException(404, "Product task not found")
    snapshot = _json_loads(product.data.gigab2b_raw_snapshot, {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    return product, snapshot


async def _existing_product_candidates(
    db: AsyncSession,
    *,
    batch_id: str,
    site: str,
    item_code: str,
    sku_code: str | None,
) -> list[AmazonStyleSnapCandidate]:
    query = select(AmazonStyleSnapCandidate).where(
        AmazonStyleSnapCandidate.batch_id == batch_id,
        AmazonStyleSnapCandidate.site == site,
        AmazonStyleSnapCandidate.item_code == item_code,
    )
    if sku_code:
        query = query.where(AmazonStyleSnapCandidate.sku_code == sku_code)
    result = await db.execute(
        query.order_by(AmazonStyleSnapCandidate.rank.asc(), AmazonStyleSnapCandidate.id.asc())
    )
    return list(result.scalars().all())


async def _delete_existing_product_candidates(
    db: AsyncSession,
    *,
    batch_id: str,
    site: str,
    item_code: str,
    sku_code: str | None,
) -> None:
    candidates = await _existing_product_candidates(
        db,
        batch_id=batch_id,
        site=site,
        item_code=item_code,
        sku_code=sku_code,
    )
    if not candidates and sku_code and sku_code != item_code:
        candidates = await _existing_product_candidates(
            db,
            batch_id=batch_id,
            site=site,
            item_code=item_code,
            sku_code=None,
        )
    candidate_ids = [candidate.id for candidate in candidates]
    if not candidate_ids:
        return
    await db.execute(delete(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id.in_(candidate_ids)))
    await db.execute(delete(AmazonStyleSnapCandidate).where(AmazonStyleSnapCandidate.id.in_(candidate_ids)))


def _clear_competitor_snapshot(snapshot: dict, *, keep_search_status: dict | None = None) -> dict:
    cleaned = dict(snapshot)
    cleaned.pop("selected_stylesnap", None)
    cleaned.pop("amazon_listing_capture", None)
    cleaned.pop("stylesnap_search", None)
    if keep_search_status is not None:
        cleaned["stylesnap_search"] = keep_search_status
    return cleaned


def _clear_listing_outputs(product: Product) -> None:
    if not product.data:
        return
    for field in (
        "categories",
        "leaf_category",
        "listing_title",
        "listing_bullets",
        "listing_search_terms",
        "listing_title_zh",
        "listing_bullets_zh",
        "listing_search_terms_zh",
        "listing_description",
        "listing_description_zh",
        "listing_check",
        "listing_primary_keyword",
        "listing_removed_keywords",
        "amazon_template_path",
        "amazon_template_warnings",
        "amazon_template_fill_summary",
        "amazon_template_generated_at",
    ):
        setattr(product.data, field, None)


def _clear_generation_outputs(product: Product) -> None:
    _clear_listing_outputs(product)
    if product.images:
        product.images.contact_sheet_path = None
        product.images.image_analysis = None
        product.images.image_selling_points = None
        product.images.category_style = None
        product.images.main_image_summary = None
        product.images.analyzed_at = None
    if product.aplus:
        product.aplus.aplus_plan = None
        product.aplus.aplus_plan_summary = None
        product.aplus.aplus_scripts = None
        product.aplus.aplus_scripts_summary = None
        product.aplus.aplus_images = None
        product.aplus.aplus_image_count = None
        product.aplus.aplus_status = None
        product.aplus.planned_at = None
        product.aplus.scripted_at = None
        product.aplus.generated_at = None


def _protected_competitor_change_reasons(product: Product) -> list[str]:
    reasons: list[str] = []
    catalog = product.catalog_item
    data = product.data
    if product.amazon_asin:
        reasons.append("商品已有真实 Amazon ASIN")
    if product.asin_sync_status not in SAFE_ASIN_SYNC_STATUSES:
        reasons.append(f"商品 ASIN 同步状态不可静默重置: {product.asin_sync_status}")
    if product.aplus_uploaded_at or product.aplus_upload_status not in SAFE_APLUS_UPLOAD_STATUSES:
        reasons.append("商品已有 A+ 上传记录或上传中状态")
    if catalog:
        if catalog.amazon_asin:
            reasons.append("Catalog 已有真实 Amazon ASIN")
        if catalog.asin_sync_status not in SAFE_ASIN_SYNC_STATUSES:
            reasons.append(f"Catalog ASIN 同步状态不可静默重置: {catalog.asin_sync_status}")
        if catalog.confirmed_at:
            reasons.append("Catalog 已人工确认")
        if catalog.exported_at or catalog.export_task_id or catalog.export_file_path:
            reasons.append("Catalog 已有真实导出历史")
        if catalog.aplus_uploaded_at or catalog.aplus_upload_status not in SAFE_APLUS_UPLOAD_STATUSES:
            reasons.append("Catalog 已有 A+ 上传记录或上传中状态")
    if data and (
        data.amazon_template_path
        or data.amazon_template_generated_at
        or data.amazon_template_fill_summary
        or data.amazon_template_warnings
    ):
        reasons.append("商品已有 Amazon 模板输出证据")
    return reasons


def _raise_if_protected_competitor_change(product: Product) -> None:
    reasons = _protected_competitor_change_reasons(product)
    if reasons:
        raise HTTPException(409, "当前商品已有不可逆外部结果，不能静默换竞品：" + "；".join(reasons))


def _ensure_select_competitor_workflow_allowed(product: Product) -> None:
    current = (product.workflow_node, product.workflow_status)
    if current in COMPETITOR_SELECT_RUNNING_WORKFLOWS:
        raise HTTPException(409, "当前商品已有下游流程正在执行，不能切换竞品；请等待任务结束后再操作")
    if current in COMPETITOR_SELECT_ALLOWED_WORKFLOWS:
        if current in COMPETITOR_DOWNSTREAM_RESELECT_WORKFLOWS:
            _raise_if_protected_competitor_change(product)
        return
    raise HTTPException(409, "当前商品 workflow 不在可选择或切换竞品节点")


def _clear_current_competitor_derived_outputs(product: Product) -> None:
    if product.data:
        snapshot = _json_loads(product.data.gigab2b_raw_snapshot, {})
        if isinstance(snapshot, dict):
            snapshot.pop("amazon_listing_capture", None)
            product.data.gigab2b_raw_snapshot = _json_dumps(snapshot)
        for field in (
            "categories",
            "leaf_category",
            "listing_title",
            "listing_bullets",
            "listing_search_terms",
            "listing_title_zh",
            "listing_bullets_zh",
            "listing_search_terms_zh",
            "listing_description",
            "listing_description_zh",
            "listing_check",
            "listing_primary_keyword",
            "listing_removed_keywords",
        ):
            setattr(product.data, field, None)
    if product.images:
        product.images.contact_sheet_path = None
        product.images.image_analysis = None
        product.images.image_selling_points = None
        product.images.category_style = None
        product.images.main_image_summary = None
        product.images.analyzed_at = None
    if product.aplus:
        product.aplus.aplus_plan = None
        product.aplus.aplus_plan_summary = None
        product.aplus.aplus_scripts = None
        product.aplus.aplus_scripts_summary = None
        product.aplus.aplus_images = None
        product.aplus.aplus_image_count = None
        product.aplus.aplus_status = None
        product.aplus.planned_at = None
        product.aplus.scripted_at = None
        product.aplus.generated_at = None
    product.aplus_upload_status = "not_uploaded"
    product.aplus_uploaded_at = None
    product.aplus_upload_error = None
    if product.catalog_item:
        product.catalog_item.aplus_upload_status = "not_uploaded"
        product.catalog_item.aplus_uploaded_at = None
        product.catalog_item.aplus_upload_error = None


def _product_competitor_query_values(product: Product, snapshot: dict) -> tuple[str | None, str, str | None, str | None]:
    batch_id = snapshot.get("batch_id")
    site = str(snapshot.get("site") or "US").strip().upper()
    item_code = product.data.item_code if product.data else None
    representative_sku = snapshot.get("representative_sku") or item_code
    return batch_id, site, item_code, representative_sku


def _classify_stylesnap_search_error(exc_or_message: Exception | str) -> tuple[str, str]:
    raw = str(exc_or_message or "").strip()
    message = raw or "Amazon 同款搜索失败"
    for keyword in STYLESNAP_TOKEN_BROWSER_ERROR_KEYWORDS:
        if keyword and keyword.lower() in message.lower():
            return WORKFLOW_NODE_GET_STYLESNAP_TOKEN, message
    if "Chrome" in message or "JS" in message or "StyleSnap 页面" in message:
        return WORKFLOW_NODE_GET_STYLESNAP_TOKEN, message
    return WORKFLOW_NODE_SEARCH_COMPETITOR, message


def _set_competitor_search_workflow(
    product: Product,
    *,
    node: str,
    status: str,
    workflow_error: str | None,
    legacy_status: str,
    legacy_current_step: int,
    legacy_error_message: str | None,
    now: datetime,
) -> None:
    set_product_workflow(
        product,
        node=node,
        status=status,
        error=workflow_error,
        now=now,
    )
    product.status = legacy_status
    product.current_step = legacy_current_step
    product.error_message = legacy_error_message
    product.updated_at = now
    if product.catalog_item:
        product.catalog_item.status = product.status
        product.catalog_item.updated_at = now


def _set_competitor_capture_workflow(
    product: Product,
    *,
    node: str,
    status: str,
    workflow_error: str | None,
    legacy_status: str,
    legacy_current_step: int,
    legacy_error_message: str | None,
    now: datetime,
) -> None:
    set_product_workflow(
        product,
        node=node,
        status=status,
        error=workflow_error,
        now=now,
    )
    product.status = legacy_status
    product.current_step = legacy_current_step
    product.error_message = legacy_error_message
    product.updated_at = now
    if product.catalog_item:
        product.catalog_item.status = product.status
        product.catalog_item.updated_at = now


def _write_stylesnap_search_snapshot(
    product: Product,
    snapshot: dict,
    *,
    batch_id: str | None = None,
    site: str | None = None,
    representative_sku: str | None = None,
    stylesnap_search: dict,
) -> None:
    if not product.data:
        return
    next_snapshot = dict(snapshot)
    if batch_id:
        next_snapshot["batch_id"] = batch_id
    if site:
        next_snapshot["site"] = site
    if representative_sku:
        next_snapshot["representative_sku"] = representative_sku
    next_snapshot["stylesnap_search"] = stylesnap_search
    product.data.gigab2b_raw_snapshot = _json_dumps(next_snapshot)


def _build_stylesnap_product_response(product: Product) -> dict:
    catalog_exported = bool(
        product.catalog_item and (product.catalog_item.exported_at or product.catalog_item.export_task_id)
    )
    workflow = build_product_workflow(product, catalog_exported=catalog_exported)
    return {
        "id": product.id,
        "source_url": product.gigab2b_url,
        "source_item_id": product.gigab2b_product_id,
        "gigab2b_url": product.gigab2b_url,
        "gigab2b_product_id": product.gigab2b_product_id,
        "competitor_asin": product.competitor_asin,
        "amazon_asin": product.amazon_asin,
        "asin_sync_status": product.asin_sync_status,
        "asin_synced_at": product.asin_synced_at,
        "asin_sync_error": product.asin_sync_error,
        "amazon_product_status": product.amazon_product_status,
        "amazon_product_status_synced_at": product.amazon_product_status_synced_at,
        "amazon_product_status_error": product.amazon_product_status_error,
        "aplus_upload_status": product.aplus_upload_status,
        "aplus_uploaded_at": product.aplus_uploaded_at,
        "aplus_upload_error": product.aplus_upload_error,
        "aplus_status": product.aplus.aplus_status if product.aplus else None,
        "upc": product.upc,
        "brand": product.brand,
        "source_data_source_id": product.source_data_source_id,
        "source_site": product.source_site,
        "source_batch_id": product.source_batch_id,
        "catalog_exported_at": product.catalog_item.exported_at if product.catalog_item else None,
        "catalog_export_task_id": product.catalog_item.export_task_id if product.catalog_item else None,
        "status": product.status,
        "current_step": product.current_step,
        "current_task_status": workflow["action_reason"],
        "workflow": workflow,
        "error_message": product.error_message,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


def _competitor_search_precondition_error(
    product: Product,
    *,
    batch_id: str | None,
    item_code: str | None,
) -> str | None:
    if not product.images or not product.images.main_image_path:
        return "当前商品还没有确认主图，无法执行 Amazon 同款搜索"
    if not batch_id or not item_code:
        return "当前商品缺少批次或 Item 信息，无法执行 Amazon 同款搜索"
    return None


def _ensure_competitor_search_workflow_allowed(product: Product, *, force: bool, has_existing: bool) -> None:
    current = (product.workflow_node, product.workflow_status)
    if current in COMPETITOR_SEARCH_ALLOWED_WORKFLOWS:
        return
    if has_existing and not force and current == (WORKFLOW_NODE_SELECT_COMPETITOR, WORKFLOW_STATUS_PENDING):
        return
    raise HTTPException(409, "当前商品 workflow 不在可搜索竞品节点，不能启动 Amazon 同款搜索")


async def _load_product_candidate_group(
    db: AsyncSession,
    product: Product,
    snapshot: dict,
    *,
    enrich_images: bool = True,
) -> AmazonStyleSnapCandidateGroupResponse:
    batch_id, site, item_code, representative_sku = _product_competitor_query_values(product, snapshot)
    if not batch_id or not item_code:
        raise HTTPException(404, "当前商品缺少 StyleSnap 批次或 Item 信息，无法加载候选竞品")

    query = select(AmazonStyleSnapCandidate).where(
        AmazonStyleSnapCandidate.batch_id == batch_id,
        AmazonStyleSnapCandidate.site == site,
        AmazonStyleSnapCandidate.item_code == item_code,
    )
    if representative_sku:
        query = query.where(AmazonStyleSnapCandidate.sku_code == representative_sku)
    result = await db.execute(
        query.order_by(AmazonStyleSnapCandidate.rank.asc(), AmazonStyleSnapCandidate.id.asc())
    )
    candidates = result.scalars().all()
    if not candidates and representative_sku and representative_sku != item_code:
        result = await db.execute(
            select(AmazonStyleSnapCandidate)
            .where(
                AmazonStyleSnapCandidate.batch_id == batch_id,
                AmazonStyleSnapCandidate.site == site,
                AmazonStyleSnapCandidate.item_code == item_code,
            )
            .order_by(AmazonStyleSnapCandidate.rank.asc(), AmazonStyleSnapCandidate.id.asc())
        )
        candidates = result.scalars().all()
    if not candidates:
        raise HTTPException(404, "当前商品未找到 StyleSnap 候选竞品")

    await _backfill_candidate_basic_info_from_raw(db, candidates)
    if enrich_images:
        await _enrich_candidate_images_from_sellersprite(db, candidates, site)
    captures = await _captures_by_candidate(db, [candidate.id for candidate in candidates])
    return _build_group(candidates, captures, {item_code: product})


def _clean_optional_text(value: object) -> str | None:
    text_value = str(value or "").strip()
    return text_value or None


async def _backfill_candidate_basic_info_from_raw(
    db: AsyncSession,
    candidates: list[AmazonStyleSnapCandidate],
) -> None:
    changed = False
    now = datetime.now()
    for candidate in candidates:
        if candidate.title and candidate.amazon_image_url:
            continue
        raw = _json_loads(candidate.raw_candidate_json, {})
        if not isinstance(raw, dict):
            continue
        stylesnap = raw.get("stylesnap") if isinstance(raw.get("stylesnap"), dict) else {}
        sellersprite = raw.get("sellersprite") if isinstance(raw.get("sellersprite"), dict) else {}
        next_title = _clean_optional_text(sellersprite.get("title")) or _clean_optional_text(stylesnap.get("title"))
        next_image = _clean_optional_text(sellersprite.get("imageUrl")) or _clean_optional_text(stylesnap.get("amazon_image_url"))
        candidate_changed = False
        if next_title and not candidate.title:
            candidate.title = next_title
            candidate_changed = True
        if next_image and not candidate.amazon_image_url:
            candidate.amazon_image_url = next_image
            candidate_changed = True
        if candidate_changed:
            changed = True
            candidate.updated_at = now
    if changed:
        await db.commit()
        for candidate in candidates:
            await db.refresh(candidate)


async def _enrich_candidate_images_from_sellersprite(
    db: AsyncSession,
    candidates: list[AmazonStyleSnapCandidate],
    site: str,
) -> None:
    missing = [
        candidate.asin
        for candidate in candidates
        if candidate.asin and (not candidate.title or not candidate.amazon_image_url)
    ]
    missing = list(dict.fromkeys(missing))[:40]
    if not missing:
        return
    try:
        seller_data = await competitor_lookup(missing, marketplace=site, size=max(len(missing), 10))
    except Exception:
        return

    changed = False
    now = datetime.now()
    for candidate in candidates:
        if candidate.title and candidate.amazon_image_url:
            continue
        item = seller_data.get(candidate.asin)
        if not item:
            continue
        next_title = str(item.get("title") or "").strip() or None
        next_image = str(item.get("imageUrl") or "").strip() or None
        if next_title and not candidate.title:
            candidate.title = next_title
        if next_image and not candidate.amazon_image_url:
            candidate.amazon_image_url = next_image
        candidate.brand = candidate.brand or item.get("brand")
        candidate.seller = candidate.seller or item.get("sellerName")
        candidate.delivery = candidate.delivery or item.get("fulfillment")
        if next_title or next_image:
            candidate.updated_at = now
            changed = True
    if changed:
        await db.commit()
        for candidate in candidates:
            await db.refresh(candidate)


async def _sync_product_competitor_snapshot(
    db: AsyncSession,
    product: Product,
    candidate: AmazonStyleSnapCandidate,
    capture: AmazonListingCapture | None,
    *,
    status: str | None = None,
    current_step: int | None = None,
    error_message: str | None = None,
    workflow_node: str | None = None,
    workflow_status: str | None = None,
    workflow_error: str | None = None,
):
    if not product.data:
        raise HTTPException(404, "Product data not found")
    now = datetime.now()
    snapshot = _json_loads(product.data.gigab2b_raw_snapshot, {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    snapshot["batch_id"] = candidate.batch_id
    snapshot["site"] = candidate.site
    snapshot["representative_sku"] = candidate.sku_code
    snapshot["selected_stylesnap"] = {
        "candidate_id": candidate.id,
        "asin": candidate.asin,
        "rank": candidate.rank,
        "url": candidate.url,
        "category_rank": candidate.category_rank,
        "raw_snippet": candidate.raw_snippet,
    }
    snapshot["amazon_listing_capture"] = _listing_capture_snapshot(capture)

    categories, leaf_category = _category_path_from_listing_capture(capture)
    if not categories and not leaf_category:
        categories, leaf_category = _category_path_from_candidate(candidate)

    product.competitor_asin = candidate.asin
    if workflow_node and workflow_status:
        _set_competitor_capture_workflow(
            product,
            node=workflow_node,
            status=workflow_status,
            workflow_error=workflow_error,
            legacy_status=status if status is not None else product.status,
            legacy_current_step=current_step if current_step is not None else product.current_step,
            legacy_error_message=error_message,
            now=now,
        )
    else:
        if status is not None:
            product.status = status
        if current_step is not None:
            product.current_step = current_step
        product.error_message = error_message
        product.updated_at = now
    product.data.gigab2b_raw_snapshot = _json_dumps(snapshot)
    if categories:
        product.data.categories = _json_dumps(categories)
    if leaf_category:
        product.data.leaf_category = leaf_category
    product.data.collected_at = product.data.collected_at or now

    result = await db.execute(select(CatalogProduct).where(CatalogProduct.source_product_id == product.id))
    catalog = result.scalar_one_or_none()
    if catalog:
        catalog.competitor_asin = candidate.asin
        if leaf_category:
            catalog.leaf_category = leaf_category
        catalog.status = product.status
        catalog.updated_at = now
    await db.commit()


async def _run_product_competitor_search_background(product_id: int):
    async with async_session() as db:
        product, snapshot = await _load_product_for_competitor_selection(db, product_id)
        batch_id, site, item_code, representative_sku = _product_competitor_query_values(product, snapshot)
        now = datetime.now()
        try:
            precondition_error = _competitor_search_precondition_error(product, batch_id=batch_id, item_code=item_code)
            if precondition_error:
                raise RuntimeError(precondition_error)
            result = await search_and_store_stylesnap_candidates(
                db,
                AmazonStyleSnapSearchInput(
                    batch_id=batch_id,
                    site=site,
                    item_code=item_code,
                    sku_code=representative_sku or item_code,
                    product_name=product.data.title if product.data else None,
                    source_image_path=product.images.main_image_path,
                    source_image_url=product.images.main_image_path if product.images.main_image_path.startswith(("http://", "https://")) else None,
                ),
            )
            if result.error or not result.count:
                raise RuntimeError(result.error or "StyleSnap 未返回候选竞品")
            all_candidates = await _existing_product_candidates(
                db,
                batch_id=batch_id,
                site=site,
                item_code=item_code,
                sku_code=representative_sku or item_code,
            )
            _set_competitor_search_workflow(
                product,
                node=WORKFLOW_NODE_SELECT_COMPETITOR,
                status=WORKFLOW_STATUS_PENDING,
                workflow_error=None,
                legacy_status=CREATED,
                legacy_current_step=max(product.current_step or 0, 2),
                legacy_error_message=None,
                now=now,
            )
            _write_stylesnap_search_snapshot(
                product,
                snapshot,
                batch_id=batch_id,
                site=site,
                representative_sku=representative_sku or item_code,
                stylesnap_search={
                    "status": "captured",
                    "count": len(all_candidates),
                    "appended_count": result.count,
                    "searched_at": now.isoformat(),
                    "source_image_path": product.images.main_image_path,
                },
            )
            await db.commit()
        except asyncio.CancelledError:
            now = datetime.now()
            error_message = "Amazon 同款搜索被中断，请重新搜索候选"
            _set_competitor_search_workflow(
                product,
                node=WORKFLOW_NODE_SEARCH_COMPETITOR,
                status=WORKFLOW_STATUS_FAILED,
                workflow_error=error_message,
                legacy_status=FAILED,
                legacy_current_step=2,
                legacy_error_message=error_message,
                now=now,
            )
            _write_stylesnap_search_snapshot(
                product,
                snapshot,
                stylesnap_search={
                    "status": "failed",
                    "error": error_message,
                    "searched_at": now.isoformat(),
                },
            )
            await db.commit()
            raise
        except Exception as exc:
            now = datetime.now()
            node, reason = _classify_stylesnap_search_error(exc)
            error_message = f"Amazon 同款搜索失败: {type(exc).__name__}: {reason}"
            _set_competitor_search_workflow(
                product,
                node=node,
                status=WORKFLOW_STATUS_PENDING if node == WORKFLOW_NODE_GET_STYLESNAP_TOKEN else WORKFLOW_STATUS_FAILED,
                workflow_error=error_message,
                legacy_status=FAILED,
                legacy_current_step=2,
                legacy_error_message=error_message,
                now=now,
            )
            _write_stylesnap_search_snapshot(
                product,
                snapshot,
                stylesnap_search={
                    "status": "failed",
                    "error": error_message,
                    "searched_at": now.isoformat(),
                },
            )
            await db.commit()


async def _queue_listing_capture(
    db: AsyncSession,
    candidate: AmazonStyleSnapCandidate,
    *,
    force: bool = False,
) -> AmazonListingCapture:
    result = await db.execute(
        select(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id == candidate.id)
    )
    capture = result.scalar_one_or_none()
    now = datetime.now()
    if capture and capture.capture_status == "captured" and not force:
        return capture
    if not capture:
        capture = AmazonListingCapture(
            selected_candidate_id=candidate.id,
            batch_id=candidate.batch_id,
            site=candidate.site,
            item_code=candidate.item_code,
            sku_code=candidate.sku_code,
            asin=candidate.asin,
            created_at=now,
        )
        db.add(capture)
    capture.url = candidate.url or f"https://www.amazon.com/dp/{candidate.asin}"
    capture.capture_status = "queued"
    capture.capture_error = None
    capture.updated_at = now
    await db.commit()
    await db.refresh(capture)
    return capture


async def _queue_listing_prefetches(
    db: AsyncSession,
    candidates: list[AmazonStyleSnapCandidate],
    *,
    force: bool = False,
) -> list[int]:
    queued_candidate_ids: list[int] = []
    now = datetime.now()
    for candidate in sorted(candidates, key=lambda item: (item.rank, item.id))[:LISTING_PREFETCH_LIMIT]:
        result = await db.execute(
            select(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id == candidate.id)
        )
        capture = result.scalar_one_or_none()
        if capture and capture.capture_status == "captured" and not force:
            continue
        if _is_active_listing_capture(capture) and not force:
            continue
        if not capture:
            capture = AmazonListingCapture(
                selected_candidate_id=candidate.id,
                batch_id=candidate.batch_id,
                site=candidate.site,
                item_code=candidate.item_code,
                sku_code=candidate.sku_code,
                asin=candidate.asin,
                created_at=now,
            )
            db.add(capture)
        capture.url = candidate.url or f"https://www.amazon.com/dp/{candidate.asin}"
        capture.capture_status = "queued"
        capture.capture_error = None
        capture.updated_at = now
        queued_candidate_ids.append(candidate.id)
    if queued_candidate_ids:
        await db.commit()
    return queued_candidate_ids


async def _capture_prefetched_listing(candidate_id: int, *, force: bool = False) -> None:
    async with _listing_prefetch_semaphore:
        async with async_session() as db:
            result = await db.execute(select(AmazonStyleSnapCandidate).where(AmazonStyleSnapCandidate.id == candidate_id))
            candidate = result.scalar_one_or_none()
            if not candidate:
                return
            existing = await db.execute(
                select(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id == candidate.id)
            )
            capture = existing.scalar_one_or_none()
            if capture and capture.capture_status == "captured" and not force:
                return
            if _is_active_listing_capture(capture) and capture.capture_status == "running" and not force:
                return
            await capture_listing_for_candidate(db, candidate, force=True)


async def _run_listing_prefetch_background(candidate_ids: list[int], *, force: bool = False) -> None:
    for candidate_id in list(dict.fromkeys(candidate_ids)):
        try:
            await _capture_prefetched_listing(candidate_id, force=force)
        except asyncio.CancelledError:
            raise
        except Exception:
            continue


async def _capture_and_sync_product_competitor_background(
    product_id: int,
    candidate_id: int,
    *,
    force_capture: bool = True,
    auto_start_generation: bool = True,
):
    async with async_session() as db:
        product, _snapshot = await _load_product_for_competitor_selection(db, product_id)
        result = await db.execute(select(AmazonStyleSnapCandidate).where(AmazonStyleSnapCandidate.id == candidate_id))
        candidate = result.scalar_one_or_none()
        if not candidate:
            return
        try:
            capture = await capture_listing_for_candidate(db, candidate, force=force_capture)
        except asyncio.CancelledError:
            capture = await _queue_listing_capture(db, candidate, force=True)
            capture.capture_status = "failed"
            capture.capture_error = "竞品详情抓取被中断，请重新抓详情"
            capture.updated_at = datetime.now()
            await db.commit()
            await _sync_product_competitor_snapshot(
                db,
                product,
                candidate,
                capture,
                status=FAILED,
                current_step=4,
                error_message=capture.capture_error,
                workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
                workflow_status=WORKFLOW_STATUS_FAILED,
                workflow_error=capture.capture_error,
            )
            raise
        except Exception as exc:
            capture = await _queue_listing_capture(db, candidate, force=True)
            capture.capture_status = "failed"
            capture.capture_error = f"竞品详情抓取失败: {type(exc).__name__}: {exc}"
            capture.updated_at = datetime.now()
            await db.commit()
            await _sync_product_competitor_snapshot(
                db,
                product,
                candidate,
                capture,
                status=FAILED,
                current_step=4,
                error_message=capture.capture_error,
                workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
                workflow_status=WORKFLOW_STATUS_FAILED,
                workflow_error=capture.capture_error,
            )
            return

        if capture.capture_status == "captured":
            await _sync_product_competitor_snapshot(
                db,
                product,
                candidate,
                capture,
                status=CREATED,
                current_step=5,
                error_message=None,
                workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
                workflow_status=WORKFLOW_STATUS_SUCCEEDED,
                workflow_error=None,
            )
            if auto_start_generation:
                await _start_image_analysis_after_capture(db, product.id)
            return

        error_message = capture.capture_error or "竞品详情抓取失败"
        await _sync_product_competitor_snapshot(
            db,
            product,
            candidate,
            capture,
            status=FAILED,
            current_step=4,
            error_message=error_message,
            workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
            workflow_status=WORKFLOW_STATUS_FAILED,
            workflow_error=error_message,
        )


@router.get("/products/{product_id}/competitor-candidates", response_model=AmazonStyleSnapCandidateGroupResponse)
async def list_product_competitor_candidates(
    product_id: int,
    enrich_images: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    product, snapshot = await _load_product_for_competitor_selection(db, product_id)
    return await _load_product_candidate_group(db, product, snapshot, enrich_images=enrich_images)


@router.post("/products/{product_id}/competitor-candidates/search", response_model=ProductResponse)
async def search_product_competitor_candidates(
    product_id: int,
    background_tasks: BackgroundTasks,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    product, snapshot = await _load_product_for_competitor_selection(db, product_id)
    await _ensure_competitor_can_be_changed(db, product, snapshot, action="搜索")
    batch_id, site, item_code, representative_sku = _product_competitor_query_values(product, snapshot)
    precondition_error = _competitor_search_precondition_error(product, batch_id=batch_id, item_code=item_code)

    existing: list[AmazonStyleSnapCandidate] = []
    if batch_id and item_code:
        existing = await _existing_product_candidates(
            db,
            batch_id=batch_id,
            site=site,
            item_code=item_code,
            sku_code=representative_sku or item_code,
        )
    _ensure_competitor_search_workflow_allowed(product, force=force, has_existing=bool(existing))

    now = datetime.now()
    if precondition_error:
        _set_competitor_search_workflow(
            product,
            node=WORKFLOW_NODE_SEARCH_COMPETITOR,
            status=WORKFLOW_STATUS_FAILED,
            workflow_error=precondition_error,
            legacy_status=FAILED,
            legacy_current_step=2,
            legacy_error_message=precondition_error,
            now=now,
        )
        _write_stylesnap_search_snapshot(
            product,
            snapshot,
            batch_id=batch_id,
            site=site,
            representative_sku=representative_sku or item_code,
            stylesnap_search={
                "status": "failed",
                "error": precondition_error,
                "searched_at": now.isoformat(),
            },
        )
        await db.commit()
        return _build_stylesnap_product_response(product)

    if existing and not force:
        _set_competitor_search_workflow(
            product,
            node=WORKFLOW_NODE_SELECT_COMPETITOR,
            status=WORKFLOW_STATUS_PENDING,
            workflow_error=None,
            legacy_status=CREATED,
            legacy_current_step=max(product.current_step or 0, 2),
            legacy_error_message=None,
            now=now,
        )
        _write_stylesnap_search_snapshot(
            product,
            snapshot,
            batch_id=batch_id,
            site=site,
            representative_sku=representative_sku or item_code,
            stylesnap_search={
                "status": "captured",
                "count": len(existing),
                "reused": True,
                "searched_at": now.isoformat(),
                "source_image_path": product.images.main_image_path if product.images else None,
            },
        )
        await db.commit()
        return _build_stylesnap_product_response(product)

    running_message = "Amazon 同款搜索中：正在获取 StyleSnap token 并调用图片搜索接口，请等待候选结果"
    _set_competitor_search_workflow(
        product,
        node=WORKFLOW_NODE_SEARCH_COMPETITOR,
        status=WORKFLOW_STATUS_PROCESSING,
        workflow_error=None,
        legacy_status=COMPETITOR_SEARCHING,
        legacy_current_step=2,
        legacy_error_message=running_message,
        now=now,
    )
    _write_stylesnap_search_snapshot(
        product,
        snapshot,
        batch_id=batch_id,
        site=site,
        representative_sku=representative_sku or item_code,
        stylesnap_search={
            "status": "running",
            "started_at": now.isoformat(),
            "source_image_path": product.images.main_image_path,
            "append": True,
            "previous_count": len(existing),
        },
    )
    await db.commit()
    background_tasks.add_task(_run_product_competitor_search_background, product.id)
    return _build_stylesnap_product_response(product)


@router.post("/products/{product_id}/competitor-candidates/{candidate_id}/select", response_model=AmazonStyleSnapCandidateGroupResponse)
async def select_product_competitor_candidate(
    product_id: int,
    candidate_id: int,
    background_tasks: BackgroundTasks,
    force_capture: bool = Query(False),
    auto_start_generation: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    product, snapshot = await _load_product_for_competitor_selection(db, product_id)
    if is_running(product.id):
        raise HTTPException(400, "商品旧流程正在运行中，不能选择/切换竞品")
    _ensure_select_competitor_workflow_allowed(product)

    batch_id, site, item_code, _representative_sku = _product_competitor_query_values(product, snapshot)
    search_state = snapshot.get("stylesnap_search") if isinstance(snapshot.get("stylesnap_search"), dict) else {}
    if search_state.get("status") == "running":
        raise HTTPException(400, "候选竞品搜索仍在进行中，不能选择竞品")
    if search_state.get("status") == "failed":
        raise HTTPException(400, "候选竞品搜索失败，请先重新搜索候选")
    if not batch_id or not item_code:
        raise HTTPException(400, "当前商品缺少批次或 Item 信息，不能选择竞品")

    result = await db.execute(select(AmazonStyleSnapCandidate).where(AmazonStyleSnapCandidate.id == candidate_id))
    selected = result.scalar_one_or_none()
    if not selected:
        raise HTTPException(404, "StyleSnap candidate not found")
    if batch_id and selected.batch_id != batch_id:
        raise HTTPException(400, "候选竞品批次与当前商品不一致")
    if selected.site != site or selected.item_code != item_code:
        raise HTTPException(400, "候选竞品不属于当前商品")
    if not (search_state.get("status") == "captured" or product.current_step >= 2):
        raise HTTPException(400, "候选竞品搜索尚未完成，不能选择竞品")

    now = datetime.now()
    switching = bool(product.competitor_asin and product.competitor_asin != selected.asin)
    if switching or force_capture:
        _raise_if_protected_competitor_change(product)
        _clear_current_competitor_derived_outputs(product)
    await db.execute(
        update(AmazonStyleSnapCandidate)
        .where(
            AmazonStyleSnapCandidate.batch_id == selected.batch_id,
            AmazonStyleSnapCandidate.site == selected.site,
            AmazonStyleSnapCandidate.item_code == selected.item_code,
            AmazonStyleSnapCandidate.sku_code == selected.sku_code,
        )
        .values(is_selected=0, selected_at=None, updated_at=now)
    )
    selected.is_selected = 1
    selected.selected_at = now
    selected.updated_at = now
    await _sync_product_competitor_snapshot(
        db,
        product,
        selected,
        None,
        status=STEP5_LISTING,
        current_step=5,
        error_message="竞品详情抓取中：正在打开选中 ASIN 的 Amazon 页面，请等待后台完成",
        workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
        workflow_status=WORKFLOW_STATUS_PROCESSING,
        workflow_error=None,
    )

    capture = await _queue_listing_capture(db, selected, force=force_capture)
    if capture.capture_status == "captured" and not force_capture:
        await _sync_product_competitor_snapshot(
            db,
            product,
            selected,
            capture,
            status=CREATED,
            current_step=5,
            error_message=None,
            workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
            workflow_status=WORKFLOW_STATUS_SUCCEEDED,
            workflow_error=None,
        )
        if auto_start_generation:
            await _start_image_analysis_after_capture(db, product.id)
    else:
        await _sync_product_competitor_snapshot(
            db,
            product,
            selected,
            capture,
            status=STEP5_LISTING,
            current_step=5,
            error_message="竞品详情抓取中：正在打开选中 ASIN 的 Amazon 页面，请等待后台完成",
            workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
            workflow_status=WORKFLOW_STATUS_PROCESSING,
            workflow_error=None,
        )
        background_tasks.add_task(
            _capture_and_sync_product_competitor_background,
            product.id,
            selected.id,
            force_capture=True,
            auto_start_generation=auto_start_generation,
        )
    return await _load_group(db, selected.batch_id, selected.site, selected.item_code, selected.sku_code)


@router.post("/products/{product_id}/competitor-candidates/capture-missing", response_model=AmazonStyleSnapCandidateGroupResponse)
async def capture_missing_product_competitor_candidates(
    product_id: int,
    background_tasks: BackgroundTasks,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    product, snapshot = await _load_product_for_competitor_selection(db, product_id)
    group = await _load_product_candidate_group(db, product, snapshot, enrich_images=True)
    candidate_ids = [
        candidate.id
        for candidate in group.candidates
        if not candidate.title
        or not candidate.amazon_image_url
        or candidate.listing_capture_status == "failed"
    ]
    if candidate_ids:
        result = await db.execute(select(AmazonStyleSnapCandidate).where(AmazonStyleSnapCandidate.id.in_(candidate_ids)))
        queued_candidate_ids = await _queue_listing_prefetches(db, result.scalars().all(), force=force)
        if queued_candidate_ids:
            background_tasks.add_task(_run_listing_prefetch_background, queued_candidate_ids, force=force)
    return await _load_product_candidate_group(db, product, snapshot, enrich_images=False)


@router.post("/products/{product_id}/competitor-candidates/{candidate_id}/capture", response_model=AmazonStyleSnapCandidateGroupResponse)
async def retry_product_competitor_candidate_capture(
    product_id: int,
    candidate_id: int,
    background_tasks: BackgroundTasks,
    force: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    product, snapshot = await _load_product_for_competitor_selection(db, product_id)
    batch_id, site, item_code, _representative_sku = _product_competitor_query_values(product, snapshot)
    result = await db.execute(select(AmazonStyleSnapCandidate).where(AmazonStyleSnapCandidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(404, "StyleSnap candidate not found")
    if batch_id and candidate.batch_id != batch_id:
        raise HTTPException(400, "候选竞品批次与当前商品不一致")
    if candidate.site != site or candidate.item_code != item_code:
        raise HTTPException(400, "候选竞品不属于当前商品")

    selected_snapshot = snapshot.get("selected_stylesnap") if isinstance(snapshot.get("selected_stylesnap"), dict) else {}
    is_current_selected = (
        bool(candidate.is_selected)
        or selected_snapshot.get("candidate_id") == candidate.id
        or (bool(product.competitor_asin) and product.competitor_asin == candidate.asin)
    )
    if is_current_selected and (
        product.workflow_node,
        product.workflow_status,
    ) == (WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL, WORKFLOW_STATUS_FAILED):
        if is_running(product.id):
            raise HTTPException(400, "商品旧流程正在运行中，不能重新抓取竞品详情")
        _raise_if_protected_competitor_change(product)
        _clear_current_competitor_derived_outputs(product)
        capture = await _queue_listing_capture(db, candidate, force=force)
        await _sync_product_competitor_snapshot(
            db,
            product,
            candidate,
            capture,
            status=STEP5_LISTING,
            current_step=5,
            error_message="竞品详情抓取中：正在重新打开选中 ASIN 的 Amazon 页面，请等待后台完成",
            workflow_node=WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
            workflow_status=WORKFLOW_STATUS_PROCESSING,
            workflow_error=None,
        )
        background_tasks.add_task(
            _capture_and_sync_product_competitor_background,
            product.id,
            candidate.id,
            force_capture=True,
            auto_start_generation=True,
        )
        return await _load_product_candidate_group(db, product, snapshot, enrich_images=False)

    queued_candidate_ids = await _queue_listing_prefetches(db, [candidate], force=force)
    if queued_candidate_ids:
        background_tasks.add_task(_run_listing_prefetch_background, queued_candidate_ids, force=force)
    return await _load_product_candidate_group(db, product, snapshot, enrich_images=False)
