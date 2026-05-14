"""
模块2：利润计算 — FBM 售价和利润计算

公式：
    T = 预估总额含运费（大健云仓成本）
    G = 货值总计
    C = T + 9 - 0.06G  (综合成本)
    P1 = (T + 9 - 0.06G) ÷ 0.635  (5%利润率)
    P2 = (T + 19 - 0.06G) ÷ 0.685 (保底$10利润)
    P = MAX(P1, P2)
    利润 = P × 0.685 - T - 9 + 0.06G
"""

import logging
from datetime import datetime

from app.database import async_session
from app.models import Product, ProductData
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


def calculate_price(T: float, G: float) -> dict:
    """
    计算 FBM 建议售价和利润
    
    Args:
        T: 预估总额含运费
        G: 货值总计
    
    Returns:
        dict: {suggested_price, cost_total, profit, profit_rate, breakdown}
    """
    if not T or not G or T <= 0 or G <= 0:
        return None

    # 综合成本
    cost = T + 9 - 0.06 * G

    # 公式一：5%利润率
    P1 = (T + 9 - 0.06 * G) / 0.635

    # 公式二：保底$10利润
    P2 = (T + 19 - 0.06 * G) / 0.685

    # 取较大值
    P = max(P1, P2)

    # 利润
    profit = P * 0.685 - T - 9 + 0.06 * G
    profit_rate = profit / P * 100 if P > 0 else 0

    # 费用明细
    breakdown = {
        "effective_sales": round(P * 0.90, 2),       # 有效成交额
        "commission": round(P * 0.90 * 0.10, 2),     # 佣金
        "coupon_discount": round(P * 0.10, 2),       # 优惠券折扣
        "coupon_clawback": round(P * 0.025, 2),      # 优惠券扣点
        "insurance": 7,                                # 保险费
        "ad_fee": 2,                                   # 广告费
        "return_insurance": round(0.10 * 0.60 * G, 2), # 退货保险赔偿
    }

    return {
        "suggested_price": round(P, 2),
        "cost_total": round(cost, 2),
        "profit": round(profit, 2),
        "profit_rate": round(profit_rate, 1),
        "breakdown": breakdown,
    }


async def run_pricing(product_id: int) -> dict:
    """
    执行利润计算
    
    读取 Step1 采集的 value_total(G) 和 estimated_total(T)，
    计算建议售价和利润，保存到 product_data 表
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        T = pd.estimated_total
        G = pd.value_total

        if not T or not G:
            logger.warning(
                f"[Step2] 跳过利润计算（缺少成本数据）: "
                f"estimated_total={T}, value_total={G}。"
                f"请确保已登录大健云仓并重新采集商品。"
            )
            return {"skipped": True, "reason": "missing_cost_data"}

        logger.info(f"[Step2] 计算利润: T=${T}, G=${G}")

        calc = calculate_price(T, G)
        if not calc:
            raise ValueError("利润计算失败")

        # 保存
        pd.suggested_price = calc["suggested_price"]
        pd.cost_total = calc["cost_total"]
        pd.profit = calc["profit"]
        pd.profit_rate = calc["profit_rate"]
        await db.commit()

        logger.info(
            f"[Step2] 利润计算完成: 建议售价=${calc['suggested_price']}, "
            f"利润=${calc['profit']} ({calc['profit_rate']}%)"
        )
        return calc
