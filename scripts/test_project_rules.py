#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


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


def test_asin_sync_uses_lingxing_product_code_for_upc() -> None:
    asin_sync_py = ROOT / "backend" / "app" / "services" / "asin_sync.py"
    text = asin_sync_py.read_text(encoding="utf-8")
    assert_true(
        'lookup_type = "商品编码" if upc else "MSKU"' in text,
        "ASIN 同步必须把 UPC 当作领星商品编码查询，只有缺少 UPC 时才用 MSKU 兜底",
    )
    assert_true(
        'if normalized.upper() == "UPC":' in text
        and 'return "商品编码"' in text
        and 'if normalized.upper() == "SKU":' in text
        and 'return "MSKU"' in text,
        "ASIN 同步必须兼容旧批次里已保存的 UPC/SKU 查询类型",
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
        "ASIN 同步必须走领星 Listing API：UPC/商品编码查 amz_product_id，商品 code 查 msku",
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
    task_center_text = (ROOT / "frontend" / "src" / "pages" / "OfflineTaskCenter.tsx").read_text(encoding="utf-8")
    task_center_spec_text = (ROOT / "docs" / "superpowers" / "specs" / "2026-06-03-offline-task-center.md").read_text(encoding="utf-8")
    main_text = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")

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
        "create_product_bulk_advance_task" in products_api_text
        and "PRODUCT_BULK_ADVANCE_MAX_PRODUCTS = 1000" in products_api_text
        and 'task_type="product_bulk_advance"' in products_api_text
        and '"rows": rows' in products_api_text
        and "尚未完成图片确认、竞品选择和竞品详情抓取" in products_api_text,
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
        "product_bulk_advance" in task_center_text
        and "resultRows" in task_center_text
        and "明细" in task_center_text,
        "任务中心必须能展示批量推进任务的逐商品 rows/report",
    )
    assert_true(
        "_with_product_bulk_advance_progress" in offline_api_text
        and '"latest_result"' in offline_api_text
        and '"export_ready_count"' in offline_api_text
        and "当前结果" in task_center_text
        and "已到待导出" in task_center_text,
        "批量推进任务报告必须只读补充 started 商品当前是否已到待导出，不能只停留在 enqueue 结果",
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
        and "isCompetitorSearchFailed &&" in product_detail_text
        and "重新搜索候选" in product_detail_text
        and "同款搜索|StyleSnap" in product_page_text
        and "候选竞品搜索失败" in products_api_text
        and "大健详情页 Gallery" in product_detail_text
        and "其它 SKU 详情页 Gallery" in product_detail_text
        and "素材包/附件素材" in product_detail_text
        and "备用/未选素材" in product_detail_text
        and "_giga_image_candidates_for_product" in products_api_text,
        "商品详情图片确认必须默认用代表 SKU 的 GIGA mainImage 做主图，再从 gallery 末尾取 8 张；旧纯路径、未知类型和其它 SKU 图片不能全量默认选中，file/brand 留作备用素材",
    )
    stylesnap_text = (ROOT / "backend" / "app" / "services" / "amazon_stylesnap_search.py").read_text(encoding="utf-8")
    assert_true(
        "chrome_get_page_info" in stylesnap_text
        and "_ensure_stylesnap_upload_page" in stylesnap_text
        and '"amazon.com/stylesnap" in url' in stylesnap_text
        and "timeout=3" in stylesnap_text,
        "StyleSnap 搜索在同一个 Chrome worker tab 中应优先复用已有页面/token，失效时再导航重新获取",
    )


def test_product_pipeline_recovers_interrupted_competitor_capture() -> None:
    engine_text = (ROOT / "backend" / "app" / "pipeline" / "engine.py").read_text(encoding="utf-8")

    assert_true(
        "recover_interrupted_pipelines" in engine_text
        and "_is_competitor_listing_capture_state(product)" in engine_text,
        "商品 pipeline 启动恢复必须识别竞品详情抓取中的特殊状态，不能当作 Listing 生成续跑",
    )
    assert_true(
        'product.error_message = "竞品详情抓取被中断，请重新抓详情"' in engine_text
        and "product.status = FAILED" in engine_text
        and "product.current_step = 4" in engine_text,
        "竞品详情抓取中断后必须落到可重试失败态，不能重启后继续显示后台抓取中",
    )
    assert_true(
        'capture.capture_status = "failed"' in engine_text
        and "capture.capture_error = product.error_message" in engine_text,
        "竞品详情抓取中断恢复必须同步 AmazonListingCapture 记录，前端才能显示重新抓详情入口",
    )
    assert_true(
        "start_pipeline(product_id, start_step=step)" in engine_text,
        "真正的商品生成节点重启后仍应按原步骤重新排队续跑",
    )


def test_competitor_review_queue_uses_workbench_status_scope() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")

    assert_true(
        "COMPETITOR_REVIEW_ERROR_KEYWORDS" in products_api_text
        and '"候选竞品"' in products_api_text
        and '"参考竞品"' in products_api_text
        and '"选择竞品"' in products_api_text,
        "商品工作台和选竞品队列必须共享候选/参考/选择竞品失败关键词，避免数量不一致",
    )
    assert_true(
        "def _competitor_search_failed_sql_condition" in products_api_text
        and "| _competitor_search_failed_sql_condition()" in products_api_text,
        "选竞品队列必须使用与工作台同源的竞品失败 SQL 条件，不能另写一套较窄筛选",
    )


def test_product_bulk_advance_runs_in_offline_task_queue() -> None:
    products_api_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    offline_tasks_text = (ROOT / "backend" / "app" / "services" / "offline_tasks.py").read_text(encoding="utf-8")
    product_list_text = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")

    assert_true(
        '"product_bulk_advance"' in offline_tasks_text
        and '"product_bulk_advance_product"' in offline_tasks_text
        and "run_pipeline_tracked" in offline_tasks_text,
        "批量推进商品必须作为任务中心 step 执行，不能只写审计记录后把真实 pipeline 丢到内存后台",
    )
    assert_true(
        "schedule_offline_task(task.id)" in products_api_text
        and "status=\"pending\"" in products_api_text
        and "enqueue_pipeline(product_id, start_step=start_step)" not in products_api_text.split("async def _create_product_bulk_advance_task_for_ids", 1)[1].split("@router.post(\"/bulk-advance-task\"", 1)[0],
        "product_bulk_advance 创建时必须入任务中心 pending 队列，不得直接 enqueue_pipeline",
    )
    assert_true(
        "autoStartReadyGeneration" not in product_list_text,
        "商品列表页不能打开后自动启动待生成商品；离线推进必须由用户显式提交任务中心",
    )
    schemas_text = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    assert_true(
        "work_status" in schemas_text
        and "_product_workbench_status(product) == body.work_status" in products_api_text
        and "work_status: generationStatusFilter === 'all' ? undefined : generationStatusFilter" in product_list_text,
        "批量推进当前筛选必须支持工作台状态分桶，已中断等前端工作状态不能只筛当前页",
    )


def test_catalog_export_uses_snapshot_and_reuses_orphan_zip() -> None:
    catalog_page_text = (ROOT / "frontend" / "src" / "pages" / "CatalogList.tsx").read_text(encoding="utf-8")
    offline_tasks_text = (ROOT / "backend" / "app" / "services" / "offline_tasks.py").read_text(encoding="utf-8")

    assert_true(
        "商品再导出" in catalog_page_text
        and "文件历史" in catalog_page_text
        and "再次导出选中(${selectedIds.length})" in catalog_page_text
        and "请先勾选要导出的商品" in catalog_page_text
        and "exportView" in catalog_page_text
        and "isCatalogProductExported" in catalog_page_text
        and "isProductListView ? fetchItems() : fetchExportFiles()" in catalog_page_text
        and "selectedIds.map(Number)" in catalog_page_text
        and "isProductListView ? (" in catalog_page_text
        and "disabled={exporting || currentLoading || exportDisabled}" in catalog_page_text,
        "导出中心商品导出必须拆成商品再导出/文件历史；商品再导出用状态列区分待导出和已导出，并且创建任务只来自勾选商品；文件历史仍按文件维度展示",
    )
    assert_true(
        "_recover_catalog_export_result_from_file" in offline_tasks_text
        and "_report_rows_from_export_zip" in offline_tasks_text
        and "glob(\"*.zip\")" in offline_tasks_text
        and "catalog_export_t{step.task_id}_s{step.id}.zip" in offline_tasks_text,
        "catalog_export step 重入时必须复用已有 zip/report 并使用稳定短文件名，避免生成未被任务 result 引用的孤儿 zip 或过长文件名",
    )


def test_amazon_export_binds_upc_after_prechecks_and_rolls_back() -> None:
    products_text = (ROOT / "backend" / "app" / "api" / "products.py").read_text(encoding="utf-8")
    step10_text = (ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py").read_text(encoding="utf-8")

    catalog_section = products_text.split("for offset, entry in enumerate(chunk):", 1)[1].split("if exported_in_workbook:", 1)[0]
    assert_true(
        catalog_section.index("if sku and not latest_inventory:") < catalog_section.index("await ensure_product_upc(db, product)"),
        "catalog export 必须先确认最新 GIGA 库存快照存在，再绑定 UPC，避免失败商品消耗 UPC",
    )
    assert_true(
        catalog_section.index("await ensure_amazon_template_semantic_fields") < catalog_section.index("await ensure_product_upc(db, product)"),
        "catalog export 必须先完成模板语义字段前置检查，再绑定 UPC",
    )
    upc_flush_index = catalog_section.index("await db.flush()")
    row_copy_index = catalog_section.index("_copy_import_data_row")
    row_commit_index = catalog_section.index("await db.commit()", row_copy_index)
    assert_true(
        upc_flush_index < row_copy_index < row_commit_index,
        "catalog export 行复制成功前只能 flush UPC 绑定，不能提前 commit",
    )
    assert_true(
        "except Exception as exc:\n                        await db.rollback()" in catalog_section,
        "catalog export 单行失败必须 rollback 未提交的 UPC 绑定",
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


def main() -> int:
    tests = [
        test_category_conflict_only_overrides_conflict,
        test_template_mapping_changes_must_be_logged,
        test_real_asin_export_guard_is_present,
        test_inventory_update_template_exports_stock_only_by_sku,
        test_catalog_export_creation_keeps_business_reasons_in_task_report,
        test_asin_sync_uses_lingxing_product_code_for_upc,
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
        test_product_bulk_advance_runs_in_offline_task_queue,
        test_catalog_export_uses_snapshot_and_reuses_orphan_zip,
        test_amazon_export_binds_upc_after_prechecks_and_rolls_back,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print(f"OK: {len(tests)} project rule test(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
