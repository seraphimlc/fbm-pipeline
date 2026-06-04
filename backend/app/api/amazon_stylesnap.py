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
from app.services.stylesnap_product_tasks import (
    _category_path_from_candidate,
    _category_path_from_listing_capture,
    _json_dumps,
    _json_loads,
    _listing_capture_snapshot,
)
from app.pipeline.engine import is_running, start_pipeline
from app.models.status import CREATED, FAILED, STEP5_LISTING


router = APIRouter(prefix="/api/amazon-stylesnap", tags=["amazon-stylesnap"])
COMPETITOR_SEARCHING = "competitor_searching"
COMPETITOR_SWITCH_BLOCKING_STATUSES = {
    COMPETITOR_SEARCHING,
    STEP5_LISTING,
    "step6_curating",
    "step7_aplus_plan",
    "step8_aplus_script",
    "step9_aplus_image",
}
LISTING_CAPTURE_ACTIVE_TTL = timedelta(minutes=5)
LISTING_CAPTURE_QUEUED_TTL = timedelta(seconds=30)


def _start_generation_after_competitor(product_id: int) -> None:
    if not is_running(product_id):
        start_pipeline(product_id, start_step=5)


def _candidate_response(
    candidate: AmazonStyleSnapCandidate,
    capture_by_candidate: dict[int, AmazonListingCapture] | None = None,
) -> AmazonStyleSnapCandidateResponse:
    data = AmazonStyleSnapCandidateResponse.model_validate(candidate)
    capture = (capture_by_candidate or {}).get(candidate.id)
    if capture:
        data.listing_capture_id = capture.id
        data.listing_capture_status = capture.capture_status
        data.listing_captured_at = capture.captured_at
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
        .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus))
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


def _product_competitor_query_values(product: Product, snapshot: dict) -> tuple[str | None, str, str | None, str | None]:
    batch_id = snapshot.get("batch_id")
    site = str(snapshot.get("site") or "US").strip().upper()
    item_code = product.data.item_code if product.data else None
    representative_sku = snapshot.get("representative_sku") or item_code
    return batch_id, site, item_code, representative_sku


async def _load_product_candidate_group(
    db: AsyncSession,
    product: Product,
    snapshot: dict,
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

    captures = await _captures_by_candidate(db, [candidate.id for candidate in candidates])
    return _build_group(candidates, captures, {item_code: product})


async def _sync_product_competitor_snapshot(
    db: AsyncSession,
    product: Product,
    candidate: AmazonStyleSnapCandidate,
    capture: AmazonListingCapture | None,
    *,
    status: str | None = None,
    current_step: int | None = None,
    error_message: str | None = None,
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
            if not batch_id or not item_code:
                raise RuntimeError("当前商品缺少批次或 Item 信息，无法执行 Amazon 同款搜索")
            if not product.images or not product.images.main_image_path:
                raise RuntimeError("当前商品还没有确认主图，无法执行 Amazon 同款搜索")
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
            product.status = CREATED
            product.current_step = max(product.current_step or 0, 2)
            product.error_message = None
            product.updated_at = now
            if product.data:
                product.data.gigab2b_raw_snapshot = _json_dumps({
                    **snapshot,
                    "batch_id": batch_id,
                    "site": site,
                    "representative_sku": representative_sku or item_code,
                    "stylesnap_search": {
                        "status": "captured",
                        "count": len(all_candidates),
                        "appended_count": result.count,
                        "searched_at": now.isoformat(),
                        "source_image_path": product.images.main_image_path,
                    },
                })
            result_catalog = await db.execute(select(CatalogProduct).where(CatalogProduct.source_product_id == product.id))
            catalog = result_catalog.scalar_one_or_none()
            if catalog:
                catalog.status = product.status
                catalog.updated_at = now
            await db.commit()
        except asyncio.CancelledError:
            product.status = FAILED
            product.current_step = 2
            product.error_message = "Amazon 同款搜索被中断，请重新搜索候选"
            product.updated_at = datetime.now()
            if product.data:
                product.data.gigab2b_raw_snapshot = _json_dumps({
                    **snapshot,
                    "stylesnap_search": {
                        "status": "failed",
                        "error": product.error_message,
                        "searched_at": product.updated_at.isoformat(),
                    },
                })
            result_catalog = await db.execute(select(CatalogProduct).where(CatalogProduct.source_product_id == product.id))
            catalog = result_catalog.scalar_one_or_none()
            if catalog:
                catalog.status = product.status
                catalog.updated_at = product.updated_at
            await db.commit()
            raise
        except Exception as exc:
            product.status = FAILED
            product.current_step = 2
            product.error_message = f"Amazon 同款搜索失败: {type(exc).__name__}: {exc}"
            product.updated_at = now
            if product.data:
                product.data.gigab2b_raw_snapshot = _json_dumps({
                    **snapshot,
                    "stylesnap_search": {
                        "status": "failed",
                        "error": product.error_message,
                        "searched_at": now.isoformat(),
                    },
                })
            result_catalog = await db.execute(select(CatalogProduct).where(CatalogProduct.source_product_id == product.id))
            catalog = result_catalog.scalar_one_or_none()
            if catalog:
                catalog.status = product.status
                catalog.updated_at = now
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


async def _capture_and_sync_product_competitor_background(
    product_id: int,
    candidate_id: int,
    *,
    force_capture: bool = True,
):
    async with async_session() as db:
        product, _snapshot = await _load_product_for_competitor_selection(db, product_id)
        result = await db.execute(select(AmazonStyleSnapCandidate).where(AmazonStyleSnapCandidate.id == candidate_id))
        candidate = result.scalar_one_or_none()
        if not candidate:
            return
        try:
            capture = await capture_listing_for_candidate(db, candidate, force=force_capture)
            if capture.capture_status == "captured":
                await _sync_product_competitor_snapshot(
                    db,
                    product,
                    candidate,
                    capture,
                    status=CREATED,
                    current_step=5,
                    error_message=None,
                )
                _start_generation_after_competitor(product.id)
            else:
                await _sync_product_competitor_snapshot(
                    db,
                    product,
                    candidate,
                    capture,
                    status=FAILED,
                    current_step=4,
                    error_message=capture.capture_error or "竞品详情抓取失败",
                )
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
            )


@router.get("/products/{product_id}/competitor-candidates", response_model=AmazonStyleSnapCandidateGroupResponse)
async def list_product_competitor_candidates(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    product, snapshot = await _load_product_for_competitor_selection(db, product_id)
    return await _load_product_candidate_group(db, product, snapshot)


@router.post("/products/{product_id}/competitor-candidates/search", response_model=ProductResponse)
async def search_product_competitor_candidates(
    product_id: int,
    background_tasks: BackgroundTasks,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    product, snapshot = await _load_product_for_competitor_selection(db, product_id)
    await _ensure_competitor_can_be_changed(db, product, snapshot, action="搜索")
    if not product.images or not product.images.main_image_path:
        raise HTTPException(400, "请先在商品详情里确认主图，再用主图搜索 Amazon 同款")

    batch_id, site, item_code, representative_sku = _product_competitor_query_values(product, snapshot)
    if not batch_id or not item_code:
        raise HTTPException(400, "当前商品缺少批次或 Item 信息，不能搜索竞品")

    existing = await _existing_product_candidates(
        db,
        batch_id=batch_id,
        site=site,
        item_code=item_code,
        sku_code=representative_sku or item_code,
    )
    now = datetime.now()
    if existing and not force:
        product.status = CREATED
        product.current_step = max(product.current_step or 0, 2)
        product.error_message = None
        product.updated_at = now
        await db.commit()
        await db.refresh(product)
        return product

    product.status = COMPETITOR_SEARCHING
    product.current_step = 2
    product.error_message = "Amazon 同款搜索中：正在获取 StyleSnap token 并调用图片搜索接口，请等待候选结果"
    product.updated_at = now
    if product.data:
        product.data.gigab2b_raw_snapshot = _json_dumps({
            **snapshot,
            "batch_id": batch_id,
            "site": site,
            "representative_sku": representative_sku or item_code,
            "stylesnap_search": {
                "status": "running",
                "started_at": now.isoformat(),
                "source_image_path": product.images.main_image_path,
                "append": True,
                "previous_count": len(existing),
            },
        })
    result_catalog = await db.execute(select(CatalogProduct).where(CatalogProduct.source_product_id == product.id))
    catalog = result_catalog.scalar_one_or_none()
    if catalog:
        catalog.status = product.status
        catalog.updated_at = now
    await db.commit()
    await db.refresh(product)
    background_tasks.add_task(_run_product_competitor_search_background, product.id)
    return product


@router.post("/products/{product_id}/competitor-candidates/{candidate_id}/select", response_model=AmazonStyleSnapCandidateGroupResponse)
async def select_product_competitor_candidate(
    product_id: int,
    candidate_id: int,
    background_tasks: BackgroundTasks,
    force_capture: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    product, snapshot = await _load_product_for_competitor_selection(db, product_id)
    await _ensure_competitor_can_be_changed(db, product, snapshot, action="选择/切换")

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
        _clear_generation_outputs(product)
    stale_result = await db.execute(
        select(AmazonStyleSnapCandidate.id).where(
            AmazonStyleSnapCandidate.batch_id == selected.batch_id,
            AmazonStyleSnapCandidate.site == selected.site,
            AmazonStyleSnapCandidate.item_code == selected.item_code,
            AmazonStyleSnapCandidate.sku_code == selected.sku_code,
            AmazonStyleSnapCandidate.id != selected.id,
        )
    )
    stale_candidate_ids = list(stale_result.scalars().all())
    if stale_candidate_ids:
        await db.execute(
            update(AmazonListingCapture)
            .where(
                AmazonListingCapture.selected_candidate_id.in_(stale_candidate_ids),
                AmazonListingCapture.capture_status == "queued",
            )
            .values(
                capture_status="failed",
                capture_error="已切换竞品，旧抓取未执行",
                updated_at=now,
            )
        )
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
    await db.commit()
    await db.refresh(selected)

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
        )
        _start_generation_after_competitor(product.id)
    else:
        await _sync_product_competitor_snapshot(
            db,
            product,
            selected,
            capture,
            status=STEP5_LISTING,
            current_step=5,
            error_message="竞品详情抓取中：正在打开选中 ASIN 的 Amazon 页面，请等待后台完成",
        )
        background_tasks.add_task(
            _capture_and_sync_product_competitor_background,
            product.id,
            selected.id,
            force_capture=True,
        )
    return await _load_group(db, selected.batch_id, selected.site, selected.item_code, selected.sku_code)
