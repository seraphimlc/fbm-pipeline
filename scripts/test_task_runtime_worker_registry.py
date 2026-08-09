#!/usr/bin/env python3
"""Verify every persisted product task type has an in-process worker."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.product_tasks.actions import PRODUCT_ACTION_TYPES, register_product_task_actions
from app.task_runtime.actions import all_actions
from app.task_runtime.registry import assert_workers_registered


def main() -> None:
    register_product_task_actions()
    registered_actions = set(all_actions())
    missing_actions = sorted(PRODUCT_ACTION_TYPES - registered_actions)
    if missing_actions:
        raise AssertionError(f"商品 TaskAction 未注册: {', '.join(missing_actions)}")
    assert_workers_registered(PRODUCT_ACTION_TYPES, scope="商品任务运行时回归测试")
    print(f"OK: {len(PRODUCT_ACTION_TYPES)} product task worker(s) registered")


if __name__ == "__main__":
    main()
