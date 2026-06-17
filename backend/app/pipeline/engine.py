"""
Pipeline 引擎 — 编排商品优化 Pipeline 的执行

状态流转：
  Step1(采集) → Step2(定价) → Step3(关键词) → Step4(类目) → Step5(图片分析) → Step6(Listing) → 待导出
"""

import asyncio
import json
import logging
import time
import traceback
from datetime import datetime

from app.config import settings
from app.database import async_session
from app.models import AmazonListingCapture, CatalogProduct, Product
from app.models.status import *
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.pipeline.step1_collect import Step1DuplicateSkipped, Step1NeedsReview, Step1ProductUnavailable
from app.pipeline.step2_pricing import run_pricing
from app.pipeline.step3_keywords import Step3NeedsLogin, run_keywords
from app.pipeline.step4_category import Step4NeedsReview, run_category
from app.pipeline.step5_listing import run_listing
from app.pipeline.step6_image import run_image_analysis

logger = logging.getLogger(__name__)

# 正在运行的Pipeline任务
_running_tasks: dict[int, asyncio.Task] = {}
_pipeline_semaphore = asyncio.Semaphore(max(1, settings.PIPELINE_MAX_CONCURRENCY))


def _json_loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


ACTIVE_LISTING_CAPTURE_STATUSES = {"queued", "running"}


async def _has_captured_competitor(db, product: Product) -> bool:
    if not product.data:
        return False
    snapshot = _json_loads(product.data.gigab2b_raw_snapshot, {})
    if not isinstance(snapshot, dict):
        return False
    selected = snapshot.get("selected_stylesnap")
    capture = snapshot.get("amazon_listing_capture")
    if _is_competitor_listing_capture_state(product):
        raise RuntimeError("前置节点未完成：竞品详情仍在抓取中，请等待完成后再进入图片分析")
    if isinstance(capture, dict) and capture.get("status") in ACTIVE_LISTING_CAPTURE_STATUSES:
        raise RuntimeError("前置节点未完成：竞品详情仍在抓取中，请等待完成后再进入图片分析")
    candidate_id = selected.get("candidate_id") if isinstance(selected, dict) else None
    if candidate_id:
        result = await db.execute(
            select(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id == int(candidate_id))
        )
        current_capture = result.scalar_one_or_none()
        if current_capture and current_capture.capture_status in ACTIVE_LISTING_CAPTURE_STATUSES:
            raise RuntimeError("前置节点未完成：竞品详情仍在抓取中，请等待完成后再进入图片分析")
        if (
            current_capture
            and current_capture.capture_status == "captured"
            and current_capture.asin == product.competitor_asin
        ):
            return True
    return bool(
        product.competitor_asin
        and isinstance(selected, dict)
        and isinstance(capture, dict)
        and capture.get("status") == "captured"
        and capture.get("asin") == product.competitor_asin
    )


def _is_competitor_listing_capture_state(product: Product) -> bool:
    return (
        product.status == STEP5_LISTING
        and bool(product.error_message)
        and "竞品" in (product.error_message or "")
        and "抓取中" in (product.error_message or "")
    )


def _selected_stylesnap_candidate_id(product: Product) -> int | None:
    if not product.data:
        return None
    snapshot = _json_loads(product.data.gigab2b_raw_snapshot, {})
    if not isinstance(snapshot, dict):
        return None
    selected = snapshot.get("selected_stylesnap")
    if not isinstance(selected, dict) or not selected.get("candidate_id"):
        return None
    try:
        return int(selected["candidate_id"])
    except (TypeError, ValueError):
        return None


async def _assert_step_prerequisites(product_id: int, step: int) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product:
            raise RuntimeError(f"Product {product_id} not found")
        if step >= 5:
            if not product.images or not product.images.main_image_path:
                raise RuntimeError("前置节点未完成：请先确认商品主图和 Listing 图片")
            if not product.competitor_asin:
                raise RuntimeError("前置节点未完成：请先从候选中选择参考竞品")
            if not await _has_captured_competitor(db, product):
                raise RuntimeError("前置节点未完成：请先抓取选中竞品的 Amazon Listing 详情")
        if step >= 6 and (not product.images or not product.images.image_analysis):
            raise RuntimeError("前置节点未完成：图片分析节点未完成，不能进入 Listing 文案")
        if step >= 7:
            raise RuntimeError("A+ 已从主流程拆出，请在 A+管理中单独生成")


def get_step_status(step: int, phase: str = "running") -> str:
    """获取步骤对应的状态字符串"""
    prefix = STEP_STATUS_MAP.get(step, "created")
    if phase == "done":
        done_map = {
            1: STEP1_DONE,
            2: STEP2_DONE,
            3: None,
            4: None,
            5: STEP6_DONE,
            6: STEP5_DONE,
            10: STEP10_DONE,
        }
        return done_map.get(step, COMPLETED)
    return prefix


async def _run_pipeline(product_id: int, start_step: int = 1):
    """
    运行完整 Pipeline（后台任务）
    """
    try:
        if start_step <= 6:
            raise RuntimeError("Step5 图片分析和 Step6 Listing 已迁移到新任务中心，请创建 product_image_analysis/product_listing_generation task_run")

        if start_step <= 1:
            raise RuntimeError(
                "Step1 浏览器采集已停用：商品中心应使用商品数据源/OpenAPI拉品，不能再自动访问大健商品页"
            )

        if start_step <= 2:
            # === Step 2: 利润计算 ===
            logger.info(f"[Pipeline] Product {product_id} Step2 利润计算开始")
            step_started = time.monotonic()
            await _update_status(product_id, STEP2_PRICING, 2)
            await run_pricing(product_id)
            await _update_status(product_id, STEP2_DONE, 2)
            logger.info(f"[Pipeline] Product {product_id} Step2 利润计算完成，耗时={time.monotonic() - step_started:.1f}s")

        if start_step <= 3:
            # === Step 3: 关键词 ===
            logger.info(f"[Pipeline] Product {product_id} Step3 关键词开始")
            step_started = time.monotonic()
            await _update_status(product_id, STEP3_KEYWORDS, 3)
            await run_keywords(product_id)
            logger.info(f"[Pipeline] Product {product_id} Step3 关键词完成，耗时={time.monotonic() - step_started:.1f}s")

        if start_step <= 4:
            # === Step 4: 类目 ===
            logger.info(f"[Pipeline] Product {product_id} Step4 类目开始")
            step_started = time.monotonic()
            await _update_status(product_id, STEP4_CATEGORY, 4)
            await run_category(product_id)
            await _update_status(product_id, STEP3_4_DONE, 4)
            logger.info(f"[Pipeline] Product {product_id} Step4 类目完成，耗时={time.monotonic() - step_started:.1f}s")

        if start_step <= 6:
            # === Step 6: Listing 文案 ===
            await _assert_step_prerequisites(product_id, 6)
            logger.info(f"[Pipeline] Product {product_id} Step6 Listing 开始")
            step_started = time.monotonic()
            await _update_status(product_id, STEP5_LISTING, 6)
            await run_listing(product_id)
            await _update_status(product_id, STEP5_DONE, 6)
            logger.info(f"[Pipeline] Product {product_id} Step6 Listing 完成，耗时={time.monotonic() - step_started:.1f}s")

        await _mark_completed_for_export(product_id)
        logger.info(f"[Pipeline] Product {product_id} Listing 完成，已自动加入待导出")

    except asyncio.CancelledError:
        await _update_status(product_id, PAUSED, None)
        logger.info(f"[Pipeline] Product {product_id} 已挂起")
    except Step1NeedsReview as e:
        await _update_status(product_id, PENDING_REVIEW, 1, error=f"Step1待人工处理: {e}")
        logger.warning(f"[Pipeline] Product {product_id} Step1 需要人工处理: {e}")
    except Step1ProductUnavailable as e:
        await _update_status(product_id, SOURCE_UNAVAILABLE, 1, error=str(e))
        logger.info(f"[Pipeline] Product {product_id} 原商品下架，停止Pipeline: {e}")
    except Step1DuplicateSkipped as e:
        await _update_status(product_id, DUPLICATE_SKIPPED, 1, error=str(e))
        logger.info(f"[Pipeline] Product {product_id} 重复商品已跳过: {e}")
    except Step3NeedsLogin as e:
        await _update_status(product_id, PENDING_REVIEW, 3, error=f"Step3待人工登录: {e}")
        logger.warning(f"[Pipeline] Product {product_id} Step3 需要人工登录: {e}")
    except Step4NeedsReview as e:
        await _update_status(product_id, PENDING_REVIEW, 4, error=f"Step4待人工补类目: {e}")
        logger.warning(f"[Pipeline] Product {product_id} Step4 需要人工补类目: {e}")
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        await _update_status(product_id, FAILED, None, error=error_msg)
        logger.error(f"[Pipeline] Product {product_id} 失败: {error_msg}\n{traceback.format_exc()}")
    finally:
        _running_tasks.pop(product_id, None)


async def _run_pipeline_with_limit(product_id: int, start_step: int = 1):
    """按配置限制同时真正执行的 Pipeline 数量，批量启动时其余任务会在后台排队。"""
    entered = False
    if _pipeline_semaphore.locked():
        logger.info(
            f"[Pipeline] Product {product_id} 等待Pipeline并发名额，"
            f"max={settings.PIPELINE_MAX_CONCURRENCY}"
        )
    try:
        async with _pipeline_semaphore:
            entered = True
            logger.info(
                f"[Pipeline] Product {product_id} 获取Pipeline并发名额，"
                f"max={settings.PIPELINE_MAX_CONCURRENCY}"
            )
            if await _is_paused(product_id):
                logger.info(f"[Pipeline] Product {product_id} 已挂起，跳过自动执行")
                return
            await _run_pipeline(product_id, start_step=start_step)
    except asyncio.CancelledError:
        if not entered:
            await _update_status(product_id, PAUSED, None)
            logger.info(f"[Pipeline] Product {product_id} 在等待Pipeline并发名额时已挂起")
        raise
    finally:
        _running_tasks.pop(product_id, None)


async def _is_paused(product_id: int) -> bool:
    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(select(Product.status).where(Product.id == product_id))
        return result.scalar_one_or_none() == PAUSED


async def _update_status(product_id: int, status: str, step: int | None, error: str | None = None):
    """更新商品状态到数据库"""
    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if product:
            product.status = status
            if step is not None:
                product.current_step = step
            if error:
                product.error_message = error
            else:
                product.error_message = None
            product.updated_at = datetime.now()
            await db.commit()


async def _mark_completed_for_export(product_id: int) -> None:
    """Listing generated successfully; sync the product into the export catalog."""
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data), selectinload(Product.catalog_item))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product:
            return

        product.status = COMPLETED
        product.current_step = 6
        product.error_message = None
        product.updated_at = datetime.now()

        pd = product.data
        item = product.catalog_item
        if not item:
            item = CatalogProduct(source_product_id=product.id, gigab2b_url=product.gigab2b_url)
            db.add(item)

        item.gigab2b_url = product.gigab2b_url
        item.gigab2b_product_id = product.gigab2b_product_id
        item.competitor_asin = product.competitor_asin
        item.amazon_asin = product.amazon_asin
        item.asin_sync_status = product.asin_sync_status
        item.asin_synced_at = product.asin_synced_at
        item.asin_sync_error = product.asin_sync_error
        item.amazon_product_status = product.amazon_product_status
        item.amazon_product_status_synced_at = product.amazon_product_status_synced_at
        item.amazon_product_status_error = product.amazon_product_status_error
        item.aplus_upload_status = product.aplus_upload_status
        item.aplus_uploaded_at = product.aplus_uploaded_at
        item.aplus_upload_error = product.aplus_upload_error
        item.upc = product.upc
        item.brand = product.brand
        item.item_code = pd.item_code if pd else None
        item.title = pd.title if pd else None
        item.leaf_category = pd.leaf_category if pd else None
        item.status = product.status
        item.confirmed_at = item.confirmed_at or datetime.now()
        item.updated_at = datetime.now()
        await db.commit()


def start_pipeline(product_id: int, start_step: int = 1) -> bool:
    """
    启动Pipeline（非阻塞）
    
    Returns:
        bool: 是否成功启动
    """
    if start_step <= 6:
        logger.warning("[Pipeline] Step5 图片分析和 Step6 Listing 已迁移到新任务中心，拒绝旧内存启动: product=%s start_step=%s", product_id, start_step)
        return False
    if product_id in _running_tasks:
        return False

    task = asyncio.create_task(_run_pipeline_with_limit(product_id, start_step=start_step))
    _running_tasks[product_id] = task
    return True


async def run_pipeline_tracked(product_id: int, start_step: int = 1) -> None:
    """Run a product pipeline in the current task while exposing it via is_running()."""
    if start_step <= 6:
        raise RuntimeError("Step5 图片分析和 Step6 Listing 已迁移到新任务中心，请创建 product_image_analysis/product_listing_generation task_run")
    current_task = asyncio.current_task()
    if current_task is None:
        await _run_pipeline_with_limit(product_id, start_step=start_step)
        return
    existing = _running_tasks.get(product_id)
    if existing and not existing.done() and existing is not current_task:
        raise RuntimeError("商品流程正在运行中")
    _running_tasks[product_id] = current_task
    await _run_pipeline_with_limit(product_id, start_step=start_step)


def cancel_pipeline(product_id: int) -> bool:
    """取消/挂起Pipeline"""
    task = _running_tasks.get(product_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def is_running(product_id: int) -> bool:
    """检查Pipeline是否在运行"""
    task = _running_tasks.get(product_id)
    return task is not None and not task.done()


async def cancel_all_pipelines() -> None:
    """服务关闭时取消内存中的 Pipeline，并让任务写入 paused 状态。"""
    tasks = [task for task in _running_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def recover_interrupted_pipelines() -> None:
    """服务启动时把上次遗留的运行中 Pipeline 重新排队继续跑。"""
    running_statuses = {
        STEP1_COLLECTING,
        STEP2_PRICING,
        STEP3_KEYWORDS,
        STEP4_CATEGORY,
        "competitor_searching",
        STEP5_LISTING,
        STEP6_CURATING,
    }
    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data))
            .where(Product.status.in_(running_statuses))
        )
        products = result.scalars().all()
        now = datetime.now()
        resume_items: list[tuple[int, int]] = []
        for product in products:
            if product.status == "competitor_searching":
                product.status = FAILED
                product.current_step = 2
                product.error_message = "Amazon 同款搜索被中断，请重新搜索候选"
                product.updated_at = now
                if product.data:
                    snapshot = _json_loads(product.data.gigab2b_raw_snapshot, {})
                    if isinstance(snapshot, dict):
                        snapshot["stylesnap_search"] = {
                            "status": "failed",
                            "error": product.error_message,
                            "searched_at": now.isoformat(),
                        }
                        product.data.gigab2b_raw_snapshot = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
                continue
            if _is_competitor_listing_capture_state(product):
                # STEP5_LISTING is also used while the selected competitor detail
                # capture is in progress. After a process restart the background
                # capture task is gone, so expose it as a retryable failure.
                product.status = FAILED
                product.current_step = 4
                product.error_message = "竞品详情抓取被中断，请重新抓详情"
                product.updated_at = now
                if product.data:
                    snapshot = _json_loads(product.data.gigab2b_raw_snapshot, {})
                    if isinstance(snapshot, dict):
                        capture_snapshot = snapshot.get("amazon_listing_capture")
                        if isinstance(capture_snapshot, dict):
                            capture_snapshot["status"] = "failed"
                            capture_snapshot["capture_status"] = "failed"
                            capture_snapshot["capture_error"] = product.error_message
                            capture_snapshot["updated_at"] = now.isoformat()
                        product.data.gigab2b_raw_snapshot = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
                candidate_id = _selected_stylesnap_candidate_id(product)
                if candidate_id:
                    capture_result = await db.execute(
                        select(AmazonListingCapture).where(AmazonListingCapture.selected_candidate_id == candidate_id)
                    )
                    capture = capture_result.scalar_one_or_none()
                    if capture and capture.capture_status in ACTIVE_LISTING_CAPTURE_STATUSES:
                        capture.capture_status = "failed"
                        capture.capture_error = product.error_message
                        capture.updated_at = now
                continue
            step = product.current_step or 1
            if step < 1:
                step = 1
            if step <= 1:
                product.status = FAILED
                product.current_step = 1
                product.error_message = "Step1 浏览器采集已停用：请通过商品数据源/OpenAPI拉品生成商品草稿"
                product.updated_at = now
                continue
            if step > 6:
                step = 6
            product.status = get_step_status(step)
            product.error_message = None
            product.updated_at = now
            resume_items.append((product.id, step))
        if products:
            await db.commit()
            logger.warning(f"[Pipeline] 启动恢复: {len(products)} 个运行中任务将从原步骤自动续跑")
    for product_id, step in resume_items:
        if start_pipeline(product_id, start_step=step):
            logger.info(f"[Pipeline] 启动恢复: Product {product_id} 已重新排队，从 Step{step} 继续")
