"""Product work status registry.

This module is the semantic source for product workbench status keys. It keeps
status metadata close to the product workflow domain without depending on API
routers or SQLAlchemy query construction.
"""

from __future__ import annotations

from dataclasses import dataclass


PRODUCT_WORK_STATUS_NEEDS_INITIALIZATION = "needs_initialization"
PRODUCT_WORK_STATUS_AUTO_SELECT_IMAGES = "auto_select_images"
PRODUCT_WORK_STATUS_SELECT_IMAGES = "select_images"
PRODUCT_WORK_STATUS_COMPETITOR_SEARCHING = "competitor_searching"
PRODUCT_WORK_STATUS_SELECT_COMPETITOR = "select_competitor"
PRODUCT_WORK_STATUS_CAPTURE_DETAIL = "capture_detail"
PRODUCT_WORK_STATUS_READY_TO_GENERATE = "ready_to_generate"
PRODUCT_WORK_STATUS_RUNNING = "running"
PRODUCT_WORK_STATUS_EXPORT_READY = "export_ready"
PRODUCT_WORK_STATUS_EXPORTED = "exported"
PRODUCT_WORK_STATUS_FAILED = "failed"

EXPORT_READY_UNEXPORTED_BUCKET = "export_ready_unexported"
EXPORT_READY_EXPORTED_BUCKET = "export_ready_exported"


@dataclass(frozen=True)
class ProductWorkStatusDefinition:
    key: str
    label: str
    short_label: str
    color: str
    overview_bucket: str
    is_list_filterable: bool
    is_workbench_bucket: bool
    frontend_visible: bool
    primary_metric: bool
    db_filter_name: str | None
    fact_source: str
    producer_note: str


PRODUCT_WORK_STATUS_DEFINITIONS: tuple[ProductWorkStatusDefinition, ...] = (
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_NEEDS_INITIALIZATION,
        label="Workflow 待初始化",
        short_label="待初始化",
        color="default",
        overview_bucket=PRODUCT_WORK_STATUS_NEEDS_INITIALIZATION,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=False,
        db_filter_name="needs_initialization",
        fact_source="products.workflow_node/workflow_status empty, excluding completed catalog facts",
        producer_note="Produced by build_product_workflow() for products without workflow fields and no stable E5 facts.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_AUTO_SELECT_IMAGES,
        label="自动选图中",
        short_label="自动选图",
        color="processing",
        overview_bucket=PRODUCT_WORK_STATUS_AUTO_SELECT_IMAGES,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=True,
        db_filter_name="auto_select_images",
        fact_source="products.workflow_node/status = auto_select_images/pending",
        producer_note="Represents queued automatic image selection before the async task is processing.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_SELECT_IMAGES,
        label="待确认商品图片",
        short_label="确认图片",
        color="cyan",
        overview_bucket=PRODUCT_WORK_STATUS_SELECT_IMAGES,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=True,
        db_filter_name="select_images",
        fact_source="products.workflow_node/status = select_images/*",
        producer_note="Manual image correction or legacy image confirmation bucket.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_COMPETITOR_SEARCHING,
        label="搜索候选竞品中",
        short_label="搜索中",
        color="processing",
        overview_bucket=PRODUCT_WORK_STATUS_COMPETITOR_SEARCHING,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=False,
        db_filter_name="competitor_searching",
        fact_source="search_competitor/processing or visual_match_competitors/processing",
        producer_note="Async competitor search or visual match is actively running.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
        label="待搜索/选择竞品",
        short_label="选竞品",
        color="purple",
        overview_bucket=PRODUCT_WORK_STATUS_SELECT_COMPETITOR,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=True,
        db_filter_name="select_competitor",
        fact_source="competitor workflow nodes that still need a final competitor path",
        producer_note="Includes auto_select_images/succeeded; that success means the product is ready for the competitor stage.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
        label="抓取竞品详情中",
        short_label="抓详情",
        color="processing",
        overview_bucket=PRODUCT_WORK_STATUS_CAPTURE_DETAIL,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=False,
        db_filter_name="capture_detail",
        fact_source="visual/detail capture workflow nodes before final competitor facts are complete",
        producer_note="Represents the candidate detail capture area, including enabled and not-yet-enabled paths.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_READY_TO_GENERATE,
        label="待自动生成 Listing",
        short_label="待自动生成",
        color="warning",
        overview_bucket=PRODUCT_WORK_STATUS_READY_TO_GENERATE,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=True,
        db_filter_name="ready_to_generate",
        fact_source="competitor/detail/image-analysis/listing workflow facts before flow_done",
        producer_note="Product has enough upstream facts for image analysis or listing generation to continue.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_RUNNING,
        label="生成中",
        short_label="生成中",
        color="processing",
        overview_bucket=PRODUCT_WORK_STATUS_RUNNING,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=True,
        db_filter_name="running",
        fact_source="processing workflow nodes owned by product task actions",
        producer_note="Task execution details stay in task center; this bucket only says the business workflow is running.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_EXPORT_READY,
        label="待导出",
        short_label="待导出",
        color="success",
        overview_bucket=EXPORT_READY_UNEXPORTED_BUCKET,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=True,
        db_filter_name="export_ready_unexported",
        fact_source="Product.status=completed + CatalogProduct.confirmed_at + no export evidence",
        producer_note="Stable E5 business fact; not inferred from a single workflow node alone.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_EXPORTED,
        label="已导出可重导",
        short_label="已导出",
        color="green",
        overview_bucket=EXPORT_READY_EXPORTED_BUCKET,
        is_list_filterable=True,
        is_workbench_bucket=False,
        frontend_visible=True,
        primary_metric=False,
        db_filter_name="exported",
        fact_source="Product.status=completed + CatalogProduct.confirmed_at + exported_at/export_task_id",
        producer_note="Derived list status for completed products with export evidence; overview uses export_ready_exported.",
    ),
    ProductWorkStatusDefinition(
        key=PRODUCT_WORK_STATUS_FAILED,
        label="失败",
        short_label="失败",
        color="error",
        overview_bucket=PRODUCT_WORK_STATUS_FAILED,
        is_list_filterable=True,
        is_workbench_bucket=True,
        frontend_visible=True,
        primary_metric=True,
        db_filter_name="failed",
        fact_source="failed workflow projection or legacy failed products without upstream facts",
        producer_note="Failed nodes that still project into recoverable competitor/detail buckets are excluded by the API predicate.",
    ),
)

PRODUCT_WORK_STATUS_BY_KEY = {definition.key: definition for definition in PRODUCT_WORK_STATUS_DEFINITIONS}

PRODUCT_WORK_STATUS_KEYS = tuple(definition.key for definition in PRODUCT_WORK_STATUS_DEFINITIONS)
PRODUCT_WORKBENCH_STATUS_KEYS = tuple(
    definition.key for definition in PRODUCT_WORK_STATUS_DEFINITIONS if definition.is_workbench_bucket
)
PRODUCT_LIST_FILTER_STATUS_KEYS = tuple(
    definition.key for definition in PRODUCT_WORK_STATUS_DEFINITIONS if definition.is_list_filterable
)
PRODUCT_FRONTEND_VISIBLE_STATUS_KEYS = tuple(
    definition.key for definition in PRODUCT_WORK_STATUS_DEFINITIONS if definition.frontend_visible
)
PRODUCT_PRIMARY_STATUS_KEYS = tuple(
    definition.key for definition in PRODUCT_WORK_STATUS_DEFINITIONS if definition.primary_metric
)
PRODUCT_OVERVIEW_BUCKET_KEYS = tuple(
    dict.fromkeys(definition.overview_bucket for definition in PRODUCT_WORK_STATUS_DEFINITIONS)
)

LEGACY_DIAGNOSTIC_WORK_STATUS_KEYS = ("interrupted", "suspended", "manual_review")


def get_product_work_status_definition(key: str) -> ProductWorkStatusDefinition:
    try:
        return PRODUCT_WORK_STATUS_BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"Unknown ProductWorkStatus: {key}") from exc


def is_product_work_status(key: str) -> bool:
    return key in PRODUCT_WORK_STATUS_BY_KEY
