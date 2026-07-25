"""Pure, read-only Legacy StyleSnap inventory classification.

The inventory accepts already-read source rows and emits deterministic records.
It never connects to a database, mutates source facts, creates tasks, launches a
browser, calls an external provider, or writes Step 10 output.
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from typing import Any, Iterable

from .common import canonical_sha256_hex


class LegacyInventoryError(ValueError):
    """Raised only for unreadable or structurally invalid inventory input."""


CLASS_AUDIT_ONLY = "audit_only"
CLASS_SELECTED_CAPTURE_COMPLETE = "selected_capture_complete"
CLASS_SELECTED_CAPTURE_INCOMPLETE = "selected_capture_incomplete"
CLASS_CANDIDATES_WITHOUT_SELECTION = "candidates_without_selection"
CLASS_WORKFLOW_INTERRUPTED = "workflow_interrupted"
CLASS_REVIEW_REQUIRED = "review_required"

LEGACY_WORKFLOW_NODES = frozenset(
    {
        "get_stylesnap_token",
        "search_competitor",
        "select_competitor",
        "capture_competitor_detail",
    }
)
LEGACY_WORKFLOW_STATUSES = frozenset({"pending", "processing", "failed", "succeeded"})
COMPLETE_CAPTURE_STATUSES = frozenset({"captured", "complete", "succeeded"})
SAFE_APLUS_UPLOAD_STATUSES = frozenset({"", "not_uploaded", "failed"})


def _text(value: Any, *, field: str, required: bool = False) -> str:
    if value is None:
        normalized = ""
    elif type(value) is str:
        normalized = unicodedata.normalize("NFKC", value).strip()
    else:
        raise LegacyInventoryError(f"{field}: expected string or null")
    if required and not normalized:
        raise LegacyInventoryError(f"{field}: expected a non-empty string")
    return normalized


def _integer(value: Any, *, field: str) -> int:
    if type(value) is not int:
        raise LegacyInventoryError(f"{field}: expected integer")
    return value


def _optional_integer(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field=field)


def _selected(value: Any, *, field: str) -> bool:
    if type(value) is bool:
        return value
    if type(value) is int and value in {0, 1}:
        return bool(value)
    raise LegacyInventoryError(f"{field}: expected boolean or integer 0/1")


def _rows(value: Any, *, table: str) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise LegacyInventoryError(f"{table}: expected an array")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, row in enumerate(value):
        if type(row) is not dict:
            raise LegacyInventoryError(f"{table}[{index}]: expected an object")
        row_id = _integer(row.get("id"), field=f"{table}[{index}].id")
        if row_id in seen_ids:
            raise LegacyInventoryError(f"{table}: duplicate primary key {row_id}")
        seen_ids.add(row_id)
        normalized.append(dict(row))
    return normalized


def _normalize_products(rows: Any) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(_rows(rows, table="products")):
        normalized.append(
            {
                "id": row["id"],
                "gigab2b_product_id": _text(
                    row.get("gigab2b_product_id"), field=f"products[{index}].gigab2b_product_id"
                ),
                "competitor_asin": _text(
                    row.get("competitor_asin"), field=f"products[{index}].competitor_asin"
                ),
                "amazon_asin": _text(
                    row.get("amazon_asin"), field=f"products[{index}].amazon_asin"
                ),
                "aplus_upload_status": _text(
                    row.get("aplus_upload_status"),
                    field=f"products[{index}].aplus_upload_status",
                ),
                "aplus_uploaded_at": _text(
                    row.get("aplus_uploaded_at"), field=f"products[{index}].aplus_uploaded_at"
                ),
                "aplus_upload_error": _text(
                    row.get("aplus_upload_error"), field=f"products[{index}].aplus_upload_error"
                ),
                "source_batch_id": _text(
                    row.get("source_batch_id"), field=f"products[{index}].source_batch_id"
                ),
                "source_site": _text(row.get("source_site"), field=f"products[{index}].source_site"),
                "workflow_node": _text(
                    row.get("workflow_node"), field=f"products[{index}].workflow_node"
                ),
                "workflow_status": _text(
                    row.get("workflow_status"), field=f"products[{index}].workflow_status"
                ),
                "workflow_error": _text(
                    row.get("workflow_error"), field=f"products[{index}].workflow_error"
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def _normalize_product_data(rows: Any) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(_rows(rows, table="product_data")):
        normalized.append(
            {
                "id": row["id"],
                "product_id": _integer(
                    row.get("product_id"), field=f"product_data[{index}].product_id"
                ),
                "item_code": _text(
                    row.get("item_code"), field=f"product_data[{index}].item_code"
                ),
                "amazon_template_path": _text(
                    row.get("amazon_template_path"),
                    field=f"product_data[{index}].amazon_template_path",
                ),
                "amazon_template_generated_at": _text(
                    row.get("amazon_template_generated_at"),
                    field=f"product_data[{index}].amazon_template_generated_at",
                ),
                "amazon_template_fill_summary": _text(
                    row.get("amazon_template_fill_summary"),
                    field=f"product_data[{index}].amazon_template_fill_summary",
                ),
                "amazon_template_warnings": _text(
                    row.get("amazon_template_warnings"),
                    field=f"product_data[{index}].amazon_template_warnings",
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def _normalize_catalog_products(rows: Any) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(_rows(rows, table="catalog_products")):
        normalized.append(
            {
                "id": row["id"],
                "source_product_id": _integer(
                    row.get("source_product_id"),
                    field=f"catalog_products[{index}].source_product_id",
                ),
                "amazon_asin": _text(
                    row.get("amazon_asin"), field=f"catalog_products[{index}].amazon_asin"
                ),
                "confirmed_at": _text(
                    row.get("confirmed_at"), field=f"catalog_products[{index}].confirmed_at"
                ),
                "exported_at": _text(
                    row.get("exported_at"), field=f"catalog_products[{index}].exported_at"
                ),
                "export_task_id": _optional_integer(
                    row.get("export_task_id"), field=f"catalog_products[{index}].export_task_id"
                ),
                "export_file_path": _text(
                    row.get("export_file_path"),
                    field=f"catalog_products[{index}].export_file_path",
                ),
                "aplus_upload_status": _text(
                    row.get("aplus_upload_status"),
                    field=f"catalog_products[{index}].aplus_upload_status",
                ),
                "aplus_uploaded_at": _text(
                    row.get("aplus_uploaded_at"),
                    field=f"catalog_products[{index}].aplus_uploaded_at",
                ),
                "aplus_upload_error": _text(
                    row.get("aplus_upload_error"),
                    field=f"catalog_products[{index}].aplus_upload_error",
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def _normalize_aplus_upload_items(rows: Any) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(_rows(rows, table="aplus_upload_items")):
        normalized.append(
            {
                "id": row["id"],
                "catalog_product_id": _integer(
                    row.get("catalog_product_id"),
                    field=f"aplus_upload_items[{index}].catalog_product_id",
                ),
                "product_id": _integer(
                    row.get("product_id"), field=f"aplus_upload_items[{index}].product_id"
                ),
                "amazon_asin": _text(
                    row.get("amazon_asin"), field=f"aplus_upload_items[{index}].amazon_asin"
                ),
                "item_code": _text(
                    row.get("item_code"), field=f"aplus_upload_items[{index}].item_code"
                ),
                "status": _text(
                    row.get("status"), field=f"aplus_upload_items[{index}].status", required=True
                ),
                "finished_at": _text(
                    row.get("finished_at"), field=f"aplus_upload_items[{index}].finished_at"
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def _normalize_candidates(rows: Any) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(_rows(rows, table="amazon_stylesnap_candidates")):
        normalized.append(
            {
                "id": row["id"],
                "batch_id": _text(
                    row.get("batch_id"), field=f"amazon_stylesnap_candidates[{index}].batch_id", required=True
                ),
                "site": _text(
                    row.get("site"), field=f"amazon_stylesnap_candidates[{index}].site", required=True
                ),
                "item_code": _text(
                    row.get("item_code"), field=f"amazon_stylesnap_candidates[{index}].item_code", required=True
                ),
                "sku_code": _text(
                    row.get("sku_code"), field=f"amazon_stylesnap_candidates[{index}].sku_code", required=True
                ),
                "rank": _integer(
                    row.get("rank"), field=f"amazon_stylesnap_candidates[{index}].rank"
                ),
                "asin": _text(
                    row.get("asin"), field=f"amazon_stylesnap_candidates[{index}].asin", required=True
                ),
                "is_selected": _selected(
                    row.get("is_selected"), field=f"amazon_stylesnap_candidates[{index}].is_selected"
                ),
                "selected_at": _text(
                    row.get("selected_at"), field=f"amazon_stylesnap_candidates[{index}].selected_at"
                ),
                "capture_error": _text(
                    row.get("capture_error"), field=f"amazon_stylesnap_candidates[{index}].capture_error"
                ),
                "captured_at": _text(
                    row.get("captured_at"), field=f"amazon_stylesnap_candidates[{index}].captured_at"
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def _normalize_captures(rows: Any) -> list[dict[str, Any]]:
    normalized = []
    for index, row in enumerate(_rows(rows, table="amazon_listing_captures")):
        normalized.append(
            {
                "id": row["id"],
                "selected_candidate_id": _integer(
                    row.get("selected_candidate_id"),
                    field=f"amazon_listing_captures[{index}].selected_candidate_id",
                ),
                "batch_id": _text(
                    row.get("batch_id"), field=f"amazon_listing_captures[{index}].batch_id", required=True
                ),
                "site": _text(
                    row.get("site"), field=f"amazon_listing_captures[{index}].site", required=True
                ),
                "item_code": _text(
                    row.get("item_code"), field=f"amazon_listing_captures[{index}].item_code", required=True
                ),
                "sku_code": _text(
                    row.get("sku_code"), field=f"amazon_listing_captures[{index}].sku_code", required=True
                ),
                "asin": _text(
                    row.get("asin"), field=f"amazon_listing_captures[{index}].asin", required=True
                ),
                "capture_status": _text(
                    row.get("capture_status"), field=f"amazon_listing_captures[{index}].capture_status", required=True
                ),
                "capture_error": _text(
                    row.get("capture_error"), field=f"amazon_listing_captures[{index}].capture_error"
                ),
                "captured_at": _text(
                    row.get("captured_at"), field=f"amazon_listing_captures[{index}].captured_at"
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def normalize_legacy_dataset(dataset: Any) -> dict[str, list[dict[str, Any]]]:
    """Normalize the exact fields used by inventory and reject read/tool errors."""

    if type(dataset) is not dict:
        raise LegacyInventoryError("dataset: expected an object")
    required = {
        "products",
        "product_data",
        "catalog_products",
        "aplus_upload_items",
        "amazon_stylesnap_candidates",
        "amazon_listing_captures",
    }
    if set(dataset) != required:
        raise LegacyInventoryError(
            f"dataset: exact tables required; missing={sorted(required - set(dataset))}, "
            f"extra={sorted(set(dataset) - required)}"
        )
    return {
        "products": _normalize_products(dataset["products"]),
        "product_data": _normalize_product_data(dataset["product_data"]),
        "catalog_products": _normalize_catalog_products(dataset["catalog_products"]),
        "aplus_upload_items": _normalize_aplus_upload_items(dataset["aplus_upload_items"]),
        "amazon_stylesnap_candidates": _normalize_candidates(
            dataset["amazon_stylesnap_candidates"]
        ),
        "amazon_listing_captures": _normalize_captures(
            dataset["amazon_listing_captures"]
        ),
    }


def _source_id(kind: str, identity: dict[str, Any]) -> str:
    return f"{kind}:{canonical_sha256_hex(identity)}"


def _source_checksum(rows: Iterable[dict[str, Any]]) -> str:
    return canonical_sha256_hex(list(rows))


def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": candidate["batch_id"],
        "site": candidate["site"],
        "item_code": candidate["item_code"],
        "sku_code": candidate["sku_code"],
    }


def _product_matches(
    identity: dict[str, Any],
    product_ids_by_source: dict[tuple[str, str, str], list[int]],
) -> list[int]:
    key = (identity["batch_id"], identity["site"], identity["item_code"])
    return list(product_ids_by_source.get(key, []))


def _has_external_aplus_evidence(status: str, uploaded_at: str) -> bool:
    return bool(uploaded_at) or status not in SAFE_APLUS_UPLOAD_STATUSES


def _record(
    *,
    identity_kind: str,
    identity: dict[str, Any],
    classification: str,
    reason: str,
    product_ids: list[int],
    source_rows: list[dict[str, Any]],
    source_row_ids: list[str],
    related_rows: list[dict[str, Any]],
    related_source_row_ids: list[str],
    irreversible_downstream_facts: list[dict[str, Any]],
    facts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_id": _source_id(identity_kind, identity),
        "source_identity": {"kind": identity_kind, **identity},
        "source_row_ids": sorted(source_row_ids),
        "source_checksum_sha256": _source_checksum(source_rows),
        "related_source_row_ids": sorted(set(related_source_row_ids)),
        "related_facts_sha256": _source_checksum(related_rows),
        "candidate_product_ids": sorted(product_ids),
        "classification": classification,
        "reason": reason,
        "requires_manual_review": classification == CLASS_REVIEW_REQUIRED,
        "irreversible_downstream_facts": sorted(
            irreversible_downstream_facts,
            key=lambda fact: (fact["source_row_id"], fact["kind"]),
        ),
        "facts": facts,
    }


def verify_inventory_records(
    records: Any, *, expected_sha256: Any, expected_count: Any
) -> dict[str, Any]:
    """Independently bind emitted per-source records to their count and digest."""

    if type(records) is not list or any(type(record) is not dict for record in records):
        raise LegacyInventoryError("records: expected an array of objects")
    if type(expected_count) is not int or expected_count < 0:
        raise LegacyInventoryError("expected_count: expected a non-negative integer")
    if len(records) != expected_count:
        raise LegacyInventoryError("inventory record count does not match records")
    actual_sha256 = canonical_sha256_hex(records)
    if type(expected_sha256) is not str or actual_sha256 != expected_sha256:
        raise LegacyInventoryError("inventory records SHA256 does not match records")
    return {"record_count": len(records), "records_sha256": actual_sha256}


def build_legacy_inventory(dataset: Any) -> dict[str, Any]:
    """Return deterministic inventory records and a stable digest."""

    normalized = normalize_legacy_dataset(dataset)
    products = normalized["products"]
    product_data = normalized["product_data"]
    catalog_products = normalized["catalog_products"]
    aplus_upload_items = normalized["aplus_upload_items"]
    candidates = normalized["amazon_stylesnap_candidates"]
    captures = normalized["amazon_listing_captures"]

    products_by_id = {row["id"]: row for row in products}
    product_data_by_product: dict[int, list[dict[str, Any]]] = defaultdict(list)
    product_ids_by_source: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for row in product_data:
        product_data_by_product[row["product_id"]].append(row)
        product = products_by_id.get(row["product_id"])
        if not product or not product["source_batch_id"] or not product["source_site"] or not row["item_code"]:
            continue
        product_ids_by_source[
            (product["source_batch_id"], product["source_site"], row["item_code"])
        ].append(product["id"])
    for key in product_ids_by_source:
        product_ids_by_source[key] = sorted(set(product_ids_by_source[key]))

    catalog_by_id = {row["id"]: row for row in catalog_products}
    catalog_by_product: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in catalog_products:
        catalog_by_product[row["source_product_id"]].append(row)
    aplus_by_product: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in aplus_upload_items:
        aplus_by_product[row["product_id"]].append(row)
    invalid_success_aplus_items = {
        row["id"]: row
        for row in aplus_upload_items
        if row["status"] == "success"
        and (
            row["product_id"] not in products_by_id
            or row["catalog_product_id"] not in catalog_by_id
            or catalog_by_id[row["catalog_product_id"]]["source_product_id"]
            != row["product_id"]
        )
    }

    def related_product_evidence(product_ids: list[int]) -> dict[str, Any]:
        related_rows: list[dict[str, Any]] = []
        related_ids: list[str] = []
        downstream_facts: list[dict[str, Any]] = []
        attribution_conflicts: list[int] = []
        workflows = []
        for product_id in sorted(product_ids):
            product = products_by_id[product_id]
            related_rows.append({"kind": "workflow_reference", **product})
            related_ids.append(f"workflow:{product_id}")
            workflows.append(
                {
                    "product_id": product_id,
                    "workflow_node": product["workflow_node"],
                    "workflow_status": product["workflow_status"],
                    "competitor_asin": product["competitor_asin"],
                }
            )
            if product["amazon_asin"]:
                downstream_facts.append(
                    {
                        "kind": "product_amazon_asin",
                        "source_row_id": f"product:{product_id}",
                        "amazon_asin": product["amazon_asin"],
                    }
                )
            if _has_external_aplus_evidence(
                product["aplus_upload_status"], product["aplus_uploaded_at"]
            ):
                downstream_facts.append(
                    {
                        "kind": "product_aplus_external_evidence",
                        "source_row_id": f"product:{product_id}",
                        "status": product["aplus_upload_status"],
                        "uploaded_at": product["aplus_uploaded_at"],
                    }
                )

            for data_row in sorted(product_data_by_product.get(product_id, []), key=lambda row: row["id"]):
                related_rows.append({"kind": "product_data", **data_row})
                related_ids.append(f"product_data:{data_row['id']}")
                if (
                    data_row["amazon_template_path"]
                    or data_row["amazon_template_generated_at"]
                    or data_row["amazon_template_fill_summary"]
                    or data_row["amazon_template_warnings"]
                ):
                    downstream_facts.append(
                        {
                            "kind": "amazon_template_output",
                            "source_row_id": f"product_data:{data_row['id']}",
                            "path": data_row["amazon_template_path"],
                            "generated_at": data_row["amazon_template_generated_at"],
                            "fill_summary": data_row["amazon_template_fill_summary"],
                            "warnings": data_row["amazon_template_warnings"],
                        }
                    )

            for catalog in sorted(catalog_by_product.get(product_id, []), key=lambda row: row["id"]):
                related_rows.append({"kind": "catalog_product", **catalog})
                related_ids.append(f"catalog_product:{catalog['id']}")
                if catalog["amazon_asin"]:
                    downstream_facts.append(
                        {
                            "kind": "catalog_amazon_asin",
                            "source_row_id": f"catalog_product:{catalog['id']}",
                            "amazon_asin": catalog["amazon_asin"],
                        }
                    )
                if catalog["confirmed_at"]:
                    downstream_facts.append(
                        {
                            "kind": "catalog_manual_confirmation",
                            "source_row_id": f"catalog_product:{catalog['id']}",
                            "confirmed_at": catalog["confirmed_at"],
                        }
                    )
                if (
                    catalog["exported_at"]
                    or catalog["export_task_id"] is not None
                    or catalog["export_file_path"]
                ):
                    downstream_facts.append(
                        {
                            "kind": "catalog_export_history",
                            "source_row_id": f"catalog_product:{catalog['id']}",
                            "exported_at": catalog["exported_at"],
                            "export_task_id": catalog["export_task_id"],
                            "export_file_path": catalog["export_file_path"],
                        }
                    )
                if _has_external_aplus_evidence(
                    catalog["aplus_upload_status"], catalog["aplus_uploaded_at"]
                ):
                    downstream_facts.append(
                        {
                            "kind": "catalog_aplus_external_evidence",
                            "source_row_id": f"catalog_product:{catalog['id']}",
                            "status": catalog["aplus_upload_status"],
                            "uploaded_at": catalog["aplus_uploaded_at"],
                        }
                    )

            for item in sorted(aplus_by_product.get(product_id, []), key=lambda row: row["id"]):
                if item["status"] != "success":
                    continue
                related_rows.append({"kind": "aplus_upload_item", **item})
                related_ids.append(f"aplus_upload_item:{item['id']}")
                if item["id"] in invalid_success_aplus_items:
                    attribution_conflicts.append(item["id"])
                    continue
                downstream_facts.append(
                    {
                        "kind": "aplus_upload_success",
                        "source_row_id": f"aplus_upload_item:{item['id']}",
                        "catalog_product_id": item["catalog_product_id"],
                        "amazon_asin": item["amazon_asin"],
                        "finished_at": item["finished_at"],
                    }
                )
        return {
            "related_rows": related_rows,
            "related_source_row_ids": related_ids,
            "irreversible_downstream_facts": downstream_facts,
            "aplus_attribution_conflict_ids": sorted(attribution_conflicts),
            "product_workflows": workflows,
        }

    candidates_by_group: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    candidates_by_id = {candidate["id"]: candidate for candidate in candidates}
    for candidate in candidates:
        identity = _candidate_identity(candidate)
        candidates_by_group[
            (identity["batch_id"], identity["site"], identity["item_code"], identity["sku_code"])
        ].append(candidate)

    captures_by_candidate: dict[int, list[dict[str, Any]]] = defaultdict(list)
    orphan_captures: list[dict[str, Any]] = []
    for capture in captures:
        if capture["selected_candidate_id"] not in candidates_by_id:
            orphan_captures.append(capture)
        else:
            captures_by_candidate[capture["selected_candidate_id"]].append(capture)

    records: list[dict[str, Any]] = []
    candidate_refs_by_product: dict[int, list[dict[str, str]]] = defaultdict(list)

    for key in sorted(candidates_by_group):
        group = sorted(candidates_by_group[key], key=lambda row: row["id"])
        identity = {
            "batch_id": key[0],
            "site": key[1],
            "item_code": key[2],
            "sku_code": key[3],
        }
        product_ids = _product_matches(identity, product_ids_by_source)
        related = related_product_evidence(product_ids)
        group_captures = sorted(
            [capture for candidate in group for capture in captures_by_candidate.get(candidate["id"], [])],
            key=lambda row: row["id"],
        )
        source_rows = [{"kind": "candidate", **candidate} for candidate in group] + [
            {"kind": "capture", **capture} for capture in group_captures
        ]
        source_row_ids = [f"candidate:{candidate['id']}" for candidate in group] + [
            f"capture:{capture['id']}" for capture in group_captures
        ]
        selected = [candidate for candidate in group if candidate["is_selected"]]
        asin_counts = Counter(candidate["asin"] for candidate in group)
        facts = {
            "candidate_count": len(group),
            "selected_candidate_ids": [candidate["id"] for candidate in selected],
            "capture_ids": [capture["id"] for capture in group_captures],
            "candidate_asins": sorted(asin_counts),
            "duplicate_candidate_asins": sorted(
                asin for asin, count in asin_counts.items() if count > 1
            ),
            "product_workflows": related["product_workflows"],
            "aplus_attribution_conflict_ids": related["aplus_attribution_conflict_ids"],
        }

        review_reason = ""
        if len(product_ids) == 0:
            review_reason = "product_match_not_found"
        elif len(product_ids) > 1:
            review_reason = "product_match_ambiguous"
        elif related["aplus_attribution_conflict_ids"]:
            review_reason = "aplus_upload_item_attribution_conflict"
        elif facts["duplicate_candidate_asins"]:
            review_reason = "duplicate_candidate_asin"
        elif len(selected) > 1:
            review_reason = "multiple_selected_candidates"
        else:
            for capture in group_captures:
                candidate = candidates_by_id[capture["selected_candidate_id"]]
                candidate_identity = (
                    candidate["batch_id"], candidate["site"], candidate["item_code"],
                    candidate["sku_code"], candidate["asin"],
                )
                capture_identity = (
                    capture["batch_id"], capture["site"], capture["item_code"],
                    capture["sku_code"], capture["asin"],
                )
                if candidate_identity != capture_identity:
                    review_reason = "candidate_capture_identity_mismatch"
                    break
            if not review_reason and not selected and group_captures:
                review_reason = "capture_without_selected_candidate"
            if not review_reason and selected:
                selected_id = selected[0]["id"]
                if any(capture["selected_candidate_id"] != selected_id for capture in group_captures):
                    review_reason = "capture_for_unselected_candidate"
                selected_captures = captures_by_candidate.get(selected_id, [])
                if not review_reason and len(selected_captures) > 1:
                    review_reason = "multiple_captures_for_selected_candidate"
                if not review_reason:
                    product = products_by_id[product_ids[0]]
                    if product["competitor_asin"] and product["competitor_asin"] != selected[0]["asin"]:
                        review_reason = "product_competitor_asin_conflict"

        if review_reason:
            classification = CLASS_REVIEW_REQUIRED
            reason = review_reason
        elif related["irreversible_downstream_facts"]:
            classification = CLASS_AUDIT_ONLY
            reason = "irreversible_downstream_facts_preserved_audit_only"
        elif not selected:
            classification = CLASS_CANDIDATES_WITHOUT_SELECTION
            reason = "candidate_rows_exist_without_selected_candidate"
        else:
            selected_captures = captures_by_candidate.get(selected[0]["id"], [])
            complete_capture = (
                len(selected_captures) == 1
                and selected_captures[0]["capture_status"] in COMPLETE_CAPTURE_STATUSES
                and not selected_captures[0]["capture_error"]
            )
            classification = (
                CLASS_SELECTED_CAPTURE_COMPLETE
                if complete_capture
                else CLASS_SELECTED_CAPTURE_INCOMPLETE
            )
            reason = (
                "unique_selected_candidate_with_complete_capture"
                if complete_capture
                else "unique_selected_candidate_without_complete_capture"
            )

        record = _record(
            identity_kind="candidate_group",
            identity=identity,
            classification=classification,
            reason=reason,
            product_ids=product_ids,
            source_rows=source_rows,
            source_row_ids=source_row_ids,
            related_rows=related["related_rows"],
            related_source_row_ids=related["related_source_row_ids"],
            irreversible_downstream_facts=related["irreversible_downstream_facts"],
            facts=facts,
        )
        records.append(record)
        for product_id in product_ids:
            candidate_refs_by_product[product_id].append(
                {
                    "source_id": record["source_id"],
                    "classification": classification,
                    "reason": reason,
                }
            )

    for capture in sorted(orphan_captures, key=lambda row: row["id"]):
        identity = {"capture_id": capture["id"]}
        product_ids = _product_matches(capture, product_ids_by_source)
        related = related_product_evidence(product_ids)
        records.append(
            _record(
                identity_kind="orphan_capture",
                identity=identity,
                classification=CLASS_REVIEW_REQUIRED,
                reason="orphan_capture",
                product_ids=product_ids,
                source_rows=[{"kind": "capture", **capture}],
                source_row_ids=[f"capture:{capture['id']}"],
                related_rows=related["related_rows"],
                related_source_row_ids=related["related_source_row_ids"],
                irreversible_downstream_facts=related["irreversible_downstream_facts"],
                facts={
                    "candidate_count": 0,
                    "selected_candidate_ids": [],
                    "capture_ids": [capture["id"]],
                    "candidate_asins": [],
                    "duplicate_candidate_asins": [],
                },
            )
        )

    legacy_products = [
        product
        for product in products
        if product["workflow_node"] in LEGACY_WORKFLOW_NODES
        and product["workflow_status"] in LEGACY_WORKFLOW_STATUSES
    ]
    for product in legacy_products:
        product_id = product["id"]
        related = related_product_evidence([product_id])
        linked_groups = sorted(
            candidate_refs_by_product.get(product_id, []), key=lambda item: item["source_id"]
        )
        supplemental_rows = [
            row for row in related["related_rows"] if row["kind"] != "workflow_reference"
        ]
        supplemental_ids = [
            source_id
            for source_id in related["related_source_row_ids"]
            if source_id != f"workflow:{product_id}"
        ]
        if related["aplus_attribution_conflict_ids"]:
            classification = CLASS_REVIEW_REQUIRED
            reason = "aplus_upload_item_attribution_conflict"
        elif not linked_groups and product["workflow_status"] == "succeeded":
            classification = CLASS_REVIEW_REQUIRED
            reason = "legacy_workflow_succeeded_without_candidate_rows"
        elif not linked_groups:
            classification = CLASS_WORKFLOW_INTERRUPTED
            reason = f"legacy_workflow_{product['workflow_status']}_without_candidate_rows"
        elif related["irreversible_downstream_facts"]:
            classification = CLASS_AUDIT_ONLY
            reason = "irreversible_downstream_facts_preserved_audit_only"
        else:
            classification = CLASS_AUDIT_ONLY
            reason = "legacy_workflow_linked_to_candidate_group_records"
        records.append(
            _record(
                identity_kind="workflow",
                identity={"product_id": product_id},
                classification=classification,
                reason=reason,
                product_ids=[product_id],
                source_rows=[{"kind": "workflow", **product}],
                source_row_ids=[f"workflow:{product_id}"],
                related_rows=supplemental_rows,
                related_source_row_ids=supplemental_ids,
                irreversible_downstream_facts=related["irreversible_downstream_facts"],
                facts={
                    "workflow_node": product["workflow_node"],
                    "workflow_status": product["workflow_status"],
                    "workflow_error_present": bool(product["workflow_error"]),
                    "linked_candidate_groups": linked_groups,
                    "aplus_attribution_conflict_ids": related["aplus_attribution_conflict_ids"],
                },
            )
        )

    covered_aplus_conflict_ids = {
        item_id
        for record in records
        for item_id in record["facts"].get("aplus_attribution_conflict_ids", [])
    }
    for item_id in sorted(set(invalid_success_aplus_items) - covered_aplus_conflict_ids):
        item = invalid_success_aplus_items[item_id]
        product_ids = [item["product_id"]] if item["product_id"] in products_by_id else []
        records.append(
            _record(
                identity_kind="aplus_attribution_conflict",
                identity={"aplus_upload_item_id": item_id},
                classification=CLASS_REVIEW_REQUIRED,
                reason="aplus_upload_item_attribution_conflict",
                product_ids=product_ids,
                source_rows=[],
                source_row_ids=[],
                related_rows=[{"kind": "aplus_upload_item", **item}],
                related_source_row_ids=[f"aplus_upload_item:{item_id}"],
                irreversible_downstream_facts=[],
                facts={"aplus_attribution_conflict_ids": [item_id]},
            )
        )

    records.sort(key=lambda record: record["source_id"])
    expected_source_row_ids = {
        *(f"candidate:{row['id']}" for row in candidates),
        *(f"capture:{row['id']}" for row in captures),
        *(f"workflow:{row['id']}" for row in legacy_products),
    }
    ownership = Counter(
        source_row_id for record in records for source_row_id in record["source_row_ids"]
    )
    duplicate_claims = sorted(source_id for source_id, count in ownership.items() if count != 1)
    missing_claims = sorted(expected_source_row_ids - set(ownership))
    unexpected_claims = sorted(set(ownership) - expected_source_row_ids)
    if duplicate_claims or missing_claims or unexpected_claims:
        raise LegacyInventoryError(
            "source row ownership invariant failed; "
            f"duplicate_or_nonunit={duplicate_claims}, missing={missing_claims}, "
            f"unexpected={unexpected_claims}"
        )

    classification_counts = dict(
        sorted(Counter(record["classification"] for record in records).items())
    )
    records_sha256 = canonical_sha256_hex(records)
    review_required_count = classification_counts.get(CLASS_REVIEW_REQUIRED, 0)
    verify_inventory_records(
        records, expected_sha256=records_sha256, expected_count=len(records)
    )
    return {
        "records": records,
        "records_sha256": records_sha256,
        "classification_counts": classification_counts,
        "review_required_count": review_required_count,
        "requires_manual_review": review_required_count > 0,
        "source_row_count": len(expected_source_row_ids),
        "source_row_ownership_sha256": canonical_sha256_hex(
            [
                {"source_row_id": source_row_id, "owner_count": owner_count}
                for source_row_id, owner_count in sorted(ownership.items())
            ]
        ),
        "inventory_record_count": len(records),
        "inventory_digest_sha256": records_sha256,
    }
