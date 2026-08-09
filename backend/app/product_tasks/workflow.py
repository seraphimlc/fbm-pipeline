"""Amazon product workflow projection and write helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.pipeline.customer_mindset import load_customer_mindset
from app.models.status import (
    AMAZON_WORKFLOW_NODES,
    AMAZON_WORKFLOW_STATUSES,
    COMPLETED,
    FAILED,
    WORKFLOW_NODE_AUTO_SELECT_IMAGES,
    WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
    WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
    WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
    WORKFLOW_NODE_CUSTOMER_MINDSET,
    WORKFLOW_NODE_CONFIRM_IMAGES_APLUS,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_GENERATE_APLUS,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_KEYWORD_RESEARCH,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_NODE_PREPARE_MATERIALS,
    WORKFLOW_NODE_SEARCH_COMPETITOR,
    WORKFLOW_NODE_SELECT_COMPETITOR,
    WORKFLOW_NODE_SELECT_IMAGES,
    WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_SUCCEEDED,
)
from app.product_tasks.work_status import (
    PRODUCT_WORK_STATUS_AUTO_SELECT_IMAGES,
    PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
    PRODUCT_WORK_STATUS_CONFIRM_IMAGES_APLUS,
    PRODUCT_WORK_STATUS_COMPETITOR_SEARCHING,
    PRODUCT_WORK_STATUS_EXPORTED,
    PRODUCT_WORK_STATUS_EXPORT_READY,
    PRODUCT_WORK_STATUS_FAILED,
    PRODUCT_WORK_STATUS_NEEDS_INITIALIZATION,
    PRODUCT_WORK_STATUS_READY_TO_GENERATE,
    PRODUCT_WORK_STATUS_RUNNING,
    PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
    PRODUCT_WORK_STATUS_SELECT_IMAGES,
)


@dataclass(frozen=True)
class WorkflowNodeView:
    label: str
    node_type: str
    default_work_status: str
    default_primary_action: str | None
    default_primary_action_label: str | None
    default_allowed_actions: tuple[str, ...]
    default_action_reason: str
    default_color: str


WORKFLOW_NODE_VIEWS: dict[str, WorkflowNodeView] = {
    WORKFLOW_NODE_PREPARE_MATERIALS: WorkflowNodeView(
        label="准备供应商素材",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_AUTO_SELECT_IMAGES,
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="正在解析商品页并下载、解压、登记供应商素材包",
        default_color="processing",
    ),
    WORKFLOW_NODE_AUTO_SELECT_IMAGES: WorkflowNodeView(
        label="自动选图",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_RUNNING,
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="自动选图正在执行或等待执行",
        default_color="processing",
    ),
    WORKFLOW_NODE_SELECT_IMAGES: WorkflowNodeView(
        label="选择图片",
        node_type="sync",
        default_work_status=PRODUCT_WORK_STATUS_SELECT_IMAGES,
        default_primary_action="open_image_review",
        default_primary_action_label="确认图片",
        default_allowed_actions=("open_image_review",),
        default_action_reason="需要先确认主图和 Listing 图片",
        default_color="cyan",
    ),
    WORKFLOW_NODE_SEARCH_COMPETITOR: WorkflowNodeView(
        label="搜索竞品",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
        default_primary_action="start_competitor_search",
        default_primary_action_label="开始搜索",
        default_allowed_actions=("start_competitor_search", "open_detail"),
        default_action_reason="等待自动搜索 Amazon 参考竞品",
        default_color="purple",
    ),
    WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS: WorkflowNodeView(
        label="视觉初筛竞品",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
        default_primary_action="retry_competitor_visual_match",
        default_primary_action_label="开始视觉初筛",
        default_allowed_actions=("retry_competitor_visual_match", "restart_competitor_search", "open_detail"),
        default_action_reason="竞品搜索已完成，等待视觉初筛 Top 候选",
        default_color="warning",
    ),
    WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES: WorkflowNodeView(
        label="抓取候选竞品",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
        default_primary_action="open_detail",
        default_primary_action_label="查看",
        default_allowed_actions=("open_detail", "restart_competitor_search"),
        default_action_reason="视觉初筛已完成；候选详情抓取入口尚未启用，可查看商品或重新搜索竞品",
        default_color="warning",
    ),
    WORKFLOW_NODE_AUTO_SELECT_COMPETITOR: WorkflowNodeView(
        label="自动选竞品",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
        default_primary_action="open_detail",
        default_primary_action_label="查看",
        default_allowed_actions=("open_detail", "restart_competitor_search"),
        default_action_reason="自动选竞品入口尚未启用，可查看商品或重新搜索竞品",
        default_color="warning",
    ),
    WORKFLOW_NODE_KEYWORD_RESEARCH: WorkflowNodeView(
        label="关键词采集",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_READY_TO_GENERATE,
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="正在获取已选竞品的关键词，完成后才会进入图片分析和 Listing 生成",
        default_color="processing",
    ),
    WORKFLOW_NODE_SELECT_COMPETITOR: WorkflowNodeView(
        label="选择竞品",
        node_type="sync",
        default_work_status=PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
        default_primary_action="open_detail",
        default_primary_action_label="查看",
        default_allowed_actions=("open_detail",),
        default_action_reason="旧人工选择竞品入口已停用，等待自动竞品链路处理",
        default_color="purple",
    ),
    WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL: WorkflowNodeView(
        label="抓取竞品详情",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
        default_primary_action="open_detail",
        default_primary_action_label="查看",
        default_allowed_actions=("open_detail",),
        default_action_reason="正在抓取已选竞品详情",
        default_color="processing",
    ),
    WORKFLOW_NODE_IMAGE_ANALYSIS: WorkflowNodeView(
        label="图片分析",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_RUNNING,
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="图片分析正在执行或等待执行",
        default_color="processing",
    ),
    WORKFLOW_NODE_CUSTOMER_MINDSET: WorkflowNodeView(
        label="用户心智梳理",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_RUNNING,
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="正在结合商品事实、关键词、竞品和图片分析梳理用户心智",
        default_color="processing",
    ),
    WORKFLOW_NODE_LISTING_GENERATION: WorkflowNodeView(
        label="Listing 生成",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_RUNNING,
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="Listing 生成正在执行或等待执行",
        default_color="processing",
    ),
    WORKFLOW_NODE_GENERATE_APLUS: WorkflowNodeView(
        label="生成 A+ 图片",
        node_type="async",
        default_work_status=PRODUCT_WORK_STATUS_RUNNING,
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="Listing 已完成，正在生成 A+ 规划、脚本和图片",
        default_color="processing",
    ),
    WORKFLOW_NODE_CONFIRM_IMAGES_APLUS: WorkflowNodeView(
        label="确认图片与 A+",
        node_type="review",
        default_work_status=PRODUCT_WORK_STATUS_CONFIRM_IMAGES_APLUS,
        default_primary_action="confirm_product",
        default_primary_action_label="确认图片与 A+",
        default_allowed_actions=("confirm_product", "open_detail"),
        default_action_reason="A+ 图片已生成，请核对 Listing 图片和 A+ 后确认进入待导出",
        default_color="cyan",
    ),
    WORKFLOW_NODE_FLOW_DONE: WorkflowNodeView(
        label="主流程完成",
        node_type="done",
        default_work_status=PRODUCT_WORK_STATUS_EXPORT_READY,
        default_primary_action="open_detail",
        default_primary_action_label="查看",
        default_allowed_actions=(),
        default_action_reason="Amazon 主流程已完成，铺货内容已生成",
        default_color="success",
    ),
}


def set_product_workflow(
    product: Any,
    *,
    node: str,
    status: str,
    error: str | None = None,
    now: datetime | None = None,
) -> None:
    if node not in AMAZON_WORKFLOW_NODES:
        raise ValueError(f"Unsupported Amazon workflow node: {node}")
    if status not in AMAZON_WORKFLOW_STATUSES:
        raise ValueError(f"Unsupported Amazon workflow status: {status}")

    product.workflow_node = node
    product.workflow_status = status
    product.workflow_error = error
    product.workflow_updated_at = now or datetime.utcnow()


def build_product_workflow(product: Any, *, catalog_exported: bool | None = None) -> dict[str, Any]:
    node = getattr(product, "workflow_node", None)
    status = getattr(product, "workflow_status", None)
    error = _compact_error(getattr(product, "workflow_error", None))

    if not node or not status:
        legacy_error = _compact_error(getattr(product, "workflow_error", None) or getattr(product, "error_message", None))
        legacy_state = _legacy_empty_workflow_state(product, catalog_exported=catalog_exported, error=legacy_error)
        if legacy_state:
            return legacy_state
        return _state(
            product,
            stage="workflow_uninitialized",
            stage_status=WORKFLOW_STATUS_PENDING,
            label="Workflow 待初始化",
            work_status=PRODUCT_WORK_STATUS_NEEDS_INITIALIZATION,
            node_key=None,
            node_label="未初始化",
            node_type="uninitialized",
            node_status=None,
            primary_action="open_detail",
            primary_action_label="查看",
            allowed_actions=(),
            action_reason=error or "商品 workflow 字段为空，需要初始化或重新拉品",
            color="default",
        )

    if node not in AMAZON_WORKFLOW_NODES:
        return _state(
            product,
            stage="workflow_unknown",
            stage_status=WORKFLOW_STATUS_FAILED,
            label="Workflow 节点未知",
            work_status=PRODUCT_WORK_STATUS_FAILED,
            node_key=str(node),
            node_label="未知节点",
            node_type="unknown",
            node_status=str(status),
            primary_action="open_detail",
            primary_action_label="查看",
            allowed_actions=(),
            action_reason=f"未知 workflow 节点：{node}",
            color="error",
        )

    if status not in AMAZON_WORKFLOW_STATUSES:
        return _state(
            product,
            stage=node,
            stage_status=WORKFLOW_STATUS_FAILED,
            label="Workflow 状态未知",
            work_status=PRODUCT_WORK_STATUS_FAILED,
            node_key=node,
            node_label=WORKFLOW_NODE_VIEWS[node].label,
            node_type=WORKFLOW_NODE_VIEWS[node].node_type,
            node_status=str(status),
            primary_action="open_detail",
            primary_action_label="查看",
            allowed_actions=(),
            action_reason=f"未知 workflow 状态：{status}",
            color="error",
        )

    view = WORKFLOW_NODE_VIEWS[node]
    overrides = _status_overrides(product, node, status)
    if catalog_exported and node == WORKFLOW_NODE_FLOW_DONE and status == WORKFLOW_STATUS_SUCCEEDED:
        overrides = {
            **overrides,
            "label": "铺货内容已导出",
            "work_status": PRODUCT_WORK_STATUS_EXPORTED,
            "primary_action": "open_detail",
            "primary_action_label": "查看",
            "allowed_actions": (),
            "action_reason": "Amazon 主流程已完成，且已有导出记录",
            "color": "green",
        }
    return _state(
        product,
        stage=node,
        stage_status=status,
        label=overrides.get("label", _default_status_label(view.label, status)),
        work_status=overrides.get("work_status", view.default_work_status),
        node_key=node,
        node_label=view.label,
        node_type=view.node_type,
        node_status=status,
        primary_action=overrides.get("primary_action", view.default_primary_action),
        primary_action_label=overrides.get("primary_action_label", view.default_primary_action_label),
        allowed_actions=overrides.get("allowed_actions", view.default_allowed_actions),
        action_reason=_action_reason(
            node=node,
            status=status,
            error=error,
            overrides=overrides,
            default=view.default_action_reason,
        ),
        color=overrides.get("color", view.default_color),
    )


def _legacy_empty_workflow_state(
    product: Any,
    *,
    catalog_exported: bool | None,
    error: str | None,
) -> dict[str, Any] | None:
    """Project pre-workflow E5 facts without mutating stored workflow fields."""
    product_status = getattr(product, "status", None)
    catalog_item = getattr(product, "catalog_item", None)

    if product_status == COMPLETED and catalog_item and getattr(catalog_item, "confirmed_at", None):
        overrides = _status_overrides(product, WORKFLOW_NODE_FLOW_DONE, WORKFLOW_STATUS_SUCCEEDED)
        if catalog_exported:
            overrides = {
                **overrides,
                "label": "铺货内容已导出",
                "work_status": PRODUCT_WORK_STATUS_EXPORTED,
                "primary_action": "open_detail",
                "primary_action_label": "查看",
                "allowed_actions": (),
                "action_reason": "Amazon 主流程已完成，且已有导出记录",
                "color": "green",
            }
        return _state(
            product,
            stage=WORKFLOW_NODE_FLOW_DONE,
            stage_status=WORKFLOW_STATUS_SUCCEEDED,
            label=overrides.get("label", "铺货内容已生成"),
            work_status=overrides.get("work_status", PRODUCT_WORK_STATUS_EXPORT_READY),
            node_key=WORKFLOW_NODE_FLOW_DONE,
            node_label=WORKFLOW_NODE_VIEWS[WORKFLOW_NODE_FLOW_DONE].label,
            node_type=WORKFLOW_NODE_VIEWS[WORKFLOW_NODE_FLOW_DONE].node_type,
            node_status=WORKFLOW_STATUS_SUCCEEDED,
            primary_action=overrides.get("primary_action", "open_detail"),
            primary_action_label=overrides.get("primary_action_label", "查看"),
            allowed_actions=overrides.get("allowed_actions", ()),
            action_reason=error or overrides.get("action_reason", "Amazon 主流程已完成，导出属于后续阶段"),
            color=overrides.get("color", "success"),
        )

    if product_status != FAILED:
        return None

    node = _legacy_failed_workflow_node(product, error)
    if not node:
        return _state(
            product,
            stage="workflow_uninitialized",
            stage_status=WORKFLOW_STATUS_FAILED,
            label="流程失败",
            work_status=PRODUCT_WORK_STATUS_FAILED,
            node_key=None,
            node_label="未初始化",
            node_type="uninitialized",
            node_status=WORKFLOW_STATUS_FAILED,
            primary_action="open_detail",
            primary_action_label="查看",
            allowed_actions=(),
            action_reason=error or "商品失败，但 workflow 字段为空；请打开详情查看原因",
            color="error",
        )

    overrides = _failed_overrides(product, node)
    return _state(
        product,
        stage=node,
        stage_status=WORKFLOW_STATUS_FAILED,
        label=overrides.get("label", f"{WORKFLOW_NODE_VIEWS[node].label}失败"),
        work_status=overrides.get("work_status", PRODUCT_WORK_STATUS_FAILED),
        node_key=node,
        node_label=WORKFLOW_NODE_VIEWS[node].label,
        node_type=WORKFLOW_NODE_VIEWS[node].node_type,
        node_status=WORKFLOW_STATUS_FAILED,
        primary_action=overrides.get("primary_action", "open_detail"),
        primary_action_label=overrides.get("primary_action_label", "查看"),
        allowed_actions=overrides.get("allowed_actions", ()),
        action_reason=error or overrides.get("action_reason", f"{WORKFLOW_NODE_VIEWS[node].label}失败"),
        color=overrides.get("color", "error"),
    )


def _legacy_failed_workflow_node(product: Any, error: str | None) -> str | None:
    images = getattr(product, "images", None)
    data = getattr(product, "data", None)
    has_image_analysis = bool(images and getattr(images, "image_analysis", None))
    has_customer_mindset = False
    if data and getattr(data, "customer_mindset", None):
        try:
            has_customer_mindset = load_customer_mindset(
                data.customer_mindset,
                required=True,
            ) is not None
        except RuntimeError:
            has_customer_mindset = False
    has_listing_content = bool(data and getattr(data, "listing_title", None))
    if not has_image_analysis:
        return WORKFLOW_NODE_IMAGE_ANALYSIS
    if not has_customer_mindset:
        return WORKFLOW_NODE_CUSTOMER_MINDSET
    if not has_listing_content:
        return WORKFLOW_NODE_LISTING_GENERATION
    return None


TARGET_DETAIL_FAILURE_NODES = {
    WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES,
    WORKFLOW_NODE_AUTO_SELECT_COMPETITOR,
    WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
}


def _related_correlation_key(product: Any, node: str) -> str | None:
    product_id = getattr(product, "id", None)
    if not product_id:
        return None
    if (
        node in {WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES, WORKFLOW_NODE_AUTO_SELECT_COMPETITOR}
        and _workflow_error_code(product) == "task_run_creation_failed"
    ):
        return None
    if node == WORKFLOW_NODE_AUTO_SELECT_IMAGES:
        return f"product:{product_id}:auto_image_selection"
    if node == WORKFLOW_NODE_SEARCH_COMPETITOR and _is_auto_competitor_search(product):
        return f"product:{product_id}:competitor_search"
    if node == WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS:
        return f"product:{product_id}:competitor_visual_match"
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES:
        return f"product:{product_id}:competitor_candidate_capture"
    if node == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR:
        return f"product:{product_id}:auto_competitor_selection"
    if node == WORKFLOW_NODE_KEYWORD_RESEARCH:
        return f"product:{product_id}:keyword_research"
    if node == WORKFLOW_NODE_IMAGE_ANALYSIS:
        return f"product:{product_id}:image_analysis"
    if node == WORKFLOW_NODE_CUSTOMER_MINDSET:
        return f"product:{product_id}:customer_mindset"
    if node == WORKFLOW_NODE_LISTING_GENERATION:
        return f"product:{product_id}:listing_generation"
    return None


def _workflow_error_code(product: Any) -> str | None:
    raw = str(getattr(product, "workflow_error", "") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        for key in ("error_type", "code"):
            value = str(parsed.get(key) or "").strip()
            if value:
                return value
    tokens = re.findall(r"(?<![A-Za-z0-9_])[a-z][a-z0-9_]+(?![A-Za-z0-9_])", raw)
    return "adapter_not_configured" if "adapter_not_configured" in tokens else None


def _failed_detail_navigation_overrides(
    product: Any,
    node: str,
    *,
    label: str,
    work_status: str,
) -> dict[str, Any]:
    error_code = _workflow_error_code(product)
    open_task_center = bool(_related_correlation_key(product, node))
    if error_code == "adapter_not_configured":
        action_reason = "当前版本尚未接入真实 Amazon 详情抓取，本商品已停止自动推进。"
    elif open_task_center:
        action_reason = "任务执行失败，可在任务中心查看原因。"
    else:
        action_reason = "任务执行失败，请在商品详情查看原因。"
    return {
        "label": label,
        "work_status": work_status,
        "primary_action": "open_task_center" if open_task_center else "open_detail",
        "primary_action_label": "任务中心" if open_task_center else "查看",
        "allowed_actions": ("open_task_center", "open_detail") if open_task_center else ("open_detail",),
        "action_reason": action_reason,
        "color": "error",
    }


def _action_reason(
    *,
    node: str,
    status: str,
    error: str | None,
    overrides: dict[str, Any],
    default: str,
) -> str:
    if status == WORKFLOW_STATUS_FAILED and node in TARGET_DETAIL_FAILURE_NODES:
        return str(overrides.get("action_reason") or default)
    return error or str(overrides.get("action_reason") or default)


def _state(
    product: Any,
    *,
    stage: str,
    stage_status: str,
    label: str,
    work_status: str,
    node_key: str | None,
    node_label: str,
    node_type: str,
    node_status: str | None,
    primary_action: str | None,
    primary_action_label: str | None,
    allowed_actions: tuple[str, ...] | list[str],
    action_reason: str,
    color: str,
) -> dict[str, Any]:
    actions = ["open_detail", *list(allowed_actions)]
    if primary_action and primary_action not in actions:
        actions.append(primary_action)

    related_correlation_key = _related_correlation_key(product, stage)

    return {
        "stage": stage,
        "stage_status": stage_status,
        "label": label,
        "work_status": work_status,
        "primary_action": primary_action,
        "primary_action_label": primary_action_label,
        "allowed_actions": list(dict.fromkeys(actions)),
        "action_reason": action_reason,
        "color": color,
        "related_task_run_id": None,
        "related_correlation_key": related_correlation_key,
        "node_key": node_key,
        "node_label": node_label,
        "node_type": node_type,
        "node_status": node_status,
    }


def _status_overrides(product: Any, node: str, status: str) -> dict[str, Any]:
    if status == WORKFLOW_STATUS_FAILED:
        return _failed_overrides(product, node)

    if node == WORKFLOW_NODE_AUTO_SELECT_IMAGES and status == WORKFLOW_STATUS_PENDING:
        return {
            "label": "待自动选图",
            "work_status": PRODUCT_WORK_STATUS_AUTO_SELECT_IMAGES,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center",),
            "action_reason": "等待自动选出商品主图和 Listing 图片",
            "color": "warning",
        }
    if node == WORKFLOW_NODE_AUTO_SELECT_IMAGES and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "自动选图完成", "work_status": PRODUCT_WORK_STATUS_SELECT_COMPETITOR, "color": "success"}
    if node == WORKFLOW_NODE_SEARCH_COMPETITOR and status == WORKFLOW_STATUS_PROCESSING:
        if not _is_auto_competitor_search(product):
            return {
                "label": "竞品搜索中",
                "work_status": PRODUCT_WORK_STATUS_COMPETITOR_SEARCHING,
                "primary_action": "open_detail",
                "primary_action_label": "查看",
                "allowed_actions": ("open_detail",),
                "action_reason": "旧竞品搜索路径已停用，请按当前自动竞品搜索任务处理",
                "color": "processing",
            }
        return {
            "label": "竞品搜索中",
            "work_status": PRODUCT_WORK_STATUS_COMPETITOR_SEARCHING,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center", "open_detail"),
            "action_reason": "自动竞品搜索正在任务中心执行或等待执行",
            "color": "processing",
        }
    if node == WORKFLOW_NODE_SEARCH_COMPETITOR and status == WORKFLOW_STATUS_SUCCEEDED:
        return {
            "label": "竞品搜索完成",
            "work_status": PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
            "primary_action": "open_detail",
            "primary_action_label": "查看",
            "allowed_actions": ("open_detail",),
            "action_reason": "竞品搜索已完成",
            "color": "purple",
        }
    if node == WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS and status == WORKFLOW_STATUS_PENDING:
        return {
            "label": "待视觉初筛竞品",
            "work_status": PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
            "primary_action": "retry_competitor_visual_match",
            "primary_action_label": "开始视觉初筛",
            "allowed_actions": ("retry_competitor_visual_match", "restart_competitor_search", "open_detail"),
            "action_reason": "Amazon 搜索候选已保存，等待视觉初筛任务",
            "color": "warning",
        }
    if node == WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS and status == WORKFLOW_STATUS_PROCESSING:
        return {
            "label": "竞品视觉初筛中",
            "work_status": PRODUCT_WORK_STATUS_COMPETITOR_SEARCHING,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center", "open_detail"),
            "action_reason": "竞品视觉初筛正在任务中心执行或等待执行",
            "color": "processing",
        }
    if node == WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS and status == WORKFLOW_STATUS_SUCCEEDED:
        return {
            "label": "竞品视觉初筛完成",
            "work_status": PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
            "primary_action": "open_detail",
            "primary_action_label": "查看",
            "allowed_actions": ("open_detail",),
            "action_reason": "竞品视觉初筛已完成",
            "color": "success",
        }
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES and status == WORKFLOW_STATUS_PENDING:
        return {
            "label": "待抓取候选竞品",
            "work_status": PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
            "primary_action": "open_detail",
            "primary_action_label": "查看",
            "allowed_actions": ("open_detail", "restart_competitor_search"),
            "color": "warning",
            "action_reason": "视觉初筛 Top 候选已保存；候选详情抓取入口尚未启用",
        }
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES and status == WORKFLOW_STATUS_PROCESSING:
        return {
            "label": "候选竞品详情抓取中",
            "work_status": PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center", "open_detail"),
            "action_reason": "候选竞品详情正在任务中心执行或等待执行",
            "color": "processing",
        }
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "候选竞品详情已抓取", "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE, "color": "success"}
    if node == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR and status == WORKFLOW_STATUS_PENDING:
        return {
            "label": "待自动选竞品",
            "work_status": PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
            "primary_action": "open_detail",
            "primary_action_label": "查看",
            "allowed_actions": ("open_detail", "restart_competitor_search"),
            "action_reason": "候选详情已抓取；自动选竞品入口尚未启用",
            "color": "warning",
        }
    if node == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR and status == WORKFLOW_STATUS_PROCESSING:
        return {
            "label": "自动选竞品中",
            "work_status": PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center", "open_detail"),
            "action_reason": "自动选竞品正在任务中心执行或等待执行",
            "color": "processing",
        }
    if node == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "自动选竞品完成", "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE, "color": "success"}
    if node == WORKFLOW_NODE_KEYWORD_RESEARCH and status == WORKFLOW_STATUS_PENDING:
        return {
            "label": "待采集关键词",
            "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center",),
            "action_reason": "已选定参考竞品，等待采集关键词",
            "color": "warning",
        }
    if node == WORKFLOW_NODE_KEYWORD_RESEARCH and status == WORKFLOW_STATUS_PROCESSING:
        return {
            "label": "关键词采集中",
            "work_status": PRODUCT_WORK_STATUS_RUNNING,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center",),
            "action_reason": "正在通过卖家精灵反查关键词，必要时使用 LLM 兜底",
            "color": "processing",
        }
    if node == WORKFLOW_NODE_KEYWORD_RESEARCH and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "关键词采集完成", "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE, "color": "success"}
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL and status == WORKFLOW_STATUS_PENDING:
        return {"label": "待抓取竞品详情", "color": "warning", "action_reason": "已选择竞品，等待抓取详情"}
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "竞品详情已抓取", "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE, "color": "success"}
    if node == WORKFLOW_NODE_IMAGE_ANALYSIS and status == WORKFLOW_STATUS_PENDING:
        return {"label": "待图片分析", "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE, "color": "warning"}
    if node == WORKFLOW_NODE_IMAGE_ANALYSIS and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "图片分析完成", "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE, "color": "success"}
    if node == WORKFLOW_NODE_CUSTOMER_MINDSET and status == WORKFLOW_STATUS_PENDING:
        return {
            "label": "待梳理用户心智",
            "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center",),
            "action_reason": "图片分析已完成，等待梳理用户心智",
            "color": "warning",
        }
    if node == WORKFLOW_NODE_CUSTOMER_MINDSET and status == WORKFLOW_STATUS_PROCESSING:
        return {
            "label": "用户心智梳理中",
            "work_status": PRODUCT_WORK_STATUS_RUNNING,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center",),
            "action_reason": "正在生成固定核心问题、商品专属问题及证据化回答",
            "color": "processing",
        }
    if node == WORKFLOW_NODE_CUSTOMER_MINDSET and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "用户心智梳理完成", "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE, "color": "success"}
    if node == WORKFLOW_NODE_LISTING_GENERATION and status == WORKFLOW_STATUS_PENDING:
        return {"label": "待生成 Listing", "work_status": PRODUCT_WORK_STATUS_READY_TO_GENERATE, "color": "warning"}
    if node == WORKFLOW_NODE_LISTING_GENERATION and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "Listing 完成", "work_status": PRODUCT_WORK_STATUS_EXPORT_READY, "color": "success"}
    if node == WORKFLOW_NODE_FLOW_DONE and status == WORKFLOW_STATUS_SUCCEEDED:
        return {
            "label": "铺货内容已生成",
            "work_status": PRODUCT_WORK_STATUS_EXPORT_READY,
            "primary_action": "open_detail",
            "primary_action_label": "查看",
            "allowed_actions": (),
            "action_reason": "Amazon 主流程已完成，导出属于后续阶段",
            "color": "success",
        }
    return {}


def _failed_overrides(product: Any, node: str) -> dict[str, Any]:
    if node == WORKFLOW_NODE_PREPARE_MATERIALS:
        return {
            "label": "供应商素材准备失败",
            "work_status": PRODUCT_WORK_STATUS_FAILED,
            "primary_action": "retry_material_prepare",
            "primary_action_label": "重试素材准备",
            "allowed_actions": ("retry_material_prepare", "open_task_center"),
            "action_reason": "供应商素材准备失败，可在修复来源后重试",
            "color": "error",
        }
    if node == WORKFLOW_NODE_AUTO_SELECT_IMAGES:
        return {
            "label": "自动选图失败",
            "work_status": PRODUCT_WORK_STATUS_FAILED,
            "primary_action": "retry_auto_image_selection",
            "primary_action_label": "重试自动选图",
            "allowed_actions": ("retry_auto_image_selection", "manual_adjust_images"),
            "action_reason": "自动选图失败，可重试或手动调整图片",
            "color": "error",
        }
    if node == WORKFLOW_NODE_SEARCH_COMPETITOR:
        if not _is_auto_competitor_search(product):
            return {
                "label": "竞品搜索失败",
                "work_status": PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
            "primary_action": "open_detail",
            "primary_action_label": "查看",
            "allowed_actions": ("open_detail",),
            "action_reason": "旧竞品搜索路径已停用，请使用自动竞品搜索任务",
                "color": "error",
            }
        return {
            "label": "竞品搜索失败",
            "work_status": PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
            "primary_action": "retry_competitor_search",
            "primary_action_label": "重试 Amazon 搜索",
            "allowed_actions": ("retry_competitor_search", "open_detail"),
            "action_reason": "竞品搜索失败，可重试 Amazon 搜索或手动选择竞品",
            "color": "error",
        }
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL:
        return _failed_detail_navigation_overrides(
            product,
            node,
            label="竞品详情抓取失败",
            work_status=PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
        )
    if node == WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS:
        return {
            "label": "竞品视觉初筛失败",
            "work_status": PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
            "primary_action": "retry_competitor_visual_match",
            "primary_action_label": "重试视觉初筛",
            "allowed_actions": ("retry_competitor_visual_match", "restart_competitor_search", "open_detail"),
            "action_reason": "竞品视觉初筛失败，可重试视觉初筛或重新搜索竞品",
            "color": "error",
        }
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES:
        return _failed_detail_navigation_overrides(
            product,
            node,
            label="候选竞品详情抓取失败",
            work_status=PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
        )
    if node == WORKFLOW_NODE_AUTO_SELECT_COMPETITOR:
        return _failed_detail_navigation_overrides(
            product,
            node,
            label="自动选竞品失败",
            work_status=PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
        )
    if node == WORKFLOW_NODE_KEYWORD_RESEARCH:
        return {
            "label": "关键词采集失败",
            "work_status": PRODUCT_WORK_STATUS_FAILED,
            "primary_action": "retry_keyword_research",
            "primary_action_label": "重试关键词采集",
            "allowed_actions": ("retry_keyword_research", "open_task_center"),
            "action_reason": "关键词采集失败，可创建新的受控任务重试",
            "color": "error",
        }
    if node == WORKFLOW_NODE_IMAGE_ANALYSIS:
        return {
            "label": "图片分析失败",
            "work_status": PRODUCT_WORK_STATUS_FAILED,
            "primary_action": "retry_image_analysis",
            "primary_action_label": "重试图片分析",
            "allowed_actions": ("retry_image_analysis",),
            "action_reason": "图片分析失败，可重试图片分析",
            "color": "error",
        }
    if node == WORKFLOW_NODE_CUSTOMER_MINDSET:
        return {
            "label": "用户心智梳理失败",
            "work_status": PRODUCT_WORK_STATUS_FAILED,
            "primary_action": "open_task_center",
            "primary_action_label": "任务中心",
            "allowed_actions": ("open_task_center",),
            "action_reason": "用户心智梳理失败，请在任务中心查看原因并重试任务",
            "color": "error",
        }
    if node == WORKFLOW_NODE_LISTING_GENERATION:
        return {
            "label": "Listing 失败",
            "work_status": PRODUCT_WORK_STATUS_FAILED,
            "primary_action": "retry_listing_generation",
            "primary_action_label": "重试 Listing",
            "allowed_actions": ("retry_listing_generation",),
            "action_reason": "Listing 生成失败，可重试 Listing",
            "color": "error",
        }
    return {
        "label": f"{WORKFLOW_NODE_VIEWS[node].label}失败",
        "work_status": PRODUCT_WORK_STATUS_FAILED,
        "primary_action": "open_detail",
        "primary_action_label": "查看",
        "allowed_actions": (),
        "action_reason": f"{WORKFLOW_NODE_VIEWS[node].label}失败",
        "color": "error",
    }


def _default_status_label(node_label: str, status: str) -> str:
    suffix = {
        WORKFLOW_STATUS_PENDING: "待处理",
        WORKFLOW_STATUS_PROCESSING: "处理中",
        WORKFLOW_STATUS_SUCCEEDED: "完成",
        WORKFLOW_STATUS_FAILED: "失败",
    }.get(status, str(status))
    return f"{node_label}{suffix}"


def _compact_error(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) <= 180:
        return text
    return text[:177].rstrip() + "..."


def _is_auto_competitor_search(product: Any) -> bool:
    marker = "自动竞品搜索"
    return marker in str(getattr(product, "error_message", "") or "") or marker in str(getattr(product, "workflow_error", "") or "")
