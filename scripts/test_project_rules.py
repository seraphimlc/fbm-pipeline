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
        "assert_gigab2b_logged_in_for_inventory" in text,
        "创建库存同步批次前必须先检查大建云仓登录态，未登录不能创建同步批次",
    )
    assert_true(
        "GIGAB2B_LOGIN_REQUIRED_ERROR" in inventory_sync_text and "_fail_whole_batch" in inventory_sync_text,
        "库存同步后台批次也必须保留大建云仓登录态兜底检查",
    )


def test_step10_keeps_sofa_dimensions_and_avoids_inventory_conflict() -> None:
    step10_py = ROOT / "backend" / "app" / "pipeline" / "step10_amazon_template.py"
    text = step10_py.read_text(encoding="utf-8")
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
    chair_block = text.split('if product_type == "CHAIR":', 1)[1].split("if pd.weight:", 1)[0]
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
        'fields["maximum_weight_recommendation"]: _weight_capacity_maximum(seating, pd)' in text,
        "Maximum Weight Recommendation 必须由商品文本和座位数共同推断，不能只按旧座位数兜底",
    )
    assert_true(
        "_shipping_template_for_product" in text and "shipping_template_by_brand" in text,
        "Amazon 导入表格必须支持按品牌指定配送模板，不能只取模板第一个下拉值",
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


def main() -> int:
    tests = [
        test_category_conflict_only_overrides_conflict,
        test_template_mapping_changes_must_be_logged,
        test_real_asin_export_guard_is_present,
        test_inventory_update_template_exports_stock_only_by_sku,
        test_step10_keeps_sofa_dimensions_and_avoids_inventory_conflict,
        test_step1_collects_product_dimensions_and_numeric_packages,
        test_step10_sums_multi_package_dimensions,
        test_mapping_sets_andy_free_shipping_template,
        test_bicycle_template_mapping_covers_current_failed_categories,
        test_search_terms_are_twenty_comma_separated_keywords,
        test_gigab2b_alphanumeric_product_id_url_is_supported,
        test_upc_pool_is_source_of_new_task_upcs,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print(f"OK: {len(tests)} project rule test(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
