"""Canonical storage and read models for optional product content sections.

The payload rows deliberately store current content only.  They are not an
event log; ``content_revision`` is an optimistic-concurrency guard for async
workers that may finish after their inputs have changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, TypeAlias

from sqlalchemy import inspect as sa_inspect, literal, select, text, union_all
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.models import (
    ProductAplusAssetsPayload,
    ProductAplusPlanPayload,
    ProductAplusScriptPayload,
    ProductCustomerMindset,
    ProductExportArtifact,
    ProductImageAnalysisPayload,
    ProductImageCompliancePayload,
    ProductImageSelectionPayload,
    ProductListingContent,
    ProductSourcePayload,
    ProductSourceSnapshot,
)


PRODUCT_LARGE_FIELDS_MIGRATION = "product_large_fields_v1"
SECTION_STATES = frozenset({"absent", "processing", "ready", "failed", "unresolved"})
PayloadModel: TypeAlias = type[
    ProductSourcePayload
    | ProductSourceSnapshot
    | ProductCustomerMindset
    | ProductListingContent
    | ProductImageAnalysisPayload
    | ProductImageSelectionPayload
    | ProductImageCompliancePayload
    | ProductAplusPlanPayload
    | ProductAplusScriptPayload
    | ProductAplusAssetsPayload
    | ProductExportArtifact
]


@dataclass(frozen=True)
class PayloadSectionSpec:
    key: str
    model: PayloadModel
    schema_version: str


SECTION_SPECS: dict[str, PayloadSectionSpec] = {
    "source": PayloadSectionSpec("source", ProductSourcePayload, "product_source_payload_v1"),
    "source_snapshot": PayloadSectionSpec("source_snapshot", ProductSourceSnapshot, "product_source_snapshot_v1"),
    "mindset": PayloadSectionSpec("mindset", ProductCustomerMindset, "customer_mindset_v1"),
    "listing": PayloadSectionSpec("listing", ProductListingContent, "product_listing_content_v1"),
    "image_analysis": PayloadSectionSpec("image_analysis", ProductImageAnalysisPayload, "product_image_analysis_v1"),
    "image_selection": PayloadSectionSpec("image_selection", ProductImageSelectionPayload, "product_image_selection_v1"),
    "image_compliance": PayloadSectionSpec("image_compliance", ProductImageCompliancePayload, "product_image_compliance_v1"),
    "aplus_plan": PayloadSectionSpec("aplus_plan", ProductAplusPlanPayload, "product_aplus_plan_v1"),
    "aplus_script": PayloadSectionSpec("aplus_script", ProductAplusScriptPayload, "product_aplus_script_v1"),
    "aplus_assets": PayloadSectionSpec("aplus_assets", ProductAplusAssetsPayload, "product_aplus_assets_v1"),
    "export_artifact": PayloadSectionSpec("export_artifact", ProductExportArtifact, "product_export_artifact_v1"),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(value: Any) -> tuple[str, int, str]:
    serialized = canonical_json(value)
    encoded = serialized.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(encoded), serialized


def parse_payload(value: str | None) -> Any | None:
    if not value:
        return None
    return json.loads(value)


def section_summary(record: Any | None) -> dict[str, Any]:
    if record is None:
        return {
            "loaded": False,
            "state": "absent",
            "has_content": False,
            "revision": None,
            "updated_at": None,
            "content_bytes": None,
        }
    return {
        "loaded": False,
        "state": record.status,
        "has_content": bool(record.payload_json),
        "revision": record.content_revision,
        "updated_at": record.updated_at,
        "content_bytes": record.content_bytes,
    }


def section_response(record: Any | None) -> dict[str, Any]:
    summary = section_summary(record)
    summary["loaded"] = True
    summary["data"] = parse_payload(record.payload_json) if record and record.payload_json else None
    if record and record.error_code:
        summary["error_code"] = record.error_code
    return summary


async def large_field_storage_enabled(db: AsyncSession) -> bool:
    """Return false on pre-migration databases without issuing DDL."""
    if not hasattr(db, "execute"):
        return False
    try:
        result = await db.execute(
            text("SELECT 1 FROM schema_migrations WHERE version = :version LIMIT 1").bindparams(
                version=PRODUCT_LARGE_FIELDS_MIGRATION
            ),
        )
    except OperationalError:
        return False
    # Unit-test fakes that model only product loading deliberately do not
    # implement Result.first(); they represent a pre-cutover database.
    first = getattr(result, "first", None)
    return bool(first and first() is not None)


async def load_section(db: AsyncSession, product_id: int, section: str) -> Any | None:
    spec = SECTION_SPECS.get(section)
    if spec is None:
        raise KeyError(section)
    result = await db.execute(select(spec.model).where(spec.model.product_id == product_id))
    return result.scalar_one_or_none()


async def load_section_summaries(db: AsyncSession, product_id: int) -> dict[str, dict[str, Any]]:
    summaries = {key: section_summary(None) for key in SECTION_SPECS}
    statements = [
        select(
            literal(key).label("section_key"),
            spec.model.status,
            spec.model.payload_json.is_not(None).label("has_content"),
            spec.model.content_revision,
            spec.model.updated_at,
            spec.model.content_bytes,
        ).where(spec.model.product_id == product_id)
        for key, spec in SECTION_SPECS.items()
    ]
    rows = (await db.execute(union_all(*statements))).all()
    for row in rows:
        summaries[row.section_key] = {
            "loaded": False,
            "state": row.status,
            "has_content": bool(row.has_content),
            "revision": row.content_revision,
            "updated_at": row.updated_at,
            "content_bytes": row.content_bytes,
        }
    source = summaries["source"]
    snapshot = summaries["source_snapshot"]
    if snapshot["state"] != "absent":
        state_priority = {"absent": 0, "ready": 1, "processing": 2, "failed": 3, "unresolved": 4}
        if state_priority[snapshot["state"]] > state_priority[source["state"]]:
            source["state"] = snapshot["state"]
        source["has_content"] = bool(source["has_content"] or snapshot["has_content"])
        source["revision"] = max(int(source["revision"] or 0), int(snapshot["revision"] or 0)) or None
        source["updated_at"] = max(
            (value for value in (source["updated_at"], snapshot["updated_at"]) if value is not None),
            default=None,
        )
        source["content_bytes"] = int(source["content_bytes"] or 0) + int(snapshot["content_bytes"] or 0)
    return summaries


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def apply_section_projection(product: Any, section: str, payload: Any) -> None:
    """Expose canonical content to unchanged domain code without dirtying ORM rows."""
    # Relationships must be explicitly loaded by the caller. Reading through
    # descriptors here can trigger async lazy IO and raise MissingGreenlet even
    # when the requested section does not use that relationship.
    data = product.__dict__.get("data")
    images = product.__dict__.get("images")
    aplus = product.__dict__.get("aplus")
    if section == "source" and data and isinstance(payload, dict):
        for field in ("packages", "features", "description", "variants"):
            value = payload.get(field)
            set_committed_value(data, field, value if field == "description" else _json_text(value))
    elif section == "source_snapshot" and data:
        set_committed_value(data, "gigab2b_raw_snapshot", _json_text(payload))
    elif section == "mindset" and data:
        set_committed_value(data, "customer_mindset", _json_text(payload))
    elif section == "listing" and data and isinstance(payload, dict):
        scalar_fields = {"listing_title", "listing_search_terms", "listing_title_zh", "listing_description", "listing_description_zh", "listing_search_terms_zh", "listing_primary_keyword"}
        for field, value in payload.items():
            if hasattr(data, field):
                set_committed_value(data, field, value if field in scalar_fields else _json_text(value))
    elif section == "image_analysis" and images:
        body = payload if isinstance(payload, dict) else {}
        set_committed_value(images, "image_analysis", _json_text(body.get("image_analysis", payload)))
        set_committed_value(images, "image_selling_points", _json_text(body.get("image_selling_points")))
    elif section == "image_selection" and images:
        set_committed_value(images, "image_selection_analysis", _json_text(payload))
    elif section == "image_compliance" and images:
        set_committed_value(images, "image_compliance_manifest", _json_text(payload))
    elif section == "aplus_plan" and aplus:
        set_committed_value(aplus, "aplus_plan", _json_text(payload))
    elif section == "aplus_script" and aplus:
        set_committed_value(aplus, "aplus_scripts", _json_text(payload))
    elif section == "aplus_assets" and aplus:
        set_committed_value(aplus, "aplus_images", _json_text(payload))
    elif section == "export_artifact" and data and isinstance(payload, dict):
        for field in ("amazon_template_path", "amazon_template_warnings", "amazon_template_fill_summary"):
            value = payload.get(field)
            set_committed_value(data, field, value if field == "amazon_template_path" else _json_text(value))


async def hydrate_product_sections(
    db: AsyncSession,
    product: Any,
    sections: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Load canonical sections and project them into existing hot ORM objects."""
    if not await large_field_storage_enabled(db):
        return {}
    loaded: dict[str, Any] = {}
    for section in sections or SECTION_SPECS:
        record = await load_section(db, int(product.id), section)
        if record and record.status == "ready" and record.payload_json:
            payload = parse_payload(record.payload_json)
            apply_section_projection(product, section, payload)
            loaded[section] = payload
    return loaded


async def invalidate_sections(db: AsyncSession, product_id: int, sections: Iterable[str]) -> None:
    now = datetime.now()
    for section in sections:
        record = await load_section(db, product_id, section)
        if record is None:
            continue
        record.payload_json = None
        record.content_sha256 = None
        record.content_bytes = None
        record.status = "absent"
        record.error_code = None
        record.content_revision += 1
        record.updated_at = now


def _restore_unmodified_value(target: Any, field: str) -> None:
    history = sa_inspect(target).attrs[field].history
    if not history.has_changes():
        return
    previous = history.deleted[0] if history.deleted else None
    set_committed_value(target, field, previous)


async def _large_field_storage_enabled_without_autoflush(db: AsyncSession) -> bool:
    # Projection writers are called after legacy-shaped attributes have been
    # assigned. The marker lookup must not flush those guarded attributes.
    with db.no_autoflush:
        return await large_field_storage_enabled(db)


async def persist_source_sections_from_projection(db: AsyncSession, product_data: Any) -> bool:
    """Move pending legacy source assignments into canonical child rows."""
    if not await _large_field_storage_enabled_without_autoflush(db):
        return False
    source = {
        "packages": parse_payload(product_data.packages) if product_data.packages else None,
        "features": parse_payload(product_data.features) if product_data.features else None,
        "description": product_data.description,
        "variants": parse_payload(product_data.variants) if product_data.variants else None,
    }
    snapshot = parse_payload(product_data.gigab2b_raw_snapshot) if product_data.gigab2b_raw_snapshot else None
    # Restore the guarded legacy columns before write_section() issues its
    # first SELECT. AsyncSession autoflushes pending ProductData rows before a
    # query, which would otherwise make post-cutover product creation hit the
    # SQLite legacy-write triggers before the canonical rows can be written.
    for field in ("packages", "features", "description", "variants", "gigab2b_raw_snapshot"):
        _restore_unmodified_value(product_data, field)
    await write_section(db, product_id=product_data.product_id, section="source", payload=source)
    if snapshot is not None:
        await write_section(db, product_id=product_data.product_id, section="source_snapshot", payload=snapshot)
    return True


async def persist_listing_section_from_projection(db: AsyncSession, product_data: Any) -> bool:
    """Persist a legacy-shaped Listing projection without updating legacy columns."""
    if not await _large_field_storage_enabled_without_autoflush(db):
        return False
    scalar_fields = {
        "listing_title", "listing_search_terms", "listing_title_zh",
        "listing_description", "listing_description_zh", "listing_search_terms_zh",
        "listing_primary_keyword",
    }
    fields = (
        "listing_title", "listing_bullets", "listing_product_highlights", "listing_search_terms",
        "listing_title_zh", "listing_bullets_zh", "listing_product_highlights_zh",
        "listing_description", "listing_description_zh", "listing_search_terms_zh",
        "listing_check", "listing_primary_keyword", "listing_removed_keywords",
    )
    payload: dict[str, Any] = {}
    for field in fields:
        value = getattr(product_data, field, None)
        payload[field] = value if field in scalar_fields or not value else parse_payload(value)
    for field in fields:
        _restore_unmodified_value(product_data, field)
    await write_section(db, product_id=product_data.product_id, section="listing", payload=payload)
    return True


async def persist_image_sections_from_projection(
    db: AsyncSession,
    product_image: Any,
    sections: Iterable[str] = ("image_analysis", "image_selection", "image_compliance"),
) -> bool:
    if not await _large_field_storage_enabled_without_autoflush(db):
        return False
    requested = set(sections)
    pending_writes: list[tuple[str, Any, datetime | None, dict[str, Any] | None]] = []
    if "image_analysis" in requested and product_image.image_analysis:
        analysis = parse_payload(product_image.image_analysis)
        selling_points = parse_payload(product_image.image_selling_points) if product_image.image_selling_points else []
        reviews = analysis.get("images", []) if isinstance(analysis, dict) else analysis if isinstance(analysis, list) else []
        pending_writes.append((
            "image_analysis",
            {"image_analysis": analysis, "image_selling_points": selling_points},
            product_image.analyzed_at,
            {"analysis_count": len(reviews), "model_name": product_image.vlm_model},
        ))
        _restore_unmodified_value(product_image, "image_analysis")
        _restore_unmodified_value(product_image, "image_selling_points")
    if "image_selection" in requested and product_image.image_selection_analysis:
        selection = parse_payload(product_image.image_selection_analysis)
        selected = selection.get("selected_gallery", []) if isinstance(selection, dict) else []
        pending_writes.append((
            "image_selection",
            selection,
            product_image.image_selected_at,
            {"selected_count": (1 if isinstance(selection, dict) and selection.get("selected_main") else 0) + len(selected)},
        ))
        _restore_unmodified_value(product_image, "image_selection_analysis")
    if "image_compliance" in requested and product_image.image_compliance_manifest:
        compliance = parse_payload(product_image.image_compliance_manifest)
        pending_writes.append(("image_compliance", compliance, None, None))
        _restore_unmodified_value(product_image, "image_compliance_manifest")
    for section, payload, generated_at, extras in pending_writes:
        await write_section(
            db,
            product_id=product_image.product_id,
            section=section,
            payload=payload,
            generated_at=generated_at,
            extras=extras,
        )
    return True


async def write_section(
    db: AsyncSession,
    *,
    product_id: int,
    section: str,
    payload: Any,
    status: str = "ready",
    input_fingerprint: str | None = None,
    source_task_run_id: int | None = None,
    generated_at: datetime | None = None,
    expected_revision: int | None = None,
    extras: dict[str, Any] | None = None,
) -> Any:
    """Insert or replace a section, rejecting stale worker completions."""
    spec = SECTION_SPECS[section]
    if status not in SECTION_STATES:
        raise ValueError(f"invalid section state: {status}")
    digest, size, serialized = payload_hash(payload)
    record = await load_section(db, product_id, section)
    now = datetime.now()
    if record is not None and expected_revision is not None and record.content_revision != expected_revision:
        raise RuntimeError(f"stale {section} payload revision for product {product_id}")
    if record is None:
        record = spec.model(
            product_id=product_id,
            schema_version=spec.schema_version,
            payload_json=serialized,
            content_sha256=digest,
            content_bytes=size,
            status=status,
            input_fingerprint=input_fingerprint,
            source_task_run_id=source_task_run_id,
            generated_at=generated_at or now,
            **(extras or {}),
        )
        db.add(record)
        return record

    if record.content_sha256 == digest and record.status == status:
        return record
    record.payload_json = serialized
    record.schema_version = spec.schema_version
    record.content_sha256 = digest
    record.content_bytes = size
    record.status = status
    record.input_fingerprint = input_fingerprint
    record.source_task_run_id = source_task_run_id
    record.generated_at = generated_at or now
    record.error_code = None
    record.content_revision += 1
    for name, value in (extras or {}).items():
        setattr(record, name, value)
    return record


async def mark_section_unresolved(
    db: AsyncSession,
    *,
    product_id: int,
    section: str,
    error_code: str,
    extras: dict[str, Any] | None = None,
) -> Any:
    spec = SECTION_SPECS[section]
    record = await load_section(db, product_id, section)
    if record is None:
        record = spec.model(product_id=product_id, schema_version=spec.schema_version)
        db.add(record)
    record.payload_json = None
    record.content_sha256 = None
    record.content_bytes = None
    record.status = "unresolved"
    record.error_code = error_code
    record.updated_at = datetime.now()
    for name, value in (extras or {}).items():
        setattr(record, name, value)
    return record
