"""
Pipeline 引擎 — 编排10步Pipeline的执行

状态流转：
  Step1(采集) → Step2(定价) → [Step3(关键词) ∥ Step4(类目)] → Step5(Listing) → Step6(主图) → Step7(A+规划) → Step8(A+脚本) → Step9(A+出图)
  
Step3/4 可并行执行
"""

import asyncio
import logging
import traceback
from datetime import datetime

from app.database import async_session
from app.models import Product
from app.models.status import *
from app.pipeline.step1_collect import collect_product
from app.pipeline.step2_pricing import run_pricing
from app.pipeline.step3_keywords import run_keywords
from app.pipeline.step4_category import run_category
from app.pipeline.step5_listing import run_listing
from app.pipeline.step6_image import run_image_analysis
from app.pipeline.step7_aplus_plan import run_aplus_plan
from app.pipeline.step8_aplus_script import run_aplus_script
from app.pipeline.step9_aplus_image import run_aplus_image

logger = logging.getLogger(__name__)

# 正在运行的Pipeline任务
_running_tasks: dict[int, asyncio.Task] = {}


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
        }
        return done_map.get(step, COMPLETED)
    return prefix


async def _run_pipeline(product_id: int):
    """
    运行完整 Pipeline（后台任务）
    """
    try:
        # === Step 1: 商品采集 ===
        await _update_status(product_id, STEP1_COLLECTING, 1)
        await collect_product(product_id)
        await _update_status(product_id, STEP1_DONE, 1)

        # === Step 2: 利润计算（可选，需要大健云仓登录态）===
        await _update_status(product_id, STEP2_PRICING, 2)
        try:
            result2 = await run_pricing(product_id)
            if isinstance(result2, dict) and result2.get("skipped"):
                logger.warning(f"[Pipeline] Step2 跳过: {result2.get('reason')}")
                await _update_status(product_id, STEP2_DONE, 2)
            else:
                await _update_status(product_id, STEP2_DONE, 2)
        except Exception as e:
            logger.warning(f"[Pipeline] Step2 失败（非阻断）: {e}")
            await _update_status(product_id, STEP2_DONE, 2)

        # === Step 3 + 4: 关键词 + 类目（可选，并行，需要ASIN+Token）===
        await _update_status(product_id, STEP3_KEYWORDS, 3)
        try:
            r3, r4 = await asyncio.gather(
                run_keywords(product_id),
                run_category(product_id),
                return_exceptions=True,
            )
            if isinstance(r3, Exception):
                logger.warning(f"[Pipeline] Step3 失败（非阻断）: {r3}")
            elif isinstance(r3, dict) and r3.get("skipped"):
                logger.warning(f"[Pipeline] Step3 跳过: {r3.get('reason')}")
            if isinstance(r4, Exception):
                logger.warning(f"[Pipeline] Step4 失败（非阻断）: {r4}")
            elif isinstance(r4, dict) and r4.get("skipped"):
                logger.warning(f"[Pipeline] Step4 跳过: {r4.get('reason')}")
            await _update_status(product_id, STEP3_4_DONE, 4)
        except Exception as e:
            logger.warning(f"[Pipeline] Step3/4 异常（非阻断）: {e}")
            await _update_status(product_id, STEP3_4_DONE, 4)

        # === Step 5: Listing 文案 ===
        await _update_status(product_id, STEP5_LISTING, 5)
        await run_listing(product_id)
        await _update_status(product_id, STEP5_DONE, 5)

        # === Step 6: 主图分析 ===
        await _update_status(product_id, STEP6_CURATING, 6)
        await run_image_analysis(product_id)
        await _update_status(product_id, STEP6_DONE, 6)

        # === Step 7: A+ 规划 ===
        await _update_status(product_id, STEP7_APLUS_PLAN, 7)
        await run_aplus_plan(product_id)
        await _update_status(product_id, STEP7_DONE, 7)

        # === Step 8: A+ 脚本 ===
        await _update_status(product_id, STEP8_APLUS_SCRIPT, 8)
        await run_aplus_script(product_id)
        await _update_status(product_id, STEP8_DONE, 8)

        # === Step 9: A+ 出图 ===
        await _update_status(product_id, STEP9_APLUS_IMAGE, 9)
        await run_aplus_image(product_id)
        await _update_status(product_id, STEP9_DONE, 9)

        # === 完成 ===
        await _update_status(product_id, COMPLETED, 9)
        logger.info(f"[Pipeline] Product {product_id} 全部完成 🎉")

    except asyncio.CancelledError:
        await _update_status(product_id, PAUSED, None)
        logger.info(f"[Pipeline] Product {product_id} 已暂停")
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        await _update_status(product_id, FAILED, None, error=error_msg)
        logger.error(f"[Pipeline] Product {product_id} 失败: {error_msg}\n{traceback.format_exc()}")
    finally:
        _running_tasks.pop(product_id, None)


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


def start_pipeline(product_id: int) -> bool:
    """
    启动Pipeline（非阻塞）
    
    Returns:
        bool: 是否成功启动
    """
    if product_id in _running_tasks:
        return False

    task = asyncio.create_task(_run_pipeline(product_id))
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
