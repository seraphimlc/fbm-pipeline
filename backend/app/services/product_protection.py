from __future__ import annotations

from app.models import Product


AMAZON_TEMPLATE_FILE_TYPES = {"amazon_import_template", "amazon_template"}


def product_external_result_protection_reasons(product: Product) -> list[str]:
    reasons: list[str] = []
    catalog = product.catalog_item
    data = product.data
    files = getattr(product, "files", None) or []
    if product.amazon_asin:
        reasons.append("商品已有真实 Amazon ASIN")
    if product.aplus_uploaded_at or product.aplus_upload_status not in {None, "", "not_uploaded", "failed"}:
        reasons.append("商品已有 A+ 上传记录或上传中状态")
    if catalog:
        if catalog.amazon_asin:
            reasons.append("Catalog 已有真实 Amazon ASIN")
        if catalog.confirmed_at:
            reasons.append("Catalog 已人工确认")
        if catalog.exported_at or catalog.export_task_id or catalog.export_file_path:
            reasons.append("Catalog 已有真实导出历史")
        if catalog.aplus_uploaded_at or catalog.aplus_upload_status not in {None, "", "not_uploaded", "failed"}:
            reasons.append("Catalog 已有 A+ 上传记录或上传中状态")
    if data and (
        data.amazon_template_path
        or data.amazon_template_generated_at
        or data.amazon_template_fill_summary
        or data.amazon_template_warnings
    ):
        reasons.append("商品已有 Amazon 模板输出证据")
    if any(str(getattr(item, "file_type", "") or "").strip().lower() in AMAZON_TEMPLATE_FILE_TYPES for item in files):
        reasons.append("商品已有 Amazon 模板文件输出证据")
    return reasons


def auto_image_selection_protection_reasons(product: Product) -> list[str]:
    return product_external_result_protection_reasons(product)


def raise_if_auto_image_selection_protected(product: Product) -> None:
    reasons = auto_image_selection_protection_reasons(product)
    if reasons:
        raise RuntimeError("当前商品已有不可逆外部结果，不能自动选图：" + "；".join(reasons))


def raise_if_image_selection_reset_protected(product: Product) -> None:
    reasons = auto_image_selection_protection_reasons(product)
    if reasons:
        raise RuntimeError("当前商品已有不可逆外部结果，不能静默重置图片下游派生：" + "；".join(reasons))
