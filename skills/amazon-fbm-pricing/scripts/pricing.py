"""
Amazon FBM 商品售价及利润计算

变量定义：
    P = 建议零售价
    T = 预估总额含运费（大建云仓成本包含邮费）
    G = 货值总计

综合成本：
    C = T + 9 - 0.06G
    其中：9 = 保险费7美元 + 广告费2美元
          0.06G = 退货率10% × 保险赔偿60% × 货值总计

公式一（利润=5%×P）：
    P1 = (T + 9 - 0.06G) ÷ 0.635

公式二（利润=$10保底）：
    P2 = (T + 19 - 0.06G) ÷ 0.685

最终建议零售价：
    P = MAX(P1, P2)

利润公式：
    利润 = P × 0.685 - T - 9 + 0.06G

推导说明：
    佣金按有效成交额计算：10% × 90%×P = 9%×P
    收入比例 = 90% - 9% - 10% - 2.5% = 68.5%
    公式一分母 = 68.5% - 5% = 63.5%
    公式二分母 = 68.5%（利润固定$10，不再按比例）
"""

MIN_PROFIT = 10  # 最低利润$10


def calc_price(T, G):
    """
    公式一：按售价5%利润计算
    P1 = (T + 9 - 0.06G) ÷ 0.635
    """
    if T is None or G is None or T <= 0 or G <= 0:
        return None
    return round((T + 9 - 0.06 * G) / 0.635, 2)


def calc_price_min_profit(T, G):
    """
    公式二：按最低利润$10计算
    P2 = (T + 19 - 0.06G) ÷ 0.685
    """
    if T is None or G is None or T <= 0 or G <= 0:
        return None
    return round((T + 19 - 0.06 * G) / 0.685, 2)


def calc_price_with_min_profit(T, G):
    """
    计算建议零售价（确保利润不低于$10）

    P = MAX(P1, P2)
    P1 = (T + 9 - 0.06G) ÷ 0.635   （5%利润）
    P2 = (T + 19 - 0.06G) ÷ 0.685  （$10保底）

    Args:
        T: 预估总额含运费
        G: 货值总计

    Returns:
        (建议售价, 利润) 元组，如果输入无效返回 (None, None)
    """
    if T is None or G is None or T <= 0 or G <= 0:
        return (None, None)

    P1 = (T + 9 - 0.06 * G) / 0.635
    P2 = (T + 19 - 0.06 * G) / 0.685

    P = max(P1, P2)
    profit = P * 0.685 - T - 9 + 0.06 * G

    return (round(P, 2), round(profit, 2))


def calc_breakdown(T, G):
    """
    计算完整的费用明细

    Args:
        T: 预估总额含运费
        G: 货值总计

    Returns:
        dict: 包含各项费用明细
    """
    P, profit = calc_price_with_min_profit(T, G)
    if P is None:
        return None

    return {
        'suggested_price': P,
        'profit': profit,
        'effective_sales': round(P * 0.90, 2),  # 有效成交额
        'commission': round(P * 0.90 * 0.10, 2),  # 佣金（按成交额）
        'coupon_discount': round(P * 0.10, 2),  # 优惠券折扣
        'coupon_clawback': round(P * 0.025, 2),  # 优惠券扣点
        'cost': T,  # 成本含运费
        'insurance': 7,  # 保险费
        'ad_fee': 2,  # 广告费
        'return_insurance': round(0.10 * 0.60 * G, 2),  # 退货保险赔偿
    }


if __name__ == '__main__':
    # 测试示例
    print("=== 正常商品 ===")
    T = 275.97
    G = 200.66
    P, profit = calc_price_with_min_profit(T, G)
    print(f"预估总额含运费: ${T}")
    print(f"货值总计: ${G}")
    print(f"建议售价: ${P}")
    print(f"预期利润: ${profit}")
    print()

    print("=== 低利润商品（利润< $10） ===")
    T = 66.01
    G = 49
    P, profit = calc_price_with_min_profit(T, G)
    print(f"预估总额含运费: ${T}")
    print(f"货值总计: ${G}")
    print(f"建议售价: ${P}")
    print(f"预期利润: ${profit}")
    print()

    # 完整明细
    breakdown = calc_breakdown(T, G)
    print("费用明细:")
    for k, v in breakdown.items():
        print(f"  {k}: ${v}")
