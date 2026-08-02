#!/usr/bin/env python3
"""定价规则回归检查：覆盖最低利润线、目标利润率线和向上取美分。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.pipeline.step2_pricing import calculate_price  # noqa: E402


def _assert_close(actual: float, expected: float, *, tolerance: float = 0.01) -> None:
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"expected {expected}, got {actual}")


def test_minimum_profit_rule() -> None:
    # G=$100、S=$30：
    # C = 130 + 货值保险费 2.5 + 广告 2 - 平均赔付 (4% × 60% × 100) = 132.1。
    # 售价低于 $250，退货管理费是售价的 0.08%（4% × 10% × 20%）。
    # 最低利润线高于 5% 利润率线，价格需向上取到 $164.63。
    result = calculate_price(130.0, 100.0)
    assert result["suggested_price"] == 164.63
    assert result["breakdown"]["selected_rule"] == "min_profit"
    _assert_close(result["profit"], 10.0)
    assert result["profit_rate"] >= 5.0
    assert result["breakdown"]["insurance_cost"] == 2.5
    assert result["breakdown"]["advertising_cost"] == 2.0


def test_target_margin_rule() -> None:
    # 成本较高时，5% 目标净利率线高于 $10 最低利润线。
    result = calculate_price(200.0, 150.0)
    assert result["breakdown"]["selected_rule"] == "target_margin"
    assert result["suggested_price"] == 248.59
    assert result["profit_rate"] >= 5.0
    assert result["profit"] >= 10.0


def test_management_fee_cap() -> None:
    # 售价超过 $250 后，每笔退货管理费固定为 $5；平均成本为 4% × $5 = $0.20。
    result = calculate_price(300.0, 220.0)
    assert result["suggested_price"] == 371.53
    assert result["breakdown"]["return_management_fee"] == 0.2


def main() -> None:
    test_minimum_profit_rule()
    test_target_margin_rule()
    test_management_fee_cap()
    print("Step 2 pricing checks passed")


if __name__ == "__main__":
    main()
