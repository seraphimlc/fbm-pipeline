from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductFile


def _json_dumps(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=bool(indent), default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def product_dimensions(data: Any) -> dict[str, float] | None:
    """Return the persisted three-axis dimensions without assuming a synthetic model property."""
    if data is None:
        return None
    dimensions = {
        "length": getattr(data, "dimension_length", None),
        "width": getattr(data, "dimension_width", None),
        "height": getattr(data, "dimension_height", None),
    }
    normalized = {key: value for key, value in dimensions.items() if value is not None}
    return normalized or None


def _analysis_dir(product: Product) -> Path:
    if not product.data or not product.data.material_dir:
        raise ValueError("商品缺少 material_dir，不能写入分析产物")
    output_dir = Path(product.data.material_dir).expanduser().resolve() / "image analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


async def _upsert_product_file(
    db: AsyncSession,
    *,
    product_id: int,
    file_type: str,
    label: str,
    path: Path,
    metadata: dict[str, Any] | None = None,
) -> ProductFile:
    result = await db.execute(
        select(ProductFile).where(
            ProductFile.product_id == product_id,
            ProductFile.file_type == file_type,
            ProductFile.path == str(path),
        )
    )
    item = result.scalar_one_or_none()
    now = datetime.now()
    if item is None:
        item = ProductFile(
            product_id=product_id,
            file_type=file_type,
            label=label,
            path=str(path),
            created_at=now,
        )
        db.add(item)
    item.label = label
    item.directory = str(path.parent)
    item.metadata_json = _json_dumps(metadata or {})
    item.updated_at = now
    await db.flush()
    return item


async def register_pipeline_artifact(
    db: AsyncSession,
    *,
    product_id: int,
    file_type: str,
    path: Path,
    metadata: dict[str, Any] | None = None,
) -> ProductFile:
    return await _upsert_product_file(
        db,
        product_id=product_id,
        file_type=file_type,
        label=path.name,
        path=path,
        metadata=metadata,
    )


async def write_image_selection_artifacts(
    db: AsyncSession,
    *,
    product: Product,
    selection: dict[str, Any],
    main_path: str,
    gallery_paths: list[str],
) -> dict[str, str]:
    output_dir = _analysis_dir(product)
    data = product.data
    reviews = selection.get("image_reviews") if isinstance(selection.get("image_reviews"), list) else []
    source_snapshot = _json_loads(data.gigab2b_raw_snapshot, {}) if data else {}
    material_facts = source_snapshot.get("material_facts") if isinstance(source_snapshot, dict) else None
    planner_input = {
        "schema": "fbm-aplus-planner-input.v1",
        "product_id": product.id,
        "item_code": data.item_code if data else None,
        "title": data.title if data else None,
        "product_facts": {
            "color": data.color if data else None,
            "material": data.material if data else None,
            "product_type": data.product_type if data else None,
            "dimensions": product_dimensions(data),
            "features": _json_loads(data.features, data.features) if data else [],
        },
        "reference_image_selling_points": reviews,
        "supplier_material_facts": material_facts if isinstance(material_facts, dict) else {},
        "selected_gallery_coverage": {
            "main": main_path,
            "gallery": gallery_paths,
        },
        "decision_coverage": selection.get("decision_coverage"),
        "source": "product_auto_image_selection",
    }
    files = {
        "image_selling_points_json": output_dir / "image_selling_points.json",
        "image_selling_points_md": output_dir / "image_selling_points.md",
        "gallery_selection_md": output_dir / "gallery_selection.md",
        "aplus_planner_input_json": output_dir / "aplus_planner_input.json",
        "aplus_planner_input_md": output_dir / "aplus_planner_input.md",
    }
    files["image_selling_points_json"].write_text(_json_dumps(selection, indent=2), encoding="utf-8")
    review_lines = ["# 图片卖点与逐图判断", ""]
    for review in reviews:
        evidence = review.get("contact_sheet_evidence") if isinstance(review, dict) else {}
        review_lines.extend([
            f"## {review.get('image_id') or '-'} · {review.get('filename') or ''}",
            f"- 视觉摘要：{review.get('visual_summary') or '-'}",
            f"- 可见卖点：{review.get('visible_selling_point') or '-'}",
            f"- 转化职责：{review.get('conversion_role') or '-'}",
            f"- 风险：{', '.join(str(item) for item in (review.get('risk_flags') or [])) or '无'}",
            f"- Contact Sheet：第 {evidence.get('sheet_page') or '-'} 页 / {evidence.get('sheet_label') or '-'}",
            "",
        ])
    files["image_selling_points_md"].write_text("\n".join(review_lines), encoding="utf-8")
    gallery_lines = [
        "# Amazon 主图与 Gallery 选择",
        "",
        f"- MAIN：{main_path}",
        *[f"- Gallery {index}: {path}" for index, path in enumerate(gallery_paths, start=2)],
        "",
        f"- 决策覆盖：{_json_dumps(selection.get('decision_coverage') or {})}",
    ]
    files["gallery_selection_md"].write_text("\n".join(gallery_lines), encoding="utf-8")
    files["aplus_planner_input_json"].write_text(_json_dumps(planner_input, indent=2), encoding="utf-8")
    files["aplus_planner_input_md"].write_text(
        "\n".join([
            "# A+ 图片规划输入",
            "",
            f"- Product ID：{product.id}",
            f"- Item Code：{data.item_code if data else '-'}",
            f"- 商品：{data.title if data else '-'}",
            f"- MAIN：{main_path}",
            f"- Gallery：{len(gallery_paths)} 张",
            f"- 已分析图片：{len(reviews)} 张",
            "",
            "详细逐图证据请读取 `image_selling_points.json`。",
        ]),
        encoding="utf-8",
    )

    for key, path in files.items():
        await _upsert_product_file(
            db,
            product_id=product.id,
            file_type=key,
            label=path.name,
            path=path,
            metadata={"source": "product_auto_image_selection", "decision_coverage": selection.get("decision_coverage")},
        )
    return {key: str(path) for key, path in files.items()}


async def write_aplus_plan_artifacts(
    db: AsyncSession,
    *,
    product: Product,
    plan: dict[str, Any],
) -> dict[str, str]:
    output_dir = _analysis_dir(product)
    json_path = output_dir / "aplus_image_plan.json"
    md_path = output_dir / "aplus_image_plan.md"
    json_path.write_text(_json_dumps(plan, indent=2), encoding="utf-8")
    modules = plan.get("modules") if isinstance(plan.get("modules"), list) else []
    lines = ["# A+ 五图规划", "", f"- Product ID：{product.id}", f"- 模块：{len(modules)}", ""]
    for index, module in enumerate(modules, start=1):
        lines.extend([
            f"## 图 {module.get('module_position') or index}：{module.get('module_title') or module.get('image_role') or module.get('semantic_role') or 'A+图'}",
            f"- 转化任务：{module.get('conversion_task') or module.get('conversion_goal') or '-'}",
            f"- 主卖点：{module.get('main_selling_point') or module.get('selling_point') or '-'}",
            f"- 买家疑虑：{module.get('buyer_doubt') or module.get('buyer_question') or '-'}",
            f"- 场景：{module.get('scenario') or module.get('scene') or '-'}",
            f"- 主参考图：{module.get('primary_reference_image_id') or '-'}",
            f"- 次参考图：{module.get('secondary_reference_image_id') or '-'}",
            "",
        ])
    lines.extend(["## 完整结构化规划", "", "```json", _json_dumps(plan, indent=2), "```", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    for path, file_type in ((json_path, "aplus_plan_json"), (md_path, "aplus_plan_md")):
        await _upsert_product_file(
            db,
            product_id=product.id,
            file_type=file_type,
            label=path.name,
            path=path,
            metadata={"module_count": len(modules), "publish_profile": plan.get("publish_profile")},
        )
    return {"json": str(json_path), "markdown": str(md_path)}


async def write_aplus_script_artifacts(
    db: AsyncSession,
    *,
    product: Product,
    scripts_data: dict[str, Any],
) -> dict[str, str]:
    output_dir = _analysis_dir(product)
    json_path = output_dir / "gpt_image_scripts.json"
    md_path = output_dir / "gpt_image_scripts.md"
    json_path.write_text(_json_dumps(scripts_data, indent=2), encoding="utf-8")
    scripts = scripts_data.get("scripts") if isinstance(scripts_data.get("scripts"), list) else []
    lines = ["# A+ GPT Image 生图脚本", "", f"- Product ID：{product.id}", f"- Scripts：{len(scripts)}", ""]
    for index, script in enumerate(scripts, start=1):
        refs = script.get("reference_images") if isinstance(script.get("reference_images"), list) else []
        lines.extend([
            f"## 图 {script.get('module_position') or index}",
            f"- 参考图：{len(refs)} 张",
            f"- 目标尺寸：{script.get('target_width') or script.get('width') or 1940} × {script.get('target_height') or script.get('height') or 1200}",
        ])
        for ref_index, ref in enumerate(refs, start=1):
            if isinstance(ref, dict):
                lines.append(f"- Reference {ref_index}：{ref.get('path') or ref.get('url') or ref.get('image_url') or '-'}")
            else:
                lines.append(f"- Reference {ref_index}：{ref}")
        lines.extend(["", "```text", str(script.get("prompt") or ""), "```", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    for path, file_type in ((json_path, "aplus_scripts_json"), (md_path, "aplus_scripts_md")):
        await _upsert_product_file(
            db,
            product_id=product.id,
            file_type=file_type,
            label=path.name,
            path=path,
            metadata={"script_count": len(scripts), "publish_profile": scripts_data.get("publish_profile")},
        )
    return {"json": str(json_path), "markdown": str(md_path)}
