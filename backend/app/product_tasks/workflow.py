"""Amazon product workflow projection and write helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.status import (
    AMAZON_WORKFLOW_NODES,
    AMAZON_WORKFLOW_STATUSES,
    WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_GET_STYLESNAP_TOKEN,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_NODE_SEARCH_COMPETITOR,
    WORKFLOW_NODE_SELECT_COMPETITOR,
    WORKFLOW_NODE_SELECT_IMAGES,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_SUCCEEDED,
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
    WORKFLOW_NODE_SELECT_IMAGES: WorkflowNodeView(
        label="选择图片",
        node_type="sync",
        default_work_status="select_images",
        default_primary_action="open_image_review",
        default_primary_action_label="确认图片",
        default_allowed_actions=("open_image_review",),
        default_action_reason="需要先确认主图和 Listing 图片",
        default_color="cyan",
    ),
    WORKFLOW_NODE_GET_STYLESNAP_TOKEN: WorkflowNodeView(
        label="获取 StyleSnap token",
        node_type="sync",
        default_work_status="select_competitor",
        default_primary_action="open_competitor_review",
        default_primary_action_label="处理 token",
        default_allowed_actions=("open_competitor_review",),
        default_action_reason="需要先处理 StyleSnap token 或浏览器上下文",
        default_color="warning",
    ),
    WORKFLOW_NODE_SEARCH_COMPETITOR: WorkflowNodeView(
        label="搜索竞品",
        node_type="semi_sync",
        default_work_status="select_competitor",
        default_primary_action="open_competitor_review",
        default_primary_action_label="搜索竞品",
        default_allowed_actions=("open_competitor_review",),
        default_action_reason="需要搜索 Amazon 参考竞品",
        default_color="purple",
    ),
    WORKFLOW_NODE_SELECT_COMPETITOR: WorkflowNodeView(
        label="选择竞品",
        node_type="sync",
        default_work_status="select_competitor",
        default_primary_action="open_competitor_review",
        default_primary_action_label="选竞品",
        default_allowed_actions=("open_competitor_review",),
        default_action_reason="需要选择参考竞品",
        default_color="purple",
    ),
    WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL: WorkflowNodeView(
        label="抓取竞品详情",
        node_type="async",
        default_work_status="capture_detail",
        default_primary_action="open_competitor_review",
        default_primary_action_label="查看竞品",
        default_allowed_actions=("open_competitor_review",),
        default_action_reason="正在抓取已选竞品详情",
        default_color="processing",
    ),
    WORKFLOW_NODE_IMAGE_ANALYSIS: WorkflowNodeView(
        label="图片分析",
        node_type="async",
        default_work_status="running",
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="图片分析正在执行或等待执行",
        default_color="processing",
    ),
    WORKFLOW_NODE_LISTING_GENERATION: WorkflowNodeView(
        label="Listing 生成",
        node_type="async",
        default_work_status="running",
        default_primary_action="open_task_center",
        default_primary_action_label="任务中心",
        default_allowed_actions=("open_task_center",),
        default_action_reason="Listing 生成正在执行或等待执行",
        default_color="processing",
    ),
    WORKFLOW_NODE_FLOW_DONE: WorkflowNodeView(
        label="主流程完成",
        node_type="done",
        default_work_status="export_ready",
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
        return _state(
            product,
            stage="workflow_uninitialized",
            stage_status=WORKFLOW_STATUS_PENDING,
            label="Workflow 待初始化",
            work_status="needs_initialization",
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
            work_status="failed",
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
            work_status="failed",
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
    overrides = _status_overrides(node, status)
    if catalog_exported and node == WORKFLOW_NODE_FLOW_DONE and status == WORKFLOW_STATUS_SUCCEEDED:
        overrides = {
            **overrides,
            "label": "铺货内容已导出",
            "work_status": "exported",
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
        action_reason=error or overrides.get("action_reason", view.default_action_reason),
        color=overrides.get("color", view.default_color),
    )


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

    related_correlation_key = None
    product_id = getattr(product, "id", None)
    if product_id and stage == WORKFLOW_NODE_IMAGE_ANALYSIS:
        related_correlation_key = f"product:{product_id}:image_analysis"
    elif product_id and stage == WORKFLOW_NODE_LISTING_GENERATION:
        related_correlation_key = f"product:{product_id}:listing_generation"

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


def _status_overrides(node: str, status: str) -> dict[str, Any]:
    if status == WORKFLOW_STATUS_FAILED:
        return _failed_overrides(node)

    if node == WORKFLOW_NODE_SEARCH_COMPETITOR and status == WORKFLOW_STATUS_PROCESSING:
        return {
            "label": "竞品搜索中",
            "work_status": "competitor_searching",
            "primary_action": "open_competitor_review",
            "primary_action_label": "查看搜索",
            "allowed_actions": ("open_competitor_review",),
            "action_reason": "正在用主图搜索 Amazon 参考竞品",
            "color": "processing",
        }
    if node == WORKFLOW_NODE_SEARCH_COMPETITOR and status == WORKFLOW_STATUS_SUCCEEDED:
        return {
            "label": "待选择竞品",
            "work_status": "select_competitor",
            "primary_action": "open_competitor_review",
            "primary_action_label": "选竞品",
            "allowed_actions": ("open_competitor_review",),
            "action_reason": "竞品搜索已完成，需要选择参考竞品",
            "color": "purple",
        }
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL and status == WORKFLOW_STATUS_PENDING:
        return {"label": "待抓取竞品详情", "color": "warning", "action_reason": "已选择竞品，等待抓取详情"}
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "竞品详情已抓取", "work_status": "ready_to_generate", "color": "success"}
    if node == WORKFLOW_NODE_IMAGE_ANALYSIS and status == WORKFLOW_STATUS_PENDING:
        return {"label": "待图片分析", "work_status": "ready_to_generate", "color": "warning"}
    if node == WORKFLOW_NODE_IMAGE_ANALYSIS and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "图片分析完成", "work_status": "ready_to_generate", "color": "success"}
    if node == WORKFLOW_NODE_LISTING_GENERATION and status == WORKFLOW_STATUS_PENDING:
        return {"label": "待生成 Listing", "work_status": "ready_to_generate", "color": "warning"}
    if node == WORKFLOW_NODE_LISTING_GENERATION and status == WORKFLOW_STATUS_SUCCEEDED:
        return {"label": "Listing 完成", "work_status": "export_ready", "color": "success"}
    if node == WORKFLOW_NODE_FLOW_DONE and status == WORKFLOW_STATUS_SUCCEEDED:
        return {
            "label": "铺货内容已生成",
            "work_status": "export_ready",
            "primary_action": "open_detail",
            "primary_action_label": "查看",
            "allowed_actions": (),
            "action_reason": "Amazon 主流程已完成，导出属于后续阶段",
            "color": "success",
        }
    return {}


def _failed_overrides(node: str) -> dict[str, Any]:
    if node == WORKFLOW_NODE_SEARCH_COMPETITOR:
        return {
            "label": "竞品搜索失败",
            "work_status": "select_competitor",
            "primary_action": "retry_competitor_search",
            "primary_action_label": "重新搜索",
            "allowed_actions": ("retry_competitor_search", "open_competitor_review"),
            "action_reason": "竞品搜索失败，可重新搜索",
            "color": "error",
        }
    if node == WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL:
        return {
            "label": "竞品详情抓取失败",
            "work_status": "select_competitor",
            "primary_action": "retry_competitor_capture",
            "primary_action_label": "重新抓取",
            "allowed_actions": ("retry_competitor_capture", "change_competitor", "open_competitor_review"),
            "action_reason": "竞品详情抓取失败，可重新抓取或更换竞品",
            "color": "error",
        }
    if node == WORKFLOW_NODE_IMAGE_ANALYSIS:
        return {
            "label": "图片分析失败",
            "work_status": "failed",
            "primary_action": "retry_image_analysis",
            "primary_action_label": "重试图片分析",
            "allowed_actions": ("retry_image_analysis",),
            "action_reason": "图片分析失败，可重试图片分析",
            "color": "error",
        }
    if node == WORKFLOW_NODE_LISTING_GENERATION:
        return {
            "label": "Listing 失败",
            "work_status": "failed",
            "primary_action": "retry_listing_generation",
            "primary_action_label": "重试 Listing",
            "allowed_actions": ("retry_listing_generation",),
            "action_reason": "Listing 生成失败，可重试 Listing",
            "color": "error",
        }
    return {
        "label": f"{WORKFLOW_NODE_VIEWS[node].label}失败",
        "work_status": "failed",
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
