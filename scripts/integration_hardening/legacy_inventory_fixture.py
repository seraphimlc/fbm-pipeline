"""Deterministic non-empty fixture for executable Legacy inventory evidence."""

from __future__ import annotations

import re
from typing import Any


FIXTURE_ID = "legacy-inventory-nonempty-v2"
_SCHEMA_RE = re.compile(r"fbm_pipeline_ih_[0-9a-f]{16}_(?:source|target)\Z")


def build_fixture_dataset() -> dict[str, list[dict[str, Any]]]:
    products = []
    product_data = []
    product_specs = (
        (101, "ITEM-COMPLETE", "capture_competitor_detail", "succeeded", None),
        (102, "ITEM-MISSING", "capture_competitor_detail", "pending", None),
        (103, "ITEM-NOSELECT", "select_competitor", "pending", None),
        (104, "ITEM-PENDING", "search_competitor", "pending", None),
        (105, "ITEM-PROCESSING", "search_competitor", "processing", None),
        (106, "ITEM-FAILED", "search_competitor", "failed", None),
        (107, "ITEM-SUCCEEDED", "search_competitor", "succeeded", None),
        (108, "ITEM-MULTISELECT", "select_competitor", "pending", None),
        (109, "ITEM-MISMATCH", "capture_competitor_detail", "succeeded", None),
        (110, "ITEM-DUPASIN", "select_competitor", "pending", None),
        (111, "ITEM-CONFLICT", "capture_competitor_detail", "succeeded", "B999999999"),
        (112, "ITEM-MULTIPROD", "select_competitor", "pending", None),
        (113, "ITEM-MULTIPROD", "select_competitor", "pending", None),
        (114, "ITEM-PRESERVE", "capture_competitor_detail", "succeeded", "B000000014"),
    )
    for offset, (product_id, item_code, node, status, competitor_asin) in enumerate(product_specs):
        products.append(
            {
                "id": product_id,
                "gigab2b_product_id": f"GIGA-{product_id}",
                "competitor_asin": competitor_asin,
                "amazon_asin": "B0REAL00014" if product_id == 114 else None,
                "aplus_upload_status": "submitted" if product_id == 114 else "not_uploaded",
                "aplus_uploaded_at": "2026-07-24 12:30:00" if product_id == 114 else None,
                "aplus_upload_error": None,
                "source_batch_id": "fixture-batch-1",
                "source_site": "US",
                "workflow_node": node,
                "workflow_status": status,
                "workflow_error": "fixture failure" if status == "failed" else None,
            }
        )
        product_data.append(
            {
                "id": 201 + offset,
                "product_id": product_id,
                "item_code": item_code,
                "amazon_template_path": "/fixture/amazon/ITEM-PRESERVE.xlsm"
                if product_id == 114
                else None,
                "amazon_template_generated_at": "2026-07-24 12:00:00"
                if product_id == 114
                else None,
                "amazon_template_fill_summary": '{"filled": 12}'
                if product_id == 114
                else None,
                "amazon_template_warnings": '["fixture warning"]'
                if product_id == 114
                else None,
            }
        )

    def candidate(
        candidate_id: int,
        item_code: str,
        sku_code: str,
        rank: int,
        asin: str,
        selected: int,
    ) -> dict[str, Any]:
        return {
            "id": candidate_id,
            "batch_id": "fixture-batch-1",
            "site": "US",
            "item_code": item_code,
            "sku_code": sku_code,
            "rank": rank,
            "asin": asin,
            "is_selected": selected,
            "selected_at": None,
            "capture_error": None,
            "captured_at": None,
        }

    candidates = [
        candidate(301, "ITEM-COMPLETE", "SKU-COMPLETE", 1, "B000000001", 1),
        candidate(302, "ITEM-MISSING", "SKU-MISSING", 1, "B000000002", 1),
        candidate(303, "ITEM-NOSELECT", "SKU-NOSELECT", 1, "B000000003", 0),
        candidate(304, "ITEM-MULTISELECT", "SKU-MULTISELECT", 1, "B000000004", 1),
        candidate(305, "ITEM-MULTISELECT", "SKU-MULTISELECT", 2, "B000000005", 1),
        candidate(306, "ITEM-MISMATCH", "SKU-MISMATCH", 1, "B000000006", 1),
        candidate(307, "ITEM-DUPASIN", "SKU-DUPASIN", 1, "B000000007", 1),
        candidate(308, "ITEM-DUPASIN", "SKU-DUPASIN", 2, "B000000007", 0),
        candidate(309, "ITEM-CONFLICT", "SKU-CONFLICT", 1, "B000000009", 1),
        candidate(310, "ITEM-MULTIPROD", "SKU-MULTIPROD", 1, "B000000010", 1),
        candidate(311, "ITEM-ORPHAN", "SKU-ORPHAN", 1, "B000000011", 1),
        candidate(312, "ITEM-PRESERVE", "SKU-PRESERVE", 1, "B000000014", 1),
    ]

    def capture(
        capture_id: int,
        candidate_id: int,
        item_code: str,
        sku_code: str,
        asin: str,
    ) -> dict[str, Any]:
        return {
            "id": capture_id,
            "selected_candidate_id": candidate_id,
            "batch_id": "fixture-batch-1",
            "site": "US",
            "item_code": item_code,
            "sku_code": sku_code,
            "asin": asin,
            "capture_status": "captured",
            "capture_error": None,
            "captured_at": None,
        }

    captures = [
        capture(401, 301, "ITEM-COMPLETE", "SKU-COMPLETE", "B000000001"),
        capture(402, 306, "ITEM-MISMATCH", "SKU-MISMATCH", "B888888888"),
        capture(403, 309, "ITEM-CONFLICT", "SKU-CONFLICT", "B000000009"),
        capture(404, 310, "ITEM-MULTIPROD", "SKU-MULTIPROD", "B000000010"),
        capture(405, 311, "ITEM-ORPHAN", "SKU-ORPHAN", "B000000011"),
        capture(406, 999, "ITEM-CAPTURE-ORPHAN", "SKU-CAPTURE-ORPHAN", "B000000012"),
        capture(407, 312, "ITEM-PRESERVE", "SKU-PRESERVE", "B000000014"),
    ]
    catalog_products = [
        {
            "id": 601,
            "source_product_id": 114,
            "amazon_asin": "B0REAL00014",
            "confirmed_at": "2026-07-24 11:45:00",
            "exported_at": "2026-07-24 12:15:00",
            "export_task_id": 701,
            "export_file_path": "/fixture/export/ITEM-PRESERVE.xlsx",
            "aplus_upload_status": "submitted",
            "aplus_uploaded_at": "2026-07-24 12:30:00",
            "aplus_upload_error": None,
        },
        {
            "id": 602,
            "source_product_id": 111,
            "amazon_asin": None,
            "confirmed_at": None,
            "exported_at": "2026-07-24 10:00:00",
            "export_task_id": 702,
            "export_file_path": "/fixture/export/ITEM-CONFLICT.xlsx",
            "aplus_upload_status": "not_uploaded",
            "aplus_uploaded_at": None,
            "aplus_upload_error": None,
        },
    ]
    aplus_upload_items = [
        {
            "id": 501,
            "catalog_product_id": 601,
            "product_id": 114,
            "amazon_asin": "B0REAL00014",
            "item_code": "ITEM-PRESERVE",
            "status": "success",
            "finished_at": "2026-07-24 12:30:00",
        }
    ]
    return {
        "products": products,
        "product_data": product_data,
        "catalog_products": catalog_products,
        "aplus_upload_items": aplus_upload_items,
        "amazon_stylesnap_candidates": candidates,
        "amazon_listing_captures": captures,
    }


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "1" if value else "0"
    if type(value) is int:
        return str(value)
    if type(value) is not str:
        raise TypeError(f"unsupported fixture SQL value: {type(value).__name__}")
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def build_fixture_sql(schema: str) -> str:
    """Return fixture DDL/DML for an already-owned protected schema."""

    if _SCHEMA_RE.fullmatch(schema) is None:
        raise ValueError("fixture schema must use the protected fbm_pipeline_ih_* source/target form")
    dataset = build_fixture_dataset()
    statements = [
        f"CREATE TABLE `{schema}`.`products` ("
        "`id` BIGINT NOT NULL PRIMARY KEY, `gigab2b_product_id` VARCHAR(50) NULL, "
        "`competitor_asin` VARCHAR(20) NULL, `amazon_asin` VARCHAR(20) NULL, "
        "`aplus_upload_status` VARCHAR(20) NULL, `aplus_uploaded_at` DATETIME NULL, "
        "`aplus_upload_error` TEXT NULL, `source_batch_id` VARCHAR(100) NULL, "
        "`source_site` VARCHAR(20) NULL, `workflow_node` VARCHAR(80) NULL, "
        "`workflow_status` VARCHAR(40) NULL, `workflow_error` TEXT NULL) ENGINE=InnoDB",
        f"CREATE TABLE `{schema}`.`product_data` ("
        "`id` BIGINT NOT NULL PRIMARY KEY, `product_id` BIGINT NOT NULL, "
        "`item_code` VARCHAR(100) NULL, `amazon_template_path` TEXT NULL, "
        "`amazon_template_generated_at` DATETIME NULL, "
        "`amazon_template_fill_summary` TEXT NULL, `amazon_template_warnings` TEXT NULL) ENGINE=InnoDB",
        f"CREATE TABLE `{schema}`.`catalog_products` ("
        "`id` BIGINT NOT NULL PRIMARY KEY, `source_product_id` BIGINT NOT NULL, "
        "`amazon_asin` VARCHAR(20) NULL, `confirmed_at` DATETIME NULL, "
        "`exported_at` DATETIME NULL, "
        "`export_task_id` BIGINT NULL, `export_file_path` TEXT NULL, "
        "`aplus_upload_status` VARCHAR(20) NULL, `aplus_uploaded_at` DATETIME NULL, "
        "`aplus_upload_error` TEXT NULL) ENGINE=InnoDB",
        f"CREATE TABLE `{schema}`.`aplus_upload_items` ("
        "`id` BIGINT NOT NULL PRIMARY KEY, `catalog_product_id` BIGINT NOT NULL, "
        "`product_id` BIGINT NOT NULL, `amazon_asin` VARCHAR(20) NULL, "
        "`item_code` VARCHAR(100) NULL, `status` VARCHAR(20) NOT NULL, "
        "`finished_at` DATETIME NULL) ENGINE=InnoDB",
        f"CREATE TABLE `{schema}`.`amazon_stylesnap_candidates` ("
        "`id` BIGINT NOT NULL PRIMARY KEY, `batch_id` VARCHAR(100) NOT NULL, "
        "`site` VARCHAR(20) NOT NULL, `item_code` VARCHAR(100) NOT NULL, "
        "`sku_code` VARCHAR(100) NOT NULL, `rank` INT NOT NULL, `asin` VARCHAR(20) NOT NULL, "
        "`is_selected` TINYINT NOT NULL, `selected_at` DATETIME NULL, "
        "`capture_error` TEXT NULL, `captured_at` DATETIME NULL) ENGINE=InnoDB",
        f"CREATE TABLE `{schema}`.`task_runs` ("
        "`id` BIGINT NOT NULL PRIMARY KEY, `title` VARCHAR(200) NOT NULL) ENGINE=InnoDB",
        f"CREATE TABLE `{schema}`.`task_steps` ("
        "`id` BIGINT NOT NULL PRIMARY KEY, `task_run_id` BIGINT NOT NULL) ENGINE=InnoDB",
        f"CREATE TABLE `{schema}`.`amazon_listing_captures` ("
        "`id` BIGINT NOT NULL PRIMARY KEY, `selected_candidate_id` BIGINT NOT NULL, "
        "`batch_id` VARCHAR(100) NOT NULL, `site` VARCHAR(20) NOT NULL, "
        "`item_code` VARCHAR(100) NOT NULL, `sku_code` VARCHAR(100) NOT NULL, "
        "`asin` VARCHAR(20) NOT NULL, `capture_status` VARCHAR(30) NOT NULL, "
        "`capture_error` TEXT NULL, `captured_at` DATETIME NULL) ENGINE=InnoDB",
    ]
    columns_by_table = {
        "products": (
            "id",
            "gigab2b_product_id",
            "competitor_asin",
            "amazon_asin",
            "aplus_upload_status",
            "aplus_uploaded_at",
            "aplus_upload_error",
            "source_batch_id",
            "source_site",
            "workflow_node",
            "workflow_status",
            "workflow_error",
        ),
        "product_data": (
            "id",
            "product_id",
            "item_code",
            "amazon_template_path",
            "amazon_template_generated_at",
            "amazon_template_fill_summary",
            "amazon_template_warnings",
        ),
        "catalog_products": (
            "id",
            "source_product_id",
            "amazon_asin",
            "confirmed_at",
            "exported_at",
            "export_task_id",
            "export_file_path",
            "aplus_upload_status",
            "aplus_uploaded_at",
            "aplus_upload_error",
        ),
        "aplus_upload_items": (
            "id",
            "catalog_product_id",
            "product_id",
            "amazon_asin",
            "item_code",
            "status",
            "finished_at",
        ),
        "amazon_stylesnap_candidates": (
            "id",
            "batch_id",
            "site",
            "item_code",
            "sku_code",
            "rank",
            "asin",
            "is_selected",
            "selected_at",
            "capture_error",
            "captured_at",
        ),
        "amazon_listing_captures": (
            "id",
            "selected_candidate_id",
            "batch_id",
            "site",
            "item_code",
            "sku_code",
            "asin",
            "capture_status",
            "capture_error",
            "captured_at",
        ),
    }
    for table, columns in columns_by_table.items():
        column_sql = ", ".join(f"`{column}`" for column in columns)
        values_sql = ",\n".join(
            "(" + ", ".join(_sql_literal(row[column]) for column in columns) + ")"
            for row in dataset[table]
        )
        statements.append(
            f"INSERT INTO `{schema}`.`{table}` ({column_sql}) VALUES\n{values_sql}"
        )
    statements.extend(
        [
            f"INSERT INTO `{schema}`.`task_runs` (`id`, `title`) VALUES (801, 'legacy inventory sentinel')",
            f"INSERT INTO `{schema}`.`task_steps` (`id`, `task_run_id`) VALUES (901, 801)",
        ]
    )
    return ";\n".join(statements) + ";\n"
