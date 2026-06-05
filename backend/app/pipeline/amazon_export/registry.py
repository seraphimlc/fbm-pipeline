from __future__ import annotations

from collections.abc import Callable

from app.pipeline.amazon_export.context import AmazonExportContext
from app.pipeline.amazon_export.strategies.bicycle import apply_bicycle_strategy
from app.pipeline.amazon_export.strategies.ride_on_toy import apply_ride_on_toy_strategy
from app.pipeline.amazon_export.strategies.sofa_chair import apply_sofa_chair_strategy
from app.pipeline.amazon_export.strategies.storage_furniture import apply_storage_furniture_strategy

Strategy = Callable[[AmazonExportContext], None]

STRATEGIES: dict[str, Strategy] = {
    "sofa_chair": apply_sofa_chair_strategy,
    "bicycle": apply_bicycle_strategy,
    "ride_on_toy": apply_ride_on_toy_strategy,
    "home_storage_furniture": apply_storage_furniture_strategy,
    "shelf_table_cabinet_gate": apply_storage_furniture_strategy,
}


def strategy_key_for_mapping(mapping: dict) -> str:
    return str(mapping.get("strategy_family") or mapping.get("category_type") or "sofa_chair")


def get_strategy(mapping: dict) -> Strategy:
    key = strategy_key_for_mapping(mapping)
    try:
        return STRATEGIES[key]
    except KeyError as exc:
        raise ValueError(f"未注册 Amazon 导出模板策略: {key}") from exc

