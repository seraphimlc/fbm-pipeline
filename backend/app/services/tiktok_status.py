"""Shared MySQL projection for TikTok product channel readiness."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import Integer, String, bindparam, text


TIKTOK_CHANNEL_STATUSES = (
    "failed",
    "draft",
    "missing_required_info",
    "unsupported",
)

TIKTOK_CHANNEL_STATUS_META: dict[str, tuple[str, str]] = {
    "failed": ("失败", "商品处理失败"),
    "draft": ("草稿", "暂无可展示 SKU"),
    "missing_required_info": ("资料不完整", "缺少采购价或分仓库存"),
    "unsupported": ("资料已齐 · 导出暂未接入", "TikTok 导出/发布尚未接入"),
}

# Canonical text keys strip exactly ASCII space, tab, LF, CR, FF and VT.
ASCII_EDGE_WHITESPACE = " \t\n\r\f\v"
ASCII_EDGE_WHITESPACE_REGEX = "^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$"
MYSQL_DECIMAL_20_6_MAX = Decimal("99999999999999.999999")
MYSQL_DECIMAL_20_6_QUANTUM = Decimal("0.000001")

# Compatibility aliases for existing TikTok callers/tests.
SKU_ASCII_WHITESPACE = ASCII_EDGE_WHITESPACE
SKU_ASCII_WHITESPACE_REGEX = ASCII_EDGE_WHITESPACE_REGEX


def canonicalize_ascii_edge_text(value: Any) -> str | None:
    """Match MySQL JSON_TABLE scalar text conversion plus ASCII edge trim."""

    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        text_value = "true" if value else "false"
    elif isinstance(value, (str, int, float, Decimal)):
        text_value = str(value)
    else:
        return None
    canonical = text_value.strip(ASCII_EDGE_WHITESPACE)
    return canonical or None


def _quantize_mysql_decimal_20_6(value: Decimal) -> Decimal | None:
    try:
        parsed = value.quantize(MYSQL_DECIMAL_20_6_QUANTUM, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    if not parsed.is_finite() or abs(parsed) > MYSQL_DECIMAL_20_6_MAX:
        return None
    return parsed


def parse_mysql_decimal_20_6(value: Any) -> Decimal | None:
    """Parse exact JSON/text numerics with MySQL DECIMAL(20, 6) semantics."""

    if value is None or value == "":
        return None
    try:
        parsed = Decimal(1 if value is True else 0 if value is False else str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return _quantize_mysql_decimal_20_6(parsed)


def parse_mysql_float_decimal_20_6(value: float | None) -> Decimal | None:
    """Parse an ORM FLOAT using its stored binary value before DECIMAL casting."""

    if value is None:
        return None
    try:
        parsed = Decimal.from_float(value)
    except (TypeError, ValueError):
        return None
    return _quantize_mysql_decimal_20_6(parsed)


def source_nonempty_string(value: Any) -> str | None:
    """Use Python string truthiness without trimming or coercion."""

    return value if isinstance(value, str) and len(value) > 0 else None


def _mysql_canonical_sku(column_sql: str) -> str:
    return f"NULLIF(REGEXP_REPLACE({column_sql}, :ascii_edge_whitespace_regex, ''), '')"


def _mysql_canonical_ascii_text(column_sql: str) -> str:
    canonical = f"REGEXP_REPLACE({column_sql}, :ascii_edge_whitespace_regex, '')"
    return f"CASE WHEN OCTET_LENGTH({canonical}) > 0 THEN {canonical} ELSE NULL END"


def _mysql_source_value(primary_sql: str, fallback_sql: str) -> str:
    return (
        "CASE "
        f"WHEN {primary_sql} IS NOT NULL AND OCTET_LENGTH({primary_sql}) > 0 THEN {primary_sql} "
        f"ELSE {fallback_sql} END"
    )


def tiktok_channel_status_fields(channel_status: str | None) -> dict[str, Any]:
    """Return stable API metadata for one projected TikTok status."""

    meta = TIKTOK_CHANNEL_STATUS_META.get(str(channel_status or ""))
    if meta is None:
        return {
            "channel_status": None,
            "channel_status_label": None,
            "channel_status_reason": None,
            "channel_capabilities": None,
        }
    label, reason = meta
    return {
        "channel_status": channel_status,
        "channel_status_label": label,
        "channel_status_reason": reason,
        "channel_capabilities": {
            "export_supported": False,
            "publish_supported": False,
        },
    }


def _normalized_product_ids(product_ids: Iterable[int] | None) -> list[int] | None:
    if product_ids is None:
        return None
    return sorted({int(product_id) for product_id in product_ids if int(product_id) > 0})


def build_tiktok_classification_cte(
    product_ids: Iterable[int] | None = None,
    data_source_id: int | None = None,
):
    """Build the only TikTok channel classification fact source.

    The returned MySQL 8 CTE emits exactly one row per TikTok product. GigaSku
    is selected as the SKU source when the product key has any GigaSku rows;
    otherwise ProductData.variants is expanded. JSON text is normalized in two
    separate stages before JSON_TYPE/JSON_TABLE consumption.
    """

    normalized_ids = _normalized_product_ids(product_ids)
    filters = ["LOWER(COALESCE(ds.sales_channel, 'amazon')) = 'tiktok'"]
    parameters = [
        bindparam("ascii_edge_whitespace_regex", value=ASCII_EDGE_WHITESPACE_REGEX),
        bindparam("mysql_decimal_20_6_max", value=MYSQL_DECIMAL_20_6_MAX),
    ]
    if data_source_id is not None:
        filters.append("p.source_data_source_id = :tiktok_data_source_id")
        parameters.append(bindparam("tiktok_data_source_id", value=int(data_source_id)))
    if normalized_ids is not None:
        if normalized_ids:
            filters.append("p.id IN :tiktok_product_ids")
            parameters.append(bindparam("tiktok_product_ids", value=normalized_ids, expanding=True))
        else:
            filters.append("0 = 1")

    variant_sku = _mysql_canonical_sku("jt.sku")
    variant_sku_code = _mysql_canonical_sku("jt.sku_code")
    variant_seller_sku = _mysql_canonical_sku("jt.seller_sku")
    giga_sku_sku = _mysql_canonical_sku("gs.sku_code")
    giga_price_sku = _mysql_canonical_sku("gp.sku_code")
    giga_inventory_sku = _mysql_canonical_sku("gi.sku_code")
    source_site = _mysql_source_value("p.source_site", "ds.site")
    item_code = _mysql_source_value("pd.item_code", "p.gigab2b_product_id")
    warehouse_code_candidates = ",\n                    ".join(
        _mysql_canonical_ascii_text(f"warehouse.warehouse_code_{index}")
        for index in range(1, 7)
    )

    statement = text(
        f"""
WITH tiktok_products_valid_json AS (
    SELECT
        p.id AS product_id,
        p.source_data_source_id AS data_source_id,
        'tiktok' AS sales_channel,
        p.status AS product_status,
        p.source_batch_id AS source_batch_id,
        {source_site} AS source_site,
        {item_code} AS item_code,
        CASE
            WHEN COALESCE(JSON_VALID(pd.variants), 0) = 1 THEN pd.variants
            ELSE JSON_ARRAY()
        END AS valid_variants_json
    FROM products AS p
    JOIN product_data_sources AS ds
      ON ds.id = p.source_data_source_id
    LEFT JOIN product_data AS pd
      ON pd.product_id = p.id
    WHERE {' AND '.join(filters)}
),
tiktok_products_safe_json AS (
    SELECT
        source.*,
        CASE
            WHEN source.data_source_id IS NOT NULL
             AND source.source_site IS NOT NULL
             AND OCTET_LENGTH(source.source_site) > 0
             AND source.source_batch_id IS NOT NULL
             AND OCTET_LENGTH(source.source_batch_id) > 0
            THEN 1 ELSE 0
        END AS fact_lookup_enabled,
        CASE
            WHEN source.data_source_id IS NOT NULL
             AND source.source_site IS NOT NULL
             AND OCTET_LENGTH(source.source_site) > 0
             AND source.source_batch_id IS NOT NULL
             AND OCTET_LENGTH(source.source_batch_id) > 0
             AND source.item_code IS NOT NULL
             AND OCTET_LENGTH(source.item_code) > 0
            THEN 1 ELSE 0
        END AS giga_sku_lookup_enabled,
        CASE
            WHEN JSON_TYPE(source.valid_variants_json) = 'ARRAY' THEN source.valid_variants_json
            ELSE JSON_ARRAY()
        END AS safe_variants_json
    FROM tiktok_products_valid_json AS source
),
tiktok_source_keys AS (
    SELECT DISTINCT
        data_source_id,
        source_site,
        source_batch_id
    FROM tiktok_products_safe_json
    WHERE fact_lookup_enabled = 1
),
tiktok_variant_rows AS (
    SELECT
        source.product_id,
        COALESCE(
            {variant_sku},
            {variant_sku_code},
            {variant_seller_sku}
        ) AS sku_code,
        jt.row_ordinal,
        jt.variant_cost,
        jt.variant_cost_total,
        jt.variant_price,
        jt.variant_purchase_price
    FROM tiktok_products_safe_json AS source
    JOIN JSON_TABLE(
        CAST(source.safe_variants_json AS JSON),
        '$[*]' COLUMNS (
            row_ordinal FOR ORDINALITY,
            sku VARCHAR(255) PATH '$.sku' NULL ON EMPTY NULL ON ERROR,
            sku_code VARCHAR(255) PATH '$.sku_code' NULL ON EMPTY NULL ON ERROR,
            seller_sku VARCHAR(255) PATH '$.seller_sku' NULL ON EMPTY NULL ON ERROR,
            variant_cost DECIMAL(20, 6) PATH '$.cost' NULL ON EMPTY NULL ON ERROR,
            variant_cost_total DECIMAL(20, 6) PATH '$.cost_total' NULL ON EMPTY NULL ON ERROR,
            variant_price DECIMAL(20, 6) PATH '$.price' NULL ON EMPTY NULL ON ERROR,
            variant_purchase_price DECIMAL(20, 6) PATH '$.purchase_price' NULL ON EMPTY NULL ON ERROR
        )
    ) AS jt
),
tiktok_variant_lookup_ranked AS (
    SELECT
        variant.*,
        ROW_NUMBER() OVER (
            PARTITION BY variant.product_id, CAST(variant.sku_code AS BINARY)
            ORDER BY variant.row_ordinal DESC
        ) AS sku_rank
    FROM tiktok_variant_rows AS variant
    WHERE variant.sku_code IS NOT NULL
),
tiktok_variant_lookup AS (
    SELECT
        product_id,
        sku_code,
        variant_cost,
        variant_cost_total,
        variant_price,
        variant_purchase_price
    FROM tiktok_variant_lookup_ranked
    WHERE sku_rank = 1
),
tiktok_giga_sku_canonical AS (
    SELECT
        source.product_id,
        gs.id AS giga_sku_id,
        gs.sku_code AS raw_sku_code,
        {giga_sku_sku} AS sku_code
    FROM tiktok_products_safe_json AS source
    JOIN giga_skus AS gs
      ON source.giga_sku_lookup_enabled = 1
     AND gs.data_source_id = source.data_source_id
     AND gs.site = source.source_site
     AND gs.batch_id = source.source_batch_id
     AND gs.item_code = source.item_code
),
tiktok_giga_sku_ranked AS (
    SELECT
        fact.*,
        ROW_NUMBER() OVER (
            PARTITION BY fact.product_id, CAST(fact.sku_code AS BINARY)
            ORDER BY
                CASE
                    WHEN CAST(fact.raw_sku_code AS BINARY) = CAST(fact.sku_code AS BINARY) THEN 1
                    ELSE 0
                END DESC,
                fact.giga_sku_id DESC
        ) AS fact_rank
    FROM tiktok_giga_sku_canonical AS fact
    WHERE fact.sku_code IS NOT NULL
),
tiktok_giga_sku_winners AS (
    SELECT
        product_id,
        giga_sku_id,
        sku_code
    FROM tiktok_giga_sku_ranked
    WHERE fact_rank = 1
),
tiktok_products_with_giga AS (
    SELECT
        source.*,
        (
            SELECT COUNT(*)
            FROM tiktok_giga_sku_winners AS gs_count
            WHERE gs_count.product_id = source.product_id
        ) AS giga_sku_count,
        (
            SELECT JSON_ARRAYAGG(JSON_OBJECT('sku_code', gs_json.sku_code))
            FROM tiktok_giga_sku_winners AS gs_json
            WHERE gs_json.product_id = source.product_id
        ) AS giga_skus_json
    FROM tiktok_products_safe_json AS source
),
tiktok_selected_products AS (
    SELECT
        source.*
    FROM tiktok_products_with_giga AS source
),
tiktok_sku_candidates AS (
    SELECT
        source.product_id,
        source.data_source_id,
        source.source_batch_id,
        source.source_site,
        CAST(giga.sku_code AS BINARY) AS sku_code,
        variant.variant_cost,
        variant.variant_cost_total,
        variant.variant_price,
        variant.variant_purchase_price
    FROM tiktok_selected_products AS source
    JOIN tiktok_giga_sku_winners AS giga
      ON giga.product_id = source.product_id
    LEFT JOIN tiktok_variant_lookup AS variant
      ON variant.product_id = source.product_id
     AND CAST(variant.sku_code AS BINARY) = CAST(giga.sku_code AS BINARY)
    WHERE source.giga_sku_count > 0

    UNION ALL

    SELECT
        source.product_id,
        source.data_source_id,
        source.source_batch_id,
        source.source_site,
        CAST(variant.sku_code AS BINARY) AS sku_code,
        variant.variant_cost,
        variant.variant_cost_total,
        variant.variant_price,
        variant.variant_purchase_price
    FROM tiktok_selected_products AS source
    JOIN tiktok_variant_lookup AS variant
      ON variant.product_id = source.product_id
    WHERE source.giga_sku_count = 0
),
tiktok_giga_price_canonical AS (
    SELECT
        gp.data_source_id,
        gp.site,
        gp.batch_id,
        gp.id AS giga_price_id,
        gp.sku_code AS raw_sku_code,
        {giga_price_sku} AS sku_code,
        gp.effective_price,
        gp.discounted_price,
        gp.exclusive_price,
        gp.price
    FROM giga_prices AS gp
    JOIN tiktok_source_keys AS source
      ON source.data_source_id = gp.data_source_id
     AND source.source_site = gp.site
     AND source.source_batch_id = gp.batch_id
),
tiktok_giga_price_ranked AS (
    SELECT
        fact.*,
        ROW_NUMBER() OVER (
            PARTITION BY
                fact.data_source_id,
                fact.site,
                fact.batch_id,
                CAST(fact.sku_code AS BINARY)
            ORDER BY
                CASE
                    WHEN CAST(fact.raw_sku_code AS BINARY) = CAST(fact.sku_code AS BINARY) THEN 1
                    ELSE 0
                END DESC,
                fact.giga_price_id DESC
        ) AS fact_rank
    FROM tiktok_giga_price_canonical AS fact
    WHERE fact.sku_code IS NOT NULL
),
tiktok_giga_price_winners AS (
    SELECT
        data_source_id,
        site,
        batch_id,
        sku_code,
        CASE
            WHEN ABS(effective_price) <= :mysql_decimal_20_6_max
                THEN CAST(effective_price AS DECIMAL(20, 6))
            ELSE NULL
        END AS effective_price,
        CASE
            WHEN ABS(discounted_price) <= :mysql_decimal_20_6_max
                THEN CAST(discounted_price AS DECIMAL(20, 6))
            ELSE NULL
        END AS discounted_price,
        CASE
            WHEN ABS(exclusive_price) <= :mysql_decimal_20_6_max
                THEN CAST(exclusive_price AS DECIMAL(20, 6))
            ELSE NULL
        END AS exclusive_price,
        CASE
            WHEN ABS(price) <= :mysql_decimal_20_6_max
                THEN CAST(price AS DECIMAL(20, 6))
            ELSE NULL
        END AS price
    FROM tiktok_giga_price_ranked
    WHERE fact_rank = 1
),
tiktok_giga_inventory_canonical AS (
    SELECT
        gi.data_source_id,
        gi.site,
        gi.batch_id,
        gi.id AS giga_inventory_id,
        gi.sku_code AS raw_sku_code,
        {giga_inventory_sku} AS sku_code,
        gi.seller_inventory_distribution
    FROM giga_inventory AS gi
    JOIN tiktok_source_keys AS source
      ON source.data_source_id = gi.data_source_id
     AND source.source_site = gi.site
     AND source.source_batch_id = gi.batch_id
),
tiktok_giga_inventory_ranked AS (
    SELECT
        fact.*,
        ROW_NUMBER() OVER (
            PARTITION BY
                fact.data_source_id,
                fact.site,
                fact.batch_id,
                CAST(fact.sku_code AS BINARY)
            ORDER BY
                CASE
                    WHEN CAST(fact.raw_sku_code AS BINARY) = CAST(fact.sku_code AS BINARY) THEN 1
                    ELSE 0
                END DESC,
                fact.giga_inventory_id DESC
        ) AS fact_rank
    FROM tiktok_giga_inventory_canonical AS fact
    WHERE fact.sku_code IS NOT NULL
),
tiktok_giga_inventory_winners AS (
    SELECT
        data_source_id,
        site,
        batch_id,
        sku_code,
        seller_inventory_distribution
    FROM tiktok_giga_inventory_ranked
    WHERE fact_rank = 1
),
tiktok_sku_valid_json AS (
    SELECT
        sku.*,
        CASE
            WHEN gp.effective_price > 0 THEN gp.effective_price
            WHEN gp.discounted_price > 0 THEN gp.discounted_price
            WHEN gp.exclusive_price > 0 THEN gp.exclusive_price
            WHEN gp.price > 0 THEN gp.price
            WHEN sku.variant_cost > 0 THEN sku.variant_cost
            WHEN sku.variant_cost_total > 0 THEN sku.variant_cost_total
            WHEN sku.variant_price > 0 THEN sku.variant_price
            WHEN sku.variant_purchase_price > 0 THEN sku.variant_purchase_price
            ELSE NULL
        END AS purchase_price,
        CASE
            WHEN COALESCE(JSON_VALID(gi.seller_inventory_distribution), 0) = 1
                THEN gi.seller_inventory_distribution
            ELSE JSON_ARRAY()
        END AS valid_warehouse_json
    FROM tiktok_sku_candidates AS sku
    LEFT JOIN tiktok_giga_price_winners AS gp
      ON gp.data_source_id = sku.data_source_id
     AND gp.site = sku.source_site
     AND gp.batch_id = sku.source_batch_id
     AND CAST(gp.sku_code AS BINARY) = CAST(sku.sku_code AS BINARY)
    LEFT JOIN tiktok_giga_inventory_winners AS gi
      ON gi.data_source_id = sku.data_source_id
     AND gi.site = sku.source_site
     AND gi.batch_id = sku.source_batch_id
     AND CAST(gi.sku_code AS BINARY) = CAST(sku.sku_code AS BINARY)
    WHERE sku.sku_code IS NOT NULL
),
tiktok_sku_safe_json AS (
    SELECT
        sku.*,
        CASE
            WHEN JSON_TYPE(sku.valid_warehouse_json) = 'ARRAY' THEN sku.valid_warehouse_json
            ELSE JSON_ARRAY()
        END AS safe_warehouse_json
    FROM tiktok_sku_valid_json AS sku
),
tiktok_sku_facts AS (
    SELECT
        sku.*,
        CASE WHEN EXISTS (
            SELECT 1
            FROM JSON_TABLE(
                CAST(sku.safe_warehouse_json AS JSON),
                '$[*]' COLUMNS (
                    row_ordinal FOR ORDINALITY,
                    warehouse_code_1 VARCHAR(255) PATH '$.warehouseCode' NULL ON EMPTY NULL ON ERROR,
                    warehouse_code_2 VARCHAR(255) PATH '$.warehouse_code' NULL ON EMPTY NULL ON ERROR,
                    warehouse_code_3 VARCHAR(255) PATH '$.warehouse' NULL ON EMPTY NULL ON ERROR,
                    warehouse_code_4 VARCHAR(255) PATH '$.sellerCode' NULL ON EMPTY NULL ON ERROR,
                    warehouse_code_5 VARCHAR(255) PATH '$.seller_code' NULL ON EMPTY NULL ON ERROR,
                    warehouse_code_6 VARCHAR(255) PATH '$.code' NULL ON EMPTY NULL ON ERROR,
                    quantity_1 DECIMAL(20, 6) PATH '$.quantity' NULL ON EMPTY NULL ON ERROR,
                    quantity_2 DECIMAL(20, 6) PATH '$.qty' NULL ON EMPTY NULL ON ERROR,
                    quantity_3 DECIMAL(20, 6) PATH '$.availableQty' NULL ON EMPTY NULL ON ERROR,
                    quantity_4 DECIMAL(20, 6) PATH '$.available_qty' NULL ON EMPTY NULL ON ERROR,
                    quantity_5 DECIMAL(20, 6) PATH '$.sellerAvailableInventory' NULL ON EMPTY NULL ON ERROR,
                    quantity_6 DECIMAL(20, 6) PATH '$.seller_available_inventory' NULL ON EMPTY NULL ON ERROR,
                    quantity_7 DECIMAL(20, 6) PATH '$.stock' NULL ON EMPTY NULL ON ERROR
                )
            ) AS warehouse
            WHERE JSON_TYPE(
                JSON_EXTRACT(sku.safe_warehouse_json, CONCAT('$[', warehouse.row_ordinal - 1, ']'))
            ) = 'OBJECT'
              AND COALESCE(
                    {warehouse_code_candidates}
                  ) IS NOT NULL
              AND COALESCE(
                    warehouse.quantity_1,
                    warehouse.quantity_2,
                    warehouse.quantity_3,
                    warehouse.quantity_4,
                    warehouse.quantity_5,
                    warehouse.quantity_6,
                    warehouse.quantity_7
                  ) IS NOT NULL
        ) THEN 1 ELSE 0 END AS has_warehouse_inventory
    FROM tiktok_sku_safe_json AS sku
),
tiktok_sku_counts AS (
    SELECT
        product_id,
        COUNT(*) AS display_sku_count,
        SUM(CASE WHEN purchase_price IS NULL THEN 1 ELSE 0 END) AS missing_price_count,
        SUM(CASE WHEN has_warehouse_inventory = 0 THEN 1 ELSE 0 END) AS missing_warehouse_count
    FROM tiktok_sku_facts
    GROUP BY product_id
)
SELECT
    product.product_id,
    product.data_source_id,
    product.sales_channel,
    COALESCE(counts.display_sku_count, 0) AS display_sku_count,
    COALESCE(counts.missing_price_count, 0) AS missing_price_count,
    COALESCE(counts.missing_warehouse_count, 0) AS missing_warehouse_count,
    CASE
        WHEN product.product_status = 'failed' THEN 'failed'
        WHEN COALESCE(counts.display_sku_count, 0) = 0 THEN 'draft'
        WHEN COALESCE(counts.missing_price_count, 0) > 0
          OR COALESCE(counts.missing_warehouse_count, 0) > 0 THEN 'missing_required_info'
        ELSE 'unsupported'
    END AS channel_status
FROM tiktok_selected_products AS product
LEFT JOIN tiktok_sku_counts AS counts
  ON counts.product_id = product.product_id
"""
    ).columns(
        product_id=Integer,
        data_source_id=Integer,
        sales_channel=String(30),
        display_sku_count=Integer,
        missing_price_count=Integer,
        missing_warehouse_count=Integer,
        channel_status=String(40),
    )
    if parameters:
        statement = statement.bindparams(*parameters)
    return statement.cte("tiktok_classification")
