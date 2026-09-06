"""Static guard for legacy large-field access after the SQLite cutover.

Legacy-shaped reads remain only inside registered projection consumers. Writes
must either be a response projection, a synchronous helper whose caller
persists through the repository, or contain an explicit repository operation.
"""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
LEGACY_FIELDS = set(
    "packages features description variants gigab2b_raw_snapshot customer_mindset "
    "listing_title listing_bullets listing_product_highlights listing_search_terms "
    "listing_title_zh listing_bullets_zh listing_product_highlights_zh "
    "listing_description listing_description_zh listing_search_terms_zh listing_check "
    "listing_primary_keyword listing_removed_keywords image_analysis image_selling_points "
    "image_selection_analysis image_compliance_manifest aplus_plan aplus_scripts aplus_images "
    "amazon_template_path amazon_template_warnings amazon_template_fill_summary"
    .split()
)

# These modules consume values projected by hydrate_product_sections at their
# async entry point. Adding a consumer in a different module requires an
# explicit review and registration here.
REGISTERED_READER_MODULES = {
    "api/products.py",
    "api/tiktok.py",
    "pipeline/amazon_export/listing_fill.py",
    "pipeline/amazon_export/writer.py",
    "pipeline/customer_mindset.py",
    "pipeline/engine.py",
    "pipeline/step10_amazon_template.py",
    "pipeline/step3_keywords.py",
    "pipeline/step4_category.py",
    "pipeline/step5_listing.py",
    "pipeline/step6_image.py",
    "pipeline/step7_aplus_plan.py",
    "pipeline/step8_aplus_script.py",
    "pipeline/step9_aplus_image.py",
    "pipeline/template_category_fallback.py",
    "product_tasks/actions.py",
    "product_tasks/auto_image_selection.py",
    "product_tasks/workflow.py",
    "services/amazon_competitor_query.py",
    "services/aplus_auto_trigger.py",
    "services/aplus_regenerate.py",
    "services/aplus_upload.py",
    "services/giga_product_drafts.py",
    "services/lingxing_aplus_publish_policy.py",
    "services/offline_tasks.py",
    "services/product_image_candidates.py",
    "services/product_material_prepare.py",
    "services/product_pipeline_artifacts.py",
    "services/product_protection.py",
    "task_planners/aplus_generate.py",
    "task_planners/product_bulk_advance.py",
    "task_runtime/aplus_generate_workers.py",
    "task_runtime/product_bulk_advance_workers.py",
}

REPOSITORY_WRITE_TOKENS = (
    "write_section(",
    "invalidate_sections(",
    "persist_source_sections_from_projection(",
    "persist_image_sections_from_projection(",
    "persist_listing_section_from_projection(",
    "large_field_storage_enabled(",
)
REGISTERED_SYNC_ADAPTERS = {
    "_compact_product_detail",
    "_hydrate_product_detail_customer_mindset",
    "_set_listing_check_template_field",
    "_ensure_listing_person_detections",
    "refresh_listing_image_alignment",
    "_restore_cached_image_analysis",
    "get_product",
}
NON_PRODUCT_RECEIVERS = {"row", "detail", "selected_row", "sku"}


def _receiver_name(node: ast.Attribute) -> str | None:
    value: ast.AST = node.value
    while isinstance(value, ast.Attribute):
        value = value.value
    return value.id if isinstance(value, ast.Name) else None


def main() -> None:
    unregistered_reads: list[str] = []
    unsafe_writes: list[str] = []
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        if relative in {"models/models.py", "services/product_payloads.py"} or relative.startswith("migrations/"):
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        parents: list[ast.AST] = []

        class Visitor(ast.NodeVisitor):
            def generic_visit(self, node: ast.AST) -> None:
                parents.append(node)
                super().generic_visit(node)
                parents.pop()

            def visit_Attribute(self, node: ast.Attribute) -> None:
                if node.attr not in LEGACY_FIELDS:
                    return self.generic_visit(node)
                function = next(
                    (item for item in reversed(parents) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))),
                    None,
                )
                function_name = function.name if function else "<module>"
                location = f"{relative}:{node.lineno}:{function_name}:{node.attr}"
                if _receiver_name(node) in NON_PRODUCT_RECEIVERS:
                    return self.generic_visit(node)
                if isinstance(node.ctx, ast.Load) and relative not in REGISTERED_READER_MODULES:
                    unregistered_reads.append(location)
                if isinstance(node.ctx, ast.Store):
                    function_source = ast.get_source_segment(source, function) if function else ""
                    if function_name not in REGISTERED_SYNC_ADAPTERS and not any(
                        token in (function_source or "") for token in REPOSITORY_WRITE_TOKENS
                    ):
                        unsafe_writes.append(location)
                return self.generic_visit(node)

        Visitor().visit(tree)

    assert not unregistered_reads, "unregistered legacy large-field readers:\n" + "\n".join(unregistered_reads)
    assert not unsafe_writes, "unsafe legacy large-field writes:\n" + "\n".join(unsafe_writes)

    frontend = (ROOT / "frontend" / "src" / "pages" / "ProductDetail.tsx").read_text(encoding="utf-8")
    tab_loader = frontend.split("const sectionsByTab", 1)[1].split("useEffect", 1)[0]
    assert "mindset: ['mindset']" in tab_loader
    assert "runPipelineStep" not in tab_loader and "runProductFromStep" not in tab_loader
    assert "sectionCacheRef.current" in frontend and "stale: true" in frontend
    for state_text in ("正在加载内容", "暂无内容", "内容加载失败", "历史内容无法解析", "内容已更新，正在刷新"):
        assert state_text in frontend, f"missing section state UI: {state_text}"

    drafts = (APP / "services" / "giga_product_drafts.py").read_text(encoding="utf-8")
    source_persist = drafts.find("await persist_source_sections_from_projection(db, pd)")
    upc_query = drafts.find("await ensure_product_upc(db, product)")
    assert 0 <= source_persist < upc_query, "GIGA draft source payload must be cleared before UPC query autoflush"

    payload_repository = (APP / "services" / "product_payloads.py").read_text(encoding="utf-8")
    projection = payload_repository.split("def apply_section_projection", 1)[1].split("async def hydrate_product_sections", 1)[0]
    assert 'product.__dict__.get("data")' in projection
    assert 'product.__dict__.get("images")' in projection
    assert 'product.__dict__.get("aplus")' in projection
    assert "getattr(product," not in projection, "section projection must not trigger async relationship lazy loads"

    giga_workers = (APP / "task_runtime" / "giga_pull_workers.py").read_text(encoding="utf-8")
    skip_existing = giga_workers.split("skipped_existing_count = 0", 1)[1].split("available_new_sku_count", 1)[0]
    assert "listed_skus=sku_codes" in skip_existing, "explicit SKU scope must survive skip-existing filtering"

    actions = (APP / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    mindset_success = actions.split("class ProductCustomerMindsetAction", 1)[1].split(
        "class ProductListingGenerationAction", 1
    )[0]
    assert 'hydrate_product_sections(db, product, ("source", "source_snapshot", "mindset"))' in mindset_success, (
        "mindset success must restore canonical source inputs after ProductData refresh before fingerprint validation"
    )
    listing_success = actions.split("class ProductListingGenerationAction", 1)[1]
    assert '("source", "source_snapshot", "mindset", "listing")' in listing_success, (
        "listing success must restore canonical mindset inputs and output after ProductData refresh"
    )

    aplus_planner = (APP / "task_planners" / "aplus_generate.py").read_text(encoding="utf-8")
    assert '("listing", "image_analysis", "aplus_assets")' in aplus_planner, (
        "A+ planner readiness must consume canonical Listing and image payloads"
    )


if __name__ == "__main__":
    main()
