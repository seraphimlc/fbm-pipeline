"""
Pipeline 引擎 — 编排10步Pipeline的执行

状态流转：
  Step1(采集) → Step2(定价) → Step3(关键词) → Step4(类目) → Step5(Listing) → Step6(主图) → Step7(A+规划) → Step8(A+脚本) → Step9(A+出图) → Step10(导入表格)
"""

import asyncio
import logging
import traceback
from datetime import datetime

from app.config import settings
from app.database import async_session
from app.models import Product
from app.models.status import *
from app.pipeline.step1_collect import Step1DuplicateSkipped, Step1NeedsReview, Step1ProductUnavailable, collect_product
from app.pipeline.step2_pricing import run_pricing
from app.pipeline.step3_keywords import Step3NeedsLogin, run_keywords
from app.pipeline.step4_category import Step4NeedsReview, run_category
from app.pipeline.step5_listing import run_listing
from app.pipeline.step6_image import run_image_analysis
from app.pipeline.step7_aplus_plan import run_aplus_plan
from app.pipeline.step8_aplus_script import run_aplus_script
from app.pipeline.step9_aplus_image import run_aplus_image
from app.pipeline.step10_amazon_template import run_amazon_template

logger = logging.getLogger(__name__)

# 正在运行的Pipeline任务
_running_tasks: dict[int, asyncio.Task] = {}
_pipeline_semaphore = asyncio.Semaphore(max(1, settings.PIPELINE_MAX_CONCURRENCY))


def get_step_status(step: int, phase: str = "running") -> str:
    """获取步骤对应的状态字符串"""
    prefix = STEP_STATUS_MAP.get(step, "created")
    if phase == "done":
        done_map = {
            1: STEP1_DONE,
            2: STEP2_DONE,
            3: None,
            4: None,
            5: STEP5_DONE,
            6: STEP6_DONE,
            7: STEP7_DONE,
            8: STEP8_DONE,
            9: STEP9_DONE,
            10: STEP10_DONE,
        }
        return done_map.get(step, COMPLETED)
    return prefix


async def _run_pipeline(product_id: int, start_step: int = 1):
    """
    运行完整 Pipeline（后台任务）
    """
    try:
        if start_step <= 1:
            # === Step 1: 商品采集 ===
            logger.info(f"[Pipeline] Product {product_id} Step1 商品采集开始")
            await _update_status(product_id, STEP1_COLLECTING, 1)
            await collect_product(product_id)
            await _update_status(product_id, STEP1_DONE, 1)
            logger.info(f"[Pipeline] Product {product_id} Step1 商品采集完成")

        if start_step <= 2:
            # === Step 2: 利润计算 ===
            logger.info(f"[Pipeline] Product {product_id} Step2 利润计算开始")
            await _update_status(product_id, STEP2_PRICING, 2)
            await run_pricing(product_id)
            await _update_status(product_id, STEP2_DONE, 2)
            logger.info(f"[Pipeline] Product {product_id} Step2 利润计算完成")

        if start_step <= 3:
            # === Step 3: 关键词 ===
            logger.info(f"[Pipeline] Product {product_id} Step3 关键词开始")
            await _update_status(product_id, STEP3_KEYWORDS, 3)
            await run_keywords(product_id)
            logger.info(f"[Pipeline] Product {product_id} Step3 关键词完成")

        if start_step <= 4:
            # === Step 4: 类目 ===
            logger.info(f"[Pipeline] Product {product_id} Step4 类目开始")
            await _update_status(product_id, STEP4_CATEGORY, 4)
            await run_category(product_id)
            await _update_status(product_id, STEP3_4_DONE, 4)
            logger.info(f"[Pipeline] Product {product_id} Step4 类目完成")

        if start_step <= 5:
            # === Step 5: Listing 文案 ===
            logger.info(f"[Pipeline] Product {product_id} Step5 Listing 开始")
            await _update_status(product_id, STEP5_LISTING, 5)
            await run_listing(product_id)
            await _update_status(product_id, STEP5_DONE, 5)

        if start_step <= 6:
            # === Step 6: 主图分析 ===
            await _update_status(product_id, STEP6_CURATING, 6)
            await run_image_analysis(product_id)
            await _update_status(product_id, STEP6_DONE, 6)

        if start_step <= 7:
            # === Step 7: A+ 规划 ===
            await _update_status(product_id, STEP7_APLUS_PLAN, 7)
            await run_aplus_plan(product_id)
            await _update_status(product_id, STEP7_DONE, 7)

        if start_step <= 8:
            # === Step 8: A+ 脚本 ===
            await _update_status(product_id, STEP8_APLUS_SCRIPT, 8)
            await run_aplus_script(product_id)
            await _update_status(product_id, STEP8_DONE, 8)

        if start_step <= 9:
            # === Step 9: A+ 出图 ===
            await _update_status(product_id, STEP9_APLUS_IMAGE, 9)
            await run_aplus_image(product_id)
            await _update_status(product_id, STEP9_DONE, 9)

        if start_step <= 10:
            # === Step 10: Amazon导入表格 ===
            await _update_status(product_id, STEP10_AMAZON_TEMPLATE, 10)
            await run_amazon_template(product_id)
            await _update_status(product_id, STEP10_DONE, 10)

        # === 等待人工确认 ===
        await _update_status(product_id, PENDING_REVIEW, 10)
        logger.info(f"[Pipeline] Product {product_id} 已生成完成，等待人工确认")

    except asyncio.CancelledError:
        await _update_status(product_id, PAUSED, None)
        logger.info(f"[Pipeline] Product {product_id} 已暂停")
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
            await _run_pipeline(product_id, start_step=start_step)
    except asyncio.CancelledError:
        if not entered:
            await _update_status(product_id, PAUSED, None)
            _running_tasks.pop(product_id, None)
            logger.info(f"[Pipeline] Product {product_id} 在等待Pipeline并发名额时已暂停")
        raise


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


def start_pipeline(product_id: int, start_step: int = 1) -> bool:
    """
    启动Pipeline（非阻塞）
    
    Returns:
        bool: 是否成功启动
    """
    if product_id in _running_tasks:
        return False

    task = asyncio.create_task(_run_pipeline_with_limit(product_id, start_step=start_step))
    _running_tasks[product_id] = task
    return True


def cancel_pipeline(product_id: int) -> bool:
    """取消/暂停Pipeline"""
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
    """服务启动时把上次遗留的运行中 Pipeline 标记为可继续。"""
    running_statuses = {
        STEP1_COLLECTING,
        STEP2_PRICING,
        STEP3_KEYWORDS,
        STEP4_CATEGORY,
        STEP5_LISTING,
        STEP6_CURATING,
        STEP7_APLUS_PLAN,
        STEP8_APLUS_SCRIPT,
        STEP9_APLUS_IMAGE,
        STEP10_AMAZON_TEMPLATE,
    }
    async with async_session() as db:
        from sqlalchemy import select
        result = await db.execute(select(Product).where(Product.status.in_(running_statuses)))
        products = result.scalars().all()
        now = datetime.now()
        for product in products:
            product.status = PAUSED
            product.error_message = "服务重启导致任务中断，可点击继续从当前步骤重试。"
            product.updated_at = now
        if products:
            await db.commit()
            logger.warning(f"[Pipeline] 启动恢复: {len(products)} 个运行中任务已标记为暂停")
