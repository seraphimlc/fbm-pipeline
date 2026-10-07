"""Short-transaction fences for results computed outside a database transaction."""
import hashlib
import json
from contextvars import ContextVar
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Product, TaskRun, TaskStep
from app.services.product_payloads import SECTION_SPECS, hydrate_product_sections, large_field_storage_enabled, load_section

generation_task_run_id = ContextVar("generation_task_run_id", default=None)
generation_task_identity = ContextVar("generation_task_identity", default=None)
GUARD_VERSION = "product-input-v2"


def bind_generation_input_files(token, files):
    token["input_files"] = {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in files}
    return token


def _hot_inputs(product):
    data = product.__dict__.get("data")
    images = product.__dict__.get("images")
    data_fields = ("item_code", "title", "color", "material", "filler", "product_type",
                   "dimension_length", "dimension_width", "dimension_height", "weight",
                   "value_total", "estimated_total", "shipping_cost", "shipping_cost_min", "shipping_cost_max",
                   "seller", "origin", "material_dir", "suggested_price", "pricing_detail",
                   "keywords_top", "categories", "leaf_category")
    image_sources = [getattr(images, "main_image_path", None)] if images else []
    if images:
        image_sources.extend(json.loads(getattr(images, "gallery_images", None) or "[]"))
    local_hashes = {}
    for source in image_sources:
        if isinstance(source, str) and not source.startswith(("http://", "https://", "data:")):
            path = Path(source).expanduser()
            local_hashes[source] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {"product": {key: getattr(product, key, None) for key in ("brand", "competitor_asin", "upc", "amazon_asin", "workflow_node", "workflow_status")},
            "data": {key: getattr(data, key, None) for key in data_fields} if data else {},
            "images": {key: getattr(images, key, None) for key in ("main_image_path", "gallery_images", "gallery_order")} if images else {},
            "local_hashes": local_hashes, "competitor": getattr(product, "_mindset_competitor_input", None)}


async def capture_generation_input(db, product, sections, *, outputs=()):
    canonical = await large_field_storage_enabled(db)
    await hydrate_product_sections(db, product, sections)
    dependencies = {}
    revisions = {}
    for section in tuple(dict.fromkeys((*sections, *outputs))):
        if canonical:
            row = await load_section(db, product.id, section)
            revisions[section] = row.content_revision if row else 0
            if section in sections:
                dependencies[section] = [row.status, row.content_sha256, row.content_revision] if row else None
        else:
            # Guard legacy inputs AND existing outputs against a late completion.
            groups = {"source": ("data", ("packages", "features", "description", "variants")),
                      "source_snapshot": ("data", ("gigab2b_raw_snapshot",)),
                      "listing": ("data", ("listing_title", "listing_bullets", "listing_product_highlights", "listing_description", "listing_search_terms")),
                      "mindset": ("data", ("customer_mindset",)),
                      "image_analysis": ("images", ("image_analysis", "image_selling_points")),
                      "image_selection": ("images", ("image_selection_analysis",)),
                      "aplus_plan": ("aplus", ("aplus_plan",)),
                      "aplus_script": ("aplus", ("aplus_scripts",)),
                      "aplus_assets": ("aplus", ("aplus_images",))}
            relationship, fields = groups.get(section, ("data", ()))
            obj = product.__dict__.get(relationship)
            values = {field: getattr(obj, field, None) for field in fields}
            if section in sections:
                dependencies[section] = values
            if section in outputs:
                revisions[section] = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    reference_hashes = {}
    def references(value, inside=False):
        if isinstance(value, dict):
            for key, item in value.items():
                references(item, inside or key == "reference_images")
        elif isinstance(value, list):
            for item in value:
                references(item, inside)
        elif inside and isinstance(value, str) and not value.startswith(("http://", "https://", "data:")):
            path = Path(value).expanduser()
            if path.is_file():
                reference_hashes[value] = hashlib.sha256(path.read_bytes()).hexdigest()
    for section, field in (("aplus_script", "aplus_scripts"), ("aplus_plan", "aplus_plan")):
        if section in sections:
            obj = product.__dict__.get("aplus")
            raw = getattr(obj, field, None)
            if raw:
                references(json.loads(raw))
    body = {"hot": _hot_inputs(product), "sections": dependencies, "reference_hashes": reference_hashes}
    business_hot = {**body["hot"], "product": {key: value for key, value in body["hot"]["product"].items() if key not in {"workflow_node", "workflow_status"}}}
    business_body = {**body, "hot": business_hot}
    return {"version": GUARD_VERSION, "product_id": product.id, "sections": list(sections),
            "outputs": list(outputs), "revisions": revisions, "canonical": canonical,
            "task_run_id": generation_task_run_id.get(), "task_identity": generation_task_identity.get(),
            "fingerprint": hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest(),
            "business_fingerprint": hashlib.sha256(json.dumps(business_body, sort_keys=True, default=str).encode()).hexdigest()}


async def validate_generation_input(db, token, *, acquire_writer=True):
    if token.get("version") != GUARD_VERSION:
        raise RuntimeError("生成输入版本契约已变化，拒绝旧任务写回")
    # Call before assigning generated ORM values. It releases the earlier read
    # snapshot and obtains SQLite's writer only for validation and persistence.
    if acquire_writer:
        await db.commit()
        if settings.is_sqlite:
            await db.execute(text("BEGIN IMMEDIATE"))
    for source, expected_hash in token.get("input_files", {}).items():
        path = Path(source)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError("生成输入文件版本已变化，拒绝旧结果写回")
    product = await db.scalar(select(Product).where(Product.id == token["product_id"]).options(
        selectinload(Product.data), selectinload(Product.images), selectinload(Product.aplus),
        selectinload(Product.catalog_item)).execution_options(populate_existing=True).with_for_update())
    if product is None:
        raise RuntimeError("商品已不存在，拒绝写回生成结果")
    await hydrate_product_sections(db, product, token["sections"])
    current = await capture_generation_input(db, product, token["sections"], outputs=token["outputs"])
    if current["fingerprint"] != token["fingerprint"] or current["revisions"] != token["revisions"]:
        raise RuntimeError("商品输入版本已变化，拒绝写回过期生成结果")
    if "confirmed_at" in token:
        item = product.__dict__.get("catalog_item")
        if not item or str(item.confirmed_at) != token["confirmed_at"] or item.amazon_asin:
            raise RuntimeError("商品确认资格已变化，拒绝导出")
    identity = token.get("task_identity")
    if identity and identity.get("step_id"):
        step = await db.scalar(select(TaskStep).where(TaskStep.id == identity["step_id"]).options(
            selectinload(TaskStep.task_run), selectinload(TaskStep.task_group)).execution_options(populate_existing=True))
        if not step or step.attempt_count != identity.get("attempt_count") or step.status not in {"running", "waiting_external"}:
            raise RuntimeError("生成任务尝试已失效，拒绝旧任务写回")
    if token.get("task_run_id"):
        run = await db.get(TaskRun, token["task_run_id"], populate_existing=True)
        if run is None or run.status not in {'pending', 'running'} or run.cancel_requested_at or run.superseded_by_run_id:
            raise RuntimeError("生成任务已终止、取消或被取代，拒绝写回")
    return product
