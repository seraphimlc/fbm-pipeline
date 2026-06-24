#!/usr/bin/env python3
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
import importlib.util
import re


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from validate_template_mappings import merge_category_options  # noqa: E402
from app.pipeline.search_terms import SEARCH_TERMS_MAX_KEYWORDS, normalize_search_terms  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_category_conflict_only_overrides_conflict() -> None:
    first_mapping = {
        "browse_category_options": [
            {
                "product_type": "SOFA",
                "node": "sofas",
                "path": "Home > Furniture > Sofas",
                "markers": ["sofa"],
            },
            {
                "product_type": "CHAIR",
                "node": "chairs",
                "path": "Home > Furniture > Chairs",
                "markers": ["chair"],
            },
        ]
    }
    later_mapping = {
        "browse_category_options": [
            {
                "product_type": "SOFA",
                "node": "sofas",
                "path": "Home > Furniture > Sofas",
                "markers": ["updated sofa"],
            }
        ]
    }

    merged, overrides = merge_category_options([
        ("first", first_mapping),
        ("later", later_mapping),
    ])

    assert_true(len(merged) == 2, "非冲突类目应该保留")
    assert_true(len(overrides) == 1, "只有冲突类目应该产生覆盖事件")
    assert_true(merged["Home > Furniture > Sofas (sofas)"]["source"] == "later", "冲突类目应以后导入为准")
    assert_true(merged["Home > Furniture > Chairs (chairs)"]["source"] == "first", "非冲突类目不应被覆盖")


def test_template_mapping_changes_must_be_logged() -> None:
    project_rule = ROOT / ".cursor" / "rules" / "projectRule.mdc"
    agents_rule = ROOT / "AGENTS.md"
    change_log = ROOT / "docs" / "template-mapping-change-log.md"
    rule_text = project_rule.read_text(encoding="utf-8")
    agents_text = agents_rule.read_text(encoding="utf-8")
    log_text = change_log.read_text(encoding="utf-8")

    assert_true(change_log.is_file(), "必须保留类目导出文件映射修改专用记录文件")
    assert_true(
        "docs/template-mapping-change-log.md" in rule_text
        and "每次新增、删除或修改 Amazon 类目导出文件映射" in rule_text,
        "Project Rule 必须要求每次类目导出文件映射修改都追加记录",
    )
    assert_true(
        "docs/template-mapping-change-log.md" in agents_text
        and "类目导出文件映射修改记录" in agents_text,
        "AGENTS.md 必须同步记录类目导出文件映射修改规则，保证 Codex 换电脑后也能读到",
    )
    assert_true(
        "backend/app/pipeline/template_mappings/*.json" in log_text
        and "backend/app/pipeline/step10_amazon_template.py" in log_text,
        "类目映射修改记录必须覆盖映射 JSON 和 Step10 类目/字段逻辑",
    )


def test_real_asin_export_guard_is_present() -> None:
    products_py = ROOT / "backend" / "app" / "api" / "products.py"
    text = products_py.read_text(encoding="utf-8")
    assert_true("已有真实 ASIN" in text, "导出逻辑必须保留真实 ASIN 防重复导出提示")
    assert_true("不能再次导出 Amazon 导入表格" in text, "已有真实 ASIN 的商品必须禁止再次导出导入表格")


def test_amazon_workflow_t1_fields_and_enums_exist() -> None:
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    status_text = (ROOT / "backend" / "app" / "models" / "status.py").read_text(encoding="utf-8")

    for field in ("workflow_node", "workflow_status", "workflow_error", "workflow_updated_at"):
        assert_true(field in models_text, f"Product ORM 必须包含 Amazon workflow 字段: {field}")
        assert_true(f'("{field}",' in database_text, f"MySQL schema ensure 必须补齐 products.{field}")

    assert_true(
        "workflow_node: Mapped[str | None] = mapped_column(String(80))" in models_text
        and "workflow_status: Mapped[str | None] = mapped_column(String(40))" in models_text
        and "workflow_error: Mapped[str | None] = mapped_column(Text)" in models_text
        and "workflow_updated_at: Mapped[datetime | None] = mapped_column(DateTime)" in models_text,
        "Amazon workflow T1 字段类型必须按 PRD 使用 String/Text/DateTime nullable 字段",
    )
    assert_true(
        "workflow_version" not in models_text
        and "workflow_version" not in database_text
        and "workflow_version" not in status_text,
        "Amazon workflow V1 不允许新增 workflow_version",
    )

    code = r'''
from app.models.status import AMAZON_WORKFLOW_NODES, AMAZON_WORKFLOW_STATUSES

assert AMAZON_WORKFLOW_NODES == (
    "auto_select_images",
    "select_images",
    "search_competitor",
    "visual_match_competitors",
    "capture_competitor_candidates",
    "auto_select_competitor",
    "select_competitor",
    "capture_competitor_detail",
    "image_analysis",
    "listing_generation",
    "flow_done",
), AMAZON_WORKFLOW_NODES
assert AMAZON_WORKFLOW_STATUSES == (
    "pending",
    "processing",
    "succeeded",
    "failed",
), AMAZON_WORKFLOW_STATUSES
for forbidden in ("export", "catalog_export", "amazon_upload"):
    assert forbidden not in AMAZON_WORKFLOW_NODES, forbidden
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"Amazon workflow T1 枚举常量验证失败: {result.stderr or result.stdout}")
    assert_true(
        "AMAZON_WORKFLOW_NODES" in status_text
        and "AMAZON_WORKFLOW_STATUSES" in status_text
        and "WORKFLOW_NODE_SELECT_IMAGES" in status_text
        and "WORKFLOW_STATUS_PROCESSING" in status_text,
        "Amazon workflow node/status 必须集中定义在 backend/app/models/status.py",
    )


def test_amazon_workflow_t2_service_projection_and_write_rules() -> None:
    workflow_text = (ROOT / "backend" / "app" / "product_tasks" / "workflow.py").read_text(encoding="utf-8")
    work_status_text = (ROOT / "backend" / "app" / "product_tasks" / "work_status.py").read_text(encoding="utf-8")
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    product_flow_index = (ROOT / "docs" / "domain-index" / "product-flow.md").read_text(encoding="utf-8")

    assert_true(
        "def set_product_workflow(" in workflow_text
        and "def build_product_workflow(" in workflow_text
        and "WORKFLOW_NODE_VIEWS" in workflow_text
        and "AMAZON_WORKFLOW_NODES" in workflow_text
        and "AMAZON_WORKFLOW_STATUSES" in workflow_text,
        "Amazon workflow T2 必须在 backend/app/product_tasks/workflow.py 集中提供写入、投影和 node/action 映射",
    )
    assert_true(
        "product.workflow_node = node" in workflow_text
        and "product.workflow_status = status" in workflow_text
        and "product.workflow_error = error" in workflow_text
        and "product.workflow_updated_at = now or datetime.utcnow()" in workflow_text
        and ".commit(" not in workflow_text
        and ".flush(" not in workflow_text
        and "create_task" not in workflow_text
        and "TaskRun" not in workflow_text,
        "set_product_workflow 只能校验并写入 Product workflow 四字段，不得提交事务、创建任务或触发副作用",
    )
    assert_true(
        "return build_product_workflow(product, catalog_exported=catalog_exported)" in products_api_text
        and "def _workflow_state(" in products_api_text
        and "_apply_product_work_status_db_filter(query, select(func.count(Product.id)), body.work_status)" in products_api_text
        and '"workflow": workflow' in products_api_text
        and "detail.workflow = _workflow_state(product, catalog_exported=catalog_exported)" in products_api_text,
        "products.py 必须把 _workflow_state 收敛为 Product Workflow Service 薄 wrapper，并让列表/详情/work_status 同源；按筛选批量推进也必须走同源 DB predicate",
    )
    workflow_state_body = products_api_text.split("def _workflow_state(", 1)[1].split("\ndef _split_category_path", 1)[0]
    assert_true(
        "current_step" not in workflow_state_body
        and "error_message" not in workflow_state_body
        and "re.search" not in workflow_state_body,
        "_workflow_state 薄 wrapper 不能继续用 current_step/error_message 正则推导 Amazon 主流程节点",
    )
    assert_true(
        "workflow_uninitialized" in workflow_text
        and 'PRODUCT_WORK_STATUS_NEEDS_INITIALIZATION = "needs_initialization"' in work_status_text
        and "PRODUCT_WORK_STATUS_NEEDS_INITIALIZATION" in workflow_text
        and "商品 workflow 字段为空" in workflow_text,
        "普通空 workflow 字段必须投影为显式未初始化/需初始化状态",
    )
    assert_true(
        "def _legacy_empty_workflow_state(" in workflow_text
        and "product_status == COMPLETED and catalog_item and getattr(catalog_item, \"confirmed_at\", None)" in workflow_text
        and "def _legacy_failed_workflow_node(" in workflow_text
        and "has_image_analysis = bool(images and getattr(images, \"image_analysis\", None))" in workflow_text
        and "has_listing_content = bool(data and getattr(data, \"listing_title\", None))" in workflow_text
        and "retry_image_analysis" in workflow_text
        and "retry_listing_generation" in workflow_text,
        "Product Workflow Service 必须用 Catalog/Image/Listing 结构化事实只读兼容 E5 前历史空 workflow 投影",
    )
    assert_true(
        "error or \"\"" not in workflow_text
        and "current_step = int(getattr(product, \"current_step\"" not in workflow_text,
        "E5 历史空 workflow 兼容不得用 error_message 字符串或 current_step 猜测节点",
    )
    assert_true(
        "node_key: str | None = None" in schemas_text
        and "node_label: str | None = None" in schemas_text
        and "node_type: str | None = None" in schemas_text
        and "node_status: str | None = None" in schemas_text,
        "ProductWorkflowState 新增 node 字段必须保持可选，避免前端本轮必须同步改",
    )
    assert_true(
        '"export"' not in workflow_text
        and '"catalog_export"' not in workflow_text
        and "amazon_upload" not in workflow_text
        and "open_export_center" not in workflow_text,
        "Amazon workflow T2 node/action 映射不得新增导出、catalog export、Amazon upload 主流程节点或导出动作",
    )
    assert_true(
        "Product Workflow Service" in product_flow_index
        and "backend/app/product_tasks/workflow.py" in product_flow_index,
        "新增 Amazon workflow 核心 service 后必须同步 product-flow domain index",
    )

    code = r'''
from datetime import datetime
from types import SimpleNamespace
from app.api.products import _product_list_work_status
from app.product_tasks.workflow import build_product_workflow, set_product_workflow
from app.models.status import (
    COMPLETED,
    FAILED,
    WORKFLOW_NODE_AUTO_SELECT_IMAGES,
    WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_NODE_SEARCH_COMPETITOR,
    WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_SUCCEEDED,
)

product = SimpleNamespace(id=123, workflow_node=None, workflow_status=None, workflow_error=None, workflow_updated_at=None)
empty = build_product_workflow(product)
assert empty["stage"] == "workflow_uninitialized", empty
assert empty["work_status"] == "needs_initialization", empty

legacy_export_ready = SimpleNamespace(
    id=124,
    status=COMPLETED,
    current_step=0,
    workflow_node=None,
    workflow_status=None,
    workflow_error=None,
    workflow_updated_at=None,
    error_message=None,
    catalog_item=SimpleNamespace(confirmed_at=datetime(2026, 6, 18), exported_at=None, export_task_id=None),
)
legacy_export_ready_view = build_product_workflow(legacy_export_ready, catalog_exported=False)
assert legacy_export_ready_view["stage"] == WORKFLOW_NODE_FLOW_DONE, legacy_export_ready_view
assert legacy_export_ready_view["stage_status"] == WORKFLOW_STATUS_SUCCEEDED, legacy_export_ready_view
assert legacy_export_ready_view["work_status"] == "export_ready", legacy_export_ready_view
assert _product_list_work_status(legacy_export_ready) == "export_ready"

legacy_exported = SimpleNamespace(
    id=125,
    status=COMPLETED,
    current_step=0,
    workflow_node=None,
    workflow_status=None,
    workflow_error=None,
    workflow_updated_at=None,
    error_message=None,
    catalog_item=SimpleNamespace(confirmed_at=datetime(2026, 6, 18), exported_at=datetime(2026, 6, 18), export_task_id=10),
)
legacy_exported_view = build_product_workflow(legacy_exported, catalog_exported=True)
assert legacy_exported_view["stage"] == WORKFLOW_NODE_FLOW_DONE, legacy_exported_view
assert legacy_exported_view["work_status"] == "exported", legacy_exported_view
assert _product_list_work_status(legacy_exported) == "exported"

legacy_image_failed = SimpleNamespace(
    id=126,
    status=FAILED,
    current_step=0,
    workflow_node=None,
    workflow_status=None,
    workflow_error=None,
    workflow_updated_at=None,
    error_message="historical failure reason for display only",
    images=SimpleNamespace(image_analysis=None),
    data=SimpleNamespace(listing_title=None),
)
legacy_image_failed_view = build_product_workflow(legacy_image_failed)
assert legacy_image_failed_view["stage"] == WORKFLOW_NODE_IMAGE_ANALYSIS, legacy_image_failed_view
assert legacy_image_failed_view["work_status"] == "failed", legacy_image_failed_view
assert legacy_image_failed_view["primary_action"] == "retry_image_analysis", legacy_image_failed_view

legacy_listing_failed = SimpleNamespace(
    id=127,
    status=FAILED,
    current_step=0,
    workflow_node=None,
    workflow_status=None,
    workflow_error=None,
    workflow_updated_at=None,
    error_message="historical failure reason for display only",
    images=SimpleNamespace(image_analysis="{\"selling_points\": []}"),
    data=SimpleNamespace(listing_title=None),
)
legacy_listing_failed_view = build_product_workflow(legacy_listing_failed)
assert legacy_listing_failed_view["stage"] == WORKFLOW_NODE_LISTING_GENERATION, legacy_listing_failed_view
assert legacy_listing_failed_view["work_status"] == "failed", legacy_listing_failed_view
assert legacy_listing_failed_view["primary_action"] == "retry_listing_generation", legacy_listing_failed_view

now = datetime(2026, 6, 18, 9, 30, 0)
set_product_workflow(product, node=WORKFLOW_NODE_SEARCH_COMPETITOR, status=WORKFLOW_STATUS_PROCESSING, now=now)
assert product.workflow_node == WORKFLOW_NODE_SEARCH_COMPETITOR
assert product.workflow_status == WORKFLOW_STATUS_PROCESSING
assert product.workflow_error is None
assert product.workflow_updated_at == now
legacy_searching = build_product_workflow(product)
assert legacy_searching["primary_action"] == "open_detail", legacy_searching
assert legacy_searching["related_correlation_key"] is None, legacy_searching
product.error_message = "自动竞品搜索已加入任务中心队列"
searching = build_product_workflow(product)
assert searching["stage"] == WORKFLOW_NODE_SEARCH_COMPETITOR, searching
assert searching["work_status"] == "competitor_searching", searching
assert searching["node_key"] == WORKFLOW_NODE_SEARCH_COMPETITOR, searching
assert searching["node_type"] == "async", searching
assert searching["primary_action"] == "open_task_center", searching
assert searching["related_correlation_key"] == "product:123:competitor_search", searching

set_product_workflow(product, node=WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS, status=WORKFLOW_STATUS_PENDING, now=now)
visual_pending = build_product_workflow(product)
assert visual_pending["stage"] == WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS, visual_pending
assert visual_pending["work_status"] == "select_competitor", visual_pending
assert visual_pending["primary_action"] == "retry_competitor_visual_match", visual_pending
assert "restart_competitor_search" in visual_pending["allowed_actions"], visual_pending
assert visual_pending["related_correlation_key"] == "product:123:competitor_visual_match", visual_pending
assert "等待视觉初筛任务" in visual_pending["action_reason"], visual_pending

for node, action in [
    (WORKFLOW_NODE_AUTO_SELECT_IMAGES, "retry_auto_image_selection"),
    (WORKFLOW_NODE_CAPTURE_COMPETITOR_DETAIL, "retry_competitor_capture"),
    (WORKFLOW_NODE_IMAGE_ANALYSIS, "retry_image_analysis"),
    (WORKFLOW_NODE_LISTING_GENERATION, "retry_listing_generation"),
]:
    item = SimpleNamespace(id=456, workflow_node=node, workflow_status=WORKFLOW_STATUS_FAILED, workflow_error="boom")
    view = build_product_workflow(item)
    assert view["primary_action"] == action, view
    assert action in view["allowed_actions"], view
    assert view["action_reason"] == "boom", view

legacy_failed_search = SimpleNamespace(
    id=457,
    workflow_node=WORKFLOW_NODE_SEARCH_COMPETITOR,
    workflow_status=WORKFLOW_STATUS_FAILED,
    workflow_error="旧竞品搜索失败",
    error_message="旧竞品搜索失败",
)
legacy_failed_view = build_product_workflow(legacy_failed_search)
assert legacy_failed_view["primary_action"] == "open_detail", legacy_failed_view
assert "retry_competitor_search" not in legacy_failed_view["allowed_actions"], legacy_failed_view

auto_failed_search = SimpleNamespace(
    id=458,
    workflow_node=WORKFLOW_NODE_SEARCH_COMPETITOR,
    workflow_status=WORKFLOW_STATUS_FAILED,
    workflow_error="自动竞品搜索失败: captcha",
    error_message="自动竞品搜索失败: captcha",
)
auto_failed_view = build_product_workflow(auto_failed_search)
assert auto_failed_view["primary_action"] == "retry_competitor_search", auto_failed_view
assert "retry_competitor_search" in auto_failed_view["allowed_actions"], auto_failed_view

done = SimpleNamespace(id=789, workflow_node=WORKFLOW_NODE_FLOW_DONE, workflow_status=WORKFLOW_STATUS_SUCCEEDED, workflow_error=None)
done_view = build_product_workflow(done)
assert done_view["stage"] == WORKFLOW_NODE_FLOW_DONE, done_view
assert done_view["node_type"] == "done", done_view
assert done_view["primary_action"] == "open_detail", done_view
assert "export" not in done_view["stage"], done_view
assert "amazon_upload" not in done_view["allowed_actions"], done_view
exported_view = build_product_workflow(done, catalog_exported=True)
assert exported_view["stage"] == WORKFLOW_NODE_FLOW_DONE, exported_view
assert exported_view["work_status"] == "exported", exported_view
assert exported_view["node_type"] == "done", exported_view
assert exported_view["primary_action"] == "open_detail", exported_view
done.catalog_item = SimpleNamespace(exported_at=datetime(2026, 6, 18), export_task_id=10)
assert _product_list_work_status(done) == "exported"

try:
    set_product_workflow(product, node="export", status=WORKFLOW_STATUS_PROCESSING)
except ValueError:
    pass
else:
    raise AssertionError("invalid workflow node must fail")

try:
    set_product_workflow(product, node=WORKFLOW_NODE_SEARCH_COMPETITOR, status="queued")
except ValueError:
    pass
else:
    raise AssertionError("invalid workflow status must fail")
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"Amazon workflow T2 service 行为验证失败: {result.stderr or result.stdout}")


def test_product_work_status_producer_outputs_are_registered() -> None:
    code = r'''
from types import SimpleNamespace
from pathlib import Path

from app.api.products import PRODUCT_LIST_WORK_STATUS_KEYS, WORKBENCH_STATUS_KEYS
from app.api.schemas import WorkbenchOverview
from app.models.status import AMAZON_WORKFLOW_NODES, AMAZON_WORKFLOW_STATUSES
from app.product_tasks.work_status import (
    EXPORT_READY_EXPORTED_BUCKET,
    LEGACY_DIAGNOSTIC_WORK_STATUS_KEYS,
    PRODUCT_FRONTEND_VISIBLE_STATUS_KEYS,
    PRODUCT_LIST_FILTER_STATUS_KEYS,
    PRODUCT_OVERVIEW_BUCKET_KEYS,
    PRODUCT_PRIMARY_STATUS_KEYS,
    PRODUCT_WORK_STATUS_BY_KEY,
    PRODUCT_WORK_STATUS_EXPORTED,
    PRODUCT_WORK_STATUS_KEYS,
    PRODUCT_WORKBENCH_STATUS_KEYS,
)
from app.product_tasks.workflow import build_product_workflow

root = Path.cwd().parent
frontend_api_text = (root / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")
product_list_text = (root / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
frontend_overview_section = frontend_api_text.split("export interface WorkbenchOverview", 1)[1].split("export const", 1)[0]
work_status_type_section = product_list_text.split("type WorkStatus =", 1)[1].split("type ProductRow", 1)[0]
work_status_meta_section = product_list_text.split("const WORK_STATUS_META", 1)[1].split("const WORK_STATUS_FILTERS", 1)[0]
work_status_filter_section = product_list_text.split("const WORK_STATUS_FILTERS", 1)[1].split("const PRIMARY_WORK_STATUS", 1)[0]
primary_work_status_section = product_list_text.split("const PRIMARY_WORK_STATUS", 1)[1].split("const workStatusParam", 1)[0]

supported_statuses = set(PRODUCT_WORK_STATUS_KEYS)
overview_fields = set(WorkbenchOverview.model_fields)
produced_statuses = set()

def product(**overrides):
    base = dict(
        id=20260622,
        status="created",
        current_step=1,
        workflow_node=None,
        workflow_status=None,
        workflow_error=None,
        workflow_updated_at=None,
        error_message="自动竞品搜索 marker",
        catalog_item=None,
        images=None,
        data=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)

for node in AMAZON_WORKFLOW_NODES:
    for status in AMAZON_WORKFLOW_STATUSES:
        state = build_product_workflow(product(workflow_node=node, workflow_status=status))
        produced_statuses.add(state["work_status"])

produced_statuses.add(build_product_workflow(product())["work_status"])
produced_statuses.add(build_product_workflow(product(workflow_node="unknown_node", workflow_status="pending"))["work_status"])
produced_statuses.add(build_product_workflow(product(workflow_node=AMAZON_WORKFLOW_NODES[0], workflow_status="unknown"))["work_status"])
produced_statuses.add(build_product_workflow(product(status="completed", catalog_item=SimpleNamespace(confirmed_at=1)))["work_status"])
produced_statuses.add(build_product_workflow(
    product(status="completed", catalog_item=SimpleNamespace(confirmed_at=1)),
    catalog_exported=True,
)["work_status"])
produced_statuses.add(build_product_workflow(
    product(status="failed", images=SimpleNamespace(image_analysis=None), data=SimpleNamespace(listing_title=None)),
)["work_status"])
produced_statuses.add(build_product_workflow(
    product(status="failed", images=SimpleNamespace(image_analysis="{}"), data=SimpleNamespace(listing_title=None)),
)["work_status"])

unknown_statuses = produced_statuses - supported_statuses
assert not unknown_statuses, (unknown_statuses, produced_statuses, supported_statuses)
assert "ready_to_search_competitor" not in produced_statuses, produced_statuses

assert tuple(WORKBENCH_STATUS_KEYS) == tuple(PRODUCT_WORKBENCH_STATUS_KEYS), (WORKBENCH_STATUS_KEYS, PRODUCT_WORKBENCH_STATUS_KEYS)
assert tuple(PRODUCT_LIST_WORK_STATUS_KEYS) == tuple(PRODUCT_LIST_FILTER_STATUS_KEYS), (PRODUCT_LIST_WORK_STATUS_KEYS, PRODUCT_LIST_FILTER_STATUS_KEYS)
assert not (set(LEGACY_DIAGNOSTIC_WORK_STATUS_KEYS) & set(PRODUCT_WORK_STATUS_KEYS)), PRODUCT_WORK_STATUS_KEYS
assert not (set(LEGACY_DIAGNOSTIC_WORK_STATUS_KEYS) & set(PRODUCT_LIST_WORK_STATUS_KEYS)), PRODUCT_LIST_WORK_STATUS_KEYS

for status in produced_statuses:
    definition = PRODUCT_WORK_STATUS_BY_KEY[status]
    assert definition.overview_bucket in PRODUCT_OVERVIEW_BUCKET_KEYS, (status, PRODUCT_OVERVIEW_BUCKET_KEYS)
    if status == PRODUCT_WORK_STATUS_EXPORTED:
        assert definition.overview_bucket == EXPORT_READY_EXPORTED_BUCKET, definition
    assert definition.overview_bucket in overview_fields, (status, definition.overview_bucket, overview_fields)
    assert (
        f"{definition.overview_bucket}:" in frontend_overview_section
        or f"{definition.overview_bucket}?: number" in frontend_overview_section
    ), (status, definition.overview_bucket, frontend_overview_section)
    assert f"| '{status}'" in work_status_type_section, (status, work_status_type_section)
    assert f"{status}:" in work_status_meta_section, (status, work_status_meta_section)
    if definition.frontend_visible:
        assert status in PRODUCT_FRONTEND_VISIBLE_STATUS_KEYS, (status, PRODUCT_FRONTEND_VISIBLE_STATUS_KEYS)
    if definition.is_list_filterable:
        assert f"'{status}'" in work_status_filter_section, (status, work_status_filter_section)
    if definition.primary_metric:
        assert f"'{status}'" in primary_work_status_section, (status, primary_work_status_section)

for frontend_section in (
    frontend_overview_section,
    work_status_type_section,
    work_status_meta_section,
    work_status_filter_section,
):
    assert "ready_to_search_competitor" not in frontend_section, frontend_section

for legacy_status in LEGACY_DIAGNOSTIC_WORK_STATUS_KEYS:
    assert f"| '{legacy_status}'" in work_status_type_section, (legacy_status, work_status_type_section)
    assert f"{legacy_status}:" in work_status_meta_section, (legacy_status, work_status_meta_section)
    assert f"'{legacy_status}'" not in work_status_filter_section, (legacy_status, work_status_filter_section)
    assert f"{legacy_status}:" not in frontend_overview_section, (legacy_status, frontend_overview_section)

auto_select_done = build_product_workflow(product(workflow_node="auto_select_images", workflow_status="succeeded"))
assert auto_select_done["label"] == "自动选图完成", auto_select_done
assert auto_select_done["work_status"] == "select_competitor", auto_select_done
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"Product work_status 生产端/消费端闭包验证失败: {result.stderr or result.stdout}")


def test_product_overview_handles_uninitialized_workflow_bucket() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    workflow_text = (ROOT / "backend" / "app" / "product_tasks" / "workflow.py").read_text(encoding="utf-8")
    work_status_text = (ROOT / "backend" / "app" / "product_tasks" / "work_status.py").read_text(encoding="utf-8")
    overview_section = products_api_text.split('@router.get("/overview"', 1)[1].split('@router.get("/{product_id}"', 1)[0]

    assert_true(
        'PRODUCT_WORK_STATUS_NEEDS_INITIALIZATION = "needs_initialization"' in work_status_text
        and "WORKBENCH_STATUS_KEYS = PRODUCT_WORKBENCH_STATUS_KEYS" in products_api_text
        and "needs_initialization: int = 0" in schemas_text
        and 'needs_initialization=status_counts["needs_initialization"]' in overview_section,
        "overview 必须把空 workflow 投影的 needs_initialization 作为显式状态桶返回，不能 KeyError 或吞错",
    )
    assert_true(
        "Product.workflow_node" in overview_section
        and "Product.workflow_status" in overview_section
        and "Product.workflow_error" in overview_section
        and "Product.workflow_updated_at" in overview_section,
        "overview load_only 调用 _product_workbench_status 前必须预加载 workflow 字段，避免 SQLAlchemy async lazy-load/MissingGreenlet 风险",
    )
    assert_true(
        "node_type=\"done\"" in workflow_text
        and "node_type=\"terminal\"" not in workflow_text,
        "flow_done/succeeded 的 node_type 必须使用 PRD 口径 done，不能引入 terminal 等额外语义",
    )


def test_product_detail_uses_workflow_as_primary_display_source() -> None:
    product_detail_text = (ROOT / "frontend" / "src" / "pages" / "ProductDetail.tsx").read_text(encoding="utf-8")
    product_flow_index = (ROOT / "docs" / "domain-index" / "product-flow.md").read_text(encoding="utf-8")
    default_tab_section = product_detail_text.split("const defaultProductDetailTab", 1)[1].split("const ProductDetail", 1)[0]
    poll_section = product_detail_text.split("// 自动轮询：任务运行中时每3秒刷新", 1)[1].split(
        "  useEffect(() => {\n    if (!product) return;\n    if (listingImageDraftProductId",
        1,
    )[0]
    run_action_section = product_detail_text.split("const runWorkflowAction", 1)[1].split("const renderWorkflowActionButton", 1)[0]
    render_action_section = product_detail_text.split("const renderWorkflowActionButton", 1)[1].split("const workflowSecondaryActions", 1)[0]
    top_action_section = product_detail_text.split("<Button icon={<ReloadOutlined />} onClick={fetchDetail}>刷新</Button>", 1)[1].split('<Popconfirm\n            title="确定删除此商品？"', 1)[0]

    labels_match = re.search(
        r"const WORKFLOW_ACTION_LABELS:[^{]+{(?P<body>.*?)};\nconst EXECUTABLE_WORKFLOW_ACTIONS",
        product_detail_text,
        re.S,
    )
    assert_true(labels_match is not None, "ProductDetail 必须集中声明前端已接通的 workflow action label")
    executable_actions = set(re.findall(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", labels_match.group("body"), re.M))
    handled_actions = set(re.findall(r"action === '([^']+)'", run_action_section))
    assert_true(
        executable_actions <= handled_actions,
        f"ProductDetail 可执行 workflow action 必须都有真实 handler，缺失: {sorted(executable_actions - handled_actions)}",
    )

    assert_true(
        "const workflow = product.workflow || null" in product_detail_text
        and "const hasWorkflow = Boolean(workflow)" in product_detail_text,
        "ProductDetail 必须显式识别 product.workflow，不能只靠旧 status/current_step 推详情页状态",
    )
    assert_true(
        "const workflowPipelineSteps = hasWorkflow ? buildWorkflowPipelineSteps(workflow) : []" in product_detail_text
        and "const pipelineSteps = hasWorkflow ? workflowPipelineSteps : legacyPipelineSteps" in product_detail_text
        and "if (hasWorkflow) return workflowStageIndex(workflow)" in product_detail_text,
        "商品详情 stepper 必须在 workflow 存在时使用 workflow stage/work_status，不得被 legacy stepper/current_step 覆盖",
    )
    assert_true(
        "if (workStatus === 'ready_to_generate') return 6" in product_detail_text
        and "if (workStatus === 'export_ready' || workStatus === 'exported') return 7" in product_detail_text
        and "if (workStatus === 'capture_detail' && (workflow?.stage_status === 'succeeded' || directIndex < 3)) return 3" in product_detail_text,
        "ProductDetail stepper 必须让已推进的 work_status 工作桶覆盖上一节点 succeeded 展示位置",
    )
    assert_true(
        "if (workflow) {" in default_tab_section
        and "const workflowStage = workflow.stage || workflow.node_key" in default_tab_section
        and "const workflowWorkStatus = workflow.work_status" in default_tab_section
        and "['ready_to_generate', 'running', 'export_ready', 'exported'].includes(workflowWorkStatus)" in default_tab_section,
        "ProductDetail 默认 tab 必须优先依据 workflow stage/node_key/work_status，避免 staged 商品落回旧图片确认页",
    )
    assert_true(
        "const legacyProductIsRunning =" in poll_section
        and "const isRunning = (product.workflow ? workflowIsRunning : legacyProductIsRunning)" in poll_section,
        "ProductDetail 轮询条件在 workflow 存在时不能继续混入旧 product.status 运行态推断",
    )
    assert_true(
        "const isReadyToExport = hasWorkflow" in product_detail_text
        and "['export_ready', 'exported'].includes(workflow?.work_status || '')" in product_detail_text,
        "商品详情待导出口径必须优先读取 workflow.work_status，不能只看旧 completed/current_step",
    )
    assert_true(
        "{hasWorkflow && (" in product_detail_text
        and "workflow?.label || workflowWorkStatusMeta?.label" in product_detail_text
        and "{!hasWorkflow && product.status === 'paused'" in product_detail_text
        and "{!hasWorkflow && showTopProductError" in product_detail_text,
        "ProductDetail 顶部状态提示必须 workflow 优先；旧 paused/running/error 提示只能作为 legacy fallback",
    )
    assert_true(
        "EXECUTABLE_WORKFLOW_ACTIONS" in product_detail_text
        and "const isExecutableWorkflowAction" in product_detail_text
        and ".filter((action: string) => isExecutableWorkflowAction(action))" in product_detail_text,
        "ProductDetail 只能渲染当前前端已接通的 workflow action，不能把未知 action 显示成无效按钮",
    )
    assert_true(
        "if (!isExecutableWorkflowAction(action)) return null;" in render_action_section
        and "{hasWorkflow && renderWorkflowActionButton(workflow?.primary_action, workflow?.primary_action_label, true)}" in top_action_section,
        "ProductDetail primary workflow action 也必须经过可执行白名单，未知 action 不能显示成假按钮",
    )
    for legacy_button_guard in (
        "{!hasWorkflow && product.status === 'failed'",
        "{!hasWorkflow && product.status === 'paused'",
        "{!hasWorkflow && product.status === 'pending_review'",
        "{!hasWorkflow && canGenerateMissingListing",
        "{!hasWorkflow && isInterruptedProduct",
        "{!hasWorkflow && isPipelineRunning",
        "{!hasWorkflow && canSuspendProduct",
        "{!hasWorkflow && canRestartProduct",
    ):
        assert_true(
            legacy_button_guard in top_action_section,
            f"ProductDetail 顶部旧主动作必须只作为无 workflow fallback: {legacy_button_guard}",
        )
    assert_true(
        "ProductDetail.tsx" in product_flow_index
        and "product.workflow" in product_flow_index
        and "legacy fallback" in product_flow_index,
        "ProductDetail workflow 展示事实源变化必须同步 product-flow domain index",
    )


def test_amazon_workflow_t3_image_selection_reset_and_initialization_rules() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    giga_product_drafts_text = (ROOT / "backend" / "app" / "services" / "giga_product_drafts.py").read_text(encoding="utf-8")
    product_flow_index = (ROOT / "docs" / "domain-index" / "product-flow.md").read_text(encoding="utf-8")
    listing_images_section = products_api_text.split('@router.put("/{product_id}/listing-images"', 1)[1].split('@router.delete("/{product_id}"', 1)[0]

    assert_true(
        "_reset_product_after_image_selection" in products_api_text
        and "WORKFLOW_NODE_SEARCH_COMPETITOR" in products_api_text
        and "WORKFLOW_NODE_SELECT_IMAGES" in products_api_text,
        "T3 必须有图片确认 destructive reset helper，并使用 workflow service 写 select_images/search_competitor 节点",
    )
    assert_true(
        "_run_product_competitor_search_background" not in listing_images_section
        and "background_tasks.add_task" not in listing_images_section
        and '"competitor_searching"' not in listing_images_section
        and '"stylesnap_search"' not in listing_images_section,
        "图片确认接口不能自动启动 StyleSnap 搜索、后台任务或写 running 搜索快照",
    )
    assert_true(
        "ProductFile" not in listing_images_section
        and "delete(ProductFile" not in products_api_text.split("async def _reset_product_after_image_selection", 1)[1].split("async def _giga_image_candidates_for_source", 1)[0]
        and "delete(CatalogProduct" not in products_api_text.split("async def _reset_product_after_image_selection", 1)[1].split("async def _giga_image_candidates_for_source", 1)[0],
        "图片确认 reset 不得删除 ProductFile、CatalogProduct、真实文件或导出历史",
    )
    assert_true(
        "_initialize_product_image_workflow(product, now=now)" in products_api_text
        and "set_product_workflow(" in giga_product_drafts_text
        and "WORKFLOW_NODE_SELECT_IMAGES" in giga_product_drafts_text,
        "手动创建、Excel 导入和 GIGA draft 新建路径必须初始化 select_images/pending",
    )
    assert_true(
        "Amazon workflow T3" in product_flow_index
        and "search_competitor/pending" in product_flow_index,
        "T3 改变图片确认 workflow 行为后必须同步 product-flow domain index",
    )

    code = r'''
import asyncio
import json
from datetime import datetime
from app.api import products
from app.models import CatalogProduct, Product, ProductAplus, ProductData, ProductFile, ProductImage
from app.models.status import WORKFLOW_NODE_SEARCH_COMPETITOR, WORKFLOW_STATUS_PENDING

class FakeDb:
    def __init__(self):
        self.added = []
    def add(self, item):
        self.added.append(item)

async def main():
    product = Product(
        id=321,
        gigab2b_url="https://www.gigab2b.com/product-detail/I321",
        gigab2b_product_id="I321",
        status="completed",
        current_step=6,
        error_message="old listing done",
        competitor_asin="B0OLD",
        upc="123456789012",
        brand="Vindhvisk",
        aplus_upload_status="not_uploaded",
        aplus_uploaded_at=None,
        aplus_upload_error=None,
    )
    product.data = ProductData(
        product_id=321,
        item_code="I321",
        title="Source title",
        material="Wood",
        gigab2b_raw_snapshot=json.dumps({
            "batch_id": "b1",
            "site": "US",
            "representative_sku": "S1",
            "giga_listing_images": [{"path": "/img/source.jpg"}],
        }),
        material_dir="/tmp/materials/I321",
        listing_title="Old Listing",
        listing_bullets="[]",
        listing_search_terms="old",
        categories='["Old"]',
        leaf_category="Old Leaf",
        amazon_template_path=None,
        amazon_template_fill_summary=None,
        amazon_template_generated_at=None,
    )
    product.images = ProductImage(
        product_id=321,
        main_image_path="/old/main.jpg",
        gallery_images='["/old/1.jpg"]',
        gallery_order='["/source/1.jpg"]',
        contact_sheet_path="/old/contact.jpg",
        image_analysis='{"old": true}',
        image_selling_points='["old"]',
        category_style="old",
        main_image_summary="old summary",
        analyzed_at=datetime(2026, 6, 3),
    )
    product.aplus = ProductAplus(
        product_id=321,
        aplus_plan='{"old": true}',
        aplus_scripts='[]',
        aplus_images='[]',
        aplus_status="generated",
    )
    product.files = [ProductFile(product_id=321, file_type="listing_output", label="Old export", path="/tmp/export/old.xlsx")]
    product.catalog_item = CatalogProduct(
        source_product_id=321,
        gigab2b_url=product.gigab2b_url,
        gigab2b_product_id=product.gigab2b_product_id,
        competitor_asin="B0OLD",
        status="completed",
        confirmed_at=None,
        exported_at=None,
        export_task_id=None,
        export_file_path=None,
    )

    now = datetime(2026, 6, 18, 10, 0, 0)
    await products._reset_product_after_image_selection(
        FakeDb(),
        product,
        main_image_path="/new/main.jpg",
        gallery_paths=["/new/main.jpg", "/new/2.jpg"],
        now=now,
    )

    assert product.workflow_node == WORKFLOW_NODE_SEARCH_COMPETITOR
    assert product.workflow_status == WORKFLOW_STATUS_PENDING
    assert product.workflow_error is None
    assert product.competitor_asin is None
    assert product.status == "created"
    assert product.current_step == 1
    assert product.error_message is None
    assert product.images.main_image_path == "/new/main.jpg"
    assert json.loads(product.images.gallery_images) == ["/new/main.jpg", "/new/2.jpg"]
    assert product.images.image_analysis is None
    assert product.images.contact_sheet_path is None
    assert product.images.gallery_order == '["/source/1.jpg"]'
    snapshot = json.loads(product.data.gigab2b_raw_snapshot)
    assert snapshot["giga_listing_images"] == [{"path": "/img/source.jpg"}]
    assert product.data.title == "Source title"
    assert product.data.material == "Wood"
    assert product.data.material_dir == "/tmp/materials/I321"
    assert product.data.listing_title is None
    assert product.data.listing_bullets is None
    assert product.data.leaf_category is None
    assert product.data.amazon_template_path is None
    assert product.data.amazon_template_fill_summary is None
    assert product.upc == "123456789012"
    assert product.brand == "Vindhvisk"
    assert len(product.files) == 1 and product.files[0].path == "/tmp/export/old.xlsx"
    assert product.catalog_item.competitor_asin is None
    assert product.catalog_item.confirmed_at is None
    assert product.catalog_item.exported_at is None
    assert product.catalog_item.export_task_id is None
    assert product.catalog_item.export_file_path is None
    assert product.aplus.aplus_plan is None
    assert product.aplus.aplus_status is None

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"Amazon workflow T3 图片确认 reset 行为验证失败: {result.stderr or result.stdout}")


def test_amazon_workflow_t4_competitor_search_rules() -> None:
    main_text = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    frontend_app_text = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    frontend_api_text = (ROOT / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")
    product_list_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    product_detail_text = (ROOT / "frontend" / "src" / "pages" / "ProductDetail.tsx").read_text(encoding="utf-8")
    product_flow_index = (ROOT / "docs" / "domain-index" / "product-flow.md").read_text(encoding="utf-8")
    style_retirement_line = next((line for line in product_flow_index.splitlines() if line.startswith("- 旧 StyleSnap")), "")
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    step10_text = (ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py").read_text(encoding="utf-8")
    export_writer_text = (ROOT / "backend" / "app" / "pipeline" / "amazon_export" / "writer.py").read_text(encoding="utf-8")
    retired_files = [
        ROOT / "backend" / "app" / "api" / "amazon_stylesnap.py",
        ROOT / "backend" / "app" / "services" / "amazon_stylesnap_search.py",
        ROOT / "backend" / "app" / "services" / "amazon_listing_capture.py",
        ROOT / "frontend" / "src" / "pages" / "ProductCompetitorReview.tsx",
    ]
    assert_true(all(not path.exists() for path in retired_files), "旧 StyleSnap API/service 和前端竞品确认页必须删除")
    assert_true("amazon_stylesnap_router" not in main_text and "include_router(amazon_stylesnap" not in main_text, "后端不得注册旧 StyleSnap router")
    assert_true("/amazon-stylesnap" not in frontend_app_text and "ProductCompetitorReview" not in frontend_app_text, "前端不得保留旧 StyleSnap 路由/页面 import")
    assert_true('path="/products/competitor-review" element={<Navigate to="/products" replace />}' in frontend_app_text, "旧竞品确认页 URL 必须重定向到商品列表")
    assert_true('"/competitor-review-queue"' not in products_api_text and '"/competitor-review-detail/{product_id}"' not in products_api_text, "products API 不得继续暴露旧竞品确认队列/detail")
    assert_true("ProductCompetitorReview" not in schemas_text, "schemas 不得继续定义旧竞品确认页响应模型")
    assert_true("/amazon-stylesnap" not in frontend_api_text and "AmazonStyleSnapCandidate" not in frontend_api_text, "前端 API client 不得保留旧 StyleSnap 候选方法")
    assert_true("open_competitor_review" not in product_list_text and "searchCompetitorCandidates" not in product_detail_text, "商品列表/详情不得保留旧竞品确认或旧搜索入口")
    assert_true(
        "AmazonStyleSnapCandidate" not in models_text
        and "AmazonListingCapture" not in models_text
        and "amazon_stylesnap_candidates" not in database_text
        and "selected_stylesnap" not in products_api_text
        and "amazon_listing_capture" not in products_api_text
        and "stylesnap_search" not in products_api_text
        and "selected_stylesnap" not in product_detail_text
        and "amazon_listing_capture" not in product_detail_text
        and "stylesnap_search" not in product_detail_text
        and "selected_stylesnap" not in step10_text
        and "amazon_listing_capture" not in step10_text
        and "stylesnap_summary" not in export_writer_text,
        "旧 StyleSnap 历史兼容代码也必须退役：模型、startup、商品 API、详情页和 Step10/export 都不得继续读取旧表或旧 snapshot key",
    )
    assert_true(
        "api/amazon_stylesnap.py" not in product_flow_index
        and "ProductCompetitorReview.tsx" not in product_flow_index
        and "历史" not in style_retirement_line,
        "product-flow index 必须同步 StyleSnap 全量退役口径",
    )
    return

def test_amazon_workflow_t5_competitor_capture_rules() -> None:
    assert_true(
        not (ROOT / "backend" / "app" / "api" / "amazon_stylesnap.py").exists()
        and not (ROOT / "backend" / "app" / "services" / "amazon_listing_capture.py").exists(),
        "旧 StyleSnap 选择竞品/抓详情入口已退役，不得继续保留 T5 运行路径",
    )
    return

def test_product_detail_get_is_readonly_for_material_videos() -> None:
    products_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    material_assets_text = (ROOT / "backend" / "app" / "services" / "material_assets.py").read_text(encoding="utf-8")
    get_product_section = products_text.split('@router.get("/{product_id}"', 1)[1].split('@router.post("/{product_id}/files/open"', 1)[0]
    assert_true(
        "_ensure_contact_sheet_oss_urls" not in get_product_section
        and "upload_private_file" not in get_product_section
        and "await db.commit()" not in get_product_section
        and "await db.refresh(" not in get_product_section,
        "GET /api/products/{product_id} 详情链路必须只读，不能 ensure contact sheet、上传 OSS、commit 或 refresh 写回 DB",
    )
    assert_true(
        "organize_video_files" not in get_product_section
        and "shutil.move" not in get_product_section
        and ".mkdir(" not in get_product_section
        and ".rename(" not in get_product_section
        and ".unlink(" not in get_product_section,
        "GET /api/products/{product_id} 详情链路必须只读素材目录，不能整理/移动/创建/删除视频文件",
    )
    assert_true(
        "video_folder_summary(material_dir)" in get_product_section
        and "def video_folder_summary" in material_assets_text
        and "shutil.move" not in material_assets_text.split("def video_folder_summary", 1)[1],
        "商品详情视频摘要必须走只读 helper，不能复用 organize_video_files 的 mutating 行为",
    )

    code = r'''
from tempfile import TemporaryDirectory
from pathlib import Path
from app.services.material_assets import video_folder_summary

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    loose = root / "loose.mov"
    nested_dir = root / "nested"
    nested_dir.mkdir()
    nested = nested_dir / "clip.mp4"
    loose.write_bytes(b"video")
    nested.write_bytes(b"video")

    summary = video_folder_summary(root)

    assert summary is not None, summary
    assert summary["exists"] is True, summary
    assert summary["file_count"] == 2, summary
    assert "loose.mov" in summary["files"], summary
    assert "nested/clip.mp4" in summary["files"], summary
    assert loose.is_file()
    assert nested.is_file()
    assert not (root / "video").exists()
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"商品详情视频只读摘要行为验证失败: {result.stderr or result.stdout}")


def test_inventory_update_template_exports_stock_only_by_sku() -> None:
    products_py = ROOT / "backend" / "app" / "api" / "products.py"
    config_py = ROOT / "backend" / "app" / "config.py"
    template_path = ROOT / "backend" / "app" / "pipeline" / "templates" / "PriceAndQuantity.xlsm"
    text = products_py.read_text(encoding="utf-8")
    inventory_sync_text = (ROOT / "backend" / "app" / "services" / "inventory_sync.py").read_text(encoding="utf-8")
    assert_true(template_path.is_file(), "库存同步 Price & Quantity 模板必须随项目保存")
    assert_true("PRICE_QUANTITY_TEMPLATE_PATH" in config_py.read_text(encoding="utf-8"), "库存同步模板路径必须可配置")
    assert_true('"/catalog/inventory-template/export"' in text, "必须提供库存同步模板导出接口")
    assert_true("缺少真实 ASIN" in text, "库存同步模板导出必须只允许已有真实 ASIN 的商品")
    assert_true("按 SKU 写入库存；价格列留空，不更新价格" in text, "库存同步模板只能写 SKU 和库存，不能更新价格")
    assert_true(
        "stock_value < 0" in text
        and "stock_value <= 0" not in text
        and "数量按最新 GIGA 库存" in text,
        "Amazon 首次导入表必须允许库存 0 写入 Quantity=0，只禁止负库存",
    )
    assert_true(
        "assert_gigab2b_logged_in_for_inventory" in text,
        "创建库存同步批次前必须先检查大建云仓登录态，未登录不能创建同步批次",
    )
    assert_true(
        "GIGAB2B_LOGIN_REQUIRED_ERROR" in inventory_sync_text and "_fail_whole_batch" in inventory_sync_text,
        "库存同步后台批次也必须保留大建云仓登录态兜底检查",
    )


def test_catalog_export_creation_keeps_business_reasons_in_task_report() -> None:
    offline_tasks_py = ROOT / "backend" / "app" / "services" / "offline_tasks.py"
    products_py = ROOT / "backend" / "app" / "api" / "products.py"
    offline_text = offline_tasks_py.read_text(encoding="utf-8")
    products_text = products_py.read_text(encoding="utf-8")
    create_section = offline_text.split("async def create_catalog_export_tasks", 1)[1].split("async def _active_aplus_product_ids", 1)[0]
    export_by_category_section = products_text.split('async def export_catalog_products_by_category', 1)[1].split('@router.post("/catalog/inventory-template/export")', 1)[0]
    assert_true(
        "_catalog_existing_asin" not in create_section
        and "已有真实 ASIN" not in create_section
        and "类目模板未就绪" not in create_section,
        "导出任务创建层不能用真实 ASIN 或模板状态前置过滤；这些原因必须进入任务 result_json.rows/导出报告",
    )
    assert_true(
        "Product.amazon_asin" not in export_by_category_section
        and "CatalogProduct.amazon_asin" not in export_by_category_section,
        "按类目导出不能在查询层过滤真实 ASIN；应由导出构建器写入逐商品报告",
    )


def test_asin_sync_uses_seller_sku_first_and_upc_auxiliary_only() -> None:
    asin_sync_py = ROOT / "backend" / "app" / "services" / "asin_sync.py"
    text = asin_sync_py.read_text(encoding="utf-8")
    build_section = text[text.index("def build_sync_item"): text.index("def build_sync_item") + 900]
    assert_true(
        "seller_sku_candidate(catalog)" in build_section
        and 'lookup_type = "MSKU" if lookup_code else None' in build_section
        and "不能用 UPC 作为 ASIN 主匹配键" in build_section
        and "upc or item_code" not in build_section
        and 'lookup_type = "商品编码" if upc else "MSKU"' not in text,
        "ASIN 同步新建 item 必须 seller SKU/MSKU first，不能继续 UPC 优先",
    )
    assert_true(
        'if normalized.upper() == "UPC":' in text
        and 'return "商品编码"' in text
        and 'if normalized.upper() == "SKU":' in text
        and 'return "MSKU"' in text,
        "ASIN 同步可兼容旧批次里已保存的 UPC/SKU 查询类型，但新生产路径不得 UPC 优先",
    )
    assert_true(
        "lookup = await _lookup_asin(lookup_code, store, lookup_type, auth)" in text,
        "ASIN 同步执行时必须把查询类型传给领星 API，不能忽略 lookup_type",
    )
    assert_true(
        "LINGXING_LISTING_API_URL" in text
        and "listing-api/api/product/showOnline" in text
        and '"amz_product_id"' in text
        and '"msku"' in text,
        "ASIN 同步旧兼容入口仍可走领星 Listing API；A+ 发布前置必须由 T2 seller SKU first policy 决定",
    )


def test_lingxing_listing_sync_t2_contract() -> None:
    listing_fill_text = (ROOT / "backend" / "app" / "pipeline" / "amazon_export" / "listing_fill.py").read_text(encoding="utf-8")
    products_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    catalog_export_worker_text = (ROOT / "backend" / "app" / "task_runtime" / "catalog_export_workers.py").read_text(encoding="utf-8")
    offline_tasks_text = (ROOT / "backend" / "app" / "services" / "offline_tasks.py").read_text(encoding="utf-8")
    policy_text = (ROOT / "backend" / "app" / "services" / "asin_match_policy.py").read_text(encoding="utf-8")
    client_text = (ROOT / "backend" / "app" / "services" / "lingxing_listing_client.py").read_text(encoding="utf-8")
    planner_text = (ROOT / "backend" / "app" / "task_planners" / "lingxing_listing_sync.py").read_text(encoding="utf-8")
    worker_text = (ROOT / "backend" / "app" / "task_runtime" / "lingxing_listing_sync_workers.py").read_text(encoding="utf-8")
    task_api_text = (ROOT / "backend" / "app" / "api" / "task_runs.py").read_text(encoding="utf-8")
    main_text = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    display_text = (ROOT / "backend" / "app" / "task_runtime" / "display.py").read_text(encoding="utf-8")
    config_text = (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    env_example_text = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    behavior_path = ROOT / "scripts" / "test_lingxing_listing_sync_tasks.py"

    assert_true(
        "def amazon_seller_sku_for_export" in listing_fill_text
        and 'fields["sku"]: seller_sku' in listing_fill_text
        and "amazon_seller_sku_for_export(product, pd)" in products_text
        and '"Seller SKU": seller_sku' in products_text,
        "Amazon export 必须从同一个模板填充事实持久化/报告 seller SKU",
    )
    assert_true(
        "item.amazon_seller_sku = seller_sku" in catalog_export_worker_text
        and "product.amazon_seller_sku = seller_sku" in catalog_export_worker_text
        and "item.amazon_seller_sku = seller_sku" in offline_tasks_text
        and "product.amazon_seller_sku = seller_sku" in offline_tasks_text
        and '"seller_sku": row.get("Seller SKU")' in offline_tasks_text,
        "新旧导出成功路径必须持久化 Product/Catalog seller SKU，并把 seller_sku 写入 result rows",
    )
    assert_true(
        "def seller_sku_candidate" in policy_text
        and "ASIN_MATCH_SOURCE_SELLER_SKU" in policy_text
        and "ASIN_MATCH_SOURCE_PRODUCT_SELLER_SKU_MIRROR" in policy_text
        and "Product/Catalog amazon_seller_sku 不一致" in policy_text
        and "catalog.exported_at" not in policy_text[policy_text.index("def seller_sku_candidate"): policy_text.index("def _market_matches")]
        and "upc_auxiliary_only" in policy_text
        and "ASIN_MATCH_SOURCE_ASIN_CONFLICT" in policy_text
        and "def local_asin_values" in policy_text
        and "local_product_catalog_asin_conflict" in policy_text
        and '"catalog"' in policy_text
        and '"product"' in policy_text
        and "wrong_store_or_site" in policy_text
        and "not_sellable" in policy_text
        and "multiple_seller_sku_rows" in policy_text,
        "asin_match_policy 必须集中 seller SKU first、Product mirror 修复、UPC auxiliary、Product/Catalog ASIN 冲突、冲突/多匹配/错店铺站点/不可售策略，且不能用 exported_at-only item_code 冒充 seller SKU",
    )
    assert_true(
        "LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS" in config_text
        and 'LINGXING_APLUS_STORE_NAME: str = ""' in config_text
        and 'LINGXING_APLUS_STORE_ID: str = ""' in config_text
        and "LINGXING_APLUS_STORE_NAME=Andy店-US" not in env_example_text
        and "LINGXING_APLUS_STORE_ID=17983" not in env_example_text
        and "if not settings.LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS" in client_text
        and '"real_external_calls_disabled"' in client_text
        and '"store_config_required"' in client_text
        and "requires explicit store_name and store_id" in client_text
        and '"Cookie"' not in worker_text
        and '"auth-token"' not in worker_text,
        "Lingxing Listing client 必须默认 fail closed，真实外部调用必须显式配置 store_name/store_id，worker event 不得记录 cookie/token/header",
    )
    assert_true(
        'task_type="lingxing_listing_sync"' in planner_text
        and 'step_type="lingxing_listing_sync_product"' in planner_text
        and "dedupe_key=dedupe_key" in planner_text
        and "correlation_key=f\"product:{catalog.source_product_id}:lingxing_aplus_publish\"" in planner_text
        and "idempotency_key=dedupe_key" in planner_text,
        "Lingxing Listing sync planner 必须 task-runtime 化并具备 dedupe/correlation/idempotency",
    )
    assert_true(
        "def lingxing_listing_sync_product" in worker_text
        and "decide_asin_match" in worker_text
        and "catalog.amazon_asin = decision.asin" in worker_text
        and "product.amazon_asin = decision.asin" in worker_text
        and "catalog.asin_match_evidence_json" in worker_text
        and "STATUS_READY_TO_UPLOAD" in worker_text
        and "STATUS_WAITING_LISTING" in worker_text,
        "Lingxing Listing sync worker 必须写 Catalog/Product ASIN 匹配事实和 A+ 前置状态",
    )
    assert_true(
        '"/lingxing-listing-sync"' in task_api_text
        and '"lingxing_listing_sync": "领星 Listing / ASIN 同步"' in task_api_text
        and '"lingxing_listing_sync_product": "Listing / ASIN 对齐"' in task_api_text
        and "register_lingxing_listing_sync_workers()" in main_text
        and '"lingxing_listing_sync_product": "Listing / ASIN 对齐"' in display_text,
        "T2 必须注册 API、worker 和任务中心 label",
    )
    assert_true(
        behavior_path.is_file()
        and "UPC auxiliary hit must not satisfy seller SKU match" in behavior_path.read_text(encoding="utf-8")
        and "active duplicate trigger must reuse the same dedupe run" in behavior_path.read_text(encoding="utf-8"),
        "T2 必须有行为脚本覆盖 UPC auxiliary-only 和重复触发幂等",
    )
    assert_true(
        "Product-only ASIN conflict should be blocked" in behavior_path.read_text(encoding="utf-8")
        and "Catalog-only ASIN conflict should be blocked" in behavior_path.read_text(encoding="utf-8")
        and "Product/Catalog local ASIN mismatch should be blocked before choosing one" in behavior_path.read_text(encoding="utf-8")
        and "exported_at-only old record must not use item_code as trusted seller SKU" in behavior_path.read_text(encoding="utf-8"),
        "T2 行为脚本必须覆盖 Product-only/Catalog-only/Product-Catalog 本地 ASIN 冲突和 exported_at-only 旧记录不能用 item_code 写 ASIN",
    )
    assert_true(
        "store_config_required must fail before old auth default fallback is called" in behavior_path.read_text(encoding="utf-8")
        and "missing store config should raise typed store_config_required" in behavior_path.read_text(encoding="utf-8"),
        "T2 行为脚本必须覆盖真实外部调用开启但缺 store config 时 fail closed，且不调用旧默认店铺 auth fallback",
    )
    assert_true(
        "AUTO_LINGXING_APLUS_AFTER_DONE" not in (ROOT / "backend" / "app" / "task_runtime" / "aplus_generate_workers.py").read_text(encoding="utf-8"),
        "T2/T3 仍不允许开启 A+ done 自动发布",
    )


def test_step10_keeps_sofa_dimensions_and_avoids_inventory_conflict() -> None:
    step10_py = ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py"
    text = step10_py.read_text(encoding="utf-8")
    sofa_strategy_py = ROOT / "backend" / "app" / "pipeline" / "amazon_export" / "strategies" / "sofa_chair.py"
    sofa_strategy_text = sofa_strategy_py.read_text(encoding="utf-8")
    assert_true(
        "SOFA_ITEM_DIMENSION_MAX_WIDTH_INCHES" not in text,
        "SOFA 不能再因为宽度阈值清空 Item Dimensions D x W x H",
    )
    assert_true(
        'fields["inventory_available"]' not in text,
        "使用 Quantity 库存时不能同时写 Inventory Always Available，否则 Amazon 会拒绝 quantity",
    )
    assert_true(
        '"living-room-chaise-lounges"' in text and "high_confidence_nodes" in text,
        "Chaise Lounges 来源类目应优先映射到休闲椅，不能被 sofa 尺寸兜底提前改成 sofas",
    )
    assert_true(
        "_existing_template_image_urls" in text and '"status": "reused"' in text,
        "重复生成 Amazon 模板时应复用既有图片 URL，避免每次导出都重新上传 OSS",
    )
    chair_block = sofa_strategy_text.split('if product_type == "CHAIR":', 1)[1].split("if pd.weight:", 1)[0]
    assert_true(
        "maximum_weight_recommendation" not in chair_block,
        "CHAIR 模板必须保留 Maximum Weight Recommendation，Amazon processing summary 会把它当必填字段",
    )
    assert_true(
        "DEFAULT_WEIGHT_CAPACITY_LBS = 500" in text,
        "无法判断几人位时，Maximum Weight Recommendation 必须默认填 500 lbs",
    )
    assert_true(
        "SINGLE_SEAT_WEIGHT_CAPACITY_LBS = 250" in text and "* 300" in text,
        "承重默认规则必须覆盖单人 250 lbs、标准座位 250 lbs/座、模块化/sectional 300 lbs/座",
    )
    assert_true(
        'fields["maximum_weight_recommendation"]: legacy._weight_capacity_maximum(seating, pd)' in sofa_strategy_text,
        "Maximum Weight Recommendation 必须由商品文本和座位数共同推断，不能只按旧座位数兜底",
    )
    assert_true(
        "_shipping_template_for_product" in text and "shipping_template_by_brand" in text,
        "Amazon 导入表格必须支持按品牌指定配送模板，不能只取模板第一个下拉值",
    )
    assert_true(
        "stock < 0" in text
        and "stock <= 0" not in text
        and "不能导出负数库存" in text,
        "Step10 单品模板生成必须允许库存 0 写入 Quantity=0，只禁止负库存",
    )


def test_step1_collects_product_dimensions_and_numeric_packages() -> None:
    step1_py = ROOT / "backend" / "app" / "pipeline" / "step1_collect.py"
    text = step1_py.read_text(encoding="utf-8")
    assert_true(
        "product_dimensions.get(\"assemble_info\")" in text
        and '"dimensionLength": dimensions.get("length_show")' in text
        and '"weight": dimensions.get("weight_show")' in text,
        "Step1 必须从大建产品尺寸读取组装长宽高和产品重量",
    )
    assert_true(
        '"length": length' in text and '"weight_value": weight' in text,
        "Step1 包装明细必须保存数值长宽高、重量和数量，供导出表格聚合",
    )
    assert_true(
        "_max_package_dimensions" not in text and "_judge_product_dimensions_with_llm" not in text,
        "产品尺寸不能再用包装尺寸最大值或大模型兜底覆盖",
    )
    assert_true(
        "stock == 0" not in text
        and "库存为 0" not in text
        and "库存为0" not in text,
        "Step1 采集层不能再把库存 0 当成不可售或跳过原因；库存 0 是导出 Quantity 事实",
    )


def test_step10_sums_multi_package_dimensions() -> None:
    step10_py = ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py"
    text = step10_py.read_text(encoding="utf-8")
    assert_true(
        "sum(item[\"length\"] for item in parsed_packages)" in text
        and "sum(item[\"weight\"] for item in parsed_packages)" in text,
        "Step10 多子产品包装尺寸必须按长宽高和重量分别相加",
    )
    assert_true(
        "重量最大的外包装" not in text,
        "Step10 不能再取重量最大的单个外包装作为代表包裹",
    )


def test_mapping_sets_andy_free_shipping_template() -> None:
    mapping_dir = ROOT / "backend" / "app" / "pipeline" / "template_mappings"
    for name in ("vindhvisk_sofa.json", "ride_on_toy.json", "vindhvisk_bicycle.json"):
        text = (mapping_dir / name).read_text(encoding="utf-8")
        assert_true(
            '"Vindhvisk": "Migrated Template FreeShipping"' in text
            and '"Andy店-US": "Migrated Template FreeShipping"' in text,
            f"{name} 必须把 Andy 店当前品牌默认配送模板设为 FreeShipping",
        )


def test_bicycle_template_mapping_covers_current_failed_categories() -> None:
    mapping_path = ROOT / "backend" / "app" / "pipeline" / "template_mappings" / "vindhvisk_bicycle.json"
    template_path = ROOT / "backend" / "app" / "pipeline" / "templates" / "BICYCLE_CYCLING.xlsm"
    mapping_text = mapping_path.read_text(encoding="utf-8")
    step10_text = (ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py").read_text(encoding="utf-8")

    assert_true(template_path.is_file(), "自行车 Amazon 模板必须随项目保存")
    for category in ("Kids' Bikes", "Cycling", "Folding Bikes", "Cruiser Bikes", "Electric Bicycles", "Mountain Bikes", "Road Bikes"):
        assert_true(category in step10_text, f"{category} 必须直接映射到自行车模板，不能落到玩具兜底")
    assert_true('"category_type": "bicycle"' in mapping_text, "自行车映射必须使用专门的 bicycle 填表逻辑")
    assert_true('"electric-bicycles"' in mapping_text and '"childrens-bicycles"' in mapping_text, "自行车映射必须包含当前缺失的细分类目")
    assert_true("_apply_bicycle_fill" in step10_text, "Step10 必须有自行车专用字段填充分支")


def test_search_terms_are_twenty_comma_separated_keywords() -> None:
    terms, changed, count = normalize_search_terms(
        "deep seat sofa, modular couch, apartment couch, sofa, living room seating",
        visible_copy="Vindhvisk sofa with deep seat",
        max_bytes=250,
    )
    assert_true(terms == "modular couch, apartment couch, living room seating", "Search Terms 必须保留关键词短语并用逗号分隔")
    assert_true(changed, "Search Terms 去重/格式化后必须标记调整")
    assert_true(count == 3, "Search Terms 数量必须按关键词短语统计")

    many_terms = ", ".join(f"keyword {idx}" for idx in range(1, 30))
    limited_terms, _, limited_count = normalize_search_terms(many_terms, max_bytes=1000)
    assert_true(limited_count == SEARCH_TERMS_MAX_KEYWORDS, "Search Terms 最多只能保留 20 个候选关键词")
    assert_true(limited_terms.count(",") == SEARCH_TERMS_MAX_KEYWORDS - 1, "Search Terms 必须使用逗号分隔关键词")

    step5_text = (ROOT / "backend" / "app" / "pipeline" / "step5_listing.py").read_text(encoding="utf-8")
    step10_text = (ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py").read_text(encoding="utf-8")
    assert_true("Select no more than {search_terms_max_keywords} keyword phrases" in step5_text, "Step5 Prompt 必须明确最多 20 个候选关键词短语")
    assert_true("when available" in step5_text, "Step5 Prompt 在缺少关键词候选时必须允许用商品事实兜底")
    assert_true('Separate keyword phrases with ", "' in step5_text, "Step5 Prompt 必须要求逗号分隔 Search Terms")
    assert_true("normalize_search_terms(" in step10_text, "Step10 写入 Amazon 模板前必须统一 Search Terms 格式")


def test_gigab2b_alphanumeric_product_id_url_is_supported() -> None:
    duplicate_text = (ROOT / "backend" / "app" / "services" / "product_duplicates.py").read_text(encoding="utf-8")
    assert_true("parse_qs(parsed.query)" in duplicate_text, "大建云仓 product_id 必须从 query 参数结构化提取")
    assert_true("[A-Za-z0-9_-]+" in duplicate_text, "大建云仓 product_id 必须支持字母数字混合 ID")

    create_page_text = (ROOT / "frontend" / "src" / "pages" / "CreateProduct.tsx").read_text(encoding="utf-8")
    assert_true("请输入竞品ASIN" not in create_page_text, "创建任务不能强制要求竞品 ASIN")
    assert_true("请输入UPC码" not in create_page_text, "创建任务不能强制要求 UPC")
    assert_true("error?.response?.data?.detail" in create_page_text, "创建失败时必须展示后端具体原因")


def test_upc_pool_is_source_of_new_task_upcs() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    upc_pool_text = (ROOT / "backend" / "app" / "services" / "upc_pool.py").read_text(encoding="utf-8")
    product_list_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    create_page_text = (ROOT / "frontend" / "src" / "pages" / "CreateProduct.tsx").read_text(encoding="utf-8")

    assert_true('IMPORT_TEMPLATE_HEADERS = ["原始数据链接", "竞品ASIN"]' in products_api_text, "批量导入模板不应再要求 UPC 列")
    assert_true("await ensure_product_upc(db, product)" in products_api_text, "创建/导入任务必须从 UPC 池领取 UPC")
    assert_true("UPC由UPC池子绑定后不可手动修改" in products_api_text, "已绑定 UPC 不能被手动改绑")
    assert_true("bound_item_code" in upc_pool_text and "bound_source_product_id" in upc_pool_text, "UPC 池必须记录商品Code和来源商品ID")
    assert_true("UPC 会自动从 UPC池子领取" in product_list_text, "前端导入提示必须说明 UPC 来自池子")
    assert_true('name="upc"' not in create_page_text, "创建任务页面不应再显示 UPC 输入框")


def test_offline_tasks_are_claimed_and_idempotent() -> None:
    offline_text = (ROOT / "backend" / "app" / "services" / "offline_tasks.py").read_text(encoding="utf-8")
    offline_api_text = (ROOT / "backend" / "app" / "api" / "offline_tasks.py").read_text(encoding="utf-8")
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    catalog_page_text = (ROOT / "frontend" / "src" / "pages" / "CatalogList.tsx").read_text(encoding="utf-8")
    product_page_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    product_detail_text = (ROOT / "frontend" / "src" / "pages" / "ProductDetail.tsx").read_text(encoding="utf-8")
    task_runs_api_text = (ROOT / "backend" / "app" / "api" / "task_runs.py").read_text(encoding="utf-8")
    task_center_text = (ROOT / "frontend" / "src" / "pages" / "OfflineTaskCenter.tsx").read_text(encoding="utf-8")
    task_run_center_text = (ROOT / "frontend" / "src" / "pages" / "TaskRunCenter.tsx").read_text(encoding="utf-8")
    task_center_spec_text = (ROOT / "docs" / "superpowers" / "specs" / "2026-06-03-offline-task-center.md").read_text(encoding="utf-8")
    main_text = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    product_bulk_planner_text = (ROOT / "backend" / "app" / "task_planners" / "product_bulk_advance.py").read_text(encoding="utf-8")

    assert_true("def _claim_offline_step" in offline_text, "离线任务步骤必须先原子 claim，避免重复调度执行同一步")
    assert_true(
        "OfflineTaskStep.status.in_(tuple(STEP_STATUS_CLAIMABLE))" in offline_text
        and ".values(" in offline_text
        and 'status="running"' in offline_text,
        "离线任务步骤 claim 必须用数据库条件更新从 pending/interrupted 切到 running",
    )
    assert_true(
        "claimed_step = await _claim_offline_step(db, step.id)" in offline_text
        and "if not claimed_step:" in offline_text,
        "_execute_offline_task 只能执行成功 claim 的步骤",
    )
    assert_true(
        "def _catalog_export_result_ready" in offline_text
        and "_catalog_export_result_ready(existing_result)" in offline_text,
        "导出任务必须有结果幂等保护，避免重复生成第二个 zip",
    )
    assert_true(
        "auto_start: bool = True" in offline_text
        and "if auto_start:" in offline_text,
        "任务创建函数必须支持 auto_start=False，避免脚本/测试创建后又手动执行导致重叠",
    )
    assert_true(
        "recover_offline_tasks" in main_text
        and 'OfflineTaskStep.status.in_(("running", "interrupted"))' in offline_text
        and "_schedule_offline_task(task_id)" in offline_text,
        "服务启动必须恢复遗留 running/interrupted 离线任务，而不是只依赖内存态",
    )
    assert_true(
        "def _catalog_export_payload" in offline_api_text
        and "step.result_json" in offline_api_text
        and "path.parent.mkdir(parents=True, exist_ok=True)" in offline_api_text,
        "导出下载必须能从任务或步骤结果恢复，并在本地缓存缺失时创建目录后从 OSS 恢复",
    )
    assert_true(
        "listCatalogExportFiles" in catalog_page_text
        and "exportFileColumns" in catalog_page_text
        and "file_product_count" in catalog_page_text
        and "task_product_count" in catalog_page_text,
        "导出中心已导出 Tab 必须按导出文件/任务维度展示文件内商品数和任务商品数，不能退回商品列表维度",
    )
    assert_true(
        "itemsTotal" in catalog_page_text
        and "exportFilesTotal" in catalog_page_text
        and "itemsLoading" in catalog_page_text
        and "exportFilesLoading" in catalog_page_text
        and "scheduleExportCompletionRefresh" in catalog_page_text,
        "导出中心待导出商品和已导出文件必须分离 total/loading，并在创建导出任务后自动刷新收敛",
    )
    assert_true(
        "_collect_export_file_category" in products_api_text
        and "_catalog_export_file_row(task)" in products_api_text
        and "task_result = await db.execute(" in products_api_text,
        "导出中心已导出类目筛选也必须从 catalog_export 文件/任务结果聚合，不能沿用已导出商品聚合",
    )
    assert_true(
        "resultSummary" in task_center_text
        and "exported_count" in task_center_text
        and "skipped_count" in task_center_text,
        "任务中心必须展示导出成功和跳过数量，不能只显示 done",
    )
    assert_true(
        "class CatalogExportBuildError" in products_api_text
        and '"商品资料ID"' in products_api_text,
        "导出构建失败时必须保留逐商品报告证据，并在报告里包含 CatalogProduct ID",
    )
    assert_true(
        "def _catalog_export_result_payload" in offline_text
        and '"rows": rows' in offline_text
        and '"success_count": success_count' in offline_text
        and '"failed_count": failed_count' in offline_text
        and '"status": status' in offline_text,
        "导出任务 result_json 必须包含结构化 rows、稳定状态和成功/跳过/失败计数",
    )
    assert_true(
        '"partial_failed"' in offline_text
        and 'payload.get("status") == "partial_failed"' in offline_text,
        "导出任务有成功产物但存在跳过/失败行时必须能表达 partial_failed",
    )
    assert_true(
        "catalog.exported_at is not None" not in offline_text
        and "已生成过导出文件，不能重复导出" not in offline_text,
        "导出任务创建不能用历史导出文件硬拦截；已导出但无真实 ASIN 的商品允许人工新建导出任务",
    )
    assert_true(
        "已有真实 ASIN" not in offline_text.split("async def create_catalog_export_tasks", 1)[1].split("async def _active_aplus_product_ids", 1)[0],
        "导出任务创建层不能用真实 ASIN 前置过滤；防重复首次导入表保护必须由导出构建器写入逐商品报告",
    )
    assert_true(
        'COMPLETED_TASK_STATUSES = {"done", "partial_failed"}' in offline_api_text
        and "response.error_message = None" in offline_api_text
        and "_task_detail_response" in offline_api_text,
        "完成或部分完成的离线任务 API 顶层不能继续暴露陈旧 error_message",
    )
    assert_true(
        "total_products: int = 0" in schemas_text
        and "WORKBENCH_STATUS_KEYS" in products_api_text
        and "data_source_id: int | None = Query(None, ge=1)" in products_api_text
        and "Product.current_step >= 6" in products_api_text,
        "商品工作台必须提供全库状态桶，并且系统状态=待导出只能返回 current_step>=6 的商品",
    )
    assert_true(
        "create_product_bulk_advance_run" in products_api_text
        and "PRODUCT_BULK_ADVANCE_MAX_PRODUCTS = 1000" in product_bulk_planner_text
        and 'task_type="product_bulk_advance"' in product_bulk_planner_text
        and '"rows": rows' in product_bulk_planner_text
        and "尚未完成图片确认和竞品选择" in product_bulk_planner_text,
        "批量推进必须走可审计任务中心 rows/report，不能直接把未就绪商品改成待导出",
    )
    assert_true(
        "createProductBulkAdvanceTask" in product_page_text
        and "批量推进当前筛选" in product_page_text
        and "overviewStatusCounts" in product_page_text
        and "表格当前筛选" in product_page_text,
        "商品工作台页面必须提供全库状态桶说明和页面触发的批量推进审计任务入口",
    )
    assert_true(
        "待自动生成 Listing" in product_page_text
        and "自动入队" in product_page_text
        and "启动选中商品" not in product_page_text
        and "全选待生成" not in product_page_text
        and "runProductFromStep" not in product_page_text,
        "商品工作台不能让用户手动点启动待生成 Listing；图片确认/竞品完成后应自动进入任务中心，列表只保留可审计批量推进补救入口",
    )
    assert_true(
        "product_bulk_advance" in task_run_center_text
        and "productBulkRowsTable" in task_run_center_text
        and "明细" in task_run_center_text,
        "任务中心必须能展示批量推进任务的逐商品 rows/report",
    )
    assert_true(
        "_with_product_bulk_advance_progress" not in task_runs_api_text
        and "latest_counts" not in task_runs_api_text
        and "submitted_count" in product_bulk_planner_text
        and "子任务" in task_run_center_text,
        "批量提交生成任务不能在读接口动态改写 summary_json 来假装父任务追踪到待导出；父任务只展示提交子任务审计",
    )
    assert_true(
        "导出文件" in catalog_page_text
        and "task_id" in catalog_page_text
        and "导出时间" in catalog_page_text
        and "暂无导出文件记录" in catalog_page_text,
        "导出中心已导出 Tab 必须能按文件审计历史任务、导出时间和下载入口",
    )
    assert_true(
        "确认基于该历史任务再次导出" in catalog_page_text
        and "原文件和任务记录会保留" in catalog_page_text
        and "createExportTasksByIds(record.catalog_product_ids" in catalog_page_text,
        "导出中心已导出再次导出必须以历史任务商品快照为入口并先确认副作用",
    )
    assert_true(
        "serverFilterSummary" in product_page_text
        and "当前服务端筛选" in product_page_text
        and "工作状态：" in product_page_text
        and "工作状态会按服务端同一口径筛选" in product_page_text,
        "批量推进当前筛选必须在确认前展示服务端筛选范围，并明确工作状态按服务端同一口径筛选",
    )
    assert_true(
        "download_images=False" in offline_text
        and "GIGA 主数据拉取只保存商品、SKU、库存、价格和图片 URL 候选" in task_center_spec_text
        and "自动继续执行该 batch 的图片下载步骤" not in task_center_spec_text
        and "giga_image_download` 仅用于历史任务兼容" in task_center_spec_text,
        "拉品后不能再表达为全量下载 GIGA 图片；旧图片下载任务只能作为历史兼容",
    )
    assert_true(
        "isDisplayImageCandidate" in product_detail_text
        and "['main', 'gallery'].includes(type)" in product_detail_text
        and "if (typeof item === 'string') return false;" in product_detail_text
        and 'image_type or "unknown"' in products_api_text
        and "representative_sku" in products_api_text
        and "variant_" in products_api_text
        and "asset_source" in products_api_text
        and "DEFAULT_LISTING_IMAGE_LIMIT = 9" in product_detail_text
        and "const mainPath = gigaMainPath" in product_detail_text
        and "persistedListingImagePathsFromImages" in product_detail_text
        and "listingImageDraftIsDirty" in product_detail_text
        and "nextPaths.length && nextPaths.join" in product_detail_text
        and "gigaMainImagePathFromOrder" in product_detail_text
        and "galleryPaths.slice(-(DEFAULT_LISTING_IMAGE_LIMIT - 1))" in product_detail_text
        and "nextPaths.length >= DEFAULT_LISTING_IMAGE_LIMIT" in product_detail_text
        and "大健详情页 Gallery" in product_detail_text
        and "其它 SKU 详情页 Gallery" in product_detail_text
        and "素材包/附件素材" in product_detail_text
        and "备用/未选素材" in product_detail_text
        and "_giga_image_candidates_for_product" in products_api_text,
        "商品详情图片确认必须默认用代表 SKU 的 GIGA mainImage 做主图，再从 gallery 末尾取 8 张；旧纯路径、未知类型和其它 SKU 图片不能全量默认选中，file/brand 留作备用素材",
    )
    image_review_text = (ROOT / "frontend" / "src" / "pages" / "ProductImageReview.tsx").read_text(encoding="utf-8")
    image_queue_endpoint_text = products_api_text.split('@router.get("/image-review-queue"', 1)[1].split('@router.get("/image-review-detail', 1)[0]
    assert_true(
        "select(func.count(Product.id))" in image_queue_endpoint_text
        and "total=total" in image_queue_endpoint_text
        and "total=len(items)" not in image_queue_endpoint_text
        and "queueTotal" in image_review_text
        and "待确认 ${queueTotal} 个" in image_review_text
        and "待确认 ${queue.length} 个" not in image_review_text,
        "图片确认页统计必须使用同筛选条件的真实总数，不能把本次 limit 加载条数当待确认总数",
    )
    assert_true(
        not (ROOT / "backend" / "app" / "services" / "amazon_stylesnap_search.py").exists(),
        "旧 StyleSnap Chrome 搜索 service 已退役，图片确认测试不得继续要求该 service 存在",
    )


def test_product_pipeline_recovers_interrupted_competitor_capture() -> None:
    engine_text = (ROOT / "backend" / "app" / "pipeline" / "engine.py").read_text(encoding="utf-8")

    assert_true(
        "recover_interrupted_pipelines" in engine_text
        and "_is_competitor_listing_capture_state(product)" in engine_text,
        "商品 pipeline 启动恢复必须识别旧竞品详情抓取中的特殊状态，不能当作 Listing 生成续跑",
    )
    assert_true(
        'product.error_message = "旧竞品详情抓取入口已停用，请重新进入当前自动竞品搜索节点"' in engine_text
        and "product.status = FAILED" in engine_text
        and "product.current_step = 4" in engine_text,
        "旧竞品详情抓取中断后必须落到失败态，不能重启后继续显示后台抓取中或提示恢复旧抓详情路径",
    )
    assert_true(
        "AmazonListingCapture" not in engine_text
        and 'snapshot["stylesnap_search"]' not in engine_text,
        "旧 StyleSnap 抓详情/搜索 runtime 已退役，pipeline 恢复不得再写旧抓详情表或 stylesnap_search",
    )
    assert_true(
        "start_pipeline(product_id, start_step=step)" in engine_text,
        "真正的商品生成节点重启后仍应按原步骤重新排队续跑",
    )


def test_competitor_review_queue_uses_workbench_status_scope() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    product_detail_text = (ROOT / "frontend" / "src" / "pages" / "ProductDetail.tsx").read_text(encoding="utf-8")
    product_list_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    frontend_api_text = (ROOT / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")
    assert_true(
        '"/competitor-review-queue"' not in products_api_text
        and '"/competitor-review-detail/{product_id}"' not in products_api_text
        and "ProductCompetitorReview" not in schemas_text
        and not (ROOT / "frontend" / "src" / "pages" / "ProductCompetitorReview.tsx").exists(),
        "旧竞品确认队列/detail API 和页面必须退役",
    )
    assert_true(
        "searchCompetitorCandidates" not in product_detail_text
        and "open_competitor_review" not in product_list_text
        and "/amazon-stylesnap" not in frontend_api_text,
        "商品工作台不能保留旧竞品确认页、旧候选搜索或 StyleSnap API client",
    )
    return


def test_product_bulk_advance_runs_in_task_run_queue() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    product_bulk_planner_text = (ROOT / "backend" / "app" / "task_planners" / "product_bulk_advance.py").read_text(encoding="utf-8")
    product_page_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    task_run_center_text = (ROOT / "frontend" / "src" / "pages" / "TaskRunCenter.tsx").read_text(encoding="utf-8")

    assert_true(
        "create_product_bulk_advance_run" in products_api_text
        and "PRODUCT_BULK_ADVANCE_MAX_PRODUCTS = 1000" in product_bulk_planner_text
        and 'task_type="product_bulk_advance"' in product_bulk_planner_text
        and '"rows": rows' in product_bulk_planner_text,
        "批量推进必须走可审计 task run planner，并输出逐商品 rows/report",
    )
    assert_true(
        "_apply_product_work_status_db_filter(query, select(func.count(Product.id)), body.work_status)" in products_api_text
        and "_product_workbench_status(product) == body.work_status" not in products_api_text,
        "按筛选批量推进的 work_status 必须复用 DB 级 ProductWorkStatus predicate，不能取全量后内存过滤",
    )
    assert_true(
        "createProductBulkAdvanceTask" in product_page_text
        and "批量推进当前筛选" in product_page_text
        and "product_bulk_advance" in task_run_center_text
        and "productBulkRowsTable" in task_run_center_text,
        "商品工作台和任务中心必须保留批量推进任务入口与明细展示",
    )


def test_catalog_export_uses_snapshot_and_reuses_orphan_zip() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    catalog_page_text = (ROOT / "frontend" / "src" / "pages" / "CatalogList.tsx").read_text(encoding="utf-8")

    assert_true(
        "_catalog_export_file_row(task)" in products_api_text
        and "task_result = await db.execute(" in products_api_text
        and "_collect_export_file_category" in products_api_text,
        "导出中心已导出类目筛选必须从导出文件/任务结果聚合",
    )
    assert_true(
        "导出文件" in catalog_page_text
        and "task_id" in catalog_page_text
        and "确认基于该历史任务再次导出" in catalog_page_text
        and "createExportTasksByIds(record.catalog_product_ids" in catalog_page_text,
        "导出中心已导出 Tab 必须能按历史任务快照再次导出，并保留原文件和任务记录",
    )


def test_export_listing_aplus_new_task_runtime_creation_paths() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    offline_tasks_text = (ROOT / "backend" / "app" / "services" / "offline_tasks.py").read_text(encoding="utf-8")
    task_runs_api_text = (ROOT / "backend" / "app" / "api" / "task_runs.py").read_text(encoding="utf-8")

    assert_true(
        "create_catalog_export_tasks" in offline_tasks_text
        and "catalog_export" in offline_tasks_text
        and "create_product_bulk_advance_run" in products_api_text,
        "导出、Listing/A+ 补救入口必须走新任务或可审计任务创建路径，不能直接在页面请求里长跑",
    )
    assert_true(
        "TaskRun" in task_runs_api_text
        and "TaskStep" in task_runs_api_text
        and "TaskRunDetailResponse" in task_runs_api_text,
        "新任务中心必须保留 task run / task step 展示入口",
    )


def test_amazon_export_binds_upc_after_prechecks_and_rolls_back() -> None:
    products_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    step10_text = (ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py").read_text(encoding="utf-8")

    assert_true(
        "await ensure_amazon_template_semantic_fields" in products_text
        and "await ensure_product_upc(db, product)" in products_text,
        "catalog export 必须保留模板语义字段检查和 UPC 绑定步骤",
    )
    step10_section = step10_text.split("async def run_amazon_template", 1)[1].split("output_path = Path(template_result", 1)[0]
    assert_true(
        step10_section.index("if not pd.item_code:") < step10_section.index("await ensure_product_upc(db, product)")
        and step10_section.index("if not pd.listing_title or not pd.listing_bullets:") < step10_section.index("await ensure_product_upc(db, product)")
        and step10_section.index("await ensure_amazon_template_semantic_fields") < step10_section.index("await ensure_product_upc(db, product)"),
        "Step10 单品模板必须先通过 item_code/Listing/语义字段检查，再绑定 UPC",
    )
    assert_true(
        "template_result = await asyncio.to_thread(_build_amazon_template_file" in step10_section
        and "except Exception:\n            await db.rollback()" in step10_section,
        "Step10 模板文件生成失败必须 rollback 未提交的 UPC 绑定",
    )


def test_tiktok_sales_channel_keeps_giga_source_and_uses_warehouse_inventory() -> None:
    data_sources_api = (ROOT / "backend" / "app" / "api" / "data_sources.py").read_text(encoding="utf-8")
    tiktok_api = (ROOT / "backend" / "app" / "api" / "tiktok.py").read_text(encoding="utf-8")
    product_list = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    image_review = (ROOT / "frontend" / "src" / "pages" / "ProductImageReview.tsx").read_text(encoding="utf-8")

    assert_true(
        'VALID_PLATFORMS = {"giga"}' in data_sources_api
        and 'VALID_SALES_CHANNELS = {"amazon", "tiktok"}' in data_sources_api
        and "_normalize_sales_channel" in data_sources_api,
        "TikTok 店铺必须通过 sales_channel 表达，不能把 product_data_sources.platform 从 GIGA 来源平台改成销售渠道",
    )
    assert_true(
        "seller_inventory_distribution" in tiktok_api
        and "TIKTOK_FIXED_SHIPPING_FEE = 50.0" in tiktok_api
        and "calculate_tiktok_price" in tiktok_api
        and "catalog_export" not in tiktok_api,
        "TikTok 详情/导出前置数据必须使用 GIGA 分仓库存和固定 50 运费，不能混用 Amazon catalog_export",
    )
    assert_true(
        "isTikTokSource" in product_list
        and "/tiktok/products/${productId}" in product_list
        and "Amazon 竞品、Listing、批量推进入口已隐藏" in product_list,
        "商品列表必须按销售渠道分流 TikTok 详情，并隐藏 Amazon 专属操作",
    )
    assert_true(
        "sales_channel: 'amazon'" in image_review
        and not (ROOT / "frontend" / "src" / "pages" / "ProductCompetitorReview.tsx").exists(),
        "图片确认只能加载 Amazon 渠道店铺；旧选竞品队列已退役，TikTok 店铺不能进入 Amazon pipeline 队列",
    )


def test_giga_pull_tasks_expose_live_sku_progress_without_group_closure_during_pull() -> None:
    giga_openapi = (ROOT / "backend" / "app" / "services" / "giga_openapi.py").read_text(encoding="utf-8")
    offline_tasks = (ROOT / "backend" / "app" / "services" / "offline_tasks.py").read_text(encoding="utf-8")
    task_center = (ROOT / "frontend" / "src" / "pages" / "OfflineTaskCenter.tsx").read_text(encoding="utf-8")

    assert_true(
        "GigaProgressCallback" in giga_openapi
        and "progress_callback" in giga_openapi
        and "_extract_total_count" in giga_openapi,
        "GIGA 拉品必须支持进度回调并提取远端 SKU 总量，不能让任务中心停在 0/0",
    )
    assert_true(
        "fetching_sku_list" in giga_openapi
        and "fetching_sku_details" in giga_openapi
        and "fetching_prices" in giga_openapi
        and "fetching_inventory" in giga_openapi
        and "writing_sku_snapshot" in giga_openapi
        and "aggregating_items" in giga_openapi,
        "GIGA 拉品 live summary 必须覆盖 SKU 列表、详情、价格、库存、写 snapshot 和统一聚合阶段",
    )
    assert_true(
        giga_openapi.index("aggregating_items") < giga_openapi.index("groups = _build_item_groups"),
        "item/group 聚合必须放在 SKU 同步完成后统一执行，不能在拉列表分页阶段做闭包",
    )
    assert_true(
        "scanned_sku_count" in giga_openapi
        and "synced_sku_count" in giga_openapi
        and "detail_count" in giga_openapi
        and "price_count" in giga_openapi
        and "inventory_count" in giga_openapi
        and "image_url_count" in giga_openapi
        and "skipped_existing_count" in giga_openapi,
        "GIGA 拉品任务必须暴露 SKU 同步口径统计，不能只显示步骤成功数",
    )
    assert_true(
        "result_json" in offline_tasks
        and '"live": live' in offline_tasks
        and "step.updated_at = datetime.now()" in offline_tasks
        and "task.updated_at = step.updated_at" in offline_tasks,
        "offline task 执行中必须写 live result 并刷新 step/task updated_at 作为心跳",
    )
    assert_true(
        "isStaleRunning" in task_center
        and "疑似卡住" in task_center
        and "总量统计中" in task_center
        and "liveResult" in task_center
        and "扫描SKU" in task_center,
        "任务中心必须展示 GIGA 拉品专属进度、未知总量和疑似卡住状态",
    )


def test_task_runtime_v1_uses_new_tables_and_keeps_old_offline_tasks_compatibility() -> None:
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    spec_text = (ROOT / "docs" / "superpowers" / "specs" / "2026-06-13-task-runtime-giga-pull-design.md").read_text(encoding="utf-8")
    task_runs_api = (ROOT / "backend" / "app" / "api" / "task_runs.py").read_text(encoding="utf-8")
    offline_tasks_api = (ROOT / "backend" / "app" / "api" / "offline_tasks.py").read_text(encoding="utf-8")
    runtime_scheduler = (ROOT / "backend" / "app" / "task_runtime" / "scheduler.py").read_text(encoding="utf-8")
    giga_workers = (ROOT / "backend" / "app" / "task_runtime" / "giga_pull_workers.py").read_text(encoding="utf-8")
    giga_planner = (ROOT / "backend" / "app" / "task_planners" / "giga_pull.py").read_text(encoding="utf-8")
    frontend_api = (ROOT / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")
    product_list = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    task_run_center_text = (ROOT / "frontend" / "src" / "pages" / "TaskRunCenter.tsx").read_text(encoding="utf-8")
    main_layout = (ROOT / "frontend" / "src" / "components" / "MainLayout.tsx").read_text(encoding="utf-8")
    inventory_page = (ROOT / "frontend" / "src" / "pages" / "InventorySyncList.tsx").read_text(encoding="utf-8")
    task_actions = (ROOT / "backend" / "app" / "task_runtime" / "actions.py").read_text(encoding="utf-8")
    product_actions = (ROOT / "backend" / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    main_text = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")

    assert_true(
        'class TaskRun(Base):' in models_text
        and 'class TaskGroup(Base):' in models_text
        and 'class TaskStep(Base):' in models_text
        and 'class TaskStepEvent(Base):' in models_text,
        "新任务调度框架 V1 必须使用 task_runs/task_groups/task_steps/task_step_events 新模型，不能继续硬扩旧 offline_tasks",
    )
    assert_true(
        "dedupe_key" in models_text
        and "correlation_key" in models_text
        and "superseded_by_run_id" in models_text
        and "cancel_requested_at" in models_text
        and "_ensure_mysql_task_run_action_columns" in database_text,
        "task_runs 必须具备 PRD 要求的 dedupe/correlation/superseded/cancel 字段，并通过 MySQL 启动期 schema 补齐",
    )
    assert_true(
        "class TaskAction" in task_actions
        and "register_action" in task_actions
        and "TaskRunPlan" in task_actions
        and "class ProductImageAnalysisAction" in product_actions
        and "class ProductListingGenerationAction" in product_actions
        and "Product.status = step" not in task_actions,
        "商品相关任务必须改成 ProductTaskAction，任务框架层不能硬编码商品状态",
    )
    assert_true(
        "backfill_product_action_task_run_keys" in product_actions
        and "This is product-domain compatibility" in product_actions
        and "await backfill_product_action_task_run_keys(db)" in main_text
        and "superseded_by_run_id = ordered[index + 1].id" in product_actions,
        "历史 ProductTaskAction task_run 必须由商品域 backfill 补齐 dedupe/correlation/superseded 元数据，不能继续让旧失败任务停在当前页可重试",
    )
    assert_true(
        "display_status" in task_runs_api
        and "display_status_label" in task_runs_api
        and "available_actions" in task_runs_api
        and "superseded_by_run_id" in task_runs_api
        and "已就绪，等待执行器领取" in task_runs_api
        and "该任务已被 #" in task_runs_api
        and '"/{run_id}/wake"' in task_runs_api
        and '"/{run_id}/cancel"' in task_runs_api
        and '"/{run_id}/mark-interrupted"' in task_runs_api,
        "任务中心 API 必须派生 display/action 字段，ready step 显示 queued，并禁止 superseded 历史任务继续重试",
    )
    assert_true(
        'conn.dialect.name not in {"mysql", "mariadb"}' in database_text
        and "fbm-pipeline now requires MySQL" in database_text
        and "PRAGMA table_info" not in database_text
        and "CREATE TABLE IF NOT EXISTS" not in database_text,
        "数据库初始化必须是 MySQL-only，不能保留本地文件数据库 fallback 或手写建表分支",
    )
    assert_true(
        "ix_task_runs_type_status_id" in database_text
        and "ix_task_groups_run_order" in database_text
        and "ix_task_steps_run_group_order" in database_text
        and "ix_task_steps_ready_claim" in database_text
        and "ix_task_step_events_run_created" in database_text,
        "新任务调度框架 V1 必须通过 MySQL ensure index 支持列表、组顺序、ready claim 和 events 查询",
    )
    assert_true(
        "backend/app/services/offline_tasks.py" in spec_text
        and "其它离线任务" in spec_text
        and "暂时继续走旧 `offline_tasks` 框架" in spec_text,
        "旧 offline_tasks 框架必须保留给未迁移任务，GIGA 拉品新框架不能破坏库存/价格/A+/导出/批量推进",
    )
    assert_true(
        "plan\n  -> details chunks\n  -> inventory chunks\n  -> price chunks\n  -> finalize\n  -> aggregate\n  -> materialize" in spec_text
        and "不做 item/group 闭包聚合" in spec_text
        and "这里才处理关联 SKU / 变体聚合" in spec_text,
        "GIGA 拉品 V1 必须保持先 SKU snapshot 后统一聚合，不能在拉取 chunk 阶段做 item/group closure",
    )
    assert_true(
        'APIRouter(prefix="/api/task-runs"' in task_runs_api
        and '"/giga-pull"' in task_runs_api
        and "create_giga_pull_runs" in task_runs_api
        and '"/giga-pull"' not in offline_tasks_api,
        "GIGA 拉品创建入口必须迁移到 /api/task-runs/giga-pull，不能继续从旧 /api/offline-tasks/giga-pull 创建",
    )
    assert_true(
        "TaskStep.status == STEP_STATUS_READY" in runtime_scheduler
        and "locked_by=worker_id" in runtime_scheduler
        and "locked_until=now + timedelta" in runtime_scheduler
        and "recover_task_runtime" in runtime_scheduler
        and "retry_step" in runtime_scheduler
        and "_runner_lock" in runtime_scheduler,
        "新 runtime 必须使用 DB ready claim、锁/心跳、过期 running 恢复、失败 step 重跑，并保持串行 drain",
    )
    assert_true(
        "giga_pull_plan" in giga_workers
        and "giga_pull_detail_chunk" in giga_workers
        and "giga_pull_inventory_chunk" in giga_workers
        and "giga_pull_price_chunk" in giga_workers
        and "giga_pull_finalize_snapshot" in giga_workers
        and "giga_pull_aggregate_items" in giga_workers
        and "giga_pull_materialize_products" in giga_workers,
        "GIGA 拉品 V1 workers 必须拆成 plan/details/inventory/prices/finalize/aggregate/materialize",
    )
    assert_true(
        giga_workers.index("async def giga_pull_aggregate_items") < giga_workers.index("groups = _build_item_groups")
        and "groups = _build_item_groups" not in giga_workers[:giga_workers.index("async def giga_pull_aggregate_items")],
        "item/group 聚合只能出现在 aggregate step，details/inventory/prices 拉取阶段不能做闭包聚合",
    )
    assert_true(
        "download_giga_product_images" not in giga_workers
        and "build_pending_giga_product_image_rows" in giga_workers
        and "download_images" not in giga_planner,
        "GIGA 拉品 V1 不允许全量下载图片，只能保存图片 URL 候选",
    )
    assert_true(
        "if not sku_codes:" in giga_workers
        and '"status": "noop"' in giga_workers
        and '"skipped_existing_count": skipped_existing_count' in giga_workers
        and '"sku_count": 0' in giga_workers
        and "group.status = RUN_STATUS_SUCCEEDED" in giga_workers
        and "batch.status = \"done\"" in giga_workers,
        "GIGA 拉品 V1 必须显式处理全部 SKU 已存在的 0 chunk/no-op 场景，不能让空 group 永久 pending",
    )
    assert_true(
        "'/task-runs/giga-pull'" in frontend_api
        and "'/offline-tasks/giga-pull'" not in frontend_api
        and "navigate('/task-runs')" in product_list
        and "listTaskRuns({ task_type: 'giga_pull'" in product_list,
        "商品列表发起 GIGA 拉品必须进入新任务中心，不能再提交旧 offline task",
    )
    assert_true(
        "key: '/offline-tasks'" not in main_layout
        and "label: '新任务中心'" not in main_layout
        and "label: '任务中心'" in main_layout
        and "createGigaInventorySyncTaskRuns" in inventory_page
        and "createGigaPriceSyncTaskRuns" in inventory_page
        and "navigate('/offline-tasks')" not in inventory_page,
        "主导航只能保留一个任务中心，库存/价格同步页面必须创建新 task_runs 并跳转 /task-runs",
    )
    assert_true(
        "displayStatusTag" in task_run_center_text
        and "record.display_status_label" in task_run_center_text
        and "record.display_reason" in task_run_center_text
        and "record.available_actions" in task_run_center_text
        and "wakeTaskRun" in task_run_center_text
        and "cancelTaskRun" in task_run_center_text
        and "markTaskRunInterrupted" in task_run_center_text
        and "重跑失败" not in task_run_center_text
        and "等待规划" not in task_run_center_text,
        "任务中心前端必须消费后端 display_status/available_actions，不得继续用底层 status/summary_json 自行拼主状态和旧文案",
    )
    assert_true(
        "display_status == \"cancel_requested\"" in task_runs_api
        and "仅在详情诊断中展示" in task_runs_api
        and "base_total_result = await db.execute(base_count_query)" in task_runs_api
        and "filtered_total=filtered_total" in task_runs_api
        and "scan_query" not in task_runs_api
        and "filtered_responses" not in task_runs_api
        and "step_key_superseded" not in task_runs_api,
        "任务中心 list API 的 display_status 筛选必须 SQL 化并保留 base_total/filtered_total；stale_running/waiting_dependency/planned 只能作为详情诊断态，列表必须明确拒绝",
    )
    task_runs_list_filter_section = task_runs_api.split("def _superseded_sql_condition", 1)[1].split("def _step_response", 1)[0]
    assert_true(
        "exists(" not in task_runs_list_filter_section
        and "_running_step_exists" not in task_runs_list_filter_section
        and "_ready_step_exists" not in task_runs_list_filter_section
        and "_pending_step_exists" not in task_runs_list_filter_section
        and "_no_steps_exist" not in task_runs_list_filter_section,
        "任务中心列表筛选必须依赖 task_runs 已落表字段，不能保留 correlated EXISTS/NOT EXISTS 或 step 子查询 helper",
    )
    assert_true(
        "TaskRun.status.in_((RUN_STATUS_SUCCEEDED, RUN_STATUS_CANCELED))" in task_runs_api,
        "任务中心 history 默认视图必须使用轻量终态/superseded 条件，避免小数据量历史页出现十几秒级延迟",
    )
    superseded_sql_section = task_runs_api.split("def _superseded_sql_condition", 1)[1].split("def _apply_condition", 1)[0]
    assert_true(
        "superseded_by_run_id.is_not(None)" in superseded_sql_section
        and "EXISTS" not in superseded_sql_section.upper()
        and "correlation_key" not in superseded_sql_section,
        "任务中心列表不能用 correlation_key 自关联实时推断 superseded；必须依赖写入/回填好的 superseded_by_run_id",
    )
    terminal_sql_section = task_runs_api.split("def _terminal_base_condition", 1)[1].split("def _canceled_sql_condition", 1)[0]
    assert_true(
        "TaskRun.status == status" in terminal_sql_section
        and "_running_step_exists" not in terminal_sql_section
        and "_ready_step_exists" not in terminal_sql_section
        and "_pending_step_exists" not in terminal_sql_section
        and "_cancel_requested_sql_condition" not in terminal_sql_section,
        "任务中心 succeeded/failed/interrupted/paused 等终态筛选必须直接读 task_runs.status，不能为了终态列表再查 task_steps",
    )
    list_task_runs_section = task_runs_api.split("async def list_task_runs", 1)[1].split('@router.post("/giga-pull"', 1)[0]
    assert_true(
        "selectinload(" not in list_task_runs_section
        and "_load_runs_for_lineage" not in list_task_runs_section,
        "任务中心主列表必须是 task_runs 单表查询；step/group/event 关联数据只允许详情页读取",
    )
    assert_true(
        "page_size: targetPageSize" in task_run_center_text
        and "setTotal(data.total)" in task_run_center_text
        and "useCallback" in task_run_center_text
        and "detailsRef.current" in task_run_center_text
        and "initialViewFromParams(searchParams)" in task_run_center_text
        and "sanitizeDisplayStatusParam(searchParams.get('display_status'))" in task_run_center_text
        and "searchParams.get('task_type')" in task_run_center_text
        and "{ value: 'stale_running'" not in task_run_center_text
        and "showTotal: (value) => `共 ${value} 条`" in task_run_center_text
        and "pagination={false}" not in task_run_center_text.split("<Table", 1)[1].split("columns={[", 1)[0],
        "任务中心主表必须接入后端分页和 total，轮询必须使用最新筛选/分页参数；URL 初始化 display_status 必须清理不支持的诊断态，前端不能展示 stale_running 列表筛选",
    )


def test_task_run_display_status_behaviour_for_current_view() -> None:
    spec = importlib.util.spec_from_file_location(
        "task_runtime_display",
        ROOT / "backend" / "app" / "task_runtime" / "display.py",
    )
    assert_true(spec is not None and spec.loader is not None, "必须能加载 task_runtime display helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    task_run_matches_display_filters = module.task_run_matches_display_filters

    assert_true(
        task_run_matches_display_filters(display_status="queued", view="current"),
        "current view 必须保留 queued 当前任务",
    )
    assert_true(
        not task_run_matches_display_filters(display_status="superseded", view="current"),
        "current view 不能混入 superseded 历史任务",
    )
    assert_true(
        task_run_matches_display_filters(display_status="superseded", view="history"),
        "history view 必须能看到 superseded 历史任务",
    )
    assert_true(
        not task_run_matches_display_filters(display_status="queued", view="history"),
        "history view 不能混入 queued 当前任务",
    )
    assert_true(
        task_run_matches_display_filters(display_status="failed", view="current", display_status_filter="failed"),
        "display_status filter 必须保留匹配状态",
    )
    assert_true(
        not task_run_matches_display_filters(display_status="failed", view="current", display_status_filter="queued"),
        "display_status filter 必须过滤不匹配状态",
    )


def test_task_run_list_default_views_are_db_pageable() -> None:
    spec = importlib.util.spec_from_file_location(
        "task_runtime_display",
        ROOT / "backend" / "app" / "task_runtime" / "display.py",
    )
    assert_true(spec is not None and spec.loader is not None, "必须能加载 task_runtime display helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    task_run_list_is_db_pageable = module.task_run_list_is_db_pageable

    assert_true(
        task_run_list_is_db_pageable(view="current", display_status_filter=None),
        "task_runs 默认 current 视图必须走 DB 分页快路径，不能全表装饰后分页",
    )
    assert_true(
        task_run_list_is_db_pageable(view="history", display_status_filter=None),
        "task_runs history 无 display_status 时也应走 DB 分页快路径",
    )
    assert_true(
        task_run_list_is_db_pageable(view="current", display_status_filter="failed"),
        "failed 等页面常用状态筛选必须走 DB 分页快路径，不能扫描窗口后内存分页",
    )
    assert_true(
        not task_run_list_is_db_pageable(view="current", display_status_filter="stale_running"),
        "stale_running 本轮只能作为详情诊断态，不能被声明为列表 DB-pageable 筛选",
    )
    assert_true(
        task_run_list_is_db_pageable(view="current", display_status_filter="cancel_requested"),
        "cancel_requested 必须走 DB 分页，不能进入受控装饰/扫描路径",
    )


def test_task_run_shrink_route_rejects_diagnostic_list_filters() -> None:
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    task_runs_api = (ROOT / "backend" / "app" / "api" / "task_runs.py").read_text(encoding="utf-8")
    scheduler_text = (ROOT / "backend" / "app" / "task_runtime" / "scheduler.py").read_text(encoding="utf-8")
    main_text = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    task_runtime_display = (ROOT / "backend" / "app" / "task_runtime" / "display.py").read_text(encoding="utf-8")

    assert_true(
        "display_status: Mapped" not in models_text
        and "available_actions_json" not in models_text
        and "projection_updated_at" not in models_text,
        "本轮收缩路线不能继续把未验收 projection 字段挂到 TaskRun ORM；已存在物理列不在本轮 DROP",
    )
    assert_true(
        "idx_task_runs_display_status_id" not in database_text
        and "(\"display_status\", \"VARCHAR(40) NULL\")" not in database_text
        and "(\"available_actions_json\", \"LONGTEXT NULL\")" not in database_text,
        "本轮不能继续通过 schema ensure 扩大 task_runs display projection；也不能新增 display_status 列表筛选索引",
    )
    assert_true(
        "TaskRun.display_status" not in task_runs_api
        and "task_run_projection_from_fields" not in task_runs_api
        and "refresh_task_run_projection" not in task_runs_api,
        "任务中心列表/API 不能依赖未验收 projection route",
    )
    assert_true(
        "refresh_task_run_projection" not in scheduler_text
        and "backfill_task_run_display_projections" not in main_text
        and "backfill_task_run_display_projections" not in task_runtime_display,
        "本轮必须移除 scheduler projection persistence 和 startup projection backfill",
    )

    code = r'''
from fastapi import HTTPException
from app.api.task_runs import _display_status_sql_condition

for value in ("stale_running", "waiting_dependency", "planned"):
    try:
        _display_status_sql_condition(value)
    except HTTPException as exc:
        assert exc.status_code == 400, (value, exc.status_code)
        assert "仅在详情诊断" in str(exc.detail), (value, exc.detail)
    else:
        raise AssertionError(f"{value} must be rejected for list filtering")
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"诊断态列表筛选拒绝行为验证失败: {result.stderr or result.stdout}")


def test_task_run_detail_keeps_stale_running_diagnostic_state() -> None:
    code = r'''
from datetime import datetime, timedelta
from types import SimpleNamespace
from app.api.task_runs import _run_display
from app.task_runtime.constants import RUN_STATUS_RUNNING
from app.task_runtime.constants import STEP_STATUS_RUNNING

step = SimpleNamespace(
    id=101,
    sort_order=1,
    status=STEP_STATUS_RUNNING,
    step_type="giga_pull_detail_chunk",
    error_message=None,
    heartbeat_at=datetime.now() - timedelta(minutes=20),
    locked_until=datetime.now() - timedelta(minutes=1),
    progress_total=5,
    progress_current=2,
)
run = SimpleNamespace(
    id=11,
    task_type="giga_pull",
    title="stale detail run",
    status=RUN_STATUS_RUNNING,
    summary_json=None,
    steps=[step],
    groups=[],
    dedupe_key=None,
    correlation_key=None,
    superseded_by_run_id=None,
    cancel_requested_at=None,
    created_at=None,
)
display = _run_display(run, superseded_by_run_id=None)
assert display["display_status"] == "stale_running", display
assert "wake_runtime" in display["available_actions"], display
assert "mark_interrupted" in display["available_actions"], display
assert "cancel" not in display["available_actions"], display
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"详情 stale_running 诊断态行为验证失败: {result.stderr or result.stdout}")


def test_runtime_security_startup_p0_boundaries() -> None:
    start_script = (ROOT / "scripts" / "start.sh").read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    env_example = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    main_text = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    config_text = (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    aplus_upload = (ROOT / "backend" / "app" / "services" / "aplus_upload.py").read_text(encoding="utf-8")
    step9_image = (ROOT / "backend" / "app" / "pipeline" / "step9_aplus_image.py").read_text(encoding="utf-8")
    runtime_security_index = (ROOT / "docs" / "domain-index" / "runtime-security.md").read_text(encoding="utf-8")

    assert_true(
        'BACKEND_HOST="$(read_env BACKEND_HOST 127.0.0.1)"' in start_script
        and 'FRONTEND_HOST="$(read_env FRONTEND_HOST 127.0.0.1)"' in start_script
        and "--host 0.0.0.0" not in start_script
        and "--host 0.0.0.0" not in readme_text,
        "默认启动命令必须只监听 127.0.0.1，不能继续绑定 0.0.0.0",
    )
    assert_true(
        "API_DEV_TOKEN" in config_text
        and "def _is_local_client" in main_text
        and "def _has_valid_dev_token" in main_text
        and '@app.middleware("http")' in main_text
        and "request.method.upper() not in SAFE_HTTP_METHODS" in main_text,
        "mutating API 必须有本机访问或显式 dev token 边界，不能远程匿名写 .env/触发任务/文件操作",
    )
    assert_true(
        "STARTUP_RUN_DB_MAINTENANCE: bool = False" in config_text
        and "STARTUP_RUN_BACKFILLS: bool = False" in config_text
        and "STARTUP_RECOVER_TASKS: bool = False" in config_text
        and "STARTUP_KICK_TASK_RUNTIME: bool = False" in config_text
        and "if settings.STARTUP_RUN_DB_MAINTENANCE:" in main_text
        and "if settings.STARTUP_RUN_BACKFILLS:" in main_text
        and "if settings.STARTUP_RECOVER_TASKS:" in main_text
        and "if settings.STARTUP_KICK_TASK_RUNTIME:" in main_text
        and "await conn.run_sync(Base.metadata.create_all)" in database_text,
        "普通 API startup 不能默认 DDL/backfill/recover/kick；维护动作必须由显式配置开启",
    )
    assert_true(
        "python -m app.database" in start_script
        and "async def run_schema_maintenance" in database_text
        and "asyncio.run(run_schema_maintenance())" in database_text,
        "本地一键启动必须显式执行可重复 schema maintenance，避免 ORM 新字段缺列导致商品 API 500",
    )
    assert_true(
        "async def _ensure_mysql_registered_tables" in database_text
        and "await _ensure_mysql_registered_tables(conn)" in database_text
        and database_text.index("await _ensure_mysql_registered_tables(conn)") < database_text.index("await _ensure_mysql_product_data_source_columns(conn)")
        and "await conn.run_sync(table.create, checkfirst=True)" in database_text,
        "schema maintenance 必须先确保所有 ORM 表存在，再执行表级列/索引 ensure，避免缺整表时启动维护失败",
    )
    assert_true(
        "EXTERNAL_HTTP_VERIFY_TLS: bool = True" in config_text
        and "EXTERNAL_HTTP_CA_BUNDLE" in config_text
        and "def external_http_verify" in config_text
        and "verify=False" not in config_text
        and "verify=False" not in aplus_upload
        and "verify=not settings.GPT_IMAGE_USE_LLM_API" not in step9_image
        and "verify=settings.external_http_verify" in aplus_upload
        and "verify=settings.external_http_verify" in step9_image,
        "外部 token-bearing HTTP 请求必须默认 TLS verify on，不能默认 verify=False 或按 provider 关闭校验",
    )
    assert_true(
        "IMAGE_PROXY_EXTRA_ROOTS" in config_text
        and ".relative_to(" in main_text
        and "Documents" not in main_text.split("_IMAGE_ROOTS", 1)[1].split("IMAGE_EXTENSIONS", 1)[0]
        and 'Path("/tmp")' not in main_text
        and "Access denied: path outside allowed roots" not in main_text,
        "图片代理必须默认只开放业务目录/显式额外目录，结构化校验路径且不泄漏完整本机路径",
    )
    assert_true(
        "API_DEV_TOKEN" in env_example
        and "STARTUP_RUN_DB_MAINTENANCE=false" in env_example
        and "EXTERNAL_HTTP_VERIFY_TLS=true" in env_example
        and "IMAGE_PROXY_EXTRA_ROOTS=" in env_example
        and "本地服务绑定" in runtime_security_index
        and "STARTUP_RUN_DB_MAINTENANCE" in runtime_security_index,
        "P0 安全/启动边界改动必须同步 .env.example 和 runtime-security 索引",
    )


def test_runtime_security_helpers_behaviour() -> None:
    code = r'''
from types import SimpleNamespace
from pathlib import Path
from app import main

class Client:
    def __init__(self, host):
        self.host = host

assert main._is_local_client(Client("127.0.0.1"))
assert main._is_local_client(Client("::1"))
assert not main._is_local_client(Client("192.168.1.10"))
assert main._has_valid_dev_token(SimpleNamespace(headers={"X-FBM-Dev-Token": "secret"}), "secret")
assert main._has_valid_dev_token(SimpleNamespace(headers={"Authorization": "Bearer secret"}), "secret")
assert not main._has_valid_dev_token(SimpleNamespace(headers={}), "secret")
assert not main._has_valid_dev_token(SimpleNamespace(headers={"X-FBM-Dev-Token": "bad"}), "secret")

root = Path("/tmp/fbm-security-root").resolve()
inside = root / "images" / "a.jpg"
outside = Path("/tmp/fbm-security-root-evil/a.jpg").resolve()
assert main._path_is_within_roots(inside, [root])
assert not main._path_is_within_roots(outside, [root])
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"P0 security helper 行为验证失败: {result.stderr or result.stdout}")


def test_failed_task_run_display_precedes_pending_steps() -> None:
    code = r'''
from types import SimpleNamespace
from app.api.task_runs import _run_display
from app.task_runtime.constants import RUN_STATUS_FAILED, STEP_STATUS_FAILED, STEP_STATUS_PENDING

def step(id, order, status, err=None):
    return SimpleNamespace(
        id=id,
        sort_order=order,
        status=status,
        step_type="giga_pull_detail_chunk",
        error_message=err,
        heartbeat_at=None,
        locked_until=None,
        progress_total=1,
        progress_current=0,
    )

run = SimpleNamespace(
    id=10,
    task_type="giga_pull",
    title="failed multi-step",
    status=RUN_STATUS_FAILED,
    summary_json=None,
    steps=[step(1, 1, STEP_STATUS_FAILED, "boom"), step(2, 2, STEP_STATUS_PENDING)],
    groups=[],
    dedupe_key=None,
    correlation_key=None,
    superseded_by_run_id=None,
    cancel_requested_at=None,
    created_at=None,
)
display = _run_display(run, superseded_by_run_id=None)
assert display["display_status"] == "failed", display
assert "retry_failed_steps" in display["available_actions"], display
assert "cancel" not in display["available_actions"], display
assert display["error_summary"] == "boom", display
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"failed run 展示优先级行为验证失败: {result.stderr or result.stdout}")


def test_task_run_creation_responses_reload_created_runs() -> None:
    code = r'''
import asyncio
from types import SimpleNamespace
from app.api import task_runs
from app.task_runtime.constants import RUN_STATUS_PENDING, STEP_STATUS_READY

def run(id, steps=None):
    return SimpleNamespace(
        id=id,
        task_type="giga_pull",
        title=f"run {id}",
        status=RUN_STATUS_PENDING,
        summary_json=None,
        steps=steps or [],
        groups=[],
        dedupe_key=None,
        correlation_key=None,
        superseded_by_run_id=None,
        cancel_requested_at=None,
        created_at=None,
    )

async def main():
    original_load = task_runs._load_run
    async def fake_load_run(db, run_id):
        return run(
            run_id,
            [
                SimpleNamespace(
                    id=100 + run_id,
                    sort_order=1,
                    status=STEP_STATUS_READY,
                    step_type="giga_pull_plan",
                    error_message=None,
                    heartbeat_at=None,
                    locked_until=None,
                    progress_total=1,
                    progress_current=0,
                )
            ],
        )
    task_runs._load_run = fake_load_run
    try:
        loaded = await task_runs._reload_created_runs_for_response(SimpleNamespace(), [run(7)])
    finally:
        task_runs._load_run = original_load
    assert [item.id for item in loaded] == [7]
    response = task_runs._run_response(loaded[0])
    assert response.display_status == "queued", response
    assert response.current_step_label == "规划 SKU", response

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"创建任务响应 reload 行为验证失败: {result.stderr or result.stdout}")


def test_product_action_backfill_updates_only_task_run_metadata() -> None:
    code = r'''
import asyncio
from datetime import datetime, timedelta
from app.models import TaskRun
from app.product_tasks.actions import backfill_product_action_task_run_keys
from app.task_runtime.constants import RUN_STATUS_FAILED, RUN_STATUS_INTERRUPTED, RUN_STATUS_SUCCEEDED
from app.task_runtime.json_utils import json_dumps

class FakeScalars:
    def __init__(self, rows):
        self.rows = rows
    def all(self):
        return self.rows

class FakeResult:
    def __init__(self, rows):
        self.rows = rows
    def scalars(self):
        return FakeScalars(self.rows)

class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.execute_count = 0
        self.commit_count = 0
        self.rollback_count = 0
    async def execute(self, statement):
        text = str(statement)
        assert "task_runs" in text
        assert "products" not in text.lower()
        self.execute_count += 1
        return FakeResult(self.rows)
    async def commit(self):
        self.commit_count += 1
    async def rollback(self):
        self.rollback_count += 1

def make_run(id, task_type, product_id, status, *, superseded_by_run_id=None, offset=0):
    return TaskRun(
        id=id,
        task_type=task_type,
        title=f"run {id}",
        status=status,
        payload_json=json_dumps({"product_id": product_id}) if product_id else json_dumps({"note": "no product"}),
        created_at=datetime(2026, 6, 17) + timedelta(minutes=offset),
        superseded_by_run_id=superseded_by_run_id,
    )

async def main():
    old_failed = make_run(1, "product_image_analysis", 101, RUN_STATUS_FAILED, offset=1)
    later_failed = make_run(2, "product_image_analysis", 101, RUN_STATUS_FAILED, offset=2)
    succeeded = make_run(3, "product_listing_generation", 202, RUN_STATUS_SUCCEEDED, offset=3)
    later_interrupted = make_run(4, "product_listing_generation", 202, RUN_STATUS_INTERRUPTED, offset=4)
    already_superseded = make_run(5, "product_image_analysis", 303, RUN_STATUS_FAILED, superseded_by_run_id=99, offset=5)
    current_failed = make_run(6, "product_image_analysis", 303, RUN_STATUS_FAILED, offset=6)
    no_product = make_run(7, "product_image_analysis", None, RUN_STATUS_FAILED, offset=7)
    db = FakeDb([old_failed, later_failed, succeeded, later_interrupted, already_superseded, current_failed, no_product])

    changed = await backfill_product_action_task_run_keys(db)

    assert changed >= 8, changed
    assert db.execute_count == 1
    assert db.commit_count == 1
    assert db.rollback_count == 0
    assert old_failed.dedupe_key == "product_image_analysis:product:101"
    assert old_failed.correlation_key == "product:101:image_analysis"
    assert old_failed.superseded_by_run_id == later_failed.id
    assert old_failed.superseded_at is not None
    assert later_failed.superseded_by_run_id is None
    assert succeeded.superseded_by_run_id is None
    assert already_superseded.superseded_by_run_id == 99
    assert no_product.dedupe_key is None
    assert no_product.correlation_key is None
    assert no_product.superseded_by_run_id is None

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"ProductTaskAction backfill 行为验证失败: {result.stderr or result.stdout}")


def test_product_task_action_reserve_states_are_not_marked_interrupted() -> None:
    code = r'''
import asyncio
from types import SimpleNamespace
from app.api.products import _current_task_status, _workflow_state
from app.product_tasks import actions as product_actions
from app.models.status import (
    STEP5_LISTING,
    STEP6_CURATING,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_STATUS_PROCESSING,
)

samples = [
    (STEP6_CURATING, 5, "图片分析已加入任务中心队列", WORKFLOW_NODE_IMAGE_ANALYSIS),
    (STEP5_LISTING, 6, "Listing 生成已加入任务中心队列", WORKFLOW_NODE_LISTING_GENERATION),
]

class ProductResult:
    def __init__(self, product):
        self.product = product
    def scalar_one_or_none(self):
        return self.product

class FakeDb:
    def __init__(self, product):
        self.product = product
    async def execute(self, statement):
        return ProductResult(self.product)

async def main():
    original_load_product = product_actions._load_product
    async def fake_load_product(_db, _product_id):
        return fake_load_product.product
    fake_load_product.product = None
    try:
        for action, status, step, message, workflow_node in [
            (product_actions.ProductImageAnalysisAction(), *samples[0]),
            (product_actions.ProductListingGenerationAction(), *samples[1]),
        ]:
            product = SimpleNamespace(
                id=999999,
                status="created",
                current_step=0,
                error_message=None,
                competitor_asin="B000TEST",
                amazon_asin=None,
                asin_sync_status=None,
                asin_synced_at=None,
                asin_sync_error=None,
                amazon_product_status=None,
                amazon_product_status_synced_at=None,
                amazon_product_status_error=None,
                aplus_upload_status="not_uploaded",
                aplus_uploaded_at=None,
                aplus_upload_error=None,
                data=None,
                files=[],
                catalog_item=None,
                workflow_node=None,
                workflow_status=None,
                workflow_error=None,
                workflow_updated_at=None,
                updated_at=None,
            )
            fake_load_product.product = product
            product_actions._load_product = fake_load_product
            await action.reserve(FakeDb(product), {"product_id": product.id}, SimpleNamespace())
            assert product.status == status, product
            assert product.current_step == step, product
            assert product.error_message == message, product
            assert product.workflow_node == workflow_node, product
            assert product.workflow_status == WORKFLOW_STATUS_PROCESSING, product
            assert product.workflow_error == message, product
            workflow = _workflow_state(product, catalog_exported=False)
            assert workflow["stage"] == workflow_node, workflow
            assert workflow["stage_status"] == WORKFLOW_STATUS_PROCESSING, workflow
            assert workflow["primary_action"] == "open_task_center", workflow
            assert workflow["primary_action"] != "retry", workflow
            assert workflow["work_status"] != "interrupted", workflow
            assert "中断" not in _current_task_status(product)
    finally:
        product_actions._load_product = original_load_product

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"ProductTaskAction reserve workflow 入队态验证失败: {result.stderr or result.stdout}")


def test_product_action_lifecycle_writes_workflow_fields() -> None:
    code = r'''
import asyncio
from types import SimpleNamespace
from app.product_tasks import actions as product_actions
from app.models.status import (
    COMPLETED,
    FAILED,
    PAUSED,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_IMAGE_ANALYSIS,
    WORKFLOW_NODE_LISTING_GENERATION,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_SUCCEEDED,
)

class FakeDb:
    def __init__(self, product):
        self.product = product
        self.commit_count = 0
    async def commit(self):
        self.commit_count += 1

def product():
    return SimpleNamespace(
        id=1001,
        status="created",
        current_step=0,
        error_message=None,
        workflow_node=None,
        workflow_status=None,
        workflow_error=None,
        workflow_updated_at=None,
        updated_at=None,
        data=None,
        catalog_item=None,
        gigab2b_url="https://example.test/item",
        gigab2b_product_id="G1001",
        competitor_asin=None,
        amazon_asin=None,
        asin_sync_status=None,
        asin_synced_at=None,
        asin_sync_error=None,
        amazon_product_status=None,
        amazon_product_status_synced_at=None,
        amazon_product_status_error=None,
        aplus_upload_status=None,
        aplus_uploaded_at=None,
        aplus_upload_error=None,
        upc=None,
        brand="Vindhvisk",
    )

async def main():
    original_load_product = product_actions._load_product
    async def fake_load_product(_db, _product_id):
        return fake_load_product.product
    fake_load_product.product = None
    try:
        failed = product()
        fake_load_product.product = failed
        product_actions._load_product = fake_load_product
        db = FakeDb(failed)
        await product_actions._project_product_failure(db, product_id=failed.id, step=5, label="图片分析", error="boom")
        assert failed.status == FAILED
        assert failed.workflow_node == WORKFLOW_NODE_IMAGE_ANALYSIS
        assert failed.workflow_status == WORKFLOW_STATUS_FAILED
        assert failed.workflow_error == "boom"
        assert db.commit_count == 1

        paused = product()
        fake_load_product.product = paused
        await product_actions._project_product_paused(db, product_id=paused.id, step=6, message="Listing 生成任务已取消")
        assert paused.status == PAUSED
        assert paused.workflow_node == WORKFLOW_NODE_LISTING_GENERATION
        assert paused.workflow_status == WORKFLOW_STATUS_FAILED
        assert paused.workflow_error == "Listing 生成任务已取消"

        done = product()
        product_actions._project_listing_completed(done)
        assert done.status == COMPLETED
        assert done.workflow_node == WORKFLOW_NODE_FLOW_DONE
        assert done.workflow_status == WORKFLOW_STATUS_SUCCEEDED
        assert done.workflow_error is None
    finally:
        product_actions._load_product = original_load_product

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"ProductTaskAction lifecycle workflow 写入验证失败: {result.stderr or result.stdout}")


def test_image_analysis_listing_e5_contract() -> None:
    actions_text = (ROOT / "backend" / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    products_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    workflow_text = (ROOT / "backend" / "app" / "product_tasks" / "workflow.py").read_text(encoding="utf-8")
    product_list_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")

    image_section = actions_text.split("class ProductImageAnalysisAction", 1)[1].split("class ProductListingGenerationAction", 1)[0]
    listing_section = actions_text.split("class ProductListingGenerationAction", 1)[1].split("async def _existing_active_run", 1)[0]
    retry_section = products_text.split("async def retry_step", 1)[1].split("async def run_product_from_step", 1)[0]
    product_list_action_section = product_list_text.split("const renderPrimaryRowAction", 1)[1].split("const columns =", 1)[0]
    e5_sections = image_section + "\n" + listing_section

    assert_true(
        actions_text.count("_project_listing_completed(") == 2
        and "ProductListingGenerationAction().on_step_success" not in actions_text,
        "E5 只能由 ProductListingGenerationAction.on_step_success 调用 _project_listing_completed；不能新增其它 completed 投影入口",
    )
    assert_true(
        "def _e5_export_ready_protection_reasons" in actions_text
        and "_raise_if_e5_export_ready_protected(product, action_label=\"启动图片分析\")" in image_section
        and "_raise_if_e5_export_ready_protected(product, action_label=\"启动 Listing 生成\")" in listing_section
        and "_raise_if_e5_export_ready_protected(product, action_label=\"完成 Listing 并进入待导出\")" in listing_section,
        "E5 图片分析/Listing reserve/success 必须走专用保护 helper，阻断外部不可逆事实",
    )
    assert_true(
        "already_completed" in image_section
        and "downstream_failed" in image_section
        and "create_product_action_runs(" in image_section
        and "self._listing_action_type()" in image_section,
        "图片分析 success 必须 completed no-op，并且只通过 ProductTaskAction planner 创建/复用 Listing run，创建失败要可见",
    )
    assert_true(
        "confirmed_at = None" not in listing_section
        and "confirmed_at = None" not in retry_section,
        "E5 Listing reserve/retry 不得清空 CatalogProduct.confirmed_at；预先确认必须由保护门阻断",
    )
    assert_true(
        '"retry_image_analysis"' in workflow_text
        and '"retry_listing_generation"' in workflow_text
        and "workflowAction === 'retry_image_analysis' || workflowAction === 'retry_listing_generation'" in product_list_action_section
        and "await retryStep(product.id)" in product_list_action_section,
        "workflow 暴露的 retry_image_analysis/retry_listing_generation 必须在 ProductList 映射到后端安全 retry，不能成为 ghost action",
    )
    for forbidden in (
        "create_catalog_export_tasks",
        "run_amazon_template",
        "aplus_upload",
        "Seller Central",
        "sellercentral",
        "tiktok",
        "BackgroundTasks",
        "threading.Thread",
        "enqueue_pipeline(",
    ):
        assert_true(forbidden not in e5_sections, f"E5 image/listing action 不得触发导出/A+/上传/TikTok/旧 pipeline 副作用: {forbidden}")


def test_aplus_auto_after_export_ready_a1_a2_contract() -> None:
    config_text = (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    env_text = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    service_path = ROOT / "backend" / "app" / "services" / "aplus_auto_trigger.py"
    service_text = service_path.read_text(encoding="utf-8")
    actions_text = (ROOT / "backend" / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    aplus_planner_text = (ROOT / "backend" / "app" / "task_planners" / "aplus_generate.py").read_text(encoding="utf-8")
    behavior_script = ROOT / "scripts" / "test_aplus_auto_trigger_a1_a2.py"
    behavior_text = behavior_script.read_text(encoding="utf-8")

    assert_true(
        "AUTO_APLUS_AFTER_EXPORT_READY: bool = False" in config_text
        and "AUTO_APLUS_AFTER_EXPORT_READY=false" in env_text,
        "A+ 自动触发 A1 必须默认关闭，并在 .env.example 明确 false",
    )
    assert_true(
        service_path.is_file()
        and "class AplusAutoStartDecision" in service_text
        and "async def should_auto_start_aplus(" in service_text
        and "async def try_auto_start_aplus_after_export_ready(" in service_text
        and "eligible: bool" in service_text
        and "code: str" in service_text
        and "message: str" in service_text
        and "details: dict[str, Any]" in service_text,
        "A+ 自动触发必须提供结构化 eligibility decision service 和 A2 best-effort trigger helper",
    )
    for code in (
        "disabled_by_config",
        "not_completed",
        "not_flow_done",
        "missing_catalog_export_ready",
        "missing_listing_content",
        "missing_image_analysis",
        "main_workflow_active",
        "active_aplus_task",
        "aplus_done",
        "aplus_upload_protected",
        "real_asin_protected",
        "export_history_protected",
        "template_output_protected",
        "eligible",
    ):
        assert_true(f'"{code}"' in service_text, f"A1 decision code 缺失: {code}")
    assert_true(
        "Product.status == completed" in service_text
        or "product.status != COMPLETED" in service_text,
        "A1 eligibility 必须要求 Product.status completed",
    )
    assert_true(
        "WORKFLOW_NODE_FLOW_DONE" in service_text
        and "WORKFLOW_STATUS_SUCCEEDED" in service_text
        and "catalog.confirmed_at is None" in service_text
        and "missing_catalog_export_ready" in service_text,
        "A1 eligibility 必须要求 flow_done/succeeded 和 CatalogProduct.confirmed_at 待导出证据",
    )
    assert_true(
        "listing_title" in service_text
        and "listing_bullets" in service_text
        and "image_analysis" in service_text,
        "A1 eligibility 必须检查 Listing 内容和图片分析事实",
    )
    assert_true(
        "PRODUCT_MAIN_ACTION_TYPES" in service_text
        and "exclude_task_run_id" in service_text
        and "aplus_generate_product" in service_text,
        "A1 policy 必须检查 active 主流程 task，并支持后续 A2 排除 source listing run，同时阻断 active A+ step",
    )
    assert_true(
        "SAFE_APLUS_UPLOAD_STATUSES" in service_text
        and "product.amazon_asin" in service_text
        and "catalog.amazon_asin" in service_text
        and "catalog.exported_at" in service_text
        and "catalog.export_task_id" in service_text
        and "catalog.export_file_path" in service_text
        and "amazon_template_path" in service_text
        and "amazon_template_fill_summary" in service_text
        and "amazon_template_warnings" in service_text
        and "amazon_template_generated_at" in service_text
        and "ProductFile" in service_text,
        "A1 policy 必须覆盖真实 ASIN、A+ 上传、导出历史、ProductData/ProductFile 模板输出保护",
    )
    for forbidden in (
        "offline_tasks",
        "ProductAplus(",
        "set_product_workflow",
        "product.workflow_node =",
        "product.workflow_status =",
        "product.workflow_error =",
    ):
        assert_true(forbidden not in service_text, f"A+ auto service 不得写商品主流程或使用旧任务/直接写 A+ 状态: {forbidden}")
    assert_true(
        "create_aplus_generate_runs" in service_text
        and "except Exception as exc:" in service_text
        and '"trigger_failed"' in service_text
        and '"reused"' in service_text
        and '"active_aplus_task"' in service_text,
        "A2 helper 必须通过现有 A+ planner best-effort 创建/复用，并结构化记录失败/复用",
    )

    listing_section = actions_text.split("class ProductListingGenerationAction", 1)[1].split("async def _existing_active_run", 1)[0]
    assert_true(
        "_project_listing_completed(product)" in listing_section
        and "await db.commit()" in listing_section
        and "try_auto_start_aplus_after_export_ready" in listing_section
        and listing_section.index("_project_listing_completed(product)") < listing_section.index("await db.commit()")
        and listing_section.index("await db.commit()") < listing_section.index("try_auto_start_aplus_after_export_ready"),
        "A2 Listing success hook 必须在 E5 export-ready 投影提交后再 best-effort 触发 A+",
    )
    assert_true(
        '"aplus_auto_trigger"' in listing_section
        and 'summary["aplus_auto_trigger"]' in listing_section
        and "result[\"aplus_auto_trigger\"]" in listing_section
        and "_best_effort_update_step_progress" in listing_section,
        "A2 必须把自动触发结果写入 listing task summary/result/progress data，并保留原 summary 字段",
    )
    assert_true(
        "async def create_aplus_generate_runs(" in aplus_planner_text
        and "kick_task_runtime()" in aplus_planner_text
        and "dedupe_key=f\"aplus_generate:product:{auto_product_id}\"" in aplus_planner_text
        and "correlation_key=f\"product:{auto_product_id}:aplus_generate\"" in aplus_planner_text,
        "A+ planner 仍是独立已有能力，A2 自动单品 run 必须带 dedupe/correlation metadata",
    )
    assert_true(
        behavior_script.is_file()
        and 'parser.add_argument("--stage", default="a1", choices=("a1", "a2"))' in behavior_text
        and "run_schema_maintenance()" in behavior_text
        and "eligible" in behavior_text
        and "active_aplus_task" in behavior_text
        and "_test_listing_success_default_off_noops" in behavior_text
        and "_test_listing_success_enabled_creates_aplus_task" in behavior_text
        and "_test_try_helper_reuses_existing_active_aplus" in behavior_text
        and "_test_listing_success_aplus_failure_does_not_rollback_export_ready" in behavior_text
        and "before_runs == after_runs" in behavior_text
        and "before_status == after_status" in behavior_text,
        "A+ 必须有 deterministic DB 行为脚本，覆盖 A1 policy 和 A2 no-op/创建/复用/失败隔离",
    )


def test_lingxing_aplus_publish_t1_data_registry_bootstrap_contract() -> None:
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    frontend_api_text = (ROOT / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")
    status_path = ROOT / "backend" / "app" / "aplus_publish" / "status.py"
    state_path = ROOT / "backend" / "app" / "services" / "aplus_publish_state.py"
    status_text = status_path.read_text(encoding="utf-8")
    state_text = state_path.read_text(encoding="utf-8")
    task_runs_api_text = (ROOT / "backend" / "app" / "api" / "task_runs.py").read_text(encoding="utf-8")
    aplus_generate_worker_text = (ROOT / "backend" / "app" / "task_runtime" / "aplus_generate_workers.py").read_text(encoding="utf-8")

    for field in (
        "amazon_seller_sku",
        "asin_match_source",
        "asin_match_evidence_json",
    ):
        assert_true(f"{field}: Mapped[str | None]" in models_text, f"Product/CatalogProduct ORM 缺少 durable 字段: {field}")
        assert_true(f'("{field}",' in database_text, f"MySQL schema ensure 必须补齐 Product/CatalogProduct.{field}")
        assert_true(field in schemas_text and field in frontend_api_text, f"API schema/frontend type 必须暴露 durable 字段: {field}")

    for field in (
        "lingxing_aplus_id_hash",
        "lingxing_status_text",
        "amazon_draft_visibility",
        "draft_visible_at",
        "submitted_at",
        "publish_evidence_json",
        "source_task_run_id",
        "source_task_step_id",
        "product_aplus_id",
        "aplus_content_fingerprint",
        "seller_sku_used",
        "store_id",
        "site",
    ):
        assert_true(field in models_text, f"AplusUploadItem ORM 缺少发布证据字段: {field}")
        assert_true(f'("{field}",' in database_text, f"MySQL schema ensure 必须补齐 AplusUploadItem.{field}")
        assert_true(field in schemas_text and field in frontend_api_text, f"API schema/frontend type 必须暴露 AplusUploadItem 证据字段: {field}")

    for index_name in (
        "ix_catalog_amazon_seller_sku",
        "ix_catalog_amazon_asin",
        "ix_catalog_aplus_upload_status",
        "ix_aplus_upload_items_lingxing_id_hash",
        "ix_aplus_upload_items_draft_visibility",
        "ix_aplus_upload_items_product_aplus",
    ):
        assert_true(index_name in database_text, f"缺少 Lingxing A+ T1 MySQL 索引 ensure: {index_name}")

    required_statuses = (
        "not_uploaded",
        "checking",
        "waiting_listing",
        "syncing_listing",
        "ready_to_upload",
        "uploading",
        "draft_saved",
        "draft_confirming",
        "draft_visible",
        "submitted",
        "failed",
        "skipped",
        "auth_required",
    )
    for status in required_statuses:
        assert_true(f'"{status}"' in status_text, f"aplus_publish status registry 缺少状态: {status}")
    assert_true(
        "STATUS_REGISTRY" in status_text
        and "ALL_APLUS_PUBLISH_STATUSES" in status_text
        and "LEGACY_APLUS_PUBLISH_STATUS_MAP" in status_text
        and '"pending": STATUS_CHECKING' in status_text
        and '"running": STATUS_UPLOADING' in status_text
        and "ITEM_ONLY_LEGACY_STATUSES" in status_text
        and "UnknownAplusPublishStatus" in status_text,
        "A+ publish registry 必须包含状态全集、legacy 映射和 unknown/item-only 拒绝策略",
    )

    assert_true(
        state_path.is_file()
        and "CatalogProduct is required as the primary Lingxing A+ publish fact" in state_text
        and "catalog.aplus_upload_status = normalized_status" in state_text
        and "product.aplus_upload_status = normalized_status" in state_text
        and "item.publish_evidence_json" in state_text
        and "Task runs own execution lifecycle" in state_text
        and "await db.flush()" in state_text
        and "await db.commit()" not in state_text,
        "aplus_publish_state.py 必须作为 Catalog 主事实/Product 镜像/AplusUploadItem 证据的单一写入入口，且不自行提交事务",
    )
    for forbidden in (
        "httpx",
        "chrome_",
        "app.pipeline.chrome_ctrl",
        "task_planners",
        "kick_task_runtime",
        "register_worker",
        "set_product_workflow",
        "workflow_node =",
        "workflow_status =",
    ):
        assert_true(forbidden not in state_text, f"T1 single writer service 不得触发外部调用、任务调度或商品主 workflow: {forbidden}")

    assert_true(
        (ROOT / "backend" / "app" / "task_planners" / "lingxing_listing_sync.py").is_file()
        and (ROOT / "backend" / "app" / "task_runtime" / "lingxing_listing_sync_workers.py").is_file(),
        "T2 后允许且要求新增 Lingxing Listing sync planner/worker",
    )
    for forbidden_path in (
        ROOT / "backend" / "app" / "task_planners" / "lingxing_aplus_draft_visibility.py",
        ROOT / "backend" / "app" / "task_planners" / "lingxing_aplus_submit.py",
    ):
        assert_true(not forbidden_path.exists(), f"T3 仍不允许新增 A+ 可见性/提交 planner: {forbidden_path}")
    assert_true(
        "/lingxing-listing-sync" in task_runs_api_text
        and "AUTO_LINGXING_APLUS_AFTER_DONE" not in aplus_generate_worker_text,
        "T3 仍不允许 A+ done 自动触发",
    )


def test_lingxing_aplus_publish_t3_draft_save_contract() -> None:
    config_text = (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    env_example_text = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    policy_text = (ROOT / "backend" / "app" / "services" / "lingxing_aplus_publish_policy.py").read_text(encoding="utf-8")
    client_text = (ROOT / "backend" / "app" / "services" / "lingxing_aplus_publish_client.py").read_text(encoding="utf-8")
    planner_text = (ROOT / "backend" / "app" / "task_planners" / "lingxing_aplus_publish.py").read_text(encoding="utf-8")
    worker_text = (ROOT / "backend" / "app" / "task_runtime" / "lingxing_aplus_publish_workers.py").read_text(encoding="utf-8")
    task_api_text = (ROOT / "backend" / "app" / "api" / "task_runs.py").read_text(encoding="utf-8")
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    main_text = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    display_text = (ROOT / "backend" / "app" / "task_runtime" / "display.py").read_text(encoding="utf-8")
    aplus_generate_worker_text = (ROOT / "backend" / "app" / "task_runtime" / "aplus_generate_workers.py").read_text(encoding="utf-8")
    policy_script_text = (ROOT / "scripts" / "test_lingxing_aplus_publish_policy.py").read_text(encoding="utf-8")
    task_script_text = (ROOT / "scripts" / "test_lingxing_aplus_publish_tasks.py").read_text(encoding="utf-8")

    assert_true(
        'LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS: bool = False' in config_text
        and 'LINGXING_APLUS_SUBMIT_FOR_APPROVAL: bool = False' in config_text
        and "LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS=false" in env_example_text
        and "LINGXING_APLUS_SUBMIT_FOR_APPROVAL=false" in env_example_text,
        "T3 配置必须默认禁止真实外部调用和提交审批",
    )
    assert_true(
        "def collect_aplus_publish_assets" in policy_text
        and "reason_code=\"image_missing\"" in policy_text
        and "reason_code=\"image_too_small\"" in policy_text
        and "reason_code=\"product_aplus_not_done\"" in policy_text
        and "reason_code=\"asin_not_aligned\"" in policy_text
        and "build_aplus_content_fingerprint" in policy_text
        and "is_protected_status" in policy_text,
        "T3 policy service 必须集中本地 A+ 内容/图片校验、typed reason、fingerprint 和 protected 状态判断",
    )
    assert_true(
        "class LingxingAplusDraftSaveClient" in client_text
        and "if not settings.LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS" in client_text
        and '"real_external_calls_disabled"' in client_text
        and "if settings.LINGXING_APLUS_SUBMIT_FOR_APPROVAL" in client_text
        and '"submit_not_supported_in_t3"' in client_text
        and "UPLOAD_DESTINATION_URL" in client_text
        and "APLUS_ADD_URL" in client_text
        and '"submitFlag": 0' in client_text
        and "APLUS_EDIT_URL" not in client_text
        and "draft_visible" not in client_text
        and "submitted_at" not in client_text,
        "T3 client 必须默认 fail closed，只支持 uploadDestination + add/save draft，不允许 edit/submit/visibility",
    )
    for forbidden in ("start_aplus_upload_batch", "asyncio.create_task", "submitFlag\": 1", "APLUS_EDIT_URL"):
        assert_true(forbidden not in planner_text and forbidden not in worker_text, f"新 T3 链路不得调用旧 batch runner、裸 create_task 或提交路径: {forbidden}")
    assert_true(
        'task_type="lingxing_aplus_publish"' in planner_text
        and 'step_type="lingxing_aplus_publish_product"' in planner_text
        and "dedupe_key=dedupe_key" in planner_text
        and "idempotency_key=dedupe_key" in planner_text
        and "已有 draft_saved/idHash，停止重复创建草稿" in planner_text
        and "ACTIVE_RUN_STATUSES" in planner_text,
        "T3 planner 必须 task-runtime 化，具备 dedupe/idempotency，并在已有 draft_saved/idHash 时停止",
    )
    assert_true(
        "def lingxing_aplus_publish_product" in worker_text
        and "STATUS_DRAFT_SAVED" in worker_text
        and '"amazon_draft_visibility": "unconfirmed"' in worker_text
        and "lingxing_aplus_id_hash" in worker_text
        and "publish_evidence" in worker_text
        and "update_aplus_publish_item_evidence" in worker_text
        and "set_aplus_publish_status" in worker_text
        and "STATUS_AUTH_REQUIRED" in worker_text
        and "STATUS_WAITING_LISTING" not in worker_text
        and "STATUS_DRAFT_VISIBLE" not in worker_text
        and "STATUS_SUBMITTED" not in worker_text,
        "T3 worker 必须只写 draft_saved/unconfirmed/idHash/evidence/auth_required，不得写 draft_visible/submitted",
    )
    draft_save_failure_branch = worker_text.split("except LingxingAplusDraftSaveClientError as exc:", 1)[1].split(
        "\n\n    return await _record_success", 1
    )[0]
    assert_true(
        "ctx.step.result_json = json_dumps(failure_payload)" in draft_save_failure_branch
        and "await ctx.db.commit()" in draft_save_failure_branch
        and "\n        raise" in draft_save_failure_branch
        and "return {" not in draft_save_failure_branch,
        "T3 领星外部保存失败 catch 分支必须先保留 sanitized evidence，再抛给 task runtime 标记 failed/retryable，禁止正常 return 成 succeeded",
    )
    assert_true(
        '"/lingxing-aplus-publish"' in task_api_text
        and "LingxingAplusPublishRequest" in schemas_text
        and '"lingxing_aplus_publish": "领星 A+ 草稿保存"' in task_api_text
        and '"lingxing_aplus_publish_product": "A+ 草稿保存"' in task_api_text
        and '"lingxing_aplus_publish_product": "A+ 草稿保存"' in display_text
        and "register_lingxing_aplus_publish_workers()" in main_text,
        "T3 必须注册安全创建 API、request schema、任务/step label 和 worker",
    )
    assert_true(
        "AUTO_LINGXING_APLUS_AFTER_DONE" not in aplus_generate_worker_text
        and "create_lingxing_aplus_publish_runs" not in aplus_generate_worker_text,
        "T3 不允许开启 A+ done 后自动发布或改 A+ generate worker 触发发布",
    )
    assert_true(
        "real client must default fail closed" in policy_script_text
        and "missing image must be a typed policy reason" in policy_script_text
        and "undersized image must be a typed policy reason" in policy_script_text
        and "missing ASIN should return waiting_listing" in task_script_text
        and "A+ not done should be skipped" in task_script_text
        and "auth failure must make TaskRun failed for retry" in task_script_text
        and "api_failed must make TaskRun failed for retry" in task_script_text
        and "request_failed must make TaskRun failed for retry" in task_script_text
        and "runtime retry should complete the same TaskRun" in task_script_text
        and "retry success should create exactly one draft item/idHash" in task_script_text
        and "duplicate trigger must reuse active task" in task_script_text
        and "already draft_saved/idHash should stop before creating a publish run" in task_script_text
        and "T3 must leave Amazon draft visibility unconfirmed" in task_script_text,
        "T3 行为脚本必须覆盖 config off、missing ASIN、A+ 未 done、auth missing、图片缺失/尺寸不足、成功/外部失败 runtime retry、重复触发和 protected draft_saved",
    )


def test_lingxing_aplus_module_mapping_m2_contract() -> None:
    registry_path = ROOT / "backend" / "app" / "aplus_publish" / "module_registry.py"
    mapper_path = ROOT / "backend" / "app" / "services" / "lingxing_aplus_module_mapper.py"
    client_path = ROOT / "backend" / "app" / "services" / "lingxing_aplus_publish_client.py"
    worker_path = ROOT / "backend" / "app" / "task_runtime" / "lingxing_aplus_publish_workers.py"
    planner_path = ROOT / "backend" / "app" / "task_planners" / "lingxing_aplus_publish.py"
    step7_path = ROOT / "backend" / "app" / "pipeline" / "step7_aplus_plan.py"
    step8_path = ROOT / "backend" / "app" / "pipeline" / "step8_aplus_script.py"
    mapper_script_path = ROOT / "scripts" / "test_lingxing_aplus_module_mapper.py"

    assert_true(registry_path.is_file(), "M2 必须新增 A+ publish module registry")
    assert_true(mapper_path.is_file(), "M2 必须新增 Lingxing A+ module mapper")
    registry_text = registry_path.read_text(encoding="utf-8")
    mapper_text = mapper_path.read_text(encoding="utf-8")
    client_text = client_path.read_text(encoding="utf-8")
    worker_text = worker_path.read_text(encoding="utf-8")
    planner_text = planner_path.read_text(encoding="utf-8")
    step7_text = step7_path.read_text(encoding="utf-8")
    step8_text = step8_path.read_text(encoding="utf-8")
    mapper_script_text = mapper_script_path.read_text(encoding="utf-8")

    assert_true(
        "APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1" in registry_text
        and "standard_header_image_text_v1" in registry_text
        and "LINGXING_STANDARD_HEADER_IMAGE_TEXT" in registry_text
        and "STANDARD_HEADER_IMAGE_TEXT" in registry_text
        and "image_min_width=970" in registry_text
        and "image_min_height=600" in registry_text
        and "SUPPORTED_POSITIONS = (1, 2, 3, 4, 5)" in registry_text
        and "FAILURE_UNSUPPORTED_PROFILE" in registry_text
        and "FAILURE_MODULE_BODY_MISSING" in registry_text,
        "M2 registry 必须集中支持 profile/type、图片要求、position 和 failure codes",
    )
    assert_true(
        "def preflight_validate(" in mapper_text
        and "def assemble_payload(" in mapper_text
        and "body\": {\"textList\": [_text_object(module.body)]}" in mapper_text
        and "headline\": _text_object(module.headline)" in mapper_text
        and "headline\": _text_object(module.subheading)" in mapper_text
        and "FAILURE_UNSUPPORTED_PROFILE" in mapper_text
        and "FAILURE_UNSUPPORTED_MODULE_TYPE" in mapper_text
        and "FAILURE_ASSET_POSITION_MISMATCH" in mapper_text,
        "M2 mapper 必须两阶段校验/组装，并使用 rich-text object list 写标题、副标题、正文",
    )
    assert_true(
        "_module_payload(" not in client_text
        and "assemble_payload(request.module_mapping, uploaded)" in client_text
        and '"contentModuleList": content_module_list' in client_text
        and '"headline": {"value": ""}' not in client_text
        and '"body": {"textList": []}' not in client_text,
        "M2 client 不得再从 image+position 硬编码空 payload，必须消费 mapper output",
    )
    before_external = worker_text.split('event_type="external_call"', 1)[0]
    assert_true(
        "preflight_validate(product, assets_result.assets)" in before_external
        and "_finish_module_mapping_failed" in before_external
        and "module_mapping=module_mapping" in worker_text,
        "M2 worker 必须在 external_call/STATUS_UPLOADING/client 前完成 mapper preflight 并 fail closed",
    )
    assert_true(
        "preflight_validate(product, assets_result.assets)" in planner_text
        and "module_mapping_evidence=module_mapping.evidence" in planner_text,
        "M2 planner fingerprint 必须纳入 mapper profile/text evidence",
    )
    assert_true(
        "APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1" in step7_text
        and "LINGXING_STANDARD_HEADER_IMAGE_TEXT" in step7_text
        and 'module["type"] = INTERNAL_STANDARD_HEADER_IMAGE_TEXT_TYPE' in step7_text
        and 'module["publish_profile"] = APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1' in step7_text
        and 'module["lingxing_content_module_type"] = LINGXING_STANDARD_HEADER_IMAGE_TEXT' in step7_text
        and "Standard Comparison Chart" not in step7_text
        and "Standard 4 Image / Text" not in step7_text,
        "M2 Step7 必须显式产出可发布 profile/type，不再产出未支持原生模块标签",
    )
    assert_true(
        "APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1" in step8_text
        and "LINGXING_STANDARD_HEADER_IMAGE_TEXT" in step8_text
        and "def _inherit_publish_contract" in step8_text
        and 'script["publish_profile"]' in step8_text
        and 'script["lingxing_content_module_type"]' in step8_text,
        "M2 Step8 必须继承 publish profile/module type trace fields",
    )
    assert_true(
        "test_valid_plan_assembles_rich_text_payload" in mapper_script_text
        and "unsupported_aplus_publish_profile" in mapper_script_text
        and "unsupported_aplus_module_type" in mapper_script_text
        and "aplus_asset_position_mismatch" in mapper_script_text
        and "body.textList must be rich-text object list" in mapper_script_text,
        "M2 mapper 行为脚本必须覆盖 success rich-text payload 和 fail-closed cases",
    )


def test_lingxing_aplus_enhanced_basic_registry_phase1_contract() -> None:
    from app.aplus_publish.module_registry import (
        APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
        APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
        AplusProfileModuleBinding,
        AplusProfileSpec,
        AplusRegistryContractError,
        ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE,
        FAILURE_ALT_TEXT_MISSING,
        FAILURE_COMPARISON_COLUMN_ASIN_INVALID,
        FAILURE_COMPARISON_COLUMN_ASIN_MISSING,
        FAILURE_COMPARISON_COLUMN_COUNT_INVALID,
        FAILURE_IMAGE_SLOT_DIMENSION_INVALID,
        FAILURE_IMAGE_SLOT_DUPLICATE,
        FAILURE_IMAGE_SLOT_MISSING,
        FAILURE_IMAGE_SLOT_UNEXPECTED,
        FAILURE_MODULE_SEMANTIC_ROLE_MISMATCH,
        FAILURE_MODULE_SPEC_UNREGISTERED,
        FAILURE_PAYLOAD_BUILDER_MISSING,
        FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH,
        FAILURE_SPEC_ROWS_INVALID,
        FAILURE_TEXT_FIELD_MISSING,
        LINGXING_STANDARD_COMPARISON_TABLE,
        LINGXING_STANDARD_HEADER_IMAGE_TEXT,
        LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
        LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
        LINGXING_STANDARD_TECH_SPECS,
        LINGXING_STANDARD_THREE_IMAGE_TEXT,
        MAPPER_FAILURE_CODES,
        PROFILE_SPECS_BY_KEY,
        get_module_spec_for_binding,
        get_profile_spec,
        get_publish_profile_spec,
        producer_contract_for_profile,
        required_image_slots,
        validate_profile_contract,
    )

    profile = get_profile_spec(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    assert_true(profile is not None, "M3.2 Phase 1 必须注册 enhanced_basic_aplus_v1 profile")
    assert_true(profile.profile_version == "1" and profile.tier == "basic", "增强版首版必须仍是 basic A+ profile")
    assert_true(
        [(binding.position, binding.semantic_role, binding.module_spec_key) for binding in profile.module_sequence]
        == [
            (1, "hero", "image_text_overlay_dark"),
            (2, "feature_grid", "three_image_text"),
            (3, "detail_proof", "single_image_specs_detail"),
            (4, "comparison", "comparison_table"),
            (5, "technical_or_closing", "tech_specs"),
        ],
        "增强版 profile sequence 必须固定为 5 个业务角色和 module spec binding",
    )

    expected_types = [
        LINGXING_STANDARD_IMAGE_TEXT_OVERLAY,
        LINGXING_STANDARD_THREE_IMAGE_TEXT,
        LINGXING_STANDARD_SINGLE_IMAGE_SPECS_DETAIL,
        LINGXING_STANDARD_COMPARISON_TABLE,
        LINGXING_STANDARD_TECH_SPECS,
    ]
    bound_specs = [
        get_module_spec_for_binding(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1, binding.position, expected_types[index])
        for index, binding in enumerate(profile.module_sequence)
    ]
    assert_true([spec.content_module_type for spec in bound_specs if spec] == expected_types, "增强版每个 binding 必须能按 profile/position/type 查到 module spec")
    assert_true(bound_specs[0].fixed_values == {"overlayColorType": "DARK"}, "hero 必须固定使用深文本覆盖 DARK")
    assert_true(all(spec.payload_evidence == ENHANCED_BASIC_APLUS_PAYLOAD_EVIDENCE for spec in bound_specs), "增强版 module specs 必须指向 M3.0 payload evidence")

    slot_shapes = {
        item.slot.slot_id: (item.position, item.semantic_role, item.slot.crop_width, item.slot.crop_height)
        for item in required_image_slots(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    }
    assert_true(
        slot_shapes
        == {
            "hero.image": (1, "hero", 970, 300),
            "feature_1.image": (2, "feature_grid", 300, 300),
            "feature_2.image": (2, "feature_grid", 300, 300),
            "feature_3.image": (2, "feature_grid", 300, 300),
            "detail.image": (3, "detail_proof", 300, 300),
            "comparison.column_1.image": (4, "comparison", 150, 300),
            "comparison.column_2.image": (4, "comparison", 150, 300),
        },
        "增强版 required image slots 必须为 7 个，且尺寸按 M3.0 evidence 固定",
    )

    contract = producer_contract_for_profile(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)
    modules = {module.semantic_role: module for module in contract.modules}
    assert_true(modules["technical_or_closing"].required_image_slots == (), "technical_or_closing/tech specs 不得要求图片")
    assert_true(modules["comparison"].comparison.min_columns == 2 and modules["comparison"].comparison.max_columns == 2, "comparison V1 必须固定两列")
    assert_true(modules["comparison"].comparison.asin_required, "comparison columns 必须要求 ASIN")
    assert_true(modules["comparison"].comparison.min_metric_rows == 3, "comparison 必须要求至少 3 行指标")
    assert_true(modules["technical_or_closing"].spec_table.min_rows == 4, "tech specs 必须要求至少 4 行")
    assert_true(modules["technical_or_closing"].spec_table.table_count_values == (1, 2), "tech specs tableCount 必须限制为 1 或 2")

    legacy = get_publish_profile_spec(APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1)
    assert_true(legacy is not None and legacy.content_module_type == LINGXING_STANDARD_HEADER_IMAGE_TEXT, "旧 M2 publish profile API 必须保持兼容")
    assert_true(get_profile_spec("unknown_profile") is None, "未知 registry profile lookup 必须返回 None")
    assert_true(get_module_spec_for_binding(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1, 1, LINGXING_STANDARD_HEADER_IMAGE_TEXT) is None, "增强版不得把旧 STANDARD_HEADER_IMAGE_TEXT 当作 hero binding")

    required_failure_codes = {
        FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH,
        FAILURE_MODULE_SEMANTIC_ROLE_MISMATCH,
        FAILURE_MODULE_SPEC_UNREGISTERED,
        FAILURE_IMAGE_SLOT_MISSING,
        FAILURE_IMAGE_SLOT_DUPLICATE,
        FAILURE_IMAGE_SLOT_UNEXPECTED,
        FAILURE_IMAGE_SLOT_DIMENSION_INVALID,
        FAILURE_ALT_TEXT_MISSING,
        FAILURE_TEXT_FIELD_MISSING,
        FAILURE_COMPARISON_COLUMN_COUNT_INVALID,
        FAILURE_COMPARISON_COLUMN_ASIN_MISSING,
        FAILURE_COMPARISON_COLUMN_ASIN_INVALID,
        FAILURE_SPEC_ROWS_INVALID,
        FAILURE_PAYLOAD_BUILDER_MISSING,
    }
    missing_failure_codes = required_failure_codes - set(MAPPER_FAILURE_CODES)
    assert_true(not missing_failure_codes, f"增强版 registry failure codes 未完整进入 MAPPER_FAILURE_CODES: {sorted(missing_failure_codes)}")

    missing_spec_key = "project_rule_missing_module_spec_profile"
    PROFILE_SPECS_BY_KEY[missing_spec_key] = AplusProfileSpec(
        profile_key=missing_spec_key,
        profile_version="test",
        tier="basic",
        module_count=1,
        module_sequence=(
            AplusProfileModuleBinding(1, "hero", "missing_module_type", "missing_module_spec"),
        ),
        payload_evidence="test",
    )
    try:
        try:
            producer_contract_for_profile(missing_spec_key)
        except AplusRegistryContractError as exc:
            assert_true(exc.reason_code == FAILURE_MODULE_SPEC_UNREGISTERED, "profile binding 指向未注册 module spec 时必须显式 fail closed")
        else:
            raise AssertionError("profile binding 指向未注册 module spec 时不得返回截断 contract")
    finally:
        PROFILE_SPECS_BY_KEY.pop(missing_spec_key, None)

    mismatch_key = "project_rule_module_count_mismatch_profile"
    PROFILE_SPECS_BY_KEY[mismatch_key] = AplusProfileSpec(
        profile_key=mismatch_key,
        profile_version="test",
        tier="basic",
        module_count=2,
        module_sequence=(
            AplusProfileModuleBinding(1, "hero", "standard_header_image_text", "standard_header_image_text"),
        ),
        payload_evidence="test",
    )
    try:
        try:
            validate_profile_contract(mismatch_key)
        except AplusRegistryContractError as exc:
            assert_true(exc.reason_code == FAILURE_PROFILE_MODULE_SEQUENCE_MISMATCH, "profile module_count 与 sequence 不一致时必须显式 fail closed")
        else:
            raise AssertionError("profile module_count 与 sequence 不一致时不得被视为可用 contract")
    finally:
        PROFILE_SPECS_BY_KEY.pop(mismatch_key, None)


def test_lingxing_aplus_step7_enhanced_phase2_producer_schema() -> None:
    step7_text = (ROOT / "backend" / "app" / "pipeline" / "step7_aplus_plan.py").read_text()
    step7_ast = ast.parse(step7_text)
    run_aplus_plan_node = next(
        node for node in step7_ast.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_aplus_plan"
    )
    run_aplus_plan_source = ast.get_source_segment(step7_text, run_aplus_plan_node) or ""
    assert_true(
        'Use exactly these semantic roles by position: hero, lifestyle, feature_proof, spec_objection, closing.' in step7_text
        and "feature_grid, detail_proof, comparison, technical_or_closing" not in step7_text.split("PLAN_PROMPT = ", 1)[1].split("def _format_reference_candidates", 1)[0],
        "Step7 默认 prompt 必须保持旧 standard_header_image_text_v1 语义，不能在旧默认链路要求 enhanced roles",
    )
    assert_true(
        "len(plan.get('modules') or [])" in run_aplus_plan_source,
        "Step7 run_aplus_plan 完成日志必须从最终 plan 读取模块数量",
    )
    assert_true(
        "profile_key=DEFAULT_APLUS_PUBLISH_PROFILE" in run_aplus_plan_source
        and "plan = fallback_aplus_plan(product, pd, pi, selling_points)" in run_aplus_plan_source
        and "APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1" not in run_aplus_plan_source,
        "Step7 run_aplus_plan 默认链路不得显式选择 enhanced profile，必须通过 DEFAULT profile selector",
    )
    code = r'''
import json
from types import SimpleNamespace

from app.aplus_publish.module_registry import (
    APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
    APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    LINGXING_STANDARD_HEADER_IMAGE_TEXT,
    producer_contract_for_profile,
)
from app.pipeline.step7_aplus_plan import (
    APLUS_MODULE_CONTRACT_SOURCE,
    DEFAULT_APLUS_PUBLISH_PROFILE,
    aplus_publish_profile_for_plan,
    build_aplus_plan_from_business_content,
    fallback_aplus_plan,
)

product = SimpleNamespace(
    id=2026062405,
    brand="Vindhvisk",
    amazon_asin="B0CURRENT1",
    competitor_asin="B0COMPET01",
)
product_data = SimpleNamespace(
    listing_title="Modular Sofa with Storage Chaise",
    title="Modular Sofa",
    leaf_category="Sofas",
    amazon_category="Furniture",
    suggested_price="499.99",
    features='["storage chaise", "soft fabric", "modular layout", "easy care"]',
    listing_primary_keyword="modular sofa",
    gigab2b_raw_snapshot="{}",
)
product_image = SimpleNamespace(
    main_image_path="/images/current-main.jpg",
    gallery_images='[{"path": "/images/current-side.jpg"}]',
    image_analysis=None,
)
malicious_llm_plan = {
    "aplus_plan_version": APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    "publish_profile": APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
    "profile_version": "999",
    "modules": [
        {
            "position": 99,
            "semantic_role": "wrong_role",
            "type": "standard_header_image_text",
            "publish_profile": APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
            "lingxing_content_module_type": LINGXING_STANDARD_HEADER_IMAGE_TEXT,
            "module_spec_key": "wrong_spec",
            "headline": f"Headline {idx}",
            "body": f"Body {idx}",
            "image_concept": f"Image concept {idx}",
            "alt_text_seed": f"Alt {idx}",
            "comparison_asin": "B0FAKE999",
        }
        for idx in range(1, 6)
    ],
}

default_plan = build_aplus_plan_from_business_content(
    malicious_llm_plan,
    product=product,
    product_data=product_data,
    product_image=product_image,
    selling_points=["storage chaise", "soft fabric"],
)
assert DEFAULT_APLUS_PUBLISH_PROFILE == APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
assert default_plan["modules"][0]["publish_profile"] == APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
assert default_plan["modules"][0]["lingxing_content_module_type"] == LINGXING_STANDARD_HEADER_IMAGE_TEXT

default_fallback = fallback_aplus_plan(product, product_data, product_image, ["storage chaise"])
assert default_fallback["modules"][0]["publish_profile"] == APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
assert default_fallback["modules"][0]["lingxing_content_module_type"] == LINGXING_STANDARD_HEADER_IMAGE_TEXT
assert [module["semantic_role"] for module in default_fallback["modules"]] == ["hero", "lifestyle", "feature_proof", "spec_objection", "closing"]

plan = build_aplus_plan_from_business_content(
    malicious_llm_plan,
    product=product,
    product_data=product_data,
    product_image=product_image,
    selling_points=["storage chaise", "soft fabric"],
    profile_key=APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
)
contract = producer_contract_for_profile(APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1)

assert plan["aplus_plan_version"] == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1
assert plan["publish_profile"] == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1
assert plan["profile_version"] == contract.profile_version == "1"
assert plan["module_contract_source"] == APLUS_MODULE_CONTRACT_SOURCE
assert len(plan["modules"]) == contract.module_count == 5

for module, expected in zip(plan["modules"], contract.modules, strict=True):
    assert module["position"] == expected.position
    assert module["semantic_role"] == expected.semantic_role
    assert module["type"] == expected.internal_type
    assert module["internal_type"] == expected.internal_type
    assert module["publish_profile"] == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1
    assert module["profile_version"] == "1"
    assert module["module_spec_key"] == expected.module_spec_key
    assert module["lingxing_content_module_type"] == expected.lingxing_content_module_type
    assert module["payload_key"] == expected.payload_key

modules = {module["semantic_role"]: module for module in plan["modules"]}
assert modules["hero"]["overlayColorType"] == "DARK"
assert modules["feature_grid"]["feature_slots"] == ["feature_1", "feature_2", "feature_3"]
assert len(modules["feature_grid"]["features"]) == 3
assert 3 <= len(modules["detail_proof"]["spec_items"]) <= 6
assert 3 <= len(modules["comparison"]["metric_row_labels"]) <= 6
assert modules["comparison"]["product_columns"][0]["asin"] == "B0CURRENT1"
assert modules["comparison"]["product_columns"][1]["asin"] == "B0COMPET01"
assert modules["comparison"]["product_columns"][1]["title"] is None
assert modules["comparison"]["product_columns"][1]["image_source"] is None
assert "B0FAKE999" not in json.dumps(plan, ensure_ascii=False)
assert modules["technical_or_closing"]["tableCount"] == 1
assert 4 <= len(modules["technical_or_closing"]["spec_rows"]) <= 10

matched_data = SimpleNamespace(**product_data.__dict__)
matched_data.gigab2b_raw_snapshot = json.dumps({
    "selected_competitor": {
        "asin": "B0COMPET01",
        "title": "Real matched competitor sofa",
        "image_url": "https://images.example/competitor.jpg",
    }
})
matched_plan = build_aplus_plan_from_business_content(
    malicious_llm_plan,
    product=product,
    product_data=matched_data,
    product_image=product_image,
    selling_points=["storage chaise", "soft fabric"],
    profile_key=APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
)
matched_column = {module["semantic_role"]: module for module in matched_plan["modules"]}["comparison"]["product_columns"][1]
assert matched_column["title"] == "Real matched competitor sofa"
assert matched_column["image_source"] == "https://images.example/competitor.jpg"
assert matched_column["title_source"] == "product_data.gigab2b_raw_snapshot.selected_competitor.title"
assert matched_column["image_source_field"] == "product_data.gigab2b_raw_snapshot.selected_competitor.image_url"

mismatched_data = SimpleNamespace(**product_data.__dict__)
mismatched_data.gigab2b_raw_snapshot = json.dumps({
    "selected_competitor": {
        "asin": "B0OTHER001",
        "title": "Wrong competitor",
        "image_url": "https://images.example/wrong.jpg",
    }
})
mismatched_plan = build_aplus_plan_from_business_content(
    malicious_llm_plan,
    product=product,
    product_data=mismatched_data,
    product_image=product_image,
    selling_points=["storage chaise", "soft fabric"],
    profile_key=APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
)
mismatched_column = {module["semantic_role"]: module for module in mismatched_plan["modules"]}["comparison"]["product_columns"][1]
assert mismatched_column["title"] is None
assert mismatched_column["image_source"] is None

fallback = fallback_aplus_plan(
    product,
    matched_data,
    product_image,
    ["storage chaise"],
    profile_key=APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1,
)
assert fallback["publish_profile"] == APLUS_PUBLISH_PROFILE_ENHANCED_BASIC_APLUS_V1
assert LINGXING_STANDARD_HEADER_IMAGE_TEXT not in json.dumps(fallback, ensure_ascii=False)

legacy = build_aplus_plan_from_business_content(
    {"modules": [{"headline": "Legacy", "text_content": "Legacy body"} for _ in range(5)]},
    product=product,
    product_data=product_data,
    product_image=product_image,
    selling_points=[],
    profile_key=APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1,
)
assert legacy["modules"][0]["publish_profile"] == APLUS_PUBLISH_PROFILE_STANDARD_HEADER_IMAGE_TEXT_V1
assert legacy["modules"][0]["lingxing_content_module_type"] == LINGXING_STANDARD_HEADER_IMAGE_TEXT
assert aplus_publish_profile_for_plan({"modules": [{"type": "standard_header_image_text", "headline": "old"}]}) is None
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"Step7 enhanced producer schema 行为验证失败: {result.stderr or result.stdout}")


def test_product_action_worker_does_not_project_failure_for_interrupted() -> None:
    code = r'''
import asyncio
from types import SimpleNamespace
from app.product_tasks import actions as product_actions
from app.task_runtime.exceptions import TaskStepInterrupted

class FakeDb:
    def __init__(self):
        self.rollback_count = 0
    async def rollback(self):
        self.rollback_count += 1

class FakeAction:
    def __init__(self):
        self.failure_count = 0
    async def execute_step(self, db, step, payload):
        raise TaskStepInterrupted("worker interrupted")
    async def on_step_success(self, db, step, result):
        raise AssertionError("interrupted step must not enter success projection")
    async def on_step_failure(self, db, step, error):
        self.failure_count += 1

async def main():
    fake_action = FakeAction()
    original_action_for = product_actions.action_for
    product_actions.action_for = lambda _step_type: fake_action
    db = FakeDb()
    try:
        ctx = SimpleNamespace(
            db=db,
            run=SimpleNamespace(cancel_requested_at=None),
            group=SimpleNamespace(),
            step=SimpleNamespace(step_type="product_image_analysis", payload_json="{}"),
        )
        try:
            await product_actions.product_action_worker(ctx)
        except TaskStepInterrupted:
            pass
        else:
            raise AssertionError("TaskStepInterrupted must be propagated to scheduler")
    finally:
        product_actions.action_for = original_action_for
    assert fake_action.failure_count == 0
    assert db.rollback_count == 0

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"TaskStepInterrupted 行为验证失败: {result.stderr or result.stdout}")


def test_product_action_final_progress_failure_is_best_effort() -> None:
    code = r'''
import asyncio
from types import SimpleNamespace
from app.product_tasks import actions as product_actions

class FakeDb:
    def __init__(self):
        self.rollback_count = 0
    async def rollback(self):
        self.rollback_count += 1

async def main():
    original_update = product_actions.update_step_progress
    async def failing_update(*args, **kwargs):
        raise RuntimeError("progress event write failed")
    db = FakeDb()
    product_actions.update_step_progress = failing_update
    try:
        await product_actions._best_effort_update_step_progress(
            db,
            SimpleNamespace(id=123),
            current=1,
            total=1,
            message="done",
            data={"product_id": 1},
        )
    finally:
        product_actions.update_step_progress = original_update
    assert db.rollback_count == 1

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"最终 progress best-effort 行为验证失败: {result.stderr or result.stdout}")


def test_auto_image_selection_phase_a_contract() -> None:
    status_text = (ROOT / "backend" / "app" / "models" / "status.py").read_text(encoding="utf-8")
    workflow_text = (ROOT / "backend" / "app" / "product_tasks" / "workflow.py").read_text(encoding="utf-8")
    actions_text = (ROOT / "backend" / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    service_text = (ROOT / "backend" / "app" / "product_tasks" / "auto_image_selection.py").read_text(encoding="utf-8")
    vlm_service_text = (ROOT / "backend" / "app" / "services" / "product_image_vlm.py").read_text(encoding="utf-8")
    step6_text = (ROOT / "backend" / "app" / "pipeline" / "step6_image.py").read_text(encoding="utf-8")
    candidate_text = (ROOT / "backend" / "app" / "services" / "product_image_candidates.py").read_text(encoding="utf-8")
    planner_text = (ROOT / "backend" / "app" / "task_planners" / "product_auto_image_selection.py").read_text(encoding="utf-8")
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    product_detail_text = (ROOT / "frontend" / "src" / "pages" / "ProductDetail.tsx").read_text(encoding="utf-8")

    assert_true(
        "WORKFLOW_NODE_AUTO_SELECT_IMAGES" in status_text
        and '"auto_select_images"' in status_text
        and "retry_auto_image_selection" in workflow_text
        and "manual_adjust_images" in workflow_text,
        "自动选图阶段 A 必须新增 auto_select_images workflow 节点和失败动作",
    )
    assert_true(
        "image_selection_analysis" in models_text
        and "image_selected_at" in models_text
        and "image_selection_analysis" in schemas_text
        and "image_selected_at" in schemas_text
        and "_ensure_mysql_product_image_selection_columns" in database_text,
        "自动选图结果字段必须进入 ORM、schema 和 MySQL 兼容补列",
    )
    assert_true(
        "class ProductAutoImageSelectionAction" in actions_text
        and '"product_auto_image_selection"' in actions_text
        and "product_auto_image_selection:product:{_product_id(payload)}" in actions_text
        and "product:{_product_id(payload)}:auto_image_selection" in actions_text
        and "ProductAutoImageSelectionAction()" in actions_text
        and "create_product_auto_image_selection_runs" in planner_text,
        "自动选图必须通过 ProductTaskAction 和任务 planner 落入新任务中心",
    )
    assert_true(
        "collect_product_image_candidates" in candidate_text
        and "GigaProductImage" in candidate_text
        and "giga_listing_images" in candidate_text
        and "gallery_order" in candidate_text
        and "mainImageUrl" in candidate_text
        and "variant_main" in candidate_text,
        "候选收集必须覆盖 GIGA detail、giga_product_images、snapshot 和 gallery_order，并保留变体分层",
    )
    assert_true(
        "run_auto_image_selection" in service_text
        and "selected_main" in service_text
        and "selected_gallery" in service_text
        and "confidence == \"low\"" in service_text
        and ".image_analysis =" not in service_text
        and "\"image_analysis\"" not in service_text,
        "自动选图服务必须输出结构化选择结果，低置信度失败，并和后续 image_analysis 语义隔离",
    )
    assert_true(
        "from app.pipeline.step6_image" not in service_text
        and "from app.services.product_image_vlm import" in service_text
        and "from app.services.product_image_vlm import" in step6_text
        and "def analyze_image_url_batch" in vlm_service_text,
        "自动选图和旧图片分析必须共享 product_image_vlm 的 direct image URL 底层能力，不能让新逻辑反向依赖 step6_image 私有实现",
    )
    for forbidden in (
        "analyze_contact_sheet",
        "build_contact_sheets",
        "download_image_records",
        "Contact Sheet",
        "contact_sheets",
    ):
        assert_true(forbidden not in service_text, f"自动选图默认路径不得保留下载/Contact Sheet 兜底: {forbidden}")
    assert_true(
        "image_batches" in service_text
        and "build_image_url_batches(records)" in service_text
        and "AutoImageSelectionError(f\"自动选图 direct image URL VLM 失败" in service_text,
        "自动选图必须只走 direct image URL 批量分析，失败后显式失败等待重试/人工纠偏",
    )
    step6_run_section = step6_text.split("async def run_image_analysis", 1)[1]
    assert_true(
        "_analyze_image_url_batch" in step6_run_section
        and "_download_image_records" not in step6_run_section
        and "_build_contact_sheets" not in step6_run_section
        and "_analyze_contact_sheet" not in step6_run_section
        and '"image_batches": analysis_image_batches' in step6_run_section
        and "pi.contact_sheet_path = None" in step6_run_section
        and "未下载图片或切换 Contact Sheet 兜底" in step6_run_section
        and "contact_sheet_fallback" not in step6_run_section,
        "Step6 图片分析不得在 URL 直传失败后下载图片或切换 Contact Sheet 兜底，新结果必须写 image_batches 并清空旧 contact_sheet_path",
    )
    assert_true(
        "const imageAnalysisBatches = imageAnalysisPayload?.image_batches || legacyContactSheets" in product_detail_text
        and "isVirtualImageBatch" in product_detail_text
        and "Contact Sheet 与分析" not in product_detail_text
        and "未生成 Contact Sheet 分析" not in product_detail_text,
        "商品详情必须消费 Step6 image_batches，不能把 direct URL 批次当 Contact Sheet 图片展示",
    )


def test_auto_image_selection_candidate_priority_behaviour() -> None:
    code = r'''
import asyncio
import json
from types import SimpleNamespace
from app.services.product_image_candidates import collect_product_image_candidates

class Result:
    def __init__(self, rows):
        self.rows = rows
    def scalars(self):
        return self
    def all(self):
        return self.rows

class FakeDb:
    async def execute(self, _statement):
        return Result([
            SimpleNamespace(
                id=1,
                batch_id="B1",
                site="US",
                data_source_id=7,
                item_code="ITEM",
                sku_code="REP",
                image_url="https://img.test/main.jpg",
                local_path="/tmp/main.jpg",
                image_type="main",
                sort_order=1,
                download_status="done",
            ),
            SimpleNamespace(
                id=2,
                batch_id="B1",
                site="US",
                data_source_id=7,
                item_code="ITEM",
                sku_code="OTHER",
                image_url="https://img.test/other.jpg",
                local_path=None,
                image_type="main",
                sort_order=2,
                download_status="pending",
            ),
        ])

async def main():
    snapshot = {
        "batch_id": "B1",
        "site": "US",
        "data_source_id": 7,
        "representative_sku": "REP",
        "mainImageUrl": "https://img.test/main.jpg",
        "imageUrls": ["https://img.test/gallery.jpg"],
        "giga_listing_images": [
            {"path": "https://img.test/snapshot.jpg", "image_type": "gallery", "sku_code": "REP", "sort_order": 3}
        ],
    }
    product = SimpleNamespace(
        source_batch_id="B1",
        source_site="US",
        source_data_source_id=7,
        gigab2b_product_id="ITEM",
        data=SimpleNamespace(item_code="ITEM", gigab2b_raw_snapshot=json.dumps(snapshot)),
        images=SimpleNamespace(gallery_order=json.dumps([
            {"path": "https://img.test/brand.jpg", "image_type": "brand", "source": "saved_gallery_order", "sort_order": 9}
        ])),
    )
    candidates = await collect_product_image_candidates(FakeDb(), product)
    paths = [item["path"] for item in candidates]
    assert paths[0] == "https://img.test/main.jpg", candidates
    assert candidates[0]["image_type"] == "main", candidates
    assert candidates[0]["is_representative_sku"] is True, candidates
    assert any(item["image_type"] == "variant_main" for item in candidates), candidates
    assert paths.count("https://img.test/main.jpg") == 1, candidates
    assert "https://img.test/brand.jpg" == paths[-1], candidates
    assert {"path", "image_url", "image_type", "source", "asset_source", "sku_code", "sort_order"}.issubset(candidates[0]), candidates

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"自动选图候选优先级行为验证失败: {result.stderr or result.stdout}")


def test_auto_image_selection_service_and_action_behaviour() -> None:
    code = r'''
import asyncio
from types import SimpleNamespace
from app.models import ProductImage
from app.models.status import (
    FAILED,
    WORKFLOW_NODE_FLOW_DONE,
    WORKFLOW_NODE_AUTO_SELECT_IMAGES,
    WORKFLOW_NODE_SEARCH_COMPETITOR,
    WORKFLOW_STATUS_FAILED,
    WORKFLOW_STATUS_PENDING,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_SUCCEEDED,
)
from app.product_tasks import actions as product_actions
from app.product_tasks.auto_image_selection import AutoImageSelectionError, _merge_batch_results

class EmptyResult:
    def all(self):
        return []
    def scalars(self):
        return self

class FakeDb:
    def __init__(self, product):
        self.product = product
        self.commit_count = 0
        self.added = []
    def add(self, item):
        self.added.append(item)
    async def execute(self, _statement):
        return EmptyResult()
    async def commit(self):
        self.commit_count += 1
    async def rollback(self):
        pass

def make_product():
    return SimpleNamespace(
        id=123,
        status="created",
        current_step=0,
        error_message=None,
        workflow_node=None,
        workflow_status=None,
        workflow_error=None,
        workflow_updated_at=None,
        updated_at=None,
        data=SimpleNamespace(
            item_code="ITEM",
            gigab2b_raw_snapshot="{}",
            categories="old",
            leaf_category="old",
            listing_title="old",
            listing_bullets="old",
            listing_search_terms="old",
            listing_title_zh="old",
            listing_bullets_zh="old",
            listing_search_terms_zh="old",
            listing_description="old",
            listing_description_zh="old",
            listing_check="old",
            listing_primary_keyword="old",
            listing_removed_keywords="old",
            amazon_template_path=None,
            amazon_template_generated_at=None,
            amazon_template_fill_summary=None,
            amazon_template_warnings=None,
        ),
        images=ProductImage(product_id=123),
        aplus=None,
        catalog_item=SimpleNamespace(
            status="created",
            competitor_asin="B000",
            confirmed_at=None,
            amazon_asin=None,
            exported_at=None,
            export_task_id=None,
            export_file_path=None,
            aplus_upload_status="not_uploaded",
            aplus_uploaded_at=None,
            aplus_upload_error=None,
            updated_at=None,
        ),
        competitor_asin="B000",
        amazon_asin=None,
        aplus_upload_status="not_uploaded",
        aplus_uploaded_at=None,
        aplus_upload_error=None,
    )

async def main():
    try:
        _merge_batch_results([
            {"selected_main": {"path": "a.jpg", "image_id": "#01", "score": 0.9, "risk_flags": []}, "selected_gallery": [], "rejected": [], "confidence": "low", "warnings": []}
        ], [], [], "test-model")
    except AutoImageSelectionError:
        pass
    else:
        raise AssertionError("low confidence must fail")

    original_load_product = product_actions._load_product
    try:
        product = make_product()
        async def fake_load_product(_db, _product_id):
            return product
        product_actions._load_product = fake_load_product
        action = product_actions.ProductAutoImageSelectionAction()
        db = FakeDb(product)

        protected_real_asin = make_product()
        protected_real_asin.amazon_asin = "BREAL"
        protected_real_asin.status = "completed"
        protected_real_asin.current_step = 6
        protected_real_asin.workflow_node = WORKFLOW_NODE_FLOW_DONE
        protected_real_asin.workflow_status = WORKFLOW_STATUS_SUCCEEDED
        protected_real_asin.workflow_error = None
        product = protected_real_asin
        for method_name in ("validate", "reserve"):
            try:
                if method_name == "validate":
                    await action.validate(db, {"product_id": protected_real_asin.id})
                else:
                    await action.reserve(db, {"product_id": protected_real_asin.id}, SimpleNamespace())
            except RuntimeError as exc:
                assert "不能自动选图" in str(exc), exc
            else:
                raise AssertionError(f"protected product must reject {method_name}")
        assert protected_real_asin.status == "completed"
        assert protected_real_asin.current_step == 6
        assert protected_real_asin.workflow_node == WORKFLOW_NODE_FLOW_DONE
        assert protected_real_asin.workflow_status == WORKFLOW_STATUS_SUCCEEDED

        protected_catalog = make_product()
        protected_catalog.catalog_item.confirmed_at = "2026-06-20"
        protected_catalog.catalog_item.exported_at = "2026-06-20"
        protected_catalog.status = "completed"
        protected_catalog.current_step = 6
        protected_catalog.workflow_node = WORKFLOW_NODE_FLOW_DONE
        protected_catalog.workflow_status = WORKFLOW_STATUS_SUCCEEDED
        product = protected_catalog
        try:
            await action.validate(db, {"product_id": protected_catalog.id})
        except RuntimeError as exc:
            assert "不能自动选图" in str(exc), exc
        else:
            raise AssertionError("catalog confirmed/exported product must reject validate")
        assert protected_catalog.status == "completed"
        assert protected_catalog.current_step == 6
        assert protected_catalog.workflow_node == WORKFLOW_NODE_FLOW_DONE
        assert protected_catalog.workflow_status == WORKFLOW_STATUS_SUCCEEDED

        product = make_product()
        db = FakeDb(product)
        await action.reserve(db, {"product_id": product.id}, SimpleNamespace())
        assert product.workflow_node == WORKFLOW_NODE_AUTO_SELECT_IMAGES
        assert product.workflow_status == WORKFLOW_STATUS_PROCESSING

        step = SimpleNamespace(id=1, task_run_id=10, task_group_id=20, task_run=SimpleNamespace(summary_json=None), payload_json='{"product_id": 123}')
        result = {
            "product_id": product.id,
            "item_code": "ITEM",
            "auto_image_selection": {
                "selected_main": {"path": "/tmp/main.jpg", "image_url": "https://img.test/main.jpg", "image_id": "#01", "score": 0.95, "reason": "clean", "risk_flags": []},
                "selected_gallery": [{"path": "/tmp/gallery.jpg", "image_url": "https://img.test/gallery.jpg", "image_id": "#02", "role": "alternate_angle", "score": 0.8, "reason": "angle", "risk_flags": []}],
                "rejected": [],
                "confidence": "high",
                "warnings": [],
                "image_batches": [],
                "model": "test-model",
            },
        }
        await action.on_step_success(db, step, result)
        assert product.images.main_image_path == "https://img.test/main.jpg"
        assert product.images.gallery_images == '["https://img.test/gallery.jpg"]'
        assert product.images.main_image_source == "model_selected"
        assert product.images.image_selection_analysis
        assert product.images.image_selected_at is not None
        assert product.images.image_analysis is None
        assert product.workflow_node == WORKFLOW_NODE_SEARCH_COMPETITOR
        assert product.workflow_status == WORKFLOW_STATUS_PENDING
        assert product.competitor_asin is None
        assert product.data.listing_title is None

        protected = make_product()
        protected.amazon_asin = "BREAL"
        product = protected
        step = SimpleNamespace(payload_json='{"product_id": 123}')
        await action.on_step_failure(db, step, RuntimeError("boom"))
        assert protected.status == FAILED
        assert protected.workflow_node == WORKFLOW_NODE_AUTO_SELECT_IMAGES
        assert protected.workflow_status == WORKFLOW_STATUS_FAILED
        assert "自动选图失败" in protected.workflow_error
    finally:
        product_actions._load_product = original_load_product

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"自动选图服务/action 行为验证失败: {result.stderr or result.stdout}")


def test_auto_image_selection_phase_b_contract() -> None:
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    giga_product_drafts_text = (ROOT / "backend" / "app" / "services" / "giga_product_drafts.py").read_text(encoding="utf-8")
    products_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    product_list_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    image_review_text = (ROOT / "frontend" / "src" / "pages" / "ProductImageReview.tsx").read_text(encoding="utf-8")
    api_text = (ROOT / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")

    commit_index = giga_product_drafts_text.find("await db.commit()")
    create_run_index = giga_product_drafts_text.find("created_by=\"giga_product_draft\"")
    assert_true(
        "WORKFLOW_NODE_AUTO_SELECT_IMAGES" in giga_product_drafts_text
        and "node=WORKFLOW_NODE_AUTO_SELECT_IMAGES" in giga_product_drafts_text
        and "created_by=\"giga_product_draft\"" in giga_product_drafts_text
        and "WORKFLOW_STATUS_FAILED" in giga_product_drafts_text
        and commit_index >= 0
        and create_run_index > commit_index,
        "Phase B 新建商品必须先完整落库，再创建/复用自动选图 task run，失败落 auto_select_images/failed",
    )
    assert_true(
        "if created:" in giga_product_drafts_text
        and "if not product.workflow_node and not product.workflow_status and not product.competitor_asin" in giga_product_drafts_text
        and "node=WORKFLOW_NODE_AUTO_SELECT_IMAGES if created else WORKFLOW_NODE_SELECT_IMAGES" in giga_product_drafts_text,
        "Phase B 只能切新建商品入口，duplicate/update 商品不得静默迁移既有 workflow",
    )

    retry_route_start = products_text.find('@router.post("/{product_id}/auto-image-selection/retry"')
    retry_route_end = products_text.find('@router.delete("/{product_id}"', retry_route_start)
    retry_route_text = products_text[retry_route_start:retry_route_end]
    assert_true(
        retry_route_start >= 0
        and "product.workflow_node != WORKFLOW_NODE_AUTO_SELECT_IMAGES" in retry_route_text
        and "WORKFLOW_STATUS_PROCESSING" in retry_route_text
        and "WORKFLOW_STATUS_FAILED" in retry_route_text
        and "WORKFLOW_STATUS_PENDING" in retry_route_text
        and "create_product_auto_image_selection_runs" in retry_route_text
        and "raise_if_auto_image_selection_protected(product)" in retry_route_text
        and ".workflow = _workflow_state(" in retry_route_text
        and "BackgroundTasks" not in retry_route_text
        and "create_task" not in retry_route_text,
        "自动选图重试 API 必须基于 workflow 状态、走任务中心 planner、复用保护门且不使用裸后台任务",
    )
    assert_true(
        "related_task_run_id" in schemas_text
        and "related_correlation_key" in schemas_text
        and "related_correlation_key?: string | null" in api_text
        and "product.workflow?.related_correlation_key" in product_list_text,
        "ProductResponse workflow schema 必须暴露任务关联字段，前端任务中心入口才能按 correlation key 定位",
    )
    assert_true(
        '"auto_select_images"' in products_text
        and "auto_select_images:" in api_text
        and "| 'auto_select_images'" in product_list_text
        and "auto_select_images:" in product_list_text
        and "'auto_select_images'" in product_list_text,
        "auto_select_images 必须成为后端 overview/list 和前端筛选一致支持的正式工作状态桶",
    )
    assert_true(
        "_apply_product_work_status_db_filter(query, count_query, work_status)" in products_text
        and "if work_status and not db_filtered_work_status:" not in products_text
        and "matched_items = [" not in products_text
        and "return query.where(predicate), count_query.where(predicate)" in products_text,
        "商品列表 work_status 筛选必须全部由 DB 级谓词和 count/page 接管，不得保留 Python 内存过滤分页 fallback",
    )
    assert_true(
        "raise_if_image_selection_reset_protected(product)" in products_text
        and "product.images.image_selection_analysis = None" in products_text
        and "product.images.image_selected_at = None" in products_text,
        "手动调整图片必须先过保护门，并清理过期自动选图分析结果",
    )
    assert_true(
        "retryProductAutoImageSelection" in api_text
        and "/auto-image-selection/retry" in api_text
        and "workflowAction === 'retry_auto_image_selection'" in product_list_text
        and "workflowAction === 'manual_adjust_images'" in product_list_text
        and "workflowAllowedActions.includes('manual_adjust_images')" in product_list_text
        and "手动调图" in product_list_text
        and "openReviewPage('/products/image-review', product.id)" in product_list_text
        and "product.current_step" not in product_list_text[product_list_text.find("workflowAction === 'retry_auto_image_selection'"):product_list_text.find("workflowAction === 'manual_adjust_images'")],
        "商品列表必须消费后端 workflow action/allowed_actions，不能用 current_step/error_message 推导自动选图动作",
    )
    assert_true(
        "图片已保存" in image_review_text
        and "商品图片已确认" not in image_review_text,
        "图片确认页必须收敛为手动调整/保存语义，不再表达默认必经确认流程",
    )
    assert_true(
        "template_mappings" not in giga_product_drafts_text
        and "step10" not in giga_product_drafts_text.lower()
        and "product_auto_competitor" not in giga_product_drafts_text
        and "product_auto_competitor" not in products_text,
        "Phase B 不得夹带 Step 10/template_mappings 或自动竞品实现",
    )


def test_auto_image_selection_phase_b_work_status_behaviour() -> None:
    code = r'''
from sqlalchemy import func, select
from app.api.products import (
    WORKBENCH_STATUS_KEYS,
    PRODUCT_LIST_WORK_STATUS_KEYS,
    _apply_product_work_status_db_filter,
    _product_workbench_status,
    _product_list_work_status,
)
from app.api.schemas import WorkbenchOverview
from app.models import Product
from app.models.status import WORKFLOW_NODE_AUTO_SELECT_IMAGES, WORKFLOW_STATUS_PENDING, WORKFLOW_STATUS_PROCESSING

product = Product(
    id=20260620,
    gigab2b_url="https://example.test/item/20260620",
    status="created",
    current_step=1,
    workflow_node=WORKFLOW_NODE_AUTO_SELECT_IMAGES,
    workflow_status=WORKFLOW_STATUS_PENDING,
)
assert _product_workbench_status(product) == "auto_select_images"
assert _product_list_work_status(product) == "auto_select_images"
assert "auto_select_images" in WORKBENCH_STATUS_KEYS
assert "auto_select_images" in PRODUCT_LIST_WORK_STATUS_KEYS
status_counts = {key: 0 for key in WORKBENCH_STATUS_KEYS}
status_counts[_product_workbench_status(product)] += 1
overview = WorkbenchOverview(total_products=1, auto_select_images=status_counts["auto_select_images"])
assert overview.auto_select_images == 1

product.workflow_status = WORKFLOW_STATUS_PROCESSING
assert _product_workbench_status(product) == "running"
assert _product_list_work_status(product) == "running"

query, count_query = _apply_product_work_status_db_filter(
    select(Product),
    select(func.count(Product.id)),
    "auto_select_images",
)
compiled_query = str(query.compile(compile_kwargs={"literal_binds": True}))
compiled_count = str(count_query.compile(compile_kwargs={"literal_binds": True}))
for sql in (compiled_query, compiled_count):
    assert "workflow_node" in sql and "auto_select_images" in sql, sql
    assert "workflow_status" in sql and "pending" in sql, sql

required_statuses = {
    "export_ready",
    "exported",
    "failed",
    "auto_select_images",
    "running",
    "select_competitor",
    "capture_detail",
    "ready_to_generate",
    "needs_initialization",
}
assert required_statuses <= set(PRODUCT_LIST_WORK_STATUS_KEYS), PRODUCT_LIST_WORK_STATUS_KEYS
for status in sorted(PRODUCT_LIST_WORK_STATUS_KEYS):
    status_query, status_count_query = _apply_product_work_status_db_filter(
        select(Product),
        select(func.count(Product.id)),
        status,
    )
    status_sql = str(status_query.compile(compile_kwargs={"literal_binds": True}))
    count_sql = str(status_count_query.compile(compile_kwargs={"literal_binds": True}))
    assert "WHERE" in status_sql, (status, status_sql)
    assert "WHERE" in count_sql, (status, count_sql)

select_competitor_query, select_competitor_count = _apply_product_work_status_db_filter(
    select(Product),
    select(func.count(Product.id)),
    "select_competitor",
)
for sql in (
    str(select_competitor_query.compile(compile_kwargs={"literal_binds": True})),
    str(select_competitor_count.compile(compile_kwargs={"literal_binds": True})),
):
    assert "auto_select_images" in sql and "succeeded" in sql, sql

try:
    _apply_product_work_status_db_filter(select(Product), select(func.count(Product.id)), "not_a_status")
except ValueError:
    pass
else:
    raise AssertionError("unsupported product list work_status must be rejected before any fallback")

for legacy_status in ("interrupted", "suspended", "manual_review"):
    assert legacy_status not in PRODUCT_LIST_WORK_STATUS_KEYS, PRODUCT_LIST_WORK_STATUS_KEYS
    try:
        _apply_product_work_status_db_filter(select(Product), select(func.count(Product.id)), legacy_status)
    except ValueError:
        pass
    else:
        raise AssertionError(f"legacy diagnostic work_status must not be accepted as ProductWorkStatus: {legacy_status}")
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"自动选图 Phase B 工作状态桶行为验证失败: {result.stderr or result.stdout}")


def test_auto_image_selection_phase_b_protection_behaviour() -> None:
    code = r'''
from types import SimpleNamespace
from app.services.product_protection import (
    auto_image_selection_protection_reasons,
    raise_if_auto_image_selection_protected,
    raise_if_image_selection_reset_protected,
)

def product(**overrides):
    base = SimpleNamespace(
        amazon_asin=None,
        aplus_uploaded_at=None,
        aplus_upload_status="not_uploaded",
        data=SimpleNamespace(
            amazon_template_path=None,
            amazon_template_generated_at=None,
            amazon_template_fill_summary=None,
            amazon_template_warnings=None,
        ),
        catalog_item=SimpleNamespace(
            amazon_asin=None,
            confirmed_at=None,
            exported_at=None,
            export_task_id=None,
            export_file_path=None,
            aplus_uploaded_at=None,
            aplus_upload_status="not_uploaded",
        ),
        files=[],
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base

safe = product()
assert auto_image_selection_protection_reasons(safe) == []
raise_if_auto_image_selection_protected(safe)
raise_if_image_selection_reset_protected(safe)

protected_asin = product(amazon_asin="B0REAL")
for guard in (raise_if_auto_image_selection_protected, raise_if_image_selection_reset_protected):
    try:
        guard(protected_asin)
    except RuntimeError as exc:
        assert "不可逆外部结果" in str(exc), exc
    else:
        raise AssertionError("real ASIN must block automatic image selection and manual reset")

protected_catalog = product()
protected_catalog.catalog_item.confirmed_at = "2026-06-20"
protected_catalog.catalog_item.exported_at = "2026-06-20"
reasons = auto_image_selection_protection_reasons(protected_catalog)
assert any("人工确认" in reason for reason in reasons), reasons
assert any("导出历史" in reason for reason in reasons), reasons

protected_template = product()
protected_template.data.amazon_template_path = "/exports/template.xlsm"
try:
    raise_if_image_selection_reset_protected(protected_template)
except RuntimeError as exc:
    assert "Amazon 模板输出证据" in str(exc), exc
else:
    raise AssertionError("Amazon template output must block manual image reset")

protected_template_file = product(files=[SimpleNamespace(file_type="Amazon_Import_Template", path="/exports/old.xlsm")])
reasons = auto_image_selection_protection_reasons(protected_template_file)
assert any("模板文件输出证据" in reason for reason in reasons), reasons
try:
    raise_if_auto_image_selection_protected(protected_template_file)
except RuntimeError as exc:
    assert "模板文件输出证据" in str(exc), exc
else:
    raise AssertionError("Amazon template ProductFile must block automatic image selection")

legacy_template_file = product(files=[SimpleNamespace(file_type="amazon_template", path="/exports/legacy.xlsm")])
reasons = auto_image_selection_protection_reasons(legacy_template_file)
assert any("模板文件输出证据" in reason for reason in reasons), reasons
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"自动选图 Phase B 保护门行为验证失败: {result.stderr or result.stdout}")


def test_auto_competitor_search_phase_a_contract() -> None:
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    actions_text = (ROOT / "backend" / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    workflow_text = (ROOT / "backend" / "app" / "product_tasks" / "workflow.py").read_text(encoding="utf-8")
    products_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    frontend_api_text = (ROOT / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")
    product_list_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    product_flow_index = (ROOT / "docs" / "domain-index" / "product-flow.md").read_text(encoding="utf-8")
    task_runtime_index = (ROOT / "docs" / "domain-index" / "task-runtime.md").read_text(encoding="utf-8")
    prd_text = (ROOT / "docs" / "superpowers" / "specs" / "2026-06-19-amazon-auto-competitor-selection-prd.md").read_text(encoding="utf-8")
    retry_section = products_text.split('@router.post("/{product_id}/competitor-search/retry"', 1)[1].split('@router.delete("/{product_id}"', 1)[0]

    assert_true(
        "class AmazonCompetitorSearchCandidate" in models_text
        and '__tablename__ = "amazon_competitor_search_candidates"' in models_text
        and 'UniqueConstraint("product_id", "asin"' in models_text,
        "Phase A 必须新增自动竞品搜索候选主事实表，并按 product_id+asin 幂等",
    )
    for field in (
        "task_run_id",
        "task_step_id",
        "source_data_source_id",
        "source_site",
        "source_batch_id",
        "search_query",
        "query_intent",
        "query_index",
        "search_rank",
        "sponsored",
        "is_accessory",
        "is_replacement_part",
        "is_cover_only",
        "is_excluded",
        "exclusion_reason",
        "raw_candidate_json",
        "raw_search_page_json",
    ):
        assert_true(field in models_text, f"自动竞品候选表缺少字段: {field}")
    assert_true(
        "ix_amz_comp_search_product_rank" in database_text
        and "ix_amz_comp_search_product_query" in database_text
        and "ix_amz_comp_search_task_run" in database_text,
        "自动竞品候选高频筛选字段必须有 MySQL ensure 索引",
    )
    assert_true(
        "ProductCompetitorSearchAction" in actions_text
        and '"product_competitor_search"' in actions_text
        and "build_amazon_competitor_queries(product)" in actions_text
        and "run_amazon_search_queries(" in actions_text
        and "_upsert_competitor_search_candidates" in actions_text
        and "WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS" in actions_text,
        "Phase A 必须通过 ProductTaskAction 实现 query/search/upsert/workflow 投影",
    )
    assert_true(
        'ProductCompetitorSearchAction(),' in actions_text
        and 'return f"product:{_product_id(payload)}:competitor_search"' in actions_text,
        "product_competitor_search 必须注册到任务中心，并提供 correlation_key",
    )
    assert_true(
        "当前商品属于旧竞品搜索状态" in actions_text
        and "_is_auto_competitor_search_product(product)" in actions_text,
        "新自动竞品搜索 action 必须阻断旧 failed/processing 误走新 task run",
    )
    assert_true(
        "WORKFLOW_NODE_VISUAL_MATCH_COMPETITORS" in workflow_text
        and "start_competitor_search" in workflow_text
        and "retry_competitor_search" in workflow_text
        and "product:{product_id}:competitor_search" in workflow_text,
        "workflow 必须提供自动竞品搜索 action 和成功落点 visual_match_competitors/pending",
    )
    assert_true(
        "create_product_competitor_search_runs" in retry_section
        and "WORKFLOW_NODE_SEARCH_COMPETITOR" in retry_section
        and "BackgroundTasks" not in retry_section
        and "_run_product_competitor_search_background" not in retry_section,
        "新自动竞品搜索 API 必须走任务中心 planner，不得复用旧 StyleSnap BackgroundTasks",
    )
    assert_true(
        "retryProductCompetitorSearch" in frontend_api_text
        and "start_competitor_search" in product_list_text
        and "retry_competitor_search" in product_list_text
        and "retryCompetitorSearch(product.id)" in product_list_text,
        "商品列表必须消费后端 workflow action 启动/重试自动竞品搜索",
    )
    assert_true(
        "Amazon 自动竞品搜索 Phase A" in product_flow_index
        and "product_competitor_search" in task_runtime_index
        and "Phase A 搜索召回实现对账" in prd_text,
        "Phase A 新任务、状态和数据契约必须同步 PRD/domain index",
    )


def test_auto_competitor_search_phase_a_query_and_fixture_behaviour() -> None:
    code = r'''
from app.models import Product, ProductData, ProductImage
from app.services.amazon_competitor_query import CompetitorQueryError, build_amazon_competitor_queries
from app.services.amazon_search_page import AmazonSearchPageError, classify_amazon_search_page, parse_amazon_search_results_html

product = Product(id=88, gigab2b_url="https://example.test/item/88", status="created", current_step=1)
product.data = ProductData(
    product_id=88,
    title="Modern Modular Sofa with Storage Chaise for Living Room SKU S-123 188cm",
    material="Fabric",
    features='["modular sectional", "living room storage"]',
    description="Upholstered modular sofa for living room seating",
)
product.images = ProductImage(product_id=88, main_image_path="/tmp/main.jpg", main_image_source="model_selected")
plan = build_amazon_competitor_queries(product)
assert 1 <= len(plan["queries"]) <= 3, plan
for item in plan["queries"]:
    assert item["rule_version"] == "amazon_competitor_query_v1", item
    assert 3 <= len(item["included_terms"]) <= 7, item
    assert "Modern Modular Sofa with Storage Chaise for Living Room SKU S-123 188cm".lower() != item["query"], item
    assert "replacement part" in item["excluded_terms"], item

bad = Product(id=89, gigab2b_url="https://example.test/item/89", status="created", current_step=1)
bad.data = ProductData(product_id=89, title="SKU X123")
bad.images = ProductImage(product_id=89, main_image_path="/tmp/main.jpg")
try:
    build_amazon_competitor_queries(bad)
except CompetitorQueryError as exc:
    assert "insufficient_product_facts_for_competitor_search" in str(exc), exc
else:
    raise AssertionError("low quality product facts must fail")

html = """
<html><body>
<div data-component-type="s-search-result" data-asin="B0TEST0001">
  <span>Sponsored</span>
  <h2><a class="a-link-normal" href="/dp/B0TEST0001"><span>Fabric Modular Sofa Cover Only</span></a></h2>
  <img class="s-image" src="https://images.example/1.jpg" />
  <span class="a-price"><span class="a-offscreen">$199.99</span></span>
  <span class="a-icon-alt">4.5 out of 5 stars</span>
  <span class="a-size-base s-underline-text">123</span>
</div>
<div data-component-type="s-search-result" data-asin="B0TEST0002">
  <h2><a class="a-link-normal" href="/dp/B0TEST0002"><span>Fabric Modular Sofa for Living Room</span></a></h2>
  <img class="s-image" src="https://images.example/2.jpg" />
</div>
</body></html>
"""
candidates = parse_amazon_search_results_html(html, query="modular sofa fabric living room")
assert len(candidates) == 2, candidates
assert candidates[0].asin == "B0TEST0001"
assert candidates[0].sponsored is True
assert candidates[0].url.endswith("/dp/B0TEST0001"), candidates[0]
assert candidates[1].search_rank == 2, candidates[1]
assert classify_amazon_search_page("<html>Robot Check</html>") == "bot_check"
try:
    parse_amazon_search_results_html("<html>Enter the characters you see below</html>", query="sofa")
except AmazonSearchPageError as exc:
    assert exc.error_type == "captcha", exc.error_type
else:
    raise AssertionError("captcha page must fail explicitly")
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"自动竞品搜索 Phase A query/fixture 行为验证失败: {result.stderr or result.stdout}")


def test_real_amazon_search_adapter_boundaries() -> None:
    amazon_search_text = (ROOT / "backend" / "app" / "services" / "amazon_search_page.py").read_text(encoding="utf-8")
    actions_text = (ROOT / "backend" / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    config_text = (ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    assert_true(
        'AMAZON_SEARCH_PAGE_ADAPTER: str = "unconfigured"' in config_text
        and "AMAZON_SEARCH_ENABLE_REAL_BROWSER: bool = False" in config_text
        and "AMAZON_SEARCH_EVIDENCE_DIR" in config_text,
        "真实 Amazon search adapter 必须默认 fail closed，并有显式配置和 evidence 目录",
    )
    assert_true(
        "class ChromeAmazonSearchPageAdapter" in amazon_search_text
        and "settings.AMAZON_SEARCH_PAGE_ADAPTER" in amazon_search_text
        and "settings.AMAZON_SEARCH_ENABLE_REAL_BROWSER" in amazon_search_text
        and "UnconfiguredAmazonSearchPageAdapter()" in amazon_search_text
        and "FixtureAmazonSearchPageAdapter" in amazon_search_text,
        "amazon_search_page 必须同时保留默认未配置、fixture parser 测试路径和显式 Chrome 真实 adapter",
    )
    assert_true(
        "AmazonSearchEvidenceContext" in amazon_search_text
        and "task_run_id" in amazon_search_text
        and "task_step_id" in amazon_search_text
        and "query_index" in amazon_search_text
        and "_write_evidence" in amazon_search_text,
        "真实 Amazon search evidence 必须按 task_run_id/task_step_id/query_index 归属",
    )
    for error_type in (
        "adapter_not_configured",
        "browser_unavailable",
        "browser_permission_denied",
        "navigation_timeout",
        "login_required",
        "captcha",
        "bot_check",
        "region_page",
        "unsupported_page_structure",
        "empty_results",
        "parser_error",
        "rate_limited",
    ):
        assert_true(error_type in amazon_search_text, f"Amazon search typed failure 缺失: {error_type}")
    competitor_section = actions_text.split("class ProductCompetitorSearchAction", 1)[1].split("class ProductCompetitorVisualMatchAction", 1)[0]
    assert_true(
        "chrome_ctrl" not in competitor_section
        and "task_run_id=step.task_run_id" in competitor_section
        and "task_step_id=step.id" in competitor_section,
        "ProductCompetitorSearchAction 只能传 evidence context，不能塞浏览器控制逻辑",
    )
    upsert_section = actions_text.split("async def _upsert_competitor_search_candidates", 1)[1].split("def _competitor_candidate_flags", 1)[0]
    assert_true(
        "settings.AMAZON_SEARCH_MAX_CANDIDATES" in upsert_section
        and "max_candidates" in upsert_section
        and "len(flattened) >= 20" not in upsert_section,
        "自动竞品搜索候选落库上限必须使用 AMAZON_SEARCH_MAX_CANDIDATES 配置，不能死写 20",
    )
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "test_amazon_search_page_real_adapter_boundaries.py")],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"真实 Amazon search adapter 边界行为验证失败: {result.stderr or result.stdout}")


def test_task_runtime_autostart_runner_lifecycle_behaviour() -> None:
    scheduler_text = (ROOT / "backend" / "app" / "task_runtime" / "scheduler.py").read_text(encoding="utf-8")
    assert_true(
        "_on_runner_done" in scheduler_text
        and "_clear_stale_runner_state" in scheduler_text
        and "runner task crashed" in scheduler_text
        and "kick ignored: runner task already active" in scheduler_text
        and "scheduling runner task" in scheduler_text,
        "task runtime kick 必须有 runner 生命周期日志、异常可见性和 stale 状态清理",
    )
    runtime_script = (ROOT / "scripts" / "test_task_runtime_autostart.py").read_text(encoding="utf-8")
    assert_true(
        "_assert_ready_step_is_claimed_and_executed_without_wake" in runtime_script
        and "TaskRun(" in runtime_script
        and f"status=STEP_STATUS_READY" in runtime_script
        and "register_worker(PROBE_STEP_TYPE" in runtime_script
        and "scheduler.kick_task_runtime()" in runtime_script,
        "task runtime auto_start 行为脚本必须构造 ready step 并触达 claim/worker 路径，不能只 stub drain_ready_steps",
    )
    assert_true(
        "wake_task_run(" not in scheduler_text
        and "wake_runtime" not in scheduler_text,
        "runtime auto-start 修复不能通过自动调用 wake 伪装",
    )
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "test_task_runtime_autostart.py")],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"task runtime auto_start 行为验证失败: {result.stderr or result.stdout}")


def test_auto_competitor_visual_match_phase_b_contract() -> None:
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    actions_text = (ROOT / "backend" / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    scheduler_text = (ROOT / "backend" / "app" / "task_runtime" / "scheduler.py").read_text(encoding="utf-8")
    service_text = (ROOT / "backend" / "app" / "services" / "amazon_competitor_visual_match.py").read_text(encoding="utf-8")
    workflow_text = (ROOT / "backend" / "app" / "product_tasks" / "workflow.py").read_text(encoding="utf-8")
    products_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    frontend_api_text = (ROOT / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")
    product_list_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    protection_text = (ROOT / "backend" / "app" / "services" / "product_protection.py").read_text(encoding="utf-8")
    product_flow_index = (ROOT / "docs" / "domain-index" / "product-flow.md").read_text(encoding="utf-8")
    task_runtime_index = (ROOT / "docs" / "domain-index" / "task-runtime.md").read_text(encoding="utf-8")
    prd_text = (ROOT / "docs" / "superpowers" / "specs" / "2026-06-19-amazon-auto-competitor-selection-prd.md").read_text(encoding="utf-8")
    visual_retry_section = products_text.split('@router.post("/{product_id}/competitor-visual-match/retry"', 1)[1].split('@router.delete("/{product_id}"', 1)[0]
    create_runs_section = actions_text.split("async def create_product_action_runs", 1)[1].split("async def product_action_worker", 1)[0]
    visual_action_section = actions_text.split("class ProductCompetitorVisualMatchAction", 1)[1].split("async def _latest_successful_competitor_search_ids", 1)[0]
    product_worker_section = actions_text.split("async def product_action_worker", 1)[1].split("def register_product_task_actions", 1)[0]

    for field in (
        "visual_similarity_score",
        "visual_same_product_type",
        "visual_attribute_match_score",
        "visual_title_match_score",
        "visual_reject",
        "visual_reject_reason",
        "visual_reason",
        "visual_sheet_path",
        "visual_sheet_page",
        "visual_sheet_label",
        "visual_rank",
        "visual_selected_for_capture",
        "visual_exclusion_reason",
        "visual_model",
        "visual_raw_json",
        "visual_matched_at",
    ):
        assert_true(field in models_text and field in database_text, f"视觉初筛字段缺少 ORM 或 MySQL ensure: {field}")
    assert_true(
        "ix_amz_comp_visual_current" in database_text
        and "ix_amz_comp_visual_run_step" in database_text,
        "视觉初筛必须有 current selected 和 run/step 输入索引",
    )
    assert_true(
        "ProductCompetitorVisualMatchAction" in actions_text
        and '"product_competitor_visual_match"' in actions_text
        and "run_competitor_visual_match(product_id, db=db)" in actions_text
        and "clear_current_visual_match(db, product_id" in actions_text
        and "WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES" in actions_text,
        "Phase B 必须通过 ProductTaskAction 实现 reserve/service/success/failure 投影",
    )
    assert_true(
        "_reload_step_for_product_action" in actions_text
        and "failure_step = await _reload_step_for_product_action(ctx.db, step_id)" in product_worker_section
        and "Product task failure projection failed; preserving original worker error" in product_worker_section
        and "result = await db.execute(" in scheduler_text.split("except Exception as exc:", 1)[1].split("await emit_event", 1)[0]
        and "step_id" in scheduler_text.split("except Exception as exc:", 1)[1].split("await emit_event", 1)[0],
        "ProductTaskAction worker/scheduler failure path 必须 rollback 后重载 step 并隔离 failure hook 二次异常，防止 MissingGreenlet 崩 runner",
    )
    assert_true(
        "await action.validate(db, payload)" in create_runs_section
        and "existing = await _existing_active_run(db, action, payload)" in create_runs_section
        and create_runs_section.index("await action.validate(db, payload)") < create_runs_section.index("existing = await _existing_active_run(db, action, payload)"),
        "create_product_action_runs 顺序仍为 validate 后查 active run，processing 复用必须走 API bypass",
    )
    assert_true(
        "if product.workflow_status == WORKFLOW_STATUS_PROCESSING" in visual_retry_section
        and "return product" in visual_retry_section.split("if product.workflow_status == WORKFLOW_STATUS_PROCESSING", 1)[1].split("if product.workflow_status not in", 1)[0]
        and "create_product_competitor_visual_match_runs" not in visual_retry_section.split("if product.workflow_status == WORKFLOW_STATUS_PROCESSING", 1)[1].split("return product", 1)[0],
        "visual_match_competitors/processing 必须在 API 层 bypass，不能调用 planner 创建重复 run",
    )
    assert_true(
        ".where(TaskRun.task_type == TASK_TYPE_COMPETITOR_SEARCH)" in service_text
        and ".where(TaskRun.status == RUN_STATUS_SUCCEEDED)" in service_text
        and ".where(TaskStep.status == STEP_STATUS_SUCCEEDED)" in service_text
        and ".where(AmazonCompetitorSearchCandidate.task_run_id == search_run_id)" in service_text
        and ".where(AmazonCompetitorSearchCandidate.task_step_id == search_step_id)" in service_text,
        "视觉初筛必须限定当前成功 Phase A run/step 候选，不能按 product 历史候选全量排序",
    )
    for marker in (
        "direct_image_url",
        "_analyze_direct_url_reviews",
        "_direct_visual_match_prompt",
        "image_loaded",
        "slot/asin 绑定失败",
        "VLM direct URL JSON 解析失败",
        "settings.VLM_MODEL",
        "use_fake_vlm: bool = False",
        "FAKE_VISUAL_MATCH_MODEL = \"fake_competitor_visual_match_v1\"",
        "selected_for_capture",
        "MIN_SELECTED = 4",
        "MAX_SELECTED = 6",
    ):
        assert_true(marker in service_text, f"视觉初筛服务缺少合同标记: {marker}")
    for forbidden in (
        "analyze_contact_sheet",
        "build_contact_sheets",
        "download_candidate_image",
        "DownloadedCandidateImage",
        "CONTACT_SHEET_SIZE",
        "MAX_IMAGE_BYTES",
        "ALLOWED_CONTENT_TYPES",
        "Image.open",
        "ImageDraw",
    ):
        assert_true(forbidden not in service_text, f"竞品视觉初筛默认路径不得保留 Contact Sheet/下载主流程: {forbidden}")
    assert_true(
        "contact_sheet_evidence" not in service_text
        and "contact_sheet_evidence" not in actions_text
        and "row.visual_sheet_path = None" in actions_text
        and "row.visual_sheet_page = None" in actions_text
        and "row.visual_sheet_label = None" in actions_text,
        "竞品视觉初筛不得继续写 Contact Sheet evidence；legacy visual_sheet_* 字段只能清空/停写",
    )
    assert_true(
        "product_external_result_protection_reasons" in protection_text
        and "return product_external_result_protection_reasons(product)" in protection_text
        and "product_external_result_protection_reasons(product)" in actions_text,
        "通用外部结果保护必须使用中性 helper，并由视觉任务直接调用",
    )
    assert_true(
        "retry_competitor_visual_match" in workflow_text
        and "restart_competitor_search" in workflow_text
        and "product:{product_id}:competitor_visual_match" in workflow_text
        and "WORKFLOW_NODE_CAPTURE_COMPETITOR_CANDIDATES" in workflow_text,
        "workflow 必须提供视觉初筛重试、重搜和任务中心 correlation",
    )
    assert_true(
        '"product_competitor_candidate_capture"' in visual_action_section
        and '"visual_task_run_id": step.task_run_id' in visual_action_section
        and '"visual_task_step_id": step.id' in visual_action_section
        and "candidate_capture_task_run_ids" in visual_action_section
        and "视觉初筛完成，已提交候选详情抓取任务" in visual_action_section
        and "_test_new_visual_success_owns_capture_set_when_old_visual_succeeded" in (ROOT / "scripts" / "test_amazon_main_chain_after_search_qa_fixes.py").read_text(encoding="utf-8"),
        "视觉初筛 success hook 必须带当前 visual run/step 创建/复用候选详情 task，不能停在 pending 或误取旧 succeeded visual run",
    )
    assert_true(
        "retryProductCompetitorVisualMatch" in frontend_api_text
        and "retry_competitor_visual_match" in product_list_text
        and "retryCompetitorVisualMatch(product.id)" in product_list_text
        and "restart_competitor_search" in product_list_text,
        "商品列表必须消费后端视觉初筛 action 和重搜 action",
    )
    assert_true(
        "Amazon 竞品视觉初筛 Phase B" in product_flow_index
        and "product_competitor_visual_match" in task_runtime_index
        and "Phase B 视觉初筛实现对账" in prd_text,
        "Phase B 新任务、状态和数据契约必须同步 PRD/domain index",
    )


def test_auto_competitor_visual_match_phase_b_fixture_behaviour() -> None:
    code = r'''
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from app.services.amazon_competitor_visual_match import (
    _fake_visual_reviews,
    _record_for_candidate,
)

with TemporaryDirectory(prefix="fbm_visual_match_fixture_") as tmp:
    root = Path(tmp)
    records = []
    product = SimpleNamespace(data=SimpleNamespace(title="Modern Modular Fabric Sofa Storage Chaise"), gigab2b_product_id="P1")
    for index in range(1, 7):
        candidate = SimpleNamespace(
            id=index,
            asin=f"B0TEST{index:03d}",
            image_url=f"https://img.test/candidate-{index}.jpg",
            search_rank=index,
            title=f"Modern Modular Fabric Sofa Storage Chaise Living Room {index}",
            price="$99.99",
            rating="4.5",
            review_count="100",
        )
        records.append(_record_for_candidate(candidate, index))
    reviews = _fake_visual_reviews(product, records)
    accepted = [item for item in reviews if not item["reject"] and item["same_product_type"] and item["visual_similarity"] >= 0.65]
    assert len(accepted) >= 4, reviews
    assert all(item["slot"] == f"C{index:02d}" for index, item in enumerate(reviews, start=1)), reviews
    assert all(item["raw"]["input_mode"] == "fake_fixture" for item in reviews), reviews

    accessory = dict(records[0])
    accessory["title"] = "Replacement spare part cover only"
    accessory_review = _fake_visual_reviews(product, [accessory])[0]
    assert accessory_review["reject"] is True
    assert accessory_review["reject_reason"] == "accessory_or_replacement", accessory_review
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"竞品视觉初筛 Phase B fake fixture 行为验证失败: {result.stderr or result.stdout}")


def test_auto_competitor_candidate_capture_and_selection_phase1_contract() -> None:
    status_text = (ROOT / "backend" / "app" / "models" / "status.py").read_text(encoding="utf-8")
    models_text = (ROOT / "backend" / "app" / "models" / "models.py").read_text(encoding="utf-8")
    database_text = (ROOT / "backend" / "app" / "database.py").read_text(encoding="utf-8")
    actions_text = (ROOT / "backend" / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    workflow_text = (ROOT / "backend" / "app" / "product_tasks" / "workflow.py").read_text(encoding="utf-8")
    capture_planner_text = (ROOT / "backend" / "app" / "task_planners" / "product_competitor_candidate_capture.py").read_text(encoding="utf-8")
    selection_planner_text = (ROOT / "backend" / "app" / "task_planners" / "product_auto_competitor_selection.py").read_text(encoding="utf-8")
    detail_service_text = (ROOT / "backend" / "app" / "services" / "amazon_listing_detail.py").read_text(encoding="utf-8")
    product_flow_index = (ROOT / "docs" / "domain-index" / "product-flow.md").read_text(encoding="utf-8")
    task_runtime_index = (ROOT / "docs" / "domain-index" / "task-runtime.md").read_text(encoding="utf-8")
    prd_text = (ROOT / "docs" / "superpowers" / "specs" / "2026-06-19-amazon-auto-competitor-selection-prd.md").read_text(encoding="utf-8")

    assert_true(
        'WORKFLOW_NODE_AUTO_SELECT_COMPETITOR = "auto_select_competitor"' in status_text
        and "WORKFLOW_NODE_AUTO_SELECT_COMPETITOR" in status_text.split("AMAZON_WORKFLOW_NODES = (", 1)[1].split(")", 1)[0],
        "Phase 1 必须把 auto_select_competitor 注册为正式 Amazon workflow node",
    )
    for field in (
        "detail_task_run_id",
        "detail_task_step_id",
        "visual_task_run_id",
        "visual_task_step_id",
        "detail_captured_at",
        "brand",
        "seller",
        "category_rank",
        "leaf_category",
        "main_image_url",
        "bullets_json",
        "description",
        "product_details_json",
        "aplus_text",
        "capture_status",
        "capture_error",
        "capture_raw_json",
        "final_selected",
        "final_rank",
        "final_score",
        "final_confidence",
        "final_dimension_scores_json",
        "final_reason",
        "final_risks_json",
        "final_model",
        "final_rule_version",
        "final_raw_json",
        "final_selected_at",
    ):
        assert_true(field in models_text and field in database_text, f"候选详情/最终选择字段缺少 ORM 或 MySQL ensure: {field}")
    assert_true(
        "_ensure_mysql_competitor_capture_selection_columns(conn)" in database_text
        and "ix_amz_comp_capture_current" in database_text
        and "ix_amz_comp_final_current" in database_text,
        "Phase 1 必须补 startup ensure 和 current fact 查询索引",
    )
    assert_true(
        "visual_task_run_id" in models_text
        and "visual_task_step_id" in models_text
        and "ix_amz_comp_visual_capture_set" in database_text
        and "row.visual_task_run_id = visual_task_run_id" in actions_text
        and "row.visual_task_step_id = visual_task_step_id" in actions_text,
        "Phase 2A 必须把视觉 Top 集合绑定到当前 visual task run/step，不能只靠商品历史或搜索 run",
    )
    assert_true(
        '"product_competitor_candidate_capture"' in actions_text
        and '"product_auto_competitor_selection"' in actions_text
        and 'return f"product_competitor_candidate_capture:product:{product_id}"' in actions_text
        and 'return f"product_auto_competitor_selection:product:{product_id}"' in actions_text
        and 'return f"product:{product_id}:competitor_candidate_capture"' in actions_text
        and 'return f"product:{product_id}:auto_competitor_selection"' in actions_text,
        "两个新 task type 必须注册到 ProductAction task type、dedupe key 和 correlation key",
    )
    assert_true(
        "ProductCompetitorCandidateCaptureAction()" in actions_text
        and "ProductAutoCompetitorSelectionAction()" in actions_text
        and "class ProductCompetitorCandidateCaptureAction" in actions_text
        and "class ProductAutoCompetitorSelectionAction" in actions_text,
        "候选详情抓取和自动选竞品 action 必须注册到 product task action registry",
    )
    assert_true(
        '"product_competitor_candidate_capture"' in capture_planner_text
        and "create_product_action_runs" in capture_planner_text
        and '"product_auto_competitor_selection"' in selection_planner_text
        and "create_product_action_runs" in selection_planner_text,
        "两个 planner 必须走 create_product_action_runs 创建/复用任务中心 run",
    )
    assert_true(
        "clear_current_competitor_capture" in actions_text
        and "row.detail_task_run_id = None" in actions_text
        and "row.capture_status = None" in actions_text
        and "row.visual_selected_for_capture" not in actions_text.split("async def clear_current_competitor_capture", 1)[1].split("async def clear_current_auto_competitor_selection", 1)[0]
        and "row.search_rank" not in actions_text.split("async def clear_current_competitor_capture", 1)[1].split("async def clear_current_auto_competitor_selection", 1)[0],
        "clear_current_competitor_capture 只能清候选详情 current fact，不得清搜索/视觉事实",
    )
    selection_clear_section = actions_text.split("async def clear_current_auto_competitor_selection", 1)[1].split("async def _latest_successful_competitor_visual_match_ids", 1)[0]
    assert_true(
        "product_external_result_protection_reasons(product)" in selection_clear_section
        and "row.final_selected = 0" in selection_clear_section
        and "row.final_score = None" in selection_clear_section
        and "product.competitor_asin = None" in selection_clear_section
        and "product.catalog_item.competitor_asin = None" in selection_clear_section
        and 'snapshot.pop("selected_competitor", None)' in selection_clear_section
        and 'snapshot.pop("auto_competitor_selection", None)' in selection_clear_section,
        "clear_current_auto_competitor_selection 必须清 final current fact，并在 clear_product_fact=True 时经过保护门后清当前派生竞品事实",
    )
    capture_action_section = actions_text.split("class ProductCompetitorCandidateCaptureAction", 1)[1].split("class ProductAutoCompetitorSelectionAction", 1)[0]
    assert_true(
        "_current_visual_selected_for_capture" in actions_text
        and "_visual_ids_from_payload(payload)" in capture_action_section
        and '"visual_task_run_id"] = visual_task_run_id' in capture_action_section
        and '"visual_task_step_id"] = visual_task_step_id' in capture_action_section
        and "visual_task_run_id=visual_task_run_id" in capture_action_section
        and "AmazonListingDetailError" in capture_action_section
        and "get_amazon_listing_detail_adapter" in capture_action_section
        and "listing_detail_to_dict" in capture_action_section
        and "候选详情抓取结果未完整匹配当前视觉 Top 集合" in capture_action_section
        and 'node=WORKFLOW_NODE_AUTO_SELECT_COMPETITOR' in capture_action_section
        and 'status=WORKFLOW_STATUS_PENDING' in capture_action_section,
        "Phase 2A candidate capture 必须按当前 visual run/step 抓详情，success hook 才写 detail facts 并推进 auto_select_competitor/pending",
    )
    assert_true(
        "row.detail_task_run_id = step.task_run_id" in capture_action_section
        and "row.capture_status = status" in capture_action_section
        and "row.capture_raw_json = json_dumps" in capture_action_section
        and "row.final_selected" not in capture_action_section
        and "product.competitor_asin" not in capture_action_section,
        "Phase 2A candidate capture 只能写候选详情 current facts，不得写 final 选择或最终竞品 ASIN",
    )
    assert_true(
        '"product_auto_competitor_selection"' in capture_action_section
        and "auto_competitor_selection_task_run_ids" in capture_action_section
        and "候选竞品详情抓取完成，已提交自动选竞品任务" in capture_action_section
        and "adapter_not_configured" in (ROOT / "scripts" / "test_amazon_main_chain_after_search_qa_fixes.py").read_text(encoding="utf-8"),
        "候选详情 success hook 必须创建/复用自动选竞品 task；默认 detail adapter 阻塞必须有 typed behavior 脚本覆盖",
    )
    selection_action_section = actions_text.split("class ProductAutoCompetitorSelectionAction", 1)[1].split("class ProductImageAnalysisAction", 1)[0]
    assert_true(
        "AUTO_COMPETITOR_HIGH_THRESHOLD = 0.78" in actions_text
        and "AUTO_COMPETITOR_MEDIUM_THRESHOLD = 0.68" in actions_text
        and "_current_captured_candidates_for_auto_selection" in actions_text
        and "_score_auto_competitor_candidates(product, rows)" in selection_action_section
        and "different_product_type_low_title_and_category_alignment" in actions_text
        and "selected_candidate_id" in selection_action_section
        and "row.final_selected = 1" not in capture_action_section
        and "selected_row.final_selected = 1" in selection_action_section
        and "product.competitor_asin = asin" in selection_action_section
        and "product.catalog_item.competitor_asin = asin" in selection_action_section
        and 'snapshot["selected_competitor"]' in selection_action_section
        and "_create_or_reuse_image_analysis_after_auto_competitor" in selection_action_section
        and "auto_start=False" in actions_text,
        "E4A 自动选竞品必须使用 current-set deterministic scoring，success hook 才写 final facts 并创建/复用 image_analysis 且不自动启动真实图片分析",
    )
    assert_true(
        "retry_competitor_candidate_capture" not in workflow_text
        and "retry_auto_competitor_selection" not in workflow_text
        and "product:{product_id}:competitor_candidate_capture" in workflow_text
        and "product:{product_id}:auto_competitor_selection" in workflow_text
        and '"primary_action": "open_task_center"' in workflow_text
        and '"allowed_actions": ("open_task_center", "open_detail")' in workflow_text
        and '"primary_action": "open_detail"' in workflow_text
        and '"allowed_actions": ("open_detail", "restart_competitor_search")' in workflow_text
        and "manual_select_competitor" not in workflow_text,
        "Phase 1 workflow 只能暴露 open_detail/restart/open_task_center 等前端已支持安全动作，不能泄漏未实现 retry 或 manual action",
    )
    assert_true(
        "FixtureAmazonListingDetailAdapter" in detail_service_text
        and "UnconfiguredAmazonListingDetailAdapter" in detail_service_text
        and "adapter_not_configured" in detail_service_text
        and "parse_amazon_listing_detail_html" in detail_service_text
        and "listing_detail_to_dict" in detail_service_text,
        "Amazon listing detail service 必须只有 fixture/default adapter 边界和 fixture parser",
    )
    for forbidden in ("requests", "httpx", "aiohttp", "playwright", "selenium", "urlopen"):
        assert_true(forbidden not in detail_service_text, f"Phase 1 listing detail adapter 禁止真实网络/浏览器依赖: {forbidden}")
    assert_true(
        "Phase 1 候选详情抓取与自动选竞品结构契约对账" in prd_text
        and "Phase 2A 候选详情抓取 fixture 执行与 current-set 对账" in prd_text
        and "Amazon 候选详情抓取 / 自动选竞品 E4A" in product_flow_index
        and "deterministic final competitor scoring/write" in product_flow_index
        and "product_competitor_candidate_capture" in task_runtime_index
        and "product_auto_competitor_selection" in task_runtime_index,
        "Phase 2A/E4A 新任务、状态和数据契约必须同步 PRD/domain index",
    )


def test_auto_competitor_candidate_capture_fixture_adapter_behaviour() -> None:
    code = r'''
import asyncio
from app.services.amazon_listing_detail import (
    AmazonListingDetailError,
    FixtureAmazonListingDetailAdapter,
    UnconfiguredAmazonListingDetailAdapter,
    listing_detail_to_dict,
    parse_amazon_listing_detail_html,
)

html = """
<html><body data-asin="B0DETAIL001">
  <span id="productTitle">Modern Modular Fabric Sofa with Storage Chaise</span>
  <a id="bylineInfo">Visit the Vindhvisk Store</a>
  <a id="sellerProfileTriggerId">Furniture Seller LLC</a>
  <img id="landingImage" src="https://images.example/detail-main.jpg" />
  <span class="a-price"><span class="a-offscreen">$399.99</span></span>
  <span class="a-icon-alt">4.6 out of 5 stars</span>
  <span id="acrCustomerReviewText">321 ratings</span>
  <div id="feature-bullets">
    <ul>
      <li><span class="a-list-item">Spacious modular sofa for living rooms.</span></li>
      <li><span class="a-list-item">Storage chaise with reversible layout.</span></li>
    </ul>
  </div>
  <div id="productDescription"><span>Comfortable upholstered seating for apartments.</span></div>
  <table>
    <tr><th>Brand</th><td>Vindhvisk</td></tr>
    <tr><th>Best Sellers Rank</th><td>#12 in Home & Kitchen &gt; Furniture &gt; Sofas</td></tr>
  </table>
  <div id="aplus">Premium fabric and sturdy frame.</div>
</body></html>
"""

detail = parse_amazon_listing_detail_html(html, asin="b0detail001", url="https://www.amazon.com/dp/B0DETAIL001")
assert detail.asin == "B0DETAIL001", detail
assert detail.title == "Modern Modular Fabric Sofa with Storage Chaise", detail
assert detail.brand == "Visit the Vindhvisk Store", detail
assert detail.seller == "Furniture Seller LLC", detail
assert detail.main_image_url == "https://images.example/detail-main.jpg", detail
assert len(detail.bullets) == 2, detail.bullets
assert detail.product_details["Brand"] == "Vindhvisk", detail.product_details
assert detail.category_rank == "#12 in Home & Kitchen > Furniture > Sofas", detail.category_rank
assert detail.leaf_category == "Sofas", detail.leaf_category
assert listing_detail_to_dict(detail)["raw"]["parser"] == "fixture_html_v1"

async def main():
    fixture = FixtureAmazonListingDetailAdapter({"B0DETAIL001": html})
    fetched = await fixture.fetch("B0DETAIL001", url="https://www.amazon.com/dp/B0DETAIL001")
    assert fetched.title == detail.title, fetched
    try:
        await fixture.fetch("B0MISSING")
    except AmazonListingDetailError as exc:
        assert exc.error_type == "fixture_missing", exc.error_type
    else:
        raise AssertionError("missing fixture must fail explicitly")
    try:
        await UnconfiguredAmazonListingDetailAdapter().fetch("B0DETAIL001")
    except AmazonListingDetailError as exc:
        assert exc.error_type == "adapter_not_configured", exc.error_type
    else:
        raise AssertionError("unconfigured adapter must not access real Amazon")

asyncio.run(main())
'''
    result = subprocess.run(
        [str(ROOT / "backend" / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT / "backend",
        text=True,
        capture_output=True,
    )
    assert_true(result.returncode == 0, f"候选详情 fixture adapter 行为验证失败: {result.stderr or result.stdout}")


def main() -> int:
    tests = [
        test_category_conflict_only_overrides_conflict,
        test_template_mapping_changes_must_be_logged,
        test_real_asin_export_guard_is_present,
        test_amazon_workflow_t1_fields_and_enums_exist,
        test_amazon_workflow_t2_service_projection_and_write_rules,
        test_product_work_status_producer_outputs_are_registered,
        test_product_overview_handles_uninitialized_workflow_bucket,
        test_product_detail_uses_workflow_as_primary_display_source,
        test_amazon_workflow_t3_image_selection_reset_and_initialization_rules,
        test_amazon_workflow_t4_competitor_search_rules,
        test_amazon_workflow_t5_competitor_capture_rules,
        test_product_detail_get_is_readonly_for_material_videos,
        test_inventory_update_template_exports_stock_only_by_sku,
        test_catalog_export_creation_keeps_business_reasons_in_task_report,
        test_asin_sync_uses_seller_sku_first_and_upc_auxiliary_only,
        test_lingxing_listing_sync_t2_contract,
        test_step10_keeps_sofa_dimensions_and_avoids_inventory_conflict,
        test_step1_collects_product_dimensions_and_numeric_packages,
        test_step10_sums_multi_package_dimensions,
        test_mapping_sets_andy_free_shipping_template,
        test_bicycle_template_mapping_covers_current_failed_categories,
        test_search_terms_are_twenty_comma_separated_keywords,
        test_gigab2b_alphanumeric_product_id_url_is_supported,
        test_upc_pool_is_source_of_new_task_upcs,
        test_offline_tasks_are_claimed_and_idempotent,
        test_product_pipeline_recovers_interrupted_competitor_capture,
        test_competitor_review_queue_uses_workbench_status_scope,
        test_product_bulk_advance_runs_in_task_run_queue,
        test_catalog_export_uses_snapshot_and_reuses_orphan_zip,
        test_export_listing_aplus_new_task_runtime_creation_paths,
        test_amazon_export_binds_upc_after_prechecks_and_rolls_back,
        test_tiktok_sales_channel_keeps_giga_source_and_uses_warehouse_inventory,
        test_giga_pull_tasks_expose_live_sku_progress_without_group_closure_during_pull,
        test_task_runtime_v1_uses_new_tables_and_keeps_old_offline_tasks_compatibility,
        test_task_run_display_status_behaviour_for_current_view,
        test_task_run_list_default_views_are_db_pageable,
        test_task_run_shrink_route_rejects_diagnostic_list_filters,
        test_task_run_detail_keeps_stale_running_diagnostic_state,
        test_runtime_security_startup_p0_boundaries,
        test_runtime_security_helpers_behaviour,
        test_failed_task_run_display_precedes_pending_steps,
        test_task_run_creation_responses_reload_created_runs,
        test_product_action_backfill_updates_only_task_run_metadata,
        test_product_task_action_reserve_states_are_not_marked_interrupted,
        test_product_action_lifecycle_writes_workflow_fields,
        test_image_analysis_listing_e5_contract,
        test_aplus_auto_after_export_ready_a1_a2_contract,
        test_lingxing_aplus_publish_t1_data_registry_bootstrap_contract,
        test_lingxing_aplus_publish_t3_draft_save_contract,
        test_lingxing_aplus_module_mapping_m2_contract,
        test_lingxing_aplus_enhanced_basic_registry_phase1_contract,
        test_lingxing_aplus_step7_enhanced_phase2_producer_schema,
        test_product_action_worker_does_not_project_failure_for_interrupted,
        test_product_action_final_progress_failure_is_best_effort,
        test_auto_image_selection_phase_a_contract,
        test_auto_image_selection_candidate_priority_behaviour,
        test_auto_image_selection_service_and_action_behaviour,
        test_auto_image_selection_phase_b_contract,
        test_auto_image_selection_phase_b_work_status_behaviour,
        test_auto_image_selection_phase_b_protection_behaviour,
        test_auto_competitor_search_phase_a_contract,
        test_auto_competitor_search_phase_a_query_and_fixture_behaviour,
        test_real_amazon_search_adapter_boundaries,
        test_task_runtime_autostart_runner_lifecycle_behaviour,
        test_auto_competitor_visual_match_phase_b_contract,
        test_auto_competitor_visual_match_phase_b_fixture_behaviour,
        test_auto_competitor_candidate_capture_and_selection_phase1_contract,
        test_auto_competitor_candidate_capture_fixture_adapter_behaviour,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print(f"OK: {len(tests)} project rule test(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
