#!/usr/bin/env python3
"""Focused R1 workflow action checks; DB behavior runs on isolated SQLite by default."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _enable_backend_imports() -> None:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def _product(node: str, status: str, *, error: str | None = None, product_id: int = 701) -> SimpleNamespace:
    return SimpleNamespace(
        id=product_id,
        status="failed" if status == "failed" else "processing",
        workflow_node=node,
        workflow_status=status,
        workflow_error=error,
        workflow_updated_at=None,
        error_message="自动竞品搜索" if node == "search_competitor" else None,
        catalog_item=None,
        images=None,
        data=None,
    )


def _actions(state: dict[str, Any]) -> set[str]:
    return {
        str(action)
        for action in [state.get("primary_action"), *(state.get("allowed_actions") or [])]
        if action
    }


def test_failed_navigation_and_messages() -> None:
    from app.models.status import (
        WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
        WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
        WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
        WORKFLOW_STATUS_FAILED,
    )
    from app.product_tasks.workflow import build_product_workflow

    target_failed_nodes = (
        WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
        WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
        WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
    )
    forbidden_failed_actions = {"retry_competitor_capture", "restart_competitor_search"}
    adapter_message = "当前版本尚未接入真实 Amazon 详情抓取，本商品已停止自动推进。"
    for node in target_failed_nodes:
        adapter_state = build_product_workflow(
            _product(node, WORKFLOW_STATUS_FAILED, error="adapter_not_configured: no real detail adapter")
        )
        normal_state = build_product_workflow(
            _product(node, WORKFLOW_STATUS_FAILED, error="RuntimeError: capture failed")
        )
        assert not (_actions(adapter_state) & forbidden_failed_actions), adapter_state
        assert not (_actions(normal_state) & forbidden_failed_actions), normal_state
        assert adapter_state["action_reason"] == adapter_message, adapter_state

        has_correlation = node in {
            WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
            WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
        }
        expected_primary = "open_task_center" if has_correlation else "open_detail"
        expected_reason = (
            "任务执行失败，可在任务中心查看原因。"
            if has_correlation
            else "任务执行失败，请在商品详情查看原因。"
        )
        assert normal_state["primary_action"] == expected_primary, normal_state
        assert normal_state["action_reason"] == expected_reason, normal_state
        assert bool(normal_state["related_correlation_key"]) is has_correlation, normal_state

    json_error_state = build_product_workflow(
        _product(
            WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
            WORKFLOW_STATUS_FAILED,
            error=json.dumps({"error_type": "adapter_not_configured", "message": "disabled"}),
        )
    )
    assert json_error_state["action_reason"] == adapter_message, json_error_state

    downstream_creation_state = build_product_workflow(
        _product(
            WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
            WORKFLOW_STATUS_FAILED,
            error=json.dumps({"code": "task_run_creation_failed", "message": "downstream planner failed"}),
        )
    )
    assert downstream_creation_state["primary_action"] == "open_detail", downstream_creation_state
    assert downstream_creation_state["related_correlation_key"] is None, downstream_creation_state
    assert downstream_creation_state["allowed_actions"] == ["open_detail"], downstream_creation_state


async def test_downstream_creation_failure_injection() -> None:
    from app.models.status import (
        WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
        WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
        WORKFLOW_STATUS_FAILED,
    )
    from app.product_tasks import actions as action_module
    from app.product_tasks.workflow import build_product_workflow

    class FakeDb:
        commits = 0
        rollbacks = 0

        async def commit(self) -> None:
            self.commits += 1

        async def rollback(self) -> None:
            self.rollbacks += 1

    product = _product("visual_match_competitors", "processing", product_id=702)
    product.status = "created"
    product.current_step = 2
    product.updated_at = None
    step = SimpleNamespace(id=902, task_run_id=901, task_run=SimpleNamespace(id=901, summary_json=None))
    result = {
        "product_id": product.id,
        "search_run_id": 801,
        "search_step_id": 802,
        "candidate_results": [{"candidate_id": 1, "selected_for_capture": True}],
        "selected_count": 1,
    }
    db = FakeDb()
    original_load = action_module._load_product
    original_write = action_module._write_visual_match_results
    original_clear_capture = action_module.clear_current_competitor_capture
    original_clear_selection = action_module.clear_current_auto_competitor_selection
    original_create = action_module.create_product_action_runs

    async def load_product(_db, _product_id):
        return product

    async def write_results(*args, **kwargs):
        return 1

    async def clear_noop(*args, **kwargs):
        return None

    async def fail_create(*args, **kwargs):
        raise RuntimeError("injected downstream create failure")

    try:
        action_module._load_product = load_product
        action_module._write_visual_match_results = write_results
        action_module.clear_current_competitor_capture = clear_noop
        action_module.clear_current_auto_competitor_selection = clear_noop
        action_module.create_product_action_runs = fail_create
        await action_module.ProductCompetitorVisualMatchAction().on_step_success(db, step, result)
    finally:
        action_module._load_product = original_load
        action_module._write_visual_match_results = original_write
        action_module.clear_current_competitor_capture = original_clear_capture
        action_module.clear_current_auto_competitor_selection = original_clear_selection
        action_module.create_product_action_runs = original_create

    error_payload = json.loads(product.workflow_error)
    assert error_payload["code"] == "task_run_creation_failed", error_payload
    assert "任务创建失败" in product.error_message, product.error_message
    state = build_product_workflow(product)
    assert state["stage"] == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, state
    assert state["stage_status"] == WORKFLOW_STATUS_FAILED, state
    assert state["primary_action"] == "open_detail", state
    assert state["related_correlation_key"] is None, state

    selection_product = _product(WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, "processing", product_id=703)
    selection_product.status = "created"
    selection_product.current_step = 2
    selection_product.updated_at = None
    selected_row = SimpleNamespace(id=11)
    selection_step = SimpleNamespace(id=912, task_run_id=911, task_run=SimpleNamespace(id=911, summary_json=None))
    selection_result = {
        "product_id": selection_product.id,
        "visual_task_run_id": 801,
        "visual_task_step_id": 802,
        "candidate_results": [
            {"candidate_id": selected_row.id, "status": "succeeded", "detail": {}, "raw": {}}
        ],
        "warnings": [],
    }
    original_current_rows = action_module._current_visual_selected_for_capture

    async def load_selection_product(_db, _product_id):
        return selection_product

    async def current_rows(*args, **kwargs):
        return [selected_row]

    try:
        action_module._load_product = load_selection_product
        action_module._current_visual_selected_for_capture = current_rows
        action_module.clear_current_auto_competitor_selection = clear_noop
        action_module.create_product_action_runs = fail_create
        await action_module.ProductCompetitorCandidateCaptureAction().on_step_success(
            db,
            selection_step,
            selection_result,
        )
    finally:
        action_module._load_product = original_load
        action_module._current_visual_selected_for_capture = original_current_rows
        action_module.clear_current_auto_competitor_selection = original_clear_selection
        action_module.create_product_action_runs = original_create

    selection_error = json.loads(selection_product.workflow_error)
    assert selection_error["code"] == "task_run_creation_failed", selection_error
    selection_state = build_product_workflow(selection_product)
    assert selection_state["stage"] == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR, selection_state
    assert selection_state["stage_status"] == WORKFLOW_STATUS_FAILED, selection_state
    assert selection_state["primary_action"] == "open_detail", selection_state
    assert selection_state["related_correlation_key"] is None, selection_state


def _backend_action_set() -> set[str]:
    from app.models.status import AMAZON_WORKFLOW_NODES, AMAZON_WORKFLOW_STATUSES, WORKFLOW_STATUS_FAILED
    from app.product_tasks.workflow import build_product_workflow

    actions: set[str] = set()
    for node in sorted(AMAZON_WORKFLOW_NODES):
        for status in sorted(AMAZON_WORKFLOW_STATUSES):
            error = "RuntimeError: failed" if status == WORKFLOW_STATUS_FAILED else None
            state = build_product_workflow(_product(node, status, error=error))
            actions.update(_actions(state))
    return actions


def _manifest() -> list[dict[str, Any]]:
    path = ROOT / "contracts" / "product_workflow_actions.json"
    assert path.is_file(), f"missing workflow action manifest: {path}"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, list) and value, "workflow action manifest must be a non-empty list"
    return value


@dataclass(frozen=True)
class ApiActionFamily:
    method: str
    route: str
    client_export: str
    actions: tuple[str, ...]


def _manifest_api_families() -> list[ApiActionFamily]:
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for definition in _manifest():
        if definition.get("kind") != "api":
            continue
        key = (
            str(definition.get("method") or "").upper(),
            str(definition.get("route") or ""),
            str(definition.get("client_export") or ""),
        )
        grouped[key].append(str(definition.get("action") or ""))
    return [
        ApiActionFamily(method, route, client_export, tuple(sorted(actions)))
        for (method, route, client_export), actions in sorted(grouped.items())
    ]


def test_manifest_closure_and_routes() -> None:
    manifest = _manifest()
    definitions = {str(item.get("action")): item for item in manifest}
    assert len(definitions) == len(manifest), "workflow action manifest contains duplicate actions"
    assert "retry_competitor_capture" not in definitions, definitions
    missing = _backend_action_set() - set(definitions)
    assert not missing, f"backend workflow actions missing from manifest: {sorted(missing)}"

    from app.main import app

    actual_routes = {
        (method.upper(), route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    for action, definition in definitions.items():
        kind = definition.get("kind")
        assert kind in {"api", "navigate"}, (action, definition)
        assert str(definition.get("default_label") or "").strip(), (action, definition)
        if kind == "api":
            expected = (str(definition.get("method") or "").upper(), str(definition.get("route") or ""))
            assert expected in actual_routes, f"manifest API route missing for {action}: {expected}"
            assert str(definition.get("client_export") or "").strip(), (action, definition)
        else:
            assert str(definition.get("target") or "").strip(), (action, definition)

    families = _manifest_api_families()
    assert len(families) == 5, families
    actions_by_route = {family.route: family.actions for family in families}
    assert actions_by_route == {
        "/api/products/{product_id}/auto-image-selection/retry": ("retry_auto_image_selection",),
        "/api/products/{product_id}/competitor-search/retry": (
            "restart_competitor_search",
            "retry_competitor_search",
            "start_competitor_search",
        ),
        "/api/products/{product_id}/competitor-visual-match/retry": ("retry_competitor_visual_match",),
        "/api/products/{product_id}/resume": ("resume",),
        "/api/products/{product_id}/retry": (
            "retry",
            "retry_image_analysis",
            "retry_listing_generation",
        ),
    }, actions_by_route


def _family_runtime_spec(route: str) -> dict[str, Any]:
    specs = {
        "/api/products/{product_id}/auto-image-selection/retry": {
            "task_type": "product_auto_image_selection",
            "correlation_suffix": "auto_image_selection",
            "initial_node": "auto_select_images",
            "success_status": "created",
            "success_step": 1,
            "success_node": "auto_select_images",
            "invalid_node": "select_images",
            "route_reuse": True,
        },
        "/api/products/{product_id}/competitor-search/retry": {
            "task_type": "product_competitor_search",
            "correlation_suffix": "competitor_search",
            "initial_node": "search_competitor",
            "success_status": "competitor_searching",
            "success_step": 2,
            "success_node": "search_competitor",
            "invalid_node": "auto_select_images",
            "needs_search_facts": True,
            "route_reuse": True,
        },
        "/api/products/{product_id}/competitor-visual-match/retry": {
            "task_type": "product_competitor_visual_match",
            "correlation_suffix": "competitor_visual_match",
            "initial_node": "visual_match_competitors",
            "success_status": "competitor_visual_matching",
            "success_step": 2,
            "success_node": "visual_match_competitors",
            "invalid_node": "search_competitor",
            "needs_successful_search": True,
            "route_reuse": True,
        },
        "/api/products/{product_id}/retry": {
            "task_type": "product_image_analysis",
            "correlation_suffix": "image_analysis",
            "initial_node": "image_analysis",
            "initial_product_status": "failed",
            "initial_step": 5,
            "success_status": "step6_curating",
            "success_step": 5,
            "success_node": "image_analysis",
            "invalid_node": "image_analysis",
            "needs_generation_facts": True,
        },
        "/api/products/{product_id}/resume": {
            "task_type": "product_image_analysis",
            "correlation_suffix": "image_analysis",
            "initial_node": "image_analysis",
            "initial_product_status": "paused",
            "initial_step": 5,
            "success_status": "step6_curating",
            "success_step": 5,
            "success_node": "image_analysis",
            "invalid_node": "image_analysis",
            "needs_generation_facts": True,
        },
    }
    assert route in specs, f"missing isolated SQLite family fixture for manifest route: {route}"
    return specs[route]


async def test_isolated_sqlite_route_and_correlation_behavior(environment) -> None:
    import httpx
    from sqlalchemy import func, select

    from app.main import app
    from app.models import Product, ProductData, ProductImage, TaskGroup, TaskRun, TaskStep
    from app.models.status import (
        WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
        WORKFLOW_STATUS_FAILED,
        WORKFLOW_STATUS_PENDING,
    )
    from app.product_tasks import actions as action_module
    from app.product_tasks.workflow import build_product_workflow, set_product_workflow

    original_kick = action_module.kick_task_runtime
    action_module.register_product_task_actions()
    action_module.kick_task_runtime = lambda: None
    try:
        families = _manifest_api_families()
        assert len(families) == 5, families
        fixtures: dict[str, tuple[int, int]] = {}
        async with environment.session_factory() as db:
            for index, family in enumerate(families, start=1):
                spec = _family_runtime_spec(family.route)
                product = Product(
                    gigab2b_url=f"https://example.invalid/r1-family-{index}",
                    gigab2b_product_id=f"R1-FAMILY-{index}",
                    competitor_asin="B0R1FIXTURE" if spec.get("needs_generation_facts") else None,
                    status=str(spec.get("initial_product_status") or "created"),
                    current_step=int(spec.get("initial_step") or 1),
                    error_message="R1 retry fixture" if spec.get("initial_product_status") in {"failed", "paused"} else None,
                )
                set_product_workflow(
                    product,
                    node=str(spec["initial_node"]),
                    status=WORKFLOW_STATUS_FAILED if spec.get("initial_product_status") in {"failed", "paused"} else WORKFLOW_STATUS_PENDING,
                    error="R1 retry fixture" if spec.get("initial_product_status") in {"failed", "paused"} else None,
                )
                if spec.get("needs_search_facts"):
                    product.data = ProductData(
                        item_code=f"R1-SEARCH-{index}",
                        title="Outdoor modular sofa for living room",
                        material="wood fabric",
                        features=json.dumps(["sectional", "adjustable"]),
                    )
                    product.images = ProductImage(main_image_path=f"/r1/search-{index}.jpg")
                elif spec.get("needs_generation_facts"):
                    product.data = ProductData(item_code=f"R1-GENERATE-{index}", title="R1 generation fixture")
                    product.images = ProductImage(main_image_path=f"/r1/generation-{index}.jpg")

                invalid_product = Product(
                    gigab2b_url=f"https://example.invalid/r1-family-{index}-invalid",
                    gigab2b_product_id=f"R1-FAMILY-{index}-INVALID",
                    status="created",
                    current_step=int(spec.get("initial_step") or 1),
                )
                set_product_workflow(
                    invalid_product,
                    node=str(spec["invalid_node"]),
                    status=WORKFLOW_STATUS_PENDING,
                    error=None,
                )
                db.add_all([product, invalid_product])
                await db.flush()

                if spec.get("needs_successful_search"):
                    search_run = TaskRun(
                        task_type="product_competitor_search",
                        title=f"R1 successful search for product {product.id}",
                        status="succeeded",
                        correlation_key=f"product:{product.id}:competitor_search",
                    )
                    db.add(search_run)
                    await db.flush()
                    search_group = TaskGroup(
                        task_run_id=search_run.id,
                        group_key="competitor_search",
                        title="R1 successful competitor search",
                        status="succeeded",
                    )
                    db.add(search_group)
                    await db.flush()
                    db.add(
                        TaskStep(
                            task_run_id=search_run.id,
                            task_group_id=search_group.id,
                            step_key=f"product:{product.id}:competitor_search",
                            step_type="product_competitor_search",
                            status="succeeded",
                        )
                    )

                fixtures[family.route] = (product.id, invalid_product.id)
            await db.commit()

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41321))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for family in families:
                spec = _family_runtime_spec(family.route)
                product_id, invalid_product_id = fixtures[family.route]
                path = family.route.replace("{product_id}", str(product_id))
                invalid_path = family.route.replace("{product_id}", str(invalid_product_id))

                created = await client.request(family.method, path)
                assert created.status_code == 200, (family, created.text)
                response = created.json()
                assert response["status"] == spec["success_status"], (family, response)
                assert response["current_step"] == spec["success_step"], (family, response)
                if response.get("workflow") is not None:
                    assert response["workflow"]["stage"] == spec["success_node"], (family, response)
                    assert response["workflow"]["stage_status"] == "processing", (family, response)
                else:
                    assert str(response.get("current_task_status") or "").strip(), (family, response)

                if spec.get("route_reuse"):
                    reused = await client.request(family.method, path)
                    assert reused.status_code == 200, (family, reused.text)

                correlation_key = f"product:{product_id}:{spec['correlation_suffix']}"
                async with environment.session_factory() as db:
                    run_rows = (
                        await db.execute(select(TaskRun).where(TaskRun.correlation_key == correlation_key))
                    ).scalars().all()
                    assert len(run_rows) == 1, (family, run_rows)
                    assert run_rows[0].task_type == spec["task_type"], (family, run_rows[0].task_type)
                    projected = await db.get(Product, product_id)
                    assert projected is not None
                    assert projected.status == spec["success_status"], (family, projected.status)
                    assert projected.current_step == spec["success_step"], (family, projected.current_step)
                    assert projected.workflow_node == spec["success_node"], (family, projected.workflow_node)
                    assert projected.workflow_status == "processing", (family, projected.workflow_status)

                    invalid_before = await db.get(Product, invalid_product_id)
                    assert invalid_before is not None
                    snapshot_before = (
                        invalid_before.workflow_node,
                        invalid_before.workflow_status,
                        invalid_before.workflow_error,
                        invalid_before.status,
                        invalid_before.current_step,
                    )
                    task_count_before = await db.scalar(select(func.count(TaskRun.id)))

                rejected = await client.request(family.method, invalid_path)
                assert 400 <= rejected.status_code < 500, (family, rejected.status_code, rejected.text)

                async with environment.session_factory() as db:
                    invalid_after = await db.get(Product, invalid_product_id)
                    assert invalid_after is not None
                    snapshot_after = (
                        invalid_after.workflow_node,
                        invalid_after.workflow_status,
                        invalid_after.workflow_error,
                        invalid_after.status,
                        invalid_after.current_step,
                    )
                    task_count_after = await db.scalar(select(func.count(TaskRun.id)))
                    assert snapshot_after == snapshot_before, (family, snapshot_before, snapshot_after)
                    assert task_count_after == task_count_before, (family, task_count_before, task_count_after)

            async with environment.session_factory() as db:
                missing_run_product = Product(
                    gigab2b_url="https://example.invalid/r1-no-downstream-run",
                    status="failed",
                    current_step=2,
                )
                set_product_workflow(
                    missing_run_product,
                    node=WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
                    status=WORKFLOW_STATUS_FAILED,
                    error=json.dumps({"code": "task_run_creation_failed", "message": "injected"}),
                )
                db.add(missing_run_product)
                await db.commit()
                await db.refresh(missing_run_product)
                missing_state = build_product_workflow(missing_run_product)
                assert missing_state["primary_action"] == "open_detail", missing_state
                assert missing_state["related_correlation_key"] is None, missing_state

                failed_run_product = Product(
                    gigab2b_url="https://example.invalid/r1-existing-failed-run",
                    status="failed",
                    current_step=2,
                )
                set_product_workflow(
                    failed_run_product,
                    node=WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
                    status=WORKFLOW_STATUS_FAILED,
                    error="RuntimeError: actual task failed",
                )
                db.add(failed_run_product)
                await db.flush()
                correlation_key = f"product:{failed_run_product.id}:competitor_candidate_capture"
                db.add(
                    TaskRun(
                        task_type="product_competitor_candidate_capture",
                        title="injected failed candidate capture",
                        status="failed",
                        correlation_key=correlation_key,
                    )
                )
                await db.commit()
                failed_state = build_product_workflow(failed_run_product)
                located_count = await db.scalar(
                    select(func.count(TaskRun.id)).where(TaskRun.correlation_key == correlation_key)
                )
                assert located_count == 1, located_count
                assert failed_state["primary_action"] == "open_task_center", failed_state
                assert failed_state["related_correlation_key"] == correlation_key, failed_state
    finally:
        action_module.kick_task_runtime = original_kick


def run_non_db_checks(*, backend_only: bool) -> None:
    _enable_backend_imports()
    test_failed_navigation_and_messages()
    asyncio.run(test_downstream_creation_failure_injection())
    if not backend_only:
        test_manifest_closure_and_routes()
        print("R1 workflow backend/manifest/route contract checks passed")
    else:
        print("R1 workflow backend projection and failure-injection checks passed")


async def run_sqlite_checks() -> None:
    from testing.r1_sqlite import isolated_r1_sqlite

    async with isolated_r1_sqlite(ROOT) as environment:
        test_failed_navigation_and_messages()
        await test_downstream_creation_failure_injection()
        test_manifest_closure_and_routes()
        await test_isolated_sqlite_route_and_correlation_behavior(environment)
        print(f"R1 isolated SQLite workflow checks passed: {environment.database_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-only", action="store_true")
    args = parser.parse_args()
    if args.backend_only:
        run_non_db_checks(backend_only=True)
    else:
        asyncio.run(run_sqlite_checks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
