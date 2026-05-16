"""
模块2：利润计算 — FBM 售价和利润计算

公式：
    T = 预估总额含运费（大健云仓成本）
    G = 货值总计
    C = T + 固定成本 - 退货保险抵扣率×G  (综合成本)
    P1 = C ÷ (净收入比例 - 目标净利率)
    P2 = (C + 最低利润) ÷ 净收入比例
    P = MAX(P1, P2)
    利润 = P × 净收入比例 - C
    净利率 = 利润 ÷ P
"""

import logging
import json
from datetime import datetime

from app.config import settings
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

    net_revenue_rate = settings.PRICING_NET_REVENUE_RATE
    target_margin_rate = settings.PRICING_TARGET_MARGIN_RATE
    min_profit = settings.PRICING_MIN_PROFIT
    fixed_cost = settings.PRICING_FIXED_COST
    return_credit_rate = settings.PRICING_RETURN_CREDIT_RATE
    if net_revenue_rate <= 0 or target_margin_rate < 0 or net_revenue_rate <= target_margin_rate:
        raise ValueError("定价配置无效：净收入比例必须大于目标净利率")

    # 综合成本：大健含运费成本 + 固定成本预留 - 退货保险抵扣。
    cost = T + fixed_cost - return_credit_rate * G

    # 公式一：确保目标净利率（利润/售价）。
    P1 = cost / (net_revenue_rate - target_margin_rate)

    # 公式二：确保单件最低利润。
    P2 = (cost + min_profit) / net_revenue_rate

    # 取较大值
    P = max(P1, P2)
    selected_rule = "target_margin" if P1 >= P2 else "min_profit"

    # 利润率按“利润 / 建议售价”计算，存储为百分数数值：5.0 表示 5%。
    profit = P * net_revenue_rate - cost
    profit_rate = profit / P * 100 if P > 0 else 0

    # 费用明细
    breakdown = {
        "net_revenue": round(P * net_revenue_rate, 2),
        "variable_fee": round(P * (1 - net_revenue_rate), 2),
        "fixed_cost": round(fixed_cost, 2),
        "return_credit": round(return_credit_rate * G, 2),
        "target_margin_rate": round(target_margin_rate * 100, 2),
        "min_profit": round(min_profit, 2),
        "price_for_margin": round(P1, 2),
        "price_for_min_profit": round(P2, 2),
        "selected_rule": selected_rule,
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
            raise ValueError(
                "缺少成本数据，停止后续步骤: "
                f"estimated_total={T}, value_total={G}。"
                "请确认大健云仓页面已展示价格/成本字段后重新开始。"
            )

        logger.info(f"[Step2] 计算利润: T=${T}, G=${G}")

        calc = calculate_price(T, G)
        if not calc:
            raise ValueError("利润计算失败")

        # 保存
        pd.suggested_price = calc["suggested_price"]
        pd.cost_total = calc["cost_total"]
        pd.profit = calc["profit"]
        pd.profit_rate = calc["profit_rate"]
        pd.pricing_detail = json.dumps(calc["breakdown"], ensure_ascii=False)
        await db.commit()

        logger.info(
            f"[Step2] 利润计算完成: 建议售价=${calc['suggested_price']}, "
            f"利润=${calc['profit']} ({calc['profit_rate']}%)"
        )
        return calc
