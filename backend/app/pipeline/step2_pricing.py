"""
模块2：Amazon FBM 建议售价和预期利润计算。

本模块采用已确认的运营口径（所有金额均为美元）：

    G = 大建云仓货值（value_total）
    T = 大建云仓含运费采购总成本（estimated_total = G + S）
    S = 大建云仓去程物流费（T - G）
    I = G × 2.5%                 # 每单退货保障保费
    A = $2                       # 每成交订单广告成本预留
    B = 退货率 × 60% × G          # 平均保险赔付；确认不包含去程物流 S
    C = T + I + A - B             # 不随售价变化的期望综合成本

    不退货订单可留存售价的 90%（扣 10% Amazon 佣金）。
    4% 退货订单会失去这部分收入，并按单笔佣金的 20% 扣退货管理费，最多 $5。

    预期利润 = P × 90% × (1 - 4%)
             - 4% × MIN(P × 10% × 20%, $5)
             - C

因此不再使用固定“退货预留比例”：退货管理费会在售价 $250 时达到 $5 封顶，
且保险赔付基数是货值而非货值加物流。计算会分别求解 $250 以下和以上两个区间。
每个区间都取满足目标净利率（5%）及最低利润（$10）的较高价格，再向上取美分。
"""

import logging
import json
from datetime import datetime
from decimal import Decimal, ROUND_UP

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

    commission_rate = settings.PRICING_COMMISSION_RATE
    return_rate = settings.PRICING_RETURN_RATE
    insurance_rate = settings.PRICING_INSURANCE_RATE
    insurance_payout_rate = settings.PRICING_INSURANCE_PAYOUT_RATE
    return_management_fee_rate = settings.PRICING_RETURN_MANAGEMENT_FEE_RATE
    return_management_fee_cap = settings.PRICING_RETURN_MANAGEMENT_FEE_CAP
    advertising_cost = settings.PRICING_ADVERTISING_COST
    target_margin_rate = settings.PRICING_TARGET_MARGIN_RATE
    min_profit = settings.PRICING_MIN_PROFIT
    retained_revenue_rate = (1 - commission_rate) * (1 - return_rate)
    uncapped_management_fee_rate = return_rate * commission_rate * return_management_fee_rate
    uncapped_retained_revenue_rate = retained_revenue_rate - uncapped_management_fee_rate
    if (
        commission_rate < 0
        or return_rate < 0
        or insurance_rate < 0
        or insurance_payout_rate < 0
        or return_management_fee_rate < 0
        or return_management_fee_cap < 0
        or advertising_cost < 0
        or target_margin_rate < 0
        or uncapped_retained_revenue_rate <= target_margin_rate
    ):
        raise ValueError("定价配置无效：佣金、退货与退货管理费后的可留存收入必须大于目标净利率")

    source_shipping_cost = T - G
    insurance_cost = G * insurance_rate
    average_insurance_payout = return_rate * insurance_payout_rate * G
    # C 不含售价相关的收入、佣金或退货管理费；平均保险赔付只抵扣货值，不抵扣物流。
    cost = T + insurance_cost + advertising_cost - average_insurance_payout

    # 单笔管理费 = min(P × 佣金 × 20%, $5)。佣金为售价 10%，所以在 P=$250 达到封顶。
    management_fee_price_cap = (
        return_management_fee_cap / (commission_rate * return_management_fee_rate)
        if commission_rate > 0 and return_management_fee_rate > 0
        else 0
    )

    # 区间 A（P <= $250）：管理费随售价变化，合并进分母。
    P1_uncapped = cost / (uncapped_retained_revenue_rate - target_margin_rate)
    P2_uncapped = (cost + min_profit) / uncapped_retained_revenue_rate
    uncapped_candidate = max(P1_uncapped, P2_uncapped)

    # 区间 B（P > $250）：平均管理费固定为 退货率 × $5，合并进成本。
    average_capped_management_fee = return_rate * return_management_fee_cap
    capped_cost = cost + average_capped_management_fee
    P1_capped = capped_cost / (retained_revenue_rate - target_margin_rate)
    P2_capped = (capped_cost + min_profit) / retained_revenue_rate
    capped_candidate = max(P1_capped, P2_capped, management_fee_price_cap)

    # 美分向上取整，不能采用普通四舍五入而意外落到利润线以下。
    def round_up_to_cent(value: float) -> float:
        return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_UP))

    if management_fee_price_cap == 0 or uncapped_candidate <= management_fee_price_cap:
        P1, P2 = P1_uncapped, P2_uncapped
    else:
        P1, P2 = P1_capped, P2_capped

    price_for_margin = round_up_to_cent(P1)
    price_for_min_profit = round_up_to_cent(P2)
    P = max(price_for_margin, price_for_min_profit)
    selected_rule = "target_margin" if P1 >= P2 else "min_profit"

    # 利润率按“利润 / 建议售价”计算，存储为百分数数值：5.0 表示 5%。
    commission_fee = P * commission_rate * (1 - return_rate)
    return_management_fee = min(
        P * commission_rate * return_management_fee_rate,
        return_management_fee_cap,
    ) * return_rate
    return_revenue_loss = P * (1 - commission_rate) * return_rate
    return_reserve = return_revenue_loss + return_management_fee - average_insurance_payout
    net_revenue = P * retained_revenue_rate - return_management_fee
    profit = net_revenue - cost
    profit_rate = profit / P * 100 if P > 0 else 0

    # 费用明细会存入 product_data.pricing_detail，并显示在商品详情页，供人工复核。
    breakdown = {
        "net_revenue": round(net_revenue, 2),
        "retained_revenue_rate": round((net_revenue / P) * 100, 2),
        "commission_rate": round(commission_rate * 100, 2),
        "commission_fee": round(commission_fee, 2),
        "return_rate": round(return_rate * 100, 2),
        "return_reserve": round(return_reserve, 2),
        "return_revenue_loss": round(return_revenue_loss, 2),
        "return_management_fee": round(return_management_fee, 2),
        "source_cost": round(T, 2),
        "source_shipping_cost": round(source_shipping_cost, 2),
        "insurance_rate": round(insurance_rate * 100, 2),
        "insurance_cost": round(insurance_cost, 2),
        "insurance_payout_rate": round(insurance_payout_rate * 100, 2),
        "average_insurance_payout": round(average_insurance_payout, 2),
        "advertising_cost": round(advertising_cost, 2),
        "target_margin_rate": round(target_margin_rate * 100, 2),
        "min_profit": round(min_profit, 2),
        "price_for_margin": price_for_margin,
        "price_for_min_profit": price_for_min_profit,
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
