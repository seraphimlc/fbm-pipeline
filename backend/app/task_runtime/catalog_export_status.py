from __future__ import annotations

from collections.abc import Iterable
import json
import math
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse


CATALOG_EXPORT_TASK_TYPE = "catalog_export"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_PARTIAL_FAILED = "partial_failed"
DOWNLOADABLE_RUN_STATUSES = frozenset({RUN_STATUS_SUCCEEDED, RUN_STATUS_PARTIAL_FAILED})
DOWNLOADABLE_PAYLOAD_STATUSES = frozenset({"done", RUN_STATUS_PARTIAL_FAILED})
ARTIFACT_REFERENCE_FIELDS = ("filename", "file_path", "oss_object_key", "oss_url")
CANONICAL_OUTCOME_FIELDS = ("rows", "requested_count", "success_count", "skipped_count", "failed_count")
ARTIFACT_MODE_LOCAL = "local"
ARTIFACT_MODE_OBJECT_KEY = "object_key"
ARTIFACT_MODE_REDIRECT = "redirect"
ARTIFACT_MODE_UNAVAILABLE = "unavailable"
CATALOG_STEP_OWNER_TASK_RUN = "task_run"
CATALOG_STEP_OWNER_OFFLINE_TASK = "offline_task"
TASK_RUN_OUTCOME_TERMINAL_STATUSES = frozenset({"succeeded", RUN_STATUS_PARTIAL_FAILED, "failed"})
OFFLINE_TASK_OUTCOME_TERMINAL_STATUSES = frozenset({"done", RUN_STATUS_PARTIAL_FAILED, "failed"})
CATALOG_EXPORT_RESPONSE_INVALID_REASON = "导出结果格式异常"
CATALOG_EXPORT_ROW_INVALID_REASON = "导出结果行格式异常"
CATALOG_EXPORT_RESPONSE_STATUSES = frozenset({"done", RUN_STATUS_PARTIAL_FAILED, "failed"})
CATALOG_EXPORT_ROW_STATUSES = frozenset({"exported", "skipped", "failed"})
MAX_SAFE_JSON_INTEGER = (2 ** 53) - 1


class CatalogExportArtifactResolution(NamedTuple):
    mode: str
    payload_status: str | None = None
    filename: str | None = None
    local_path: Path | None = None
    object_key: str | None = None
    cache_path: Path | None = None
    redirect_url: str | None = None
    fallback_url: str | None = None
    reason: str | None = None


class CatalogEffectiveTerminalRecord(NamedTuple):
    selected_payload: dict
    outcome: dict
    effective_status: str
    authoritative: bool


class CatalogEffectiveTerminalProjection(NamedTuple):
    records_by_id: dict[int, CatalogEffectiveTerminalRecord]
    authoritative_ids: frozenset[int]
    succeeded_ids: frozenset[int]
    done_ids: frozenset[int]
    partial_failed_ids: frozenset[int]
    failed_ids: frozenset[int]


class CatalogPayloadParseResult(NamedTuple):
    payload: dict
    json_valid: bool
    material: bool
    malformed: bool


def _reject_nonstandard_json_constant(_value: str):
    raise ValueError("non-standard JSON constant")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _validate_catalog_export_raw_value(value: object, *, depth: int = 0) -> None:
    if depth > 512:
        raise RecursionError("catalog export payload is too deeply nested")
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_catalog_export_raw_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("catalog export payload keys must be strings")
            _validate_catalog_export_raw_value(item, depth=depth + 1)
        return
    raise TypeError(f"unsupported catalog export payload value: {type(value).__name__}")


def _validated_catalog_export_raw_payload(payload: dict) -> CatalogPayloadParseResult:
    try:
        _validate_catalog_export_raw_value(payload)
    except (MemoryError, OverflowError, RecursionError, TypeError, ValueError):
        return CatalogPayloadParseResult({}, False, False, True)
    return CatalogPayloadParseResult(
        payload,
        True,
        _is_material_catalog_export_payload(payload),
        False,
    )


def _parse_catalog_export_payload_result(value: object) -> CatalogPayloadParseResult:
    if isinstance(value, dict):
        return _validated_catalog_export_raw_payload(value)
    if not isinstance(value, str) or not value.strip():
        return CatalogPayloadParseResult({}, True, False, False)
    try:
        parsed = json.loads(
            value,
            parse_constant=_reject_nonstandard_json_constant,
            parse_float=_parse_finite_json_float,
        )
    except (MemoryError, OverflowError, RecursionError, TypeError, ValueError):
        return CatalogPayloadParseResult({}, False, False, True)
    if not isinstance(parsed, dict):
        return CatalogPayloadParseResult({}, True, False, False)
    return _validated_catalog_export_raw_payload(parsed)


def _parse_catalog_export_payload(value: object) -> dict:
    return _parse_catalog_export_payload_result(value).payload


def _is_material_catalog_export_payload(payload: dict) -> bool:
    return (
        "artifact_available" in payload
        or any(field in payload for field in ARTIFACT_REFERENCE_FIELDS)
        or any(field in payload for field in CANONICAL_OUTCOME_FIELDS)
    )


def _select_catalog_export_payload_result(
    summary_json_or_dict: object,
    step_result_jsons_or_dicts: Iterable[object],
) -> CatalogPayloadParseResult:
    summary = _parse_catalog_export_payload_result(summary_json_or_dict)
    if summary.json_valid and summary.material:
        return summary
    for source in step_result_jsons_or_dicts:
        parsed = _parse_catalog_export_payload_result(source)
        if parsed.json_valid and parsed.material:
            return parsed
    return summary


def select_catalog_export_payload(
    summary_json_or_dict: object,
    step_result_jsons_or_dicts: Iterable[object],
) -> dict:
    return _select_catalog_export_payload_result(
        summary_json_or_dict,
        step_result_jsons_or_dicts,
    ).payload


def project_catalog_effective_terminal_record(
    *,
    owner_kind: str,
    task_type: str,
    status: str,
    summary_json_or_dict: object,
    step_result_json_or_dict: object = None,
) -> CatalogEffectiveTerminalRecord:
    selected = _select_catalog_export_payload_result(
        summary_json_or_dict,
        () if step_result_json_or_dict is None else (step_result_json_or_dict,),
    )
    selected_payload = selected.payload
    outcome = normalize_catalog_export_response(selected_payload)
    authoritative_material = selected.json_valid and selected.material
    if owner_kind == CATALOG_STEP_OWNER_TASK_RUN:
        terminal_statuses = TASK_RUN_OUTCOME_TERMINAL_STATUSES
        completed_status = RUN_STATUS_SUCCEEDED
    elif owner_kind == CATALOG_STEP_OWNER_OFFLINE_TASK:
        terminal_statuses = OFFLINE_TASK_OUTCOME_TERMINAL_STATUSES
        completed_status = "done"
    else:
        raise ValueError(f"unsupported catalog step owner kind: {owner_kind}")

    if task_type != CATALOG_EXPORT_TASK_TYPE or status not in terminal_statuses:
        return CatalogEffectiveTerminalRecord(selected_payload, outcome, status, False)

    if authoritative_material:
        outcome_status = outcome.get("status")
        effective_status = completed_status if outcome_status == "done" else str(outcome_status or "failed")
        return CatalogEffectiveTerminalRecord(selected_payload, outcome, effective_status, True)

    selected_status = selected_payload.get("status")
    if status == completed_status and selected_status == RUN_STATUS_PARTIAL_FAILED:
        return CatalogEffectiveTerminalRecord(
            selected_payload,
            outcome,
            RUN_STATUS_PARTIAL_FAILED,
            True,
        )
    return CatalogEffectiveTerminalRecord(selected_payload, outcome, status, False)


def _safe_response_int(value: object, *, nonnegative: bool = False) -> tuple[int | None, bool]:
    if value is None:
        return None, True
    if isinstance(value, bool) or not isinstance(value, int):
        return None, False
    if value < -MAX_SAFE_JSON_INTEGER or value > MAX_SAFE_JSON_INTEGER:
        return None, False
    if nonnegative and value < 0:
        return None, False
    return value, True


def _safe_response_text(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, True
    if not isinstance(value, str):
        return None, False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return None, False
    normalized = value.strip()
    return normalized or None, True


def _normalize_catalog_export_response_row(value: object, *, row_ordinal: int) -> dict:
    source = value if isinstance(value, dict) else {}
    invalid = not isinstance(value, dict)

    normalized: dict[str, object] = {"row_ordinal": row_ordinal}
    for field in ("catalog_id", "product_id"):
        field_value, valid = _safe_response_int(source.get(field))
        normalized[field] = field_value
        invalid = invalid or not valid

    for field in (
        "item_code",
        "seller_sku",
        "category",
        "reason",
        "template_file",
        "output_file",
    ):
        field_value, valid = _safe_response_text(source.get(field))
        normalized[field] = field_value
        invalid = invalid or not valid

    raw_status = source.get("status")
    status, status_valid = _safe_response_text(raw_status)
    if not status_valid or status not in CATALOG_EXPORT_ROW_STATUSES:
        status = "failed"
        invalid = True
    if invalid:
        status = "failed"
        normalized["reason"] = CATALOG_EXPORT_ROW_INVALID_REASON
    normalized["status"] = status
    return normalized


def normalize_catalog_export_response(payload: object) -> dict:
    """Build the only validated catalog outcome consumed by responses and artifact gates."""

    source = payload if isinstance(payload, dict) else {}
    format_invalid = not isinstance(payload, dict)
    outcome_inconsistent = not isinstance(payload, dict)

    artifact_available_present = "artifact_available" in source
    raw_artifact_available = source.get("artifact_available")
    artifact_available: bool | None = None
    artifact_explicitly_unavailable = False
    if artifact_available_present:
        if raw_artifact_available is True:
            artifact_available = True
        else:
            artifact_available = False
            artifact_explicitly_unavailable = True
            if raw_artifact_available not in (False, None):
                format_invalid = True

    raw_rows = source.get("rows")
    if raw_rows is None:
        raw_rows = []
    elif not isinstance(raw_rows, list):
        raw_rows = []
        format_invalid = True
        outcome_inconsistent = True
    rows = [
        _normalize_catalog_export_response_row(row, row_ordinal=index)
        for index, row in enumerate(raw_rows, start=1)
    ]

    row_counts = {
        "success_count": sum(1 for row in rows if row["status"] == "exported"),
        "skipped_count": sum(1 for row in rows if row["status"] == "skipped"),
        "failed_count": sum(1 for row in rows if row["status"] == "failed"),
    }
    counts: dict[str, int]
    raw_status = source.get("status")
    raw_status_text, raw_status_valid = _safe_response_text(raw_status)

    if rows:
        counts = row_counts
        requested_count = len(rows)
        report_count = len(rows)
        if counts["success_count"] <= 0:
            status = "failed"
        elif counts["skipped_count"] or counts["failed_count"]:
            status = RUN_STATUS_PARTIAL_FAILED
        else:
            status = "done"
        if artifact_explicitly_unavailable:
            status = "failed"

        expected_raw_counts = {
            "requested_count": requested_count,
            "success_count": counts["success_count"],
            "exported_count": counts["success_count"],
            "skipped_count": counts["skipped_count"],
            "failed_count": counts["failed_count"],
            "report_count": report_count,
        }
        for field, expected in expected_raw_counts.items():
            if field not in source:
                continue
            parsed, valid = _safe_response_int(source.get(field), nonnegative=True)
            if not valid or parsed != expected:
                format_invalid = True
        if raw_status is not None and (not raw_status_valid or raw_status_text != status):
            format_invalid = True
    else:
        counts_provided = any(
            field in source
            for field in ("requested_count", "success_count", "exported_count", "skipped_count", "failed_count")
        )

        def legacy_count(field: str, *, fallback: str | None = None) -> int:
            nonlocal format_invalid, outcome_inconsistent
            if field in source:
                raw_value = source.get(field)
            elif fallback and fallback in source:
                raw_value = source.get(fallback)
            else:
                return 0
            parsed, valid = _safe_response_int(raw_value, nonnegative=True)
            if not valid or parsed is None:
                format_invalid = True
                outcome_inconsistent = True
                return 0
            return parsed

        counts = {
            "success_count": legacy_count("success_count", fallback="exported_count"),
            "skipped_count": legacy_count("skipped_count"),
            "failed_count": legacy_count("failed_count"),
        }
        if "success_count" in source and "exported_count" in source:
            exported_count, exported_valid = _safe_response_int(source.get("exported_count"), nonnegative=True)
            if not exported_valid or exported_count != counts["success_count"]:
                format_invalid = True
                outcome_inconsistent = True
        requested_count = sum(counts.values())
        if "requested_count" in source:
            raw_requested_count, requested_valid = _safe_response_int(
                source.get("requested_count"),
                nonnegative=True,
            )
            if not requested_valid or raw_requested_count != requested_count:
                format_invalid = True
                outcome_inconsistent = True

        report_count, report_valid = _safe_response_int(source.get("report_count"), nonnegative=True)
        if "report_count" in source and (not report_valid or report_count is None):
            format_invalid = True
            outcome_inconsistent = True
            report_count = 0
        elif report_count is None:
            report_count = 0

        status = raw_status_text if raw_status_valid and raw_status_text in CATALOG_EXPORT_RESPONSE_STATUSES else "failed"
        if raw_status is None or not raw_status_valid or raw_status_text not in CATALOG_EXPORT_RESPONSE_STATUSES:
            format_invalid = True
            outcome_inconsistent = True
        if counts_provided:
            if status == "done" and (counts["skipped_count"] or counts["failed_count"]):
                outcome_inconsistent = True
            elif status == RUN_STATUS_PARTIAL_FAILED and not (
                counts["success_count"] > 0
                and (counts["skipped_count"] > 0 or counts["failed_count"] > 0)
            ):
                outcome_inconsistent = True
        if artifact_explicitly_unavailable or outcome_inconsistent:
            status = "failed"

    text_fields: dict[str, str | None] = {}
    for field in (
        "filename",
        "file_path",
        "oss_object_key",
        "oss_url",
        "category",
        "template_name",
        "template_path",
        "reason",
        "report_filename",
        "created_at",
    ):
        parsed, valid = _safe_response_text(source.get(field))
        text_fields[field] = parsed
        if source.get(field) is not None and not valid:
            format_invalid = True

    file_size, file_size_valid = _safe_response_int(source.get("file_size"), nonnegative=True)
    if source.get("file_size") is not None and not file_size_valid:
        format_invalid = True

    categories: list[str] = []
    raw_categories = source.get("categories")
    if raw_categories is not None and not isinstance(raw_categories, list):
        format_invalid = True
    for raw_category in raw_categories if isinstance(raw_categories, list) else []:
        category, valid = _safe_response_text(raw_category)
        if not valid:
            format_invalid = True
            continue
        if category and category not in categories:
            categories.append(category)
    if not categories:
        for row in rows:
            category = row.get("category")
            if isinstance(category, str) and category not in categories:
                categories.append(category)
        if text_fields["category"] and text_fields["category"] not in categories:
            categories.insert(0, text_fields["category"])

    catalog_product_ids: list[int] = []
    raw_catalog_ids = source.get("catalog_product_ids")
    if raw_catalog_ids is not None and not isinstance(raw_catalog_ids, list):
        format_invalid = True
    for raw_catalog_id in raw_catalog_ids if isinstance(raw_catalog_ids, list) else []:
        catalog_id, valid = _safe_response_int(raw_catalog_id)
        if not valid:
            format_invalid = True
            continue
        if catalog_id is not None and catalog_id not in catalog_product_ids:
            catalog_product_ids.append(catalog_id)
    if not catalog_product_ids:
        for row in rows:
            catalog_id = row.get("catalog_id")
            if isinstance(catalog_id, int) and catalog_id not in catalog_product_ids:
                catalog_product_ids.append(catalog_id)

    if outcome_inconsistent:
        format_invalid = True
    reason = CATALOG_EXPORT_RESPONSE_INVALID_REASON if format_invalid else text_fields["reason"]
    outcome = {
        "status": status,
        "requested_count": requested_count,
        "success_count": counts["success_count"],
        "exported_count": counts["success_count"],
        "skipped_count": counts["skipped_count"],
        "failed_count": counts["failed_count"],
        "report_count": report_count,
        "filename": text_fields["filename"],
        "file_path": text_fields["file_path"],
        "oss_object_key": text_fields["oss_object_key"],
        "oss_url": text_fields["oss_url"],
        "file_size": file_size,
        "category": text_fields["category"],
        "categories": categories,
        "template_name": text_fields["template_name"],
        "template_path": text_fields["template_path"],
        "catalog_product_ids": catalog_product_ids,
        "rows": rows,
        "reason": reason,
        "report_filename": text_fields["report_filename"],
        "created_at": text_fields["created_at"],
    }
    if artifact_available_present:
        outcome["artifact_available"] = artifact_available
    return outcome


async def load_newest_material_catalog_step_results(
    db,
    *,
    owner_kind: str,
    owner_ids: Iterable[int],
) -> dict[int, dict]:
    """Load one newest material catalog step result per owner using stable step id order."""

    from sqlalchemy import select

    from app.models import OfflineTaskStep, TaskStep

    normalized_ids: set[int] = set()
    for value in owner_ids:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            normalized_ids.add(parsed)
    if not normalized_ids:
        return {}

    if owner_kind == CATALOG_STEP_OWNER_TASK_RUN:
        step_model = TaskStep
        owner_column = TaskStep.task_run_id
    elif owner_kind == CATALOG_STEP_OWNER_OFFLINE_TASK:
        step_model = OfflineTaskStep
        owner_column = OfflineTaskStep.task_id
    else:
        raise ValueError(f"unsupported catalog step owner kind: {owner_kind}")

    result = await db.execute(
        select(
            owner_column.label("owner_id"),
            step_model.id.label("step_id"),
            step_model.result_json.label("result_json"),
        )
        .where(
            owner_column.in_(sorted(normalized_ids)),
            step_model.step_type == "catalog_export_template",
        )
        .order_by(owner_column.asc(), step_model.id.desc())
    )
    selected: dict[int, dict] = {}
    for owner_id, _step_id, result_json in result.all():
        normalized_owner_id = int(owner_id)
        if normalized_owner_id in selected:
            continue
        parsed = _parse_catalog_export_payload_result(result_json)
        if parsed.json_valid and parsed.material:
            selected[normalized_owner_id] = parsed.payload
    return selected


async def load_catalog_effective_terminal_projection(
    db,
    *,
    owner_kind: str,
    owner_ids: Iterable[int] | None = None,
) -> CatalogEffectiveTerminalProjection:
    """Batch-project authoritative catalog outcomes before SQL pagination/filtering."""

    from sqlalchemy import select

    from app.models import OfflineTask, TaskRun

    if owner_kind == CATALOG_STEP_OWNER_TASK_RUN:
        owner_model = TaskRun
        payload_column = TaskRun.summary_json
    elif owner_kind == CATALOG_STEP_OWNER_OFFLINE_TASK:
        owner_model = OfflineTask
        payload_column = OfflineTask.result_json
    else:
        raise ValueError(f"unsupported catalog step owner kind: {owner_kind}")

    query = select(owner_model.id, owner_model.status, payload_column).where(
        owner_model.task_type == CATALOG_EXPORT_TASK_TYPE,
    )
    if owner_ids is not None:
        normalized_ids = sorted({int(owner_id) for owner_id in owner_ids if int(owner_id) > 0})
        if not normalized_ids:
            return CatalogEffectiveTerminalProjection({}, frozenset(), frozenset(), frozenset(), frozenset(), frozenset())
        query = query.where(owner_model.id.in_(normalized_ids))

    rows = (await db.execute(query)).all()
    candidate_ids = [int(owner_id) for owner_id, _status, _payload in rows]
    step_results = await load_newest_material_catalog_step_results(
        db,
        owner_kind=owner_kind,
        owner_ids=candidate_ids,
    )

    records_by_id: dict[int, CatalogEffectiveTerminalRecord] = {}
    authoritative_ids: set[int] = set()
    status_ids: dict[str, set[int]] = {
        RUN_STATUS_SUCCEEDED: set(),
        "done": set(),
        RUN_STATUS_PARTIAL_FAILED: set(),
        "failed": set(),
    }
    for owner_id, status, payload in rows:
        normalized_owner_id = int(owner_id)
        record = project_catalog_effective_terminal_record(
            owner_kind=owner_kind,
            task_type=CATALOG_EXPORT_TASK_TYPE,
            status=str(status),
            summary_json_or_dict=payload,
            step_result_json_or_dict=step_results.get(normalized_owner_id),
        )
        records_by_id[normalized_owner_id] = record
        if not record.authoritative:
            continue
        authoritative_ids.add(normalized_owner_id)
        status_ids.setdefault(record.effective_status, set()).add(normalized_owner_id)

    return CatalogEffectiveTerminalProjection(
        records_by_id=records_by_id,
        authoritative_ids=frozenset(authoritative_ids),
        succeeded_ids=frozenset(status_ids[RUN_STATUS_SUCCEEDED]),
        done_ids=frozenset(status_ids["done"]),
        partial_failed_ids=frozenset(status_ids[RUN_STATUS_PARTIAL_FAILED]),
        failed_ids=frozenset(status_ids["failed"]),
    )


def _nonempty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    try:
        raw.encode("utf-8")
    except UnicodeError:
        return None
    return raw or None


def _usable_http_url(value: object) -> bool:
    raw = _nonempty_string(value)
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _safe_artifact_filename(value: object) -> str | None:
    raw = _nonempty_string(value)
    if not raw:
        return None
    filename = Path(raw).name.strip()
    return filename if filename not in {"", ".", ".."} else None


def _inside_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def resolve_catalog_export_artifact(
    payload: object,
    *,
    allowed_export_root: Path,
    object_cache_subdir: str,
) -> CatalogExportArtifactResolution:
    payload_dict = payload if isinstance(payload, dict) else {}
    payload_status_value = payload_dict.get("status")
    payload_status = str(payload_status_value).strip() if payload_status_value is not None else None
    filename = _safe_artifact_filename(payload_dict.get("filename"))

    def unavailable(reason: str) -> CatalogExportArtifactResolution:
        return CatalogExportArtifactResolution(
            mode=ARTIFACT_MODE_UNAVAILABLE,
            payload_status=payload_status,
            filename=filename,
            reason=reason,
        )

    if not isinstance(payload, dict):
        return unavailable("payload 不是对象")
    if "artifact_available" in payload and payload.get("artifact_available") is not True:
        return unavailable("artifact_available 显式不可用")

    root = Path(allowed_export_root).expanduser().resolve()
    raw_file_path = _nonempty_string(payload.get("file_path")) or ""
    local_path: Path | None = None
    if raw_file_path and not _usable_http_url(raw_file_path):
        try:
            candidate = Path(raw_file_path).expanduser().resolve()
            if _inside_root(candidate, root) and candidate.is_file():
                local_path = candidate
        except (OSError, UnicodeError, ValueError):
            local_path = None
    if local_path is not None:
        return CatalogExportArtifactResolution(
            mode=ARTIFACT_MODE_LOCAL,
            payload_status=payload_status,
            filename=filename or local_path.name,
            local_path=local_path,
        )

    redirect_url = raw_file_path if _usable_http_url(raw_file_path) else None
    if redirect_url is None:
        raw_oss_url = _nonempty_string(payload.get("oss_url")) or ""
        redirect_url = raw_oss_url if _usable_http_url(raw_oss_url) else None

    object_key_value = _nonempty_string(payload.get("oss_object_key"))
    object_key = object_key_value.lstrip("/") if object_key_value else ""
    if object_key and filename:
        cache_dir = (root / object_cache_subdir).resolve()
        if not _inside_root(cache_dir, root):
            cache_dir = root / "artifact-cache"
        return CatalogExportArtifactResolution(
            mode=ARTIFACT_MODE_OBJECT_KEY,
            payload_status=payload_status,
            filename=filename,
            object_key=object_key,
            cache_path=cache_dir / filename,
            fallback_url=redirect_url,
        )
    if redirect_url and filename:
        return CatalogExportArtifactResolution(
            mode=ARTIFACT_MODE_REDIRECT,
            payload_status=payload_status,
            filename=filename,
            redirect_url=redirect_url,
        )
    return unavailable("没有 allowed-root 本地文件、object_key 或可重定向 URL")


def catalog_export_resolution_is_ready(resolution: CatalogExportArtifactResolution) -> bool:
    return (
        str(resolution.payload_status or "").strip() in DOWNLOADABLE_PAYLOAD_STATUSES
        and resolution.mode != ARTIFACT_MODE_UNAVAILABLE
    )


def _summary_status(summary_json: str | None) -> str | None:
    payload = _parse_catalog_export_payload(summary_json)
    value = payload.get("status")
    return value.strip() if isinstance(value, str) else None


def is_legacy_catalog_export_partial(
    *,
    task_type: str,
    status: str,
    summary_json: str | None,
) -> bool:
    return (
        task_type == CATALOG_EXPORT_TASK_TYPE
        and status == RUN_STATUS_SUCCEEDED
        and _summary_status(summary_json) == RUN_STATUS_PARTIAL_FAILED
    )


def effective_task_run_status(
    *,
    task_type: str,
    status: str,
    summary_json: str | None,
) -> str:
    if is_legacy_catalog_export_partial(
        task_type=task_type,
        status=status,
        summary_json=summary_json,
    ):
        return RUN_STATUS_PARTIAL_FAILED
    return status


def catalog_export_result_is_downloadable(
    *,
    effective_status: str,
    resolution: CatalogExportArtifactResolution,
) -> bool:
    return (
        effective_status in DOWNLOADABLE_RUN_STATUSES
        and catalog_export_resolution_is_ready(resolution)
    )


def projected_task_run_status_condition(
    status: str,
    projection: CatalogEffectiveTerminalProjection,
):
    """Match effective TaskRun status without JSON SQL or post-pagination filtering."""

    from sqlalchemy import and_, false, or_

    from app.models import TaskRun

    target_ids = {
        RUN_STATUS_SUCCEEDED: projection.succeeded_ids,
        RUN_STATUS_PARTIAL_FAILED: projection.partial_failed_ids,
        "failed": projection.failed_ids,
    }.get(status, frozenset())
    raw_condition = TaskRun.status == status
    if projection.authoritative_ids:
        raw_condition = and_(raw_condition, TaskRun.id.not_in(sorted(projection.authoritative_ids)))
    projected_condition = TaskRun.id.in_(sorted(target_ids)) if target_ids else false()
    return or_(raw_condition, projected_condition)


def projected_offline_task_status_condition(
    status: str,
    projection: CatalogEffectiveTerminalProjection,
):
    """Match effective OfflineTask status without JSON SQL or post-pagination filtering."""

    from sqlalchemy import and_, false, or_

    from app.models import OfflineTask

    target_ids = {
        "done": projection.done_ids,
        RUN_STATUS_PARTIAL_FAILED: projection.partial_failed_ids,
        "failed": projection.failed_ids,
    }.get(status, frozenset())
    raw_condition = OfflineTask.status == status
    if projection.authoritative_ids:
        raw_condition = and_(raw_condition, OfflineTask.id.not_in(sorted(projection.authoritative_ids)))
    projected_condition = OfflineTask.id.in_(sorted(target_ids)) if target_ids else false()
    return or_(raw_condition, projected_condition)
