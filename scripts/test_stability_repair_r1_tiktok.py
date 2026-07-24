#!/usr/bin/env python3
"""R1 TikTok channel-status checks on an isolated MySQL database."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.testing.r1_mysql import R1MysqlNotConfigured, isolated_r1_mysql


CHANNEL_STATUSES = ("failed", "draft", "missing_required_info", "unsupported")
DEFAULT_ITEM_CODE = object()


@dataclass(frozen=True)
class FixtureState:
    tiktok_data_source_id: int
    amazon_data_source_id: int
    product_ids: dict[str, int]
    tiktok_product_ids: tuple[int, ...]
    pagination_tie_product_ids: tuple[int, ...]
    pagination_tie_timestamp: str


def test_contract_files() -> None:
    service_path = ROOT / "backend" / "app" / "services" / "tiktok_status.py"
    assert service_path.is_file(), "TikTok classification must have a shared service"
    tiktok_api = (ROOT / "backend" / "app" / "api" / "tiktok.py").read_text(encoding="utf-8")
    schemas = (ROOT / "backend" / "app" / "api" / "schemas.py").read_text(encoding="utf-8")
    service = service_path.read_text(encoding="utf-8")
    frontend_api = (ROOT / "frontend" / "src" / "api" / "index.ts").read_text(encoding="utf-8")
    detail_page = (ROOT / "frontend" / "src" / "pages" / "TikTokProductDetail.tsx").read_text(encoding="utf-8")
    product_list = (ROOT / "frontend" / "src" / "pages" / "ProductList.tsx").read_text(encoding="utf-8")
    browser_spec = (ROOT / "frontend" / "tests" / "tiktok-status.r1.spec.ts").read_text(encoding="utf-8")
    for name, source in (
        ("TikTok service", service),
        ("TikTok API", tiktok_api),
        ("TikTok detail page", detail_page),
    ):
        assert "export_ready" not in source, f"{name} must not expose TikTok export_ready semantics"
    assert "待 TikTok 导出" not in product_list
    assert "待 TikTok 导出" not in detail_page
    assert "page.route(" not in browser_spec and "routeFromHAR" not in browser_spec
    contract_failures: list[str] = []
    if 'sales_channel: Literal["amazon", "tiktok"] = "amazon"' not in schemas:
        contract_failures.append("ProductResponse.sales_channel must be a non-null Amazon/TikTok Literal")
    if "sales_channel: 'amazon' | 'tiktok';" not in frontend_api:
        contract_failures.append("frontend Product.sales_channel must be a required closed union")
    assert not contract_failures, "sales_channel contract failures:\n" + "\n".join(contract_failures)


async def _seed_fixtures(environment) -> FixtureState:
    from app.models import GigaInventory, GigaPrice, GigaSku, Product, ProductData, ProductDataSource

    product_ids: dict[str, int] = {}
    tiktok_product_ids: list[int] = []
    pagination_tie_product_ids: list[int] = []
    async with environment.session_factory() as db:
        tiktok_source = ProductDataSource(
            name="R1 TikTok Status",
            platform="giga",
            sales_channel="tiktok",
            site="US",
            country="US",
        )
        amazon_source = ProductDataSource(
            name="R1 Amazon Status",
            platform="giga",
            sales_channel="amazon",
            site="US",
            country="US",
        )
        db.add_all([tiktok_source, amazon_source])
        await db.flush()

        async def add_product(
            key: str,
            *,
            status: str = "created",
            variants: Any = None,
            raw_variants: str | None = None,
            data_source_id: int | None = None,
            source_site: str | None = "US",
            batch_id: str | None = "R1-TIKTOK-BATCH",
            item_code: str | None | object = DEFAULT_ITEM_CODE,
            source_item_id: str | None = None,
            created_at: datetime | None = None,
            updated_at: datetime | None = None,
        ) -> Product:
            code = f"R1-TK-{key.upper().replace('_', '-')}"
            resolved_source_item_id = code if source_item_id is None else source_item_id
            resolved_item_code = code if item_code is DEFAULT_ITEM_CODE else item_code
            product = Product(
                gigab2b_url=f"https://example.invalid/{code}",
                gigab2b_product_id=resolved_source_item_id,
                source_data_source_id=data_source_id or tiktok_source.id,
                source_site=source_site,
                source_batch_id=batch_id,
                status=status,
                current_step=6 if status == "completed" else 1,
                error_message="R1 source failure" if status == "failed" else None,
            )
            if created_at is not None:
                product.created_at = created_at
            if updated_at is not None:
                product.updated_at = updated_at
            if raw_variants is not None:
                variants_text = raw_variants
            elif variants is None:
                variants_text = None
            else:
                variants_text = json.dumps(variants, ensure_ascii=False)
            product.data = ProductData(
                item_code=resolved_item_code,
                title=f"R1 TikTok {key}",
                variants=variants_text,
            )
            db.add(product)
            await db.flush()
            product_ids[key] = product.id
            if product.source_data_source_id == tiktok_source.id:
                tiktok_product_ids.append(product.id)
            return product

        def add_giga_sku(product: Product, sku_code: str, **values: Any) -> GigaSku:
            row = GigaSku(
                batch_id=values.pop("batch_id", product.source_batch_id or ""),
                site=values.pop("site", product.source_site or tiktok_source.site),
                data_source_id=product.source_data_source_id,
                sku_code=sku_code,
                item_code=values.pop("item_code", product.data.item_code if product.data else None),
                product_name=values.pop("product_name", f"R1 {sku_code}"),
                **values,
            )
            db.add(row)
            return row

        def add_price(product: Product, sku_code: str, **values: Any) -> GigaPrice:
            row = GigaPrice(
                batch_id=values.pop("batch_id", product.source_batch_id or ""),
                site=values.pop("site", product.source_site or tiktok_source.site),
                data_source_id=product.source_data_source_id,
                sku_code=sku_code,
                **values,
            )
            db.add(row)
            return row

        def add_inventory(
            product: Product,
            sku_code: str,
            distribution: str | None,
            **values: Any,
        ) -> GigaInventory:
            row = GigaInventory(
                batch_id=values.pop("batch_id", product.source_batch_id or ""),
                site=values.pop("site", product.source_site or tiktok_source.site),
                data_source_id=product.source_data_source_id,
                sku_code=sku_code,
                seller_inventory_distribution=distribution,
                **values,
            )
            db.add(row)
            return row

        await add_product("failed", status="failed", variants=[])
        await add_product("draft", raw_variants="{not-json")

        missing = await add_product("missing_required_info", variants=[{"sku": "IGNORED-VARIANT", "cost": 9}])
        add_giga_sku(missing, "R1-MISSING")
        add_inventory(missing, "R1-MISSING", json.dumps([{"warehouseCode": "WH-1", "quantity": 5}]))

        unsupported = await add_product("unsupported", status="completed", variants=[])
        add_giga_sku(unsupported, "R1-UNSUPPORTED")
        add_price(unsupported, "R1-UNSUPPORTED", effective_price=12.5, discounted_price=10.0, price=8.0)
        add_inventory(unsupported, "R1-UNSUPPORTED", json.dumps([{"warehouseCode": "WH-ZERO", "quantity": 0}]))

        variant_price = await add_product(
            "variant_gigaprice",
            variants=[{"seller_sku": "R1-VARIANT-PRICE", "cost": "not-a-number", "purchase_price": "4.5"}],
        )
        add_price(variant_price, "R1-VARIANT-PRICE", discounted_price=6.25, price=5.0)
        add_inventory(variant_price, "R1-VARIANT-PRICE", json.dumps([{"seller_code": "WH-2", "qty": 1}]))

        variant_sku_fallback = await add_product(
            "variant_sku_fallback",
            variants=[{"sku": "  ", "sku_code": "R1-SKU-FALLBACK", "cost": 5.5}],
        )
        add_inventory(
            variant_sku_fallback,
            "R1-SKU-FALLBACK",
            json.dumps([{"warehouse_code": "WH-FALLBACK", "available_qty": 1}]),
        )

        malformed_variant_price = await add_product(
            "malformed_variant_price",
            variants=[{"sku": "R1-MALFORMED-PRICE", "cost": "12oops", "price": {"bad": True}}],
        )
        add_inventory(
            malformed_variant_price,
            "R1-MALFORMED-PRICE",
            json.dumps([{"warehouse": "WH-3", "availableQty": 2}]),
        )

        no_union = await add_product(
            "giga_excludes_variants",
            variants=[{"sku": "R1-SHOULD-NOT-COUNT", "cost": 3}],
        )
        add_giga_sku(no_union, "R1-GIGA-ONLY")
        add_price(no_union, "R1-GIGA-ONLY", price=7.0)
        add_inventory(no_union, "R1-GIGA-ONLY", json.dumps([{"code": "WH-4", "stock": 3}]))

        giga_variant_fallback = await add_product(
            "giga_variant_price_fallback",
            variants=[
                {"sku": "R1-GIGA-VARIANT-FALLBACK", "cost": 5.5},
                {"sku": "R1-VARIANT-ONLY-EXCLUDED", "purchase_price": 99.0},
            ],
        )
        add_giga_sku(giga_variant_fallback, "R1-GIGA-VARIANT-FALLBACK")
        add_inventory(
            giga_variant_fallback,
            "R1-GIGA-VARIANT-FALLBACK",
            json.dumps([{"warehouseCode": "WH-GIGA-VARIANT", "quantity": 0}]),
        )

        case_variant_conflict = await add_product(
            "case_variant_conflict",
            variants=[
                {"sku": "R1-CASE", "cost": "not-a-number"},
                {"sku": "r1-case", "cost": 9.0},
            ],
        )
        add_giga_sku(case_variant_conflict, "R1-CASE")
        add_inventory(
            case_variant_conflict,
            "R1-CASE",
            json.dumps([{"warehouseCode": "WH-CASE", "quantity": 0}]),
        )

        exact_duplicate_variant = await add_product(
            "exact_duplicate_variant",
            variants=[
                {"sku": "R1-DUPLICATE", "cost": "not-a-number"},
                {"sku": "R1-DUPLICATE", "purchase_price": 7.25},
            ],
        )
        add_giga_sku(exact_duplicate_variant, "R1-DUPLICATE")
        add_inventory(
            exact_duplicate_variant,
            "R1-DUPLICATE",
            json.dumps([{"warehouseCode": "WH-DUPLICATE", "quantity": 0}]),
        )

        wrong_case_gigaprice = await add_product(
            "wrong_case_gigaprice",
            variants=[{"sku": "R1-PRICE-CASE", "cost": "not-a-number"}],
        )
        add_giga_sku(wrong_case_gigaprice, "R1-PRICE-CASE")
        add_price(wrong_case_gigaprice, "r1-price-case", effective_price=11.0)
        add_inventory(
            wrong_case_gigaprice,
            "R1-PRICE-CASE",
            json.dumps([{"warehouseCode": "WH-PRICE-CASE", "quantity": 0}]),
        )

        wrong_case_inventory = await add_product(
            "wrong_case_inventory",
            variants=[{"sku": "R1-INVENTORY-CASE", "cost": 4.0}],
        )
        add_giga_sku(wrong_case_inventory, "R1-INVENTORY-CASE")
        add_price(wrong_case_inventory, "R1-INVENTORY-CASE", effective_price=8.0)
        add_inventory(
            wrong_case_inventory,
            "r1-inventory-case",
            json.dumps([{"warehouseCode": "WH-INVENTORY-CASE", "quantity": 0}]),
        )

        trimmed_exact_sku = await add_product(
            "trimmed_exact_sku",
            variants=[{"sku": "  R1-TRIM  ", "cost": 5.0}],
        )
        add_giga_sku(trimmed_exact_sku, "  R1-TRIM  ")
        add_price(trimmed_exact_sku, "R1-TRIM", effective_price=8.0)
        add_inventory(
            trimmed_exact_sku,
            "R1-TRIM",
            json.dumps([{"warehouseCode": "WH-TRIM", "quantity": 0}]),
        )

        ascii_tab_giga_variant = await add_product(
            "ascii_tab_giga_variant",
            variants=[{"sku": "R1-ASCII-TAB", "cost": 5.1}],
        )
        add_giga_sku(ascii_tab_giga_variant, "R1-ASCII-TAB\t")
        add_inventory(
            ascii_tab_giga_variant,
            "R1-ASCII-TAB",
            json.dumps([{"warehouseCode": "WH-ASCII-TAB", "quantity": 0}]),
        )

        ascii_lf_variant_fallback = await add_product(
            "ascii_lf_variant_fallback",
            variants=[{"sku": "\nR1-ASCII-LF\n", "cost": 6.1}],
        )
        add_inventory(
            ascii_lf_variant_fallback,
            "R1-ASCII-LF",
            json.dumps([{"warehouseCode": "WH-ASCII-LF", "quantity": 0}]),
        )

        ascii_cr_gigaprice = await add_product(
            "ascii_cr_gigaprice",
            variants=[{"sku": "R1-ASCII-CR", "cost": "not-a-number"}],
        )
        add_giga_sku(ascii_cr_gigaprice, "R1-ASCII-CR")
        add_price(ascii_cr_gigaprice, "\rR1-ASCII-CR\r", effective_price=7.1)
        add_inventory(
            ascii_cr_gigaprice,
            "R1-ASCII-CR",
            json.dumps([{"warehouseCode": "WH-ASCII-CR", "quantity": 0}]),
        )

        ascii_ff_inventory = await add_product(
            "ascii_ff_inventory",
            variants=[{"sku": "R1-ASCII-FF", "cost": 4.1}],
        )
        add_giga_sku(ascii_ff_inventory, "R1-ASCII-FF")
        add_price(ascii_ff_inventory, "R1-ASCII-FF", effective_price=8.1)
        add_inventory(
            ascii_ff_inventory,
            "\fR1-ASCII-FF\f",
            json.dumps([{"warehouseCode": "WH-ASCII-FF", "quantity": 0}]),
        )

        ascii_vt_variant = await add_product(
            "ascii_vt_variant",
            variants=[{"sku": "\vR1-ASCII-VT\v", "cost": 9.1}],
        )
        add_giga_sku(ascii_vt_variant, "R1-ASCII-VT")
        add_inventory(
            ascii_vt_variant,
            "R1-ASCII-VT",
            json.dumps([{"warehouseCode": "WH-ASCII-VT", "quantity": 0}]),
        )

        ascii_mixed_facts = await add_product(
            "ascii_mixed_facts",
            variants=[{"sku": "R1-ASCII-MIXED", "cost": 10.1}],
        )
        add_giga_sku(ascii_mixed_facts, "\t\n R1-ASCII-MIXED \r\f\v")
        add_price(ascii_mixed_facts, "\v\fR1-ASCII-MIXED\r\n", effective_price=12.1)
        add_inventory(
            ascii_mixed_facts,
            "\t R1-ASCII-MIXED \n",
            json.dumps([{"warehouseCode": "WH-ASCII-MIXED", "quantity": 0}]),
        )

        collision_inventory_exact_valid = await add_product(
            "collision_inventory_exact_valid",
            variants=[{"sku": "R1-COLLISION-INV-VALID", "cost": 5.2}],
        )
        add_giga_sku(collision_inventory_exact_valid, "R1-COLLISION-INV-VALID")
        add_inventory(
            collision_inventory_exact_valid,
            "R1-COLLISION-INV-VALID",
            json.dumps([{"warehouseCode": "WH-COLLISION-INV-VALID", "quantity": 0}]),
        )
        add_inventory(collision_inventory_exact_valid, "\tR1-COLLISION-INV-VALID", "{bad-json")

        collision_inventory_exact_invalid = await add_product(
            "collision_inventory_exact_invalid",
            variants=[{"sku": "R1-COLLISION-INV-INVALID", "cost": 5.3}],
        )
        add_giga_sku(collision_inventory_exact_invalid, "R1-COLLISION-INV-INVALID")
        add_inventory(collision_inventory_exact_invalid, "R1-COLLISION-INV-INVALID", "{bad-json")
        add_inventory(
            collision_inventory_exact_invalid,
            "\tR1-COLLISION-INV-INVALID",
            json.dumps([{"warehouseCode": "WH-COLLISION-INV-LOSER", "quantity": 0}]),
        )

        collision_price_exact_valid = await add_product(
            "collision_price_exact_valid",
            variants=[{"sku": "R1-COLLISION-PRICE-VALID", "cost": "not-a-number"}],
        )
        add_giga_sku(collision_price_exact_valid, "R1-COLLISION-PRICE-VALID")
        add_price(collision_price_exact_valid, "R1-COLLISION-PRICE-VALID", effective_price=13.2)
        add_price(collision_price_exact_valid, "\tR1-COLLISION-PRICE-VALID")
        add_inventory(
            collision_price_exact_valid,
            "R1-COLLISION-PRICE-VALID",
            json.dumps([{"warehouseCode": "WH-COLLISION-PRICE-VALID", "quantity": 0}]),
        )

        collision_price_exact_invalid = await add_product(
            "collision_price_exact_invalid",
            variants=[{"sku": "R1-COLLISION-PRICE-INVALID", "cost": "not-a-number"}],
        )
        add_giga_sku(collision_price_exact_invalid, "R1-COLLISION-PRICE-INVALID")
        add_price(collision_price_exact_invalid, "R1-COLLISION-PRICE-INVALID")
        add_price(collision_price_exact_invalid, "\tR1-COLLISION-PRICE-INVALID", effective_price=14.3)
        add_inventory(
            collision_price_exact_invalid,
            "R1-COLLISION-PRICE-INVALID",
            json.dumps([{"warehouseCode": "WH-COLLISION-PRICE-INVALID", "quantity": 0}]),
        )

        collision_gigasku_exact = await add_product(
            "collision_gigasku_exact",
            variants=[{"sku": "R1-COLLISION-SKU-EXACT", "cost": 6.2}],
        )
        add_giga_sku(
            collision_gigasku_exact,
            "R1-COLLISION-SKU-EXACT",
            product_name="Exact GigaSku Winner",
            child_sequence=2,
        )
        add_giga_sku(
            collision_gigasku_exact,
            "\tR1-COLLISION-SKU-EXACT",
            product_name="Whitespace GigaSku Loser",
            child_sequence=1,
        )
        add_inventory(
            collision_gigasku_exact,
            "R1-COLLISION-SKU-EXACT",
            json.dumps([{"warehouseCode": "WH-COLLISION-SKU-EXACT", "quantity": 0}]),
        )

        collision_gigasku_latest = await add_product(
            "collision_gigasku_latest",
            variants=[{"sku": "R1-COLLISION-SKU-LATEST", "cost": 6.3}],
        )
        add_giga_sku(
            collision_gigasku_latest,
            " R1-COLLISION-SKU-LATEST",
            product_name="Older Noncanonical GigaSku",
            child_sequence=2,
        )
        add_giga_sku(
            collision_gigasku_latest,
            "\tR1-COLLISION-SKU-LATEST",
            product_name="Newest Noncanonical GigaSku Winner",
            child_sequence=1,
        )
        add_inventory(
            collision_gigasku_latest,
            "R1-COLLISION-SKU-LATEST",
            json.dumps([{"warehouseCode": "WH-COLLISION-SKU-LATEST", "quantity": 0}]),
        )

        empty_gigasku_fallback = await add_product(
            "empty_gigasku_fallback",
            variants=[{"sku": "R1-EMPTY-GIGA-FALLBACK", "cost": 6.4}],
        )
        add_giga_sku(empty_gigasku_fallback, " \t\n\r\f\v ")
        add_inventory(
            empty_gigasku_fallback,
            "R1-EMPTY-GIGA-FALLBACK",
            json.dumps([{"warehouseCode": "WH-EMPTY-GIGA-FALLBACK", "quantity": 0}]),
        )

        source_keys_spaced = await add_product(
            "source_keys_spaced",
            source_site=" US ",
            item_code=" ITEM ",
            variants=[{"sku": "R1-SOURCE-SPACED", "cost": 2.1}],
        )
        add_giga_sku(source_keys_spaced, "R1-SOURCE-SPACED", product_name="Spaced source winner")
        add_price(source_keys_spaced, "R1-SOURCE-SPACED", effective_price=8.2)
        add_inventory(
            source_keys_spaced,
            "R1-SOURCE-SPACED",
            json.dumps([{"warehouseCode": "WH-SOURCE-SPACED", "quantity": 0}]),
        )

        for key, source_site in (
            ("source_site_empty_fallback", ""),
            ("source_site_null_fallback", None),
        ):
            product = await add_product(key, source_site=source_site, variants=[])
            sku_code = f"R1-{key.upper().replace('_', '-')}"
            add_giga_sku(product, sku_code)
            add_price(product, sku_code, effective_price=8.3)
            add_inventory(
                product,
                sku_code,
                json.dumps([{"warehouseCode": "WH-SITE-FALLBACK", "quantity": 0}]),
            )

        for key, item_code in (
            ("item_code_empty_fallback", ""),
            ("item_code_null_fallback", None),
        ):
            product = await add_product(key, item_code=item_code, variants=[])
            sku_code = f"R1-{key.upper().replace('_', '-')}"
            add_giga_sku(product, sku_code, item_code=product.gigab2b_product_id)
            add_price(product, sku_code, effective_price=8.4)
            add_inventory(
                product,
                sku_code,
                json.dumps([{"warehouseCode": "WH-ITEM-FALLBACK", "quantity": 0}]),
            )

        batch_empty_variants_only = await add_product(
            "batch_empty_variants_only",
            batch_id="",
            variants=[{"sku": "R1-BATCH-EMPTY-VARIANT", "cost": 5.4}],
        )
        add_giga_sku(batch_empty_variants_only, "R1-BATCH-EMPTY-GIGA")
        add_price(batch_empty_variants_only, "R1-BATCH-EMPTY-GIGA", effective_price=9.4)
        add_inventory(
            batch_empty_variants_only,
            "R1-BATCH-EMPTY-GIGA",
            json.dumps([{"warehouseCode": "WH-BATCH-EMPTY-GIGA", "quantity": 0}]),
        )
        add_price(batch_empty_variants_only, "R1-BATCH-EMPTY-VARIANT", effective_price=9.5)
        add_inventory(
            batch_empty_variants_only,
            "R1-BATCH-EMPTY-VARIANT",
            json.dumps([{"warehouseCode": "WH-BATCH-EMPTY-VARIANT", "quantity": 0}]),
        )

        batch_null_variants_only = await add_product(
            "batch_null_variants_only",
            batch_id=None,
            variants=[{"sku": "R1-BATCH-NULL-VARIANT", "cost": 5.5}],
        )
        add_giga_sku(batch_null_variants_only, "R1-BATCH-NULL-GIGA", batch_id="")
        add_price(batch_null_variants_only, "R1-BATCH-NULL-VARIANT", batch_id="", effective_price=9.6)
        add_inventory(
            batch_null_variants_only,
            "R1-BATCH-NULL-VARIANT",
            json.dumps([{"warehouseCode": "WH-BATCH-NULL", "quantity": 0}]),
            batch_id="",
        )

        batch_control_lookup = await add_product(
            "batch_control_lookup",
            batch_id="R1-BATCH-CONTROL",
            variants=[{"sku": "R1-BATCH-CONTROL", "cost": "bad"}],
        )
        add_giga_sku(batch_control_lookup, "R1-BATCH-CONTROL")
        add_price(batch_control_lookup, "R1-BATCH-CONTROL", effective_price=9.7)
        add_inventory(
            batch_control_lookup,
            "R1-BATCH-CONTROL",
            json.dumps([{"warehouseCode": "WH-BATCH-CONTROL", "quantity": 0}]),
        )

        await add_product(
            "invalid_json_nan_constant",
            raw_variants='[{"sku":"R1-JSON-NAN","cost":NaN}]',
        )
        await add_product(
            "invalid_json_infinity_constant",
            raw_variants='[{"sku":"R1-JSON-INFINITY","cost":Infinity}]',
        )

        for key, price_value in (
            ("variant_price_nan", "NaN"),
            ("variant_price_infinity", "Infinity"),
            ("variant_price_overflow", "100000000000000"),
        ):
            sku_code = f"R1-{key.upper().replace('_', '-')}"
            product = await add_product(key, variants=[{"sku": sku_code, "cost": price_value}])
            add_inventory(
                product,
                sku_code,
                json.dumps([{"warehouseCode": "WH-INVALID-PRICE", "quantity": 0}]),
            )

        giga_price_overflow = await add_product(
            "giga_price_overflow",
            variants=[{"sku": "R1-GIGA-PRICE-OVERFLOW", "cost": "bad"}],
        )
        add_giga_sku(giga_price_overflow, "R1-GIGA-PRICE-OVERFLOW")
        add_price(giga_price_overflow, "R1-GIGA-PRICE-OVERFLOW", effective_price=1e20)
        add_inventory(
            giga_price_overflow,
            "R1-GIGA-PRICE-OVERFLOW",
            json.dumps([{"warehouseCode": "WH-GIGA-PRICE-OVERFLOW", "quantity": 0}]),
        )

        for key, price_values in (
            (
                "variant_decimal_below_half_fallback",
                {"cost": "0.0000004", "cost_total": "1.25"},
            ),
            ("variant_decimal_half", {"cost": "0.0000005"}),
            (
                "variant_decimal_exact_max",
                {"cost": "99999999999999.999999"},
            ),
            (
                "variant_decimal_round_overflow_fallback",
                {"cost": "99999999999999.9999995", "cost_total": "2.5"},
            ),
            (
                "variant_decimal_nan_fallback",
                {"cost": "NaN", "cost_total": "2.6"},
            ),
            (
                "variant_decimal_infinity_fallback",
                {"cost": "Infinity", "cost_total": "2.7"},
            ),
            (
                "variant_decimal_obvious_overflow_fallback",
                {"cost": "1e20", "cost_total": "2.8"},
            ),
        ):
            sku_code = f"R1-{key.upper().replace('_', '-')}"
            product = await add_product(key, variants=[{"sku": sku_code, **price_values}])
            add_inventory(
                product,
                sku_code,
                json.dumps([{"warehouseCode": "WH-DECIMAL-VARIANT", "quantity": 0}]),
            )

        for key, price_values in (
            (
                "giga_price_float_below_half_fallback",
                {"effective_price": 0.0000004, "discounted_price": 1.5},
            ),
            (
                "giga_price_float_half_fallback",
                {"effective_price": 0.0000005, "discounted_price": 1.6},
            ),
            ("giga_price_float_above_half", {"effective_price": 0.0000006}),
            (
                "giga_price_float_exact_max_fallback",
                {"effective_price": 99999999999999.999999, "discounted_price": 1.7},
            ),
            (
                "giga_price_float_round_overflow_fallback",
                {"effective_price": 99999999999999.9999995, "discounted_price": 1.8},
            ),
            (
                "giga_price_float_obvious_overflow_fallback",
                {"effective_price": 1e20, "discounted_price": 1.9},
            ),
        ):
            sku_code = f"R1-{key.upper().replace('_', '-')}"
            product = await add_product(key, variants=[{"sku": sku_code, "cost": "bad"}])
            add_giga_sku(product, sku_code)
            add_price(product, sku_code, **price_values)
            add_inventory(
                product,
                sku_code,
                json.dumps([{"warehouseCode": "WH-DECIMAL-GIGA", "quantity": 0}]),
            )

        for key, quantity_value in (
            ("quantity_nan", "NaN"),
            ("quantity_infinity", "Infinity"),
            ("quantity_overflow", "100000000000000"),
        ):
            sku_code = f"R1-{key.upper().replace('_', '-')}"
            product = await add_product(key, variants=[])
            add_giga_sku(product, sku_code)
            add_price(product, sku_code, effective_price=9.8)
            add_inventory(
                product,
                sku_code,
                json.dumps([{"warehouseCode": "WH-INVALID-QUANTITY", "quantity": quantity_value}]),
            )

        warehouse_code_zero = await add_product("warehouse_code_zero", variants=[])
        add_giga_sku(warehouse_code_zero, "R1-WAREHOUSE-CODE-ZERO")
        add_price(warehouse_code_zero, "R1-WAREHOUSE-CODE-ZERO", effective_price=9.9)
        add_inventory(
            warehouse_code_zero,
            "R1-WAREHOUSE-CODE-ZERO",
            json.dumps([{"warehouseCode": 0, "quantity": 0}]),
        )

        warehouse_code_ascii_empty = await add_product("warehouse_code_ascii_empty", variants=[])
        add_giga_sku(warehouse_code_ascii_empty, "R1-WAREHOUSE-CODE-ASCII-EMPTY")
        add_price(warehouse_code_ascii_empty, "R1-WAREHOUSE-CODE-ASCII-EMPTY", effective_price=10.0)
        add_inventory(
            warehouse_code_ascii_empty,
            "R1-WAREHOUSE-CODE-ASCII-EMPTY",
            json.dumps([{"warehouseCode": " \t\n\r\f\v ", "quantity": 0}]),
        )

        for key, invalid_code, fallback_code in (
            ("warehouse_code_object_fallback", {"bad": True}, "WH-OBJECT-FALLBACK"),
            ("warehouse_code_array_fallback", ["bad"], "WH-ARRAY-FALLBACK"),
        ):
            sku_code = f"R1-{key.upper().replace('_', '-')}"
            product = await add_product(key, variants=[])
            add_giga_sku(product, sku_code)
            add_price(product, sku_code, effective_price=10.1)
            add_inventory(
                product,
                sku_code,
                json.dumps([
                    {
                        "warehouseCode": invalid_code,
                        "warehouse_code": fallback_code,
                        "quantity": 0,
                    }
                ]),
            )

        warehouse_quantity_fallback = await add_product("warehouse_quantity_fallback", variants=[])
        add_giga_sku(warehouse_quantity_fallback, "R1-WAREHOUSE-QUANTITY-FALLBACK")
        add_price(warehouse_quantity_fallback, "R1-WAREHOUSE-QUANTITY-FALLBACK", effective_price=10.2)
        add_inventory(
            warehouse_quantity_fallback,
            "R1-WAREHOUSE-QUANTITY-FALLBACK",
            json.dumps([{"warehouseCode": "WH-QUANTITY-FALLBACK", "quantity": "NaN", "qty": 0}]),
        )

        pure_variant_exact_duplicate = await add_product(
            "pure_variant_exact_duplicate",
            variants=[
                {"sku": "R1-PURE-EXACT", "cost": 2.2, "title": "Older exact variant"},
                {"sku": "R1-PURE-EXACT", "purchase_price": 7.7, "title": "Newest exact variant"},
            ],
        )
        add_inventory(
            pure_variant_exact_duplicate,
            "R1-PURE-EXACT",
            json.dumps([{"warehouseCode": "WH-PURE-EXACT", "quantity": 0}]),
        )

        pure_variant_ascii_duplicate = await add_product(
            "pure_variant_ascii_duplicate",
            variants=[
                {"sku": " \tR1-PURE-ASCII \v", "cost": 2.3, "title": "Older ASCII variant"},
                {"sku": "R1-PURE-ASCII", "purchase_price": 8.8, "title": "Newest ASCII variant"},
            ],
        )
        add_inventory(
            pure_variant_ascii_duplicate,
            "R1-PURE-ASCII",
            json.dumps([{"warehouseCode": "WH-PURE-ASCII", "quantity": 0}]),
        )

        pagination_tie_time = datetime(2020, 1, 2, 3, 4, 5)
        for index in range(1, 24):
            key = f"pagination_tie_{index:02d}"
            sku_code = f"R1-PAGINATION-TIE-{index:02d}"
            product = await add_product(
                key,
                variants=[{"sku": sku_code, "cost": 5.0}],
                created_at=pagination_tie_time,
                updated_at=pagination_tie_time,
            )
            add_inventory(
                product,
                sku_code,
                json.dumps([{"warehouseCode": "WH-PAGINATION-TIE", "quantity": 0}]),
            )
            pagination_tie_product_ids.append(product.id)

        for key, raw_variants in (
            ("variants_object", json.dumps({"sku": "OBJECT"})),
            ("variants_scalar", json.dumps("SCALAR")),
            ("variants_empty", json.dumps([])),
        ):
            await add_product(key, raw_variants=raw_variants)

        warehouse_cases = {
            "warehouse_invalid": "{bad-json",
            "warehouse_object": json.dumps({"warehouseCode": "WH", "quantity": 1}),
            "warehouse_scalar": json.dumps("WH"),
            "warehouse_empty": json.dumps([]),
            "warehouse_non_object": json.dumps(["WH", 1, None]),
            "warehouse_missing_code": json.dumps([{"quantity": 1}]),
            "warehouse_missing_quantity": json.dumps([{"warehouseCode": "WH"}]),
            "warehouse_bad_quantity": json.dumps([{"warehouseCode": "WH", "quantity": "oops"}]),
        }
        for index, (key, distribution) in enumerate(warehouse_cases.items(), start=1):
            product = await add_product(key, variants=[])
            sku_code = f"R1-WH-{index}"
            add_giga_sku(product, sku_code)
            add_price(product, sku_code, price=9.0)
            add_inventory(product, sku_code, distribution)

        amazon_product = await add_product(
            "amazon",
            status="completed",
            variants=[],
            data_source_id=amazon_source.id,
        )
        amazon_product.current_step = 6

        legacy_code = "R1-LEGACY-MISSING-SOURCE"
        legacy_product = Product(
            gigab2b_url=f"https://example.invalid/{legacy_code}",
            gigab2b_product_id=legacy_code,
            source_data_source_id=None,
            source_site=None,
            source_batch_id=None,
            status="completed",
            current_step=6,
            workflow_node="flow_done",
            workflow_status="succeeded",
        )
        legacy_product.data = ProductData(
            item_code=legacy_code,
            title="R1 legacy product without source mapping",
            variants=json.dumps([], ensure_ascii=False),
        )
        db.add(legacy_product)
        await db.flush()
        product_ids["legacy_missing_source"] = legacy_product.id

        await db.commit()
        return FixtureState(
            tiktok_data_source_id=tiktok_source.id,
            amazon_data_source_id=amazon_source.id,
            product_ids=product_ids,
            tiktok_product_ids=tuple(tiktok_product_ids),
            pagination_tie_product_ids=tuple(pagination_tie_product_ids),
            pagination_tie_timestamp=pagination_tie_time.isoformat(),
        )


async def test_giga_variant_price_fallback_counterexample(environment, state: FixtureState) -> None:
    import httpx
    from sqlalchemy import select

    from app.main import app
    from app.services.tiktok_status import build_tiktok_classification_cte

    product_id = state.product_ids["giga_variant_price_fallback"]
    cte = build_tiktok_classification_cte(product_ids=[product_id])
    async with environment.session_factory() as db:
        row = (await db.execute(select(cte))).mappings().one()
    assert row["channel_status"] == "unsupported", row
    assert row["display_sku_count"] == 1, row
    assert row["missing_price_count"] == 0, row
    assert row["missing_warehouse_count"] == 0, row

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        detail = await client.get(f"/api/tiktok/products/{product_id}")
        assert detail.status_code == 200, detail.text
        detail_payload = detail.json()
        assert detail_payload["status"] == "unsupported", detail_payload
        assert len(detail_payload["skus"]) == 1, detail_payload
        assert detail_payload["skus"][0]["sku_code"] == "R1-GIGA-VARIANT-FALLBACK", detail_payload
        assert detail_payload["skus"][0]["purchase_price"] == 5.5, detail_payload
        assert all(
            sku["sku_code"] != "R1-VARIANT-ONLY-EXCLUDED"
            for sku in detail_payload["skus"]
        ), detail_payload

        unsupported = await client.get(
            "/api/products",
            params={
                "data_source_id": state.tiktok_data_source_id,
                "channel_status": "unsupported",
                "page_size": 100,
            },
        )
        assert unsupported.status_code == 200, unsupported.text
        unsupported_payload = unsupported.json()
        assert unsupported_payload["total"] == len(unsupported_payload["items"]), unsupported_payload
        assert product_id in {int(item["id"]) for item in unsupported_payload["items"]}, unsupported_payload

        overview = await client.get(
            "/api/products/overview",
            params={"data_source_id": state.tiktok_data_source_id},
        )
        assert overview.status_code == 200, overview.text
        assert overview.json()["channel_status_counts"]["unsupported"] == unsupported_payload["total"], (
            overview.json(),
            unsupported_payload,
        )


async def test_legacy_missing_source_defaults_to_amazon(environment, state: FixtureState) -> None:
    import httpx

    from app.main import app

    product_id = state.product_ids["legacy_missing_source"]
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/products", params={"page_size": 100})
    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["items"] if int(item["id"]) == product_id)
    assert item["sales_channel"] == "amazon", item
    assert item["channel_status"] is None, item
    assert item["channel_status_label"] is None, item
    assert item["channel_status_reason"] is None, item
    assert item["channel_capabilities"] is None, item
    assert item["workflow"]["work_status"] == "export_ready", item


async def test_qa_p1_counterexamples(environment, state: FixtureState) -> None:
    failures: list[str] = []
    for name, test_case in (
        ("GigaSku same-SKU variant price fallback", test_giga_variant_price_fallback_counterexample),
        ("legacy missing source defaults to Amazon", test_legacy_missing_source_defaults_to_amazon),
    ):
        try:
            await test_case(environment, state)
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
    assert not failures, "QA P1 counterexamples failed:\n" + "\n".join(failures)


async def test_sku_canonicalization_counterexamples(environment, state: FixtureState) -> None:
    import httpx
    from sqlalchemy import select

    from app.main import app
    from app.services.tiktok_status import build_tiktok_classification_cte

    expected = {
        "case_variant_conflict": {
            "status": "missing_required_info",
            "purchase_price": None,
            "warehouse_count": 1,
            "missing_field": "采购价",
        },
        "exact_duplicate_variant": {
            "status": "unsupported",
            "purchase_price": 7.25,
            "warehouse_count": 1,
            "missing_field": None,
        },
        "wrong_case_gigaprice": {
            "status": "missing_required_info",
            "purchase_price": None,
            "warehouse_count": 1,
            "missing_field": "采购价",
        },
        "wrong_case_inventory": {
            "status": "missing_required_info",
            "purchase_price": 8.0,
            "warehouse_count": 0,
            "missing_field": "分仓库存",
        },
        "trimmed_exact_sku": {
            "status": "unsupported",
            "purchase_price": 8.0,
            "warehouse_count": 1,
            "missing_field": None,
            "sku_code": "R1-TRIM",
        },
        "ascii_tab_giga_variant": {
            "status": "unsupported",
            "purchase_price": 5.1,
            "warehouse_count": 1,
            "missing_field": None,
            "sku_code": "R1-ASCII-TAB",
        },
        "ascii_lf_variant_fallback": {
            "status": "unsupported",
            "purchase_price": 6.1,
            "warehouse_count": 1,
            "missing_field": None,
            "sku_code": "R1-ASCII-LF",
        },
        "ascii_cr_gigaprice": {
            "status": "unsupported",
            "purchase_price": 7.1,
            "warehouse_count": 1,
            "missing_field": None,
            "sku_code": "R1-ASCII-CR",
        },
        "ascii_ff_inventory": {
            "status": "unsupported",
            "purchase_price": 8.1,
            "warehouse_count": 1,
            "missing_field": None,
            "sku_code": "R1-ASCII-FF",
        },
        "ascii_vt_variant": {
            "status": "unsupported",
            "purchase_price": 9.1,
            "warehouse_count": 1,
            "missing_field": None,
            "sku_code": "R1-ASCII-VT",
        },
        "ascii_mixed_facts": {
            "status": "unsupported",
            "purchase_price": 12.1,
            "warehouse_count": 1,
            "missing_field": None,
            "sku_code": "R1-ASCII-MIXED",
        },
    }
    product_ids = [state.product_ids[key] for key in expected]
    cte = build_tiktok_classification_cte(product_ids=product_ids)
    async with environment.session_factory() as db:
        rows = (await db.execute(select(cte))).mappings().all()
    cte_by_id = {int(row["product_id"]): dict(row) for row in rows}

    failures: list[str] = []
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for key, expectation in expected.items():
            product_id = state.product_ids[key]
            cte_row = cte_by_id[product_id]
            if cte_row["channel_status"] != expectation["status"]:
                failures.append(f"{key} CTE status: {cte_row}")
            if cte_row["display_sku_count"] != 1:
                failures.append(f"{key} display count: {cte_row}")

            detail = await client.get(f"/api/tiktok/products/{product_id}")
            if detail.status_code != 200:
                failures.append(f"{key} detail HTTP {detail.status_code}: {detail.text}")
                continue
            detail_payload = detail.json()
            if detail_payload["status"] != expectation["status"]:
                failures.append(f"{key} detail status: {detail_payload}")
            if len(detail_payload["skus"]) != 1:
                failures.append(f"{key} detail SKU count: {detail_payload}")
                continue
            sku = detail_payload["skus"][0]
            expected_sku_code = expectation.get("sku_code")
            if expected_sku_code and sku["sku_code"] != expected_sku_code:
                failures.append(f"{key} normalized SKU: {detail_payload}")
            if sku["purchase_price"] != expectation["purchase_price"]:
                failures.append(f"{key} detail price: {detail_payload}")
            if len(sku["warehouse_inventory"]) != expectation["warehouse_count"]:
                failures.append(f"{key} detail inventory: {detail_payload}")
            missing_field = expectation["missing_field"]
            if missing_field and missing_field not in sku["missing_fields"]:
                failures.append(f"{key} missing fields: {detail_payload}")
            if missing_field is None and sku["missing_fields"]:
                failures.append(f"{key} unexpected missing fields: {detail_payload}")

        unfiltered = await client.get(
            "/api/products",
            params={"data_source_id": state.tiktok_data_source_id, "page_size": 100},
        )
        unfiltered_payload = unfiltered.json()
        items_by_id = {int(item["id"]): item for item in unfiltered_payload["items"]}
        for key, expectation in expected.items():
            item = items_by_id[state.product_ids[key]]
            if item["channel_status"] != expectation["status"]:
                failures.append(f"{key} list status: {item}")

        missing_items = [
            item for item in unfiltered_payload["items"]
            if item["channel_status"] == "missing_required_info"
        ]
        filtered = await client.get(
            "/api/products",
            params={
                "data_source_id": state.tiktok_data_source_id,
                "channel_status": "missing_required_info",
                "page_size": 100,
            },
        )
        filtered_payload = filtered.json()
        if filtered_payload["total"] != len(missing_items):
            failures.append(f"missing filter total: {filtered_payload}")

        overview = await client.get(
            "/api/products/overview",
            params={"data_source_id": state.tiktok_data_source_id},
        )
        overview_payload = overview.json()
        if overview_payload["channel_status_counts"]["missing_required_info"] != len(missing_items):
            failures.append(f"missing overview count: {overview_payload}")

    assert not failures, "SKU canonicalization counterexamples failed:\n" + "\n".join(failures)


async def test_canonical_collision_counterexamples(environment, state: FixtureState) -> None:
    import httpx
    from sqlalchemy import select

    from app.main import app
    from app.services.tiktok_status import build_tiktok_classification_cte

    expected = {
        "collision_inventory_exact_valid": {
            "status": "unsupported",
            "purchase_price": 5.2,
            "warehouse_count": 1,
            "quantity": 0,
        },
        "collision_inventory_exact_invalid": {
            "status": "missing_required_info",
            "purchase_price": 5.3,
            "warehouse_count": 0,
        },
        "collision_price_exact_valid": {
            "status": "unsupported",
            "purchase_price": 13.2,
            "warehouse_count": 1,
        },
        "collision_price_exact_invalid": {
            "status": "missing_required_info",
            "purchase_price": None,
            "warehouse_count": 1,
        },
        "collision_gigasku_exact": {
            "status": "unsupported",
            "purchase_price": 6.2,
            "warehouse_count": 1,
            "title": "Exact GigaSku Winner",
        },
        "collision_gigasku_latest": {
            "status": "unsupported",
            "purchase_price": 6.3,
            "warehouse_count": 1,
            "title": "Newest Noncanonical GigaSku Winner",
        },
        "empty_gigasku_fallback": {
            "status": "unsupported",
            "purchase_price": 6.4,
            "warehouse_count": 1,
            "sku_code": "R1-EMPTY-GIGA-FALLBACK",
        },
    }
    product_ids = [state.product_ids[key] for key in expected]
    cte = build_tiktok_classification_cte(product_ids=product_ids)
    async with environment.session_factory() as db:
        rows = (await db.execute(select(cte))).mappings().all()
    cte_by_id = {int(row["product_id"]): dict(row) for row in rows}

    failures: list[str] = []
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for key, expectation in expected.items():
            product_id = state.product_ids[key]
            cte_row = cte_by_id[product_id]
            if cte_row["channel_status"] != expectation["status"]:
                failures.append(f"{key} CTE status: {cte_row}")
            if cte_row["display_sku_count"] != 1:
                failures.append(f"{key} CTE display count: {cte_row}")

            detail = await client.get(f"/api/tiktok/products/{product_id}")
            if detail.status_code != 200:
                failures.append(f"{key} detail HTTP {detail.status_code}: {detail.text}")
                continue
            payload = detail.json()
            if payload["status"] != expectation["status"]:
                failures.append(f"{key} detail status: {payload}")
            if len(payload["skus"]) != 1:
                failures.append(f"{key} detail SKU count: {payload}")
                continue
            sku = payload["skus"][0]
            if sku["purchase_price"] != expectation["purchase_price"]:
                failures.append(f"{key} detail price: {payload}")
            if len(sku["warehouse_inventory"]) != expectation["warehouse_count"]:
                failures.append(f"{key} detail inventory: {payload}")
            if "quantity" in expectation and sku["warehouse_inventory"]:
                if sku["warehouse_inventory"][0]["quantity"] != expectation["quantity"]:
                    failures.append(f"{key} detail quantity: {payload}")
            if expectation.get("title") and sku["title"] != expectation["title"]:
                failures.append(f"{key} detail winner title: {payload}")
            if expectation.get("sku_code") and sku["sku_code"] != expectation["sku_code"]:
                failures.append(f"{key} detail fallback SKU: {payload}")

        unfiltered = await client.get(
            "/api/products",
            params={"data_source_id": state.tiktok_data_source_id, "page_size": 100},
        )
        items = unfiltered.json()["items"]
        items_by_id = {int(item["id"]): item for item in items}
        for key, expectation in expected.items():
            item = items_by_id[state.product_ids[key]]
            if item["channel_status"] != expectation["status"]:
                failures.append(f"{key} list status: {item}")

        for status in ("missing_required_info", "unsupported"):
            expected_total = sum(item["channel_status"] == status for item in items)
            filtered = await client.get(
                "/api/products",
                params={
                    "data_source_id": state.tiktok_data_source_id,
                    "channel_status": status,
                    "page_size": 100,
                },
            )
            if filtered.json()["total"] != expected_total:
                failures.append(f"{status} collision filter total: {filtered.json()}")
            overview = await client.get(
                "/api/products/overview",
                params={"data_source_id": state.tiktok_data_source_id},
            )
            if overview.json()["channel_status_counts"][status] != expected_total:
                failures.append(f"{status} collision overview count: {overview.json()}")

    assert not failures, "canonical collision counterexamples failed:\n" + "\n".join(failures)


async def test_source_key_decision_counterexamples(environment, state: FixtureState) -> None:
    import httpx
    from sqlalchemy import select

    from app.main import app
    from app.services.tiktok_status import build_tiktok_classification_cte

    expected = {
        "source_keys_spaced": "unsupported",
        "source_site_empty_fallback": "unsupported",
        "source_site_null_fallback": "unsupported",
        "item_code_empty_fallback": "unsupported",
        "item_code_null_fallback": "unsupported",
        "batch_empty_variants_only": "missing_required_info",
        "batch_null_variants_only": "missing_required_info",
        "batch_control_lookup": "unsupported",
    }
    cte = build_tiktok_classification_cte(
        product_ids=[state.product_ids[key] for key in expected],
    )
    async with environment.session_factory() as db:
        cte_rows = (await db.execute(select(cte))).mappings().all()
        missing_source_cte = build_tiktok_classification_cte(
            product_ids=[state.product_ids["legacy_missing_source"]],
        )
        missing_source_rows = (await db.execute(select(missing_source_cte))).mappings().all()
    cte_by_id = {int(row["product_id"]): dict(row) for row in cte_rows}

    failures: list[str] = []
    if missing_source_rows:
        failures.append(f"missing source_data_source_id must not classify: {missing_source_rows}")

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unfiltered = await client.get(
            "/api/products",
            params={"data_source_id": state.tiktok_data_source_id, "page_size": 100},
        )
        items = unfiltered.json()["items"]
        items_by_id = {int(item["id"]): item for item in items}

        for key, status in expected.items():
            product_id = state.product_ids[key]
            cte_row = cte_by_id.get(product_id)
            if not cte_row or cte_row["channel_status"] != status:
                failures.append(f"{key} CTE status: {cte_row}")
            item = items_by_id.get(product_id)
            if not item or item["channel_status"] != status:
                failures.append(f"{key} list status: {item}")

            detail = await client.get(f"/api/tiktok/products/{product_id}")
            if detail.status_code != 200:
                failures.append(f"{key} detail HTTP {detail.status_code}: {detail.text}")
                continue
            payload = detail.json()
            if payload["status"] != status:
                failures.append(f"{key} detail status: {payload}")
            if status == "unsupported" and not payload["skus"]:
                failures.append(f"{key} must not expose unsupported with empty skus: {payload}")

            if key == "source_keys_spaced":
                if payload["source_site"] != " US " or payload["item_code"] != " ITEM ":
                    failures.append(f"{key} raw source keys: {payload}")
                if len(payload["skus"]) != 1 or payload["skus"][0]["purchase_price"] != 8.2:
                    failures.append(f"{key} source lookup result: {payload}")
            elif key.startswith("source_site_") and payload["source_site"] != "US":
                failures.append(f"{key} site fallback: {payload}")
            elif key.startswith("item_code_"):
                expected_item_code = f"R1-TK-{key.upper().replace('_', '-')}"
                if payload["item_code"] != expected_item_code:
                    failures.append(f"{key} item fallback: {payload}")
            elif key == "batch_empty_variants_only":
                if payload["source_batch_id"] != "":
                    failures.append(f"{key} batch response: {payload}")
                if [sku["sku_code"] for sku in payload["skus"]] != ["R1-BATCH-EMPTY-VARIANT"]:
                    failures.append(f"{key} variants-only source: {payload}")
                elif payload["skus"][0]["purchase_price"] != 5.4 or payload["skus"][0]["warehouse_inventory"]:
                    failures.append(f"{key} lookup must be disabled: {payload}")
            elif key == "batch_null_variants_only":
                if payload["source_batch_id"] is not None:
                    failures.append(f"{key} batch response: {payload}")
                if [sku["sku_code"] for sku in payload["skus"]] != ["R1-BATCH-NULL-VARIANT"]:
                    failures.append(f"{key} variants-only source: {payload}")
                elif payload["skus"][0]["purchase_price"] != 5.5 or payload["skus"][0]["warehouse_inventory"]:
                    failures.append(f"{key} lookup must be disabled: {payload}")

        missing_source_detail = await client.get(
            f"/api/tiktok/products/{state.product_ids['legacy_missing_source']}",
        )
        if missing_source_detail.status_code != 400:
            failures.append(
                f"missing source_data_source_id detail must reject: "
                f"{missing_source_detail.status_code} {missing_source_detail.text}"
            )

        overview = await client.get(
            "/api/products/overview",
            params={"data_source_id": state.tiktok_data_source_id},
        )
        overview_counts = overview.json()["channel_status_counts"]
        for status in set(expected.values()):
            expected_total = sum(item["channel_status"] == status for item in items)
            filtered = await client.get(
                "/api/products",
                params={
                    "data_source_id": state.tiktok_data_source_id,
                    "channel_status": status,
                    "page_size": 100,
                },
            )
            if filtered.json()["total"] != expected_total:
                failures.append(f"{status} source-key filter total: {filtered.json()}")
            if overview_counts[status] != expected_total:
                failures.append(f"{status} source-key overview count: {overview.json()}")

    assert not failures, "source-key decision counterexamples failed:\n" + "\n".join(failures)


async def test_invalid_number_and_warehouse_counterexamples(environment, state: FixtureState) -> None:
    import httpx
    from sqlalchemy import select

    from app.main import app
    from app.services.tiktok_status import build_tiktok_classification_cte

    expected = {
        "invalid_json_nan_constant": "draft",
        "invalid_json_infinity_constant": "draft",
        "variant_price_nan": "missing_required_info",
        "variant_price_infinity": "missing_required_info",
        "variant_price_overflow": "missing_required_info",
        "giga_price_overflow": "missing_required_info",
        "quantity_nan": "missing_required_info",
        "quantity_infinity": "missing_required_info",
        "quantity_overflow": "missing_required_info",
        "warehouse_code_zero": "unsupported",
        "warehouse_code_ascii_empty": "missing_required_info",
        "warehouse_code_object_fallback": "unsupported",
        "warehouse_code_array_fallback": "unsupported",
        "warehouse_quantity_fallback": "unsupported",
    }
    cte = build_tiktok_classification_cte(
        product_ids=[state.product_ids[key] for key in expected],
    )
    async with environment.session_factory() as db:
        cte_rows = (await db.execute(select(cte))).mappings().all()
    cte_by_id = {int(row["product_id"]): dict(row) for row in cte_rows}

    failures: list[str] = []
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unfiltered = await client.get(
            "/api/products",
            params={"data_source_id": state.tiktok_data_source_id, "page_size": 100},
        )
        items = unfiltered.json()["items"]
        items_by_id = {int(item["id"]): item for item in items}

        for key, status in expected.items():
            product_id = state.product_ids[key]
            cte_row = cte_by_id[product_id]
            if cte_row["channel_status"] != status:
                failures.append(f"{key} CTE status: {cte_row}")
            item = items_by_id.get(product_id)
            if not item or item["channel_status"] != status:
                failures.append(f"{key} list status: {item}")

            detail = await client.get(f"/api/tiktok/products/{product_id}")
            if detail.status_code != 200:
                failures.append(f"{key} detail HTTP {detail.status_code}: {detail.text}")
                continue
            payload = detail.json()
            if payload["status"] != status:
                failures.append(f"{key} detail status: {payload}")
            if key.startswith("invalid_json_"):
                if payload["skus"]:
                    failures.append(f"{key} invalid JSON must fail closed: {payload}")
                continue
            if len(payload["skus"]) != 1:
                failures.append(f"{key} detail SKU count: {payload}")
                continue
            sku = payload["skus"][0]
            if key.startswith("variant_price_") or key == "giga_price_overflow":
                if sku["purchase_price"] is not None or "采购价" not in sku["missing_fields"]:
                    failures.append(f"{key} invalid price must be missing: {payload}")
            elif key.startswith("quantity_") or key == "warehouse_code_ascii_empty":
                if sku["warehouse_inventory"] or "分仓库存" not in sku["missing_fields"]:
                    failures.append(f"{key} invalid warehouse must be missing: {payload}")
            elif key == "warehouse_code_zero":
                if sku["warehouse_inventory"] != [{"warehouse_code": "0", "quantity": 0}]:
                    failures.append(f"{key} scalar zero code: {payload}")
            elif key == "warehouse_code_object_fallback":
                if sku["warehouse_inventory"] != [{"warehouse_code": "WH-OBJECT-FALLBACK", "quantity": 0}]:
                    failures.append(f"{key} object fallback: {payload}")
            elif key == "warehouse_code_array_fallback":
                if sku["warehouse_inventory"] != [{"warehouse_code": "WH-ARRAY-FALLBACK", "quantity": 0}]:
                    failures.append(f"{key} array fallback: {payload}")
            elif key == "warehouse_quantity_fallback":
                if sku["warehouse_inventory"] != [{"warehouse_code": "WH-QUANTITY-FALLBACK", "quantity": 0}]:
                    failures.append(f"{key} quantity fallback: {payload}")

        overview = await client.get(
            "/api/products/overview",
            params={"data_source_id": state.tiktok_data_source_id},
        )
        overview_counts = overview.json()["channel_status_counts"]
        for status in set(expected.values()):
            expected_total = sum(item["channel_status"] == status for item in items)
            filtered = await client.get(
                "/api/products",
                params={
                    "data_source_id": state.tiktok_data_source_id,
                    "channel_status": status,
                    "page_size": 100,
                },
            )
            if filtered.json()["total"] != expected_total:
                failures.append(f"{status} invalid-data filter total: {filtered.json()}")
            if overview_counts[status] != expected_total:
                failures.append(f"{status} invalid-data overview count: {overview.json()}")

    assert not failures, "invalid number/warehouse counterexamples failed:\n" + "\n".join(failures)


async def test_decimal_price_counterexamples(environment, state: FixtureState) -> None:
    import httpx
    from sqlalchemy import select

    from app.main import app
    from app.services.tiktok_status import (
        MYSQL_DECIMAL_20_6_MAX,
        build_tiktok_classification_cte,
        parse_mysql_decimal_20_6,
    )

    parser_cases = (
        ("below half", "0.0000004", Decimal("0.000000")),
        ("half up", "0.0000005", Decimal("0.000001")),
        ("exact max", "99999999999999.999999", MYSQL_DECIMAL_20_6_MAX),
        ("round overflow", "99999999999999.9999995", None),
        ("NaN", "NaN", None),
        ("Infinity", "Infinity", None),
        ("obvious overflow", "1e20", None),
    )
    expected = {
        "variant_decimal_below_half_fallback": Decimal("1.25"),
        "variant_decimal_half": Decimal("0.000001"),
        "variant_decimal_exact_max": Decimal("99999999999999.999999"),
        "variant_decimal_round_overflow_fallback": Decimal("2.5"),
        "variant_decimal_nan_fallback": Decimal("2.6"),
        "variant_decimal_infinity_fallback": Decimal("2.7"),
        "variant_decimal_obvious_overflow_fallback": Decimal("2.8"),
        "giga_price_float_below_half_fallback": Decimal("1.5"),
        "giga_price_float_half_fallback": Decimal("1.6"),
        "giga_price_float_above_half": Decimal("0.000001"),
        "giga_price_float_exact_max_fallback": Decimal("1.7"),
        "giga_price_float_round_overflow_fallback": Decimal("1.8"),
        "giga_price_float_obvious_overflow_fallback": Decimal("1.9"),
    }
    cte = build_tiktok_classification_cte(
        product_ids=[state.product_ids[key] for key in expected],
    )
    async with environment.session_factory() as db:
        cte_rows = (await db.execute(select(cte))).mappings().all()
    cte_by_id = {int(row["product_id"]): dict(row) for row in cte_rows}

    failures: list[str] = []
    for label, raw_value, expected_value in parser_cases:
        actual = parse_mysql_decimal_20_6(raw_value)
        if actual != expected_value:
            failures.append(f"parser {label}: expected {expected_value!r}, got {actual!r}")

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unfiltered = await client.get(
            "/api/products",
            params={"data_source_id": state.tiktok_data_source_id, "page_size": 100},
        )
        items_by_id = {int(item["id"]): item for item in unfiltered.json()["items"]}
        for key, expected_purchase_price in expected.items():
            product_id = state.product_ids[key]
            cte_row = cte_by_id[product_id]
            if cte_row["channel_status"] != "unsupported":
                failures.append(f"{key} CTE status: {cte_row}")
            if cte_row["missing_price_count"] != 0:
                failures.append(f"{key} CTE missing price: {cte_row}")
            item = items_by_id.get(product_id)
            if not item or item["channel_status"] != "unsupported":
                failures.append(f"{key} list status: {item}")

            detail = await client.get(f"/api/tiktok/products/{product_id}")
            if detail.status_code != 200:
                failures.append(f"{key} detail HTTP {detail.status_code}: {detail.text}")
                continue
            payload = detail.json()
            if payload["status"] != "unsupported" or len(payload["skus"]) != 1:
                failures.append(f"{key} detail status/SKU: {payload}")
                continue
            sku = payload["skus"][0]
            if sku["purchase_price"] != float(expected_purchase_price):
                failures.append(f"{key} detail purchase price: {payload}")
            if "采购价" in sku["missing_fields"]:
                failures.append(f"{key} unexpected missing purchase price: {payload}")
            expected_tiktok_price = float(
                ((expected_purchase_price + Decimal("70")) * Decimal("2.4")).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
            )
            if sku["tiktok_price"] != expected_tiktok_price:
                failures.append(
                    f"{key} TikTok price: expected {expected_tiktok_price}, got {payload}"
                )

    assert not failures, "DECIMAL purchase-price counterexamples failed:\n" + "\n".join(failures)


async def test_pure_variant_winner_counterexamples(environment, state: FixtureState) -> None:
    import httpx
    from sqlalchemy import select

    from app.main import app
    from app.services.tiktok_status import build_tiktok_classification_cte

    expected = {
        "pure_variant_exact_duplicate": {
            "sku_code": "R1-PURE-EXACT",
            "purchase_price": 7.7,
            "title": "Newest exact variant",
        },
        "pure_variant_ascii_duplicate": {
            "sku_code": "R1-PURE-ASCII",
            "purchase_price": 8.8,
            "title": "Newest ASCII variant",
        },
    }
    cte = build_tiktok_classification_cte(
        product_ids=[state.product_ids[key] for key in expected],
    )
    async with environment.session_factory() as db:
        cte_rows = (await db.execute(select(cte))).mappings().all()
    cte_by_id = {int(row["product_id"]): dict(row) for row in cte_rows}

    failures: list[str] = []
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unfiltered = await client.get(
            "/api/products",
            params={"data_source_id": state.tiktok_data_source_id, "page_size": 100},
        )
        items = unfiltered.json()["items"]
        items_by_id = {int(item["id"]): item for item in items}
        for key, expectation in expected.items():
            product_id = state.product_ids[key]
            cte_row = cte_by_id[product_id]
            if cte_row["channel_status"] != "unsupported" or cte_row["display_sku_count"] != 1:
                failures.append(f"{key} CTE canonical winner: {cte_row}")
            item = items_by_id.get(product_id)
            if not item or item["channel_status"] != "unsupported":
                failures.append(f"{key} list status: {item}")

            detail = await client.get(f"/api/tiktok/products/{product_id}")
            if detail.status_code != 200:
                failures.append(f"{key} detail HTTP {detail.status_code}: {detail.text}")
                continue
            payload = detail.json()
            if payload["status"] != "unsupported" or len(payload["skus"]) != 1:
                failures.append(f"{key} detail canonical winner: {payload}")
                continue
            sku = payload["skus"][0]
            for field in ("sku_code", "purchase_price", "title"):
                if sku[field] != expectation[field]:
                    failures.append(f"{key} last ordinal {field}: {payload}")

        unsupported_total = sum(item["channel_status"] == "unsupported" for item in items)
        filtered = await client.get(
            "/api/products",
            params={
                "data_source_id": state.tiktok_data_source_id,
                "channel_status": "unsupported",
                "page_size": 100,
            },
        )
        if filtered.json()["total"] != unsupported_total:
            failures.append(f"pure variant filter total: {filtered.json()}")
        overview = await client.get(
            "/api/products/overview",
            params={"data_source_id": state.tiktok_data_source_id},
        )
        if overview.json()["channel_status_counts"]["unsupported"] != unsupported_total:
            failures.append(f"pure variant overview count: {overview.json()}")

    assert not failures, "pure variant winner counterexamples failed:\n" + "\n".join(failures)


async def test_stable_product_pagination_counterexample(environment, state: FixtureState) -> None:
    import httpx

    from app.main import app

    expected_ids = sorted(state.pagination_tie_product_ids, reverse=True)
    failures: list[str] = []
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        observed_runs: list[list[int]] = []
        for run_index in range(2):
            observed_ids: list[int] = []
            page = 1
            while len(observed_ids) < len(expected_ids):
                response = await client.get(
                    "/api/products",
                    params={
                        "data_source_id": state.tiktok_data_source_id,
                        "created_from": state.pagination_tie_timestamp,
                        "created_to": state.pagination_tie_timestamp,
                        "page": page,
                        "page_size": 7,
                    },
                )
                if response.status_code != 200:
                    failures.append(
                        f"pagination run {run_index + 1} page {page} HTTP "
                        f"{response.status_code}: {response.text}"
                    )
                    break
                payload = response.json()
                if payload["total"] != len(expected_ids):
                    failures.append(f"pagination total: {payload}")
                    break
                page_ids = [int(item["id"]) for item in payload["items"]]
                if any(item["channel_status"] != "unsupported" for item in payload["items"]):
                    failures.append(f"pagination channel status: {payload}")
                if len(page_ids) != len(set(page_ids)):
                    failures.append(f"pagination duplicates within page {page}: {page_ids}")
                observed_ids.extend(page_ids)
                if not page_ids:
                    break
                page += 1
            observed_runs.append(observed_ids)

        for run_index, observed_ids in enumerate(observed_runs, start=1):
            if len(observed_ids) != len(set(observed_ids)):
                failures.append(f"pagination run {run_index} duplicate IDs: {observed_ids}")
            if set(observed_ids) != set(expected_ids):
                failures.append(f"pagination run {run_index} missing/extra IDs: {observed_ids}")
            if observed_ids != expected_ids:
                failures.append(
                    f"pagination run {run_index} unstable order: "
                    f"expected {expected_ids}, got {observed_ids}"
                )
        if len(observed_runs) == 2 and observed_runs[0] != observed_runs[1]:
            failures.append(f"pagination repeated runs differ: {observed_runs}")

    assert not failures, "stable product pagination counterexample failed:\n" + "\n".join(failures)


async def test_mirror_review_counterexamples(environment, state: FixtureState) -> None:
    failures: list[str] = []
    for name, test_case in (
        ("source-key decision", test_source_key_decision_counterexamples),
        ("invalid number/warehouse", test_invalid_number_and_warehouse_counterexamples),
        ("DECIMAL purchase prices", test_decimal_price_counterexamples),
        ("pure variant winners", test_pure_variant_winner_counterexamples),
        ("stable product pagination", test_stable_product_pagination_counterexample),
    ):
        try:
            await test_case(environment, state)
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
    assert not failures, "mirror review counterexamples failed:\n" + "\n".join(failures)


async def test_cte_classification(environment, state: FixtureState) -> None:
    from sqlalchemy import select

    from app.services.tiktok_status import build_tiktok_classification_cte

    cte = build_tiktok_classification_cte(data_source_id=state.tiktok_data_source_id)
    async with environment.session_factory() as db:
        rows = (await db.execute(select(cte))).mappings().all()
    by_id = {int(row["product_id"]): dict(row) for row in rows}

    expected = {
        "failed": "failed",
        "draft": "draft",
        "missing_required_info": "missing_required_info",
        "unsupported": "unsupported",
        "variant_gigaprice": "unsupported",
        "variant_sku_fallback": "unsupported",
        "malformed_variant_price": "missing_required_info",
        "giga_excludes_variants": "unsupported",
        "giga_variant_price_fallback": "unsupported",
        "case_variant_conflict": "missing_required_info",
        "exact_duplicate_variant": "unsupported",
        "wrong_case_gigaprice": "missing_required_info",
        "wrong_case_inventory": "missing_required_info",
        "trimmed_exact_sku": "unsupported",
        "ascii_tab_giga_variant": "unsupported",
        "ascii_lf_variant_fallback": "unsupported",
        "ascii_cr_gigaprice": "unsupported",
        "ascii_ff_inventory": "unsupported",
        "ascii_vt_variant": "unsupported",
        "ascii_mixed_facts": "unsupported",
        "collision_inventory_exact_valid": "unsupported",
        "collision_inventory_exact_invalid": "missing_required_info",
        "collision_price_exact_valid": "unsupported",
        "collision_price_exact_invalid": "missing_required_info",
        "collision_gigasku_exact": "unsupported",
        "collision_gigasku_latest": "unsupported",
        "empty_gigasku_fallback": "unsupported",
        "variants_object": "draft",
        "variants_scalar": "draft",
        "variants_empty": "draft",
        "warehouse_invalid": "missing_required_info",
        "warehouse_object": "missing_required_info",
        "warehouse_scalar": "missing_required_info",
        "warehouse_empty": "missing_required_info",
        "warehouse_non_object": "missing_required_info",
        "warehouse_missing_code": "missing_required_info",
        "warehouse_missing_quantity": "missing_required_info",
        "warehouse_bad_quantity": "missing_required_info",
    }
    for key, status in expected.items():
        row = by_id[state.product_ids[key]]
        assert row["channel_status"] == status, (key, row)
        assert row["sales_channel"] == "tiktok", (key, row)

    assert by_id[state.product_ids["failed"]]["display_sku_count"] == 0
    assert by_id[state.product_ids["draft"]]["display_sku_count"] == 0
    assert by_id[state.product_ids["giga_excludes_variants"]]["display_sku_count"] == 1
    assert by_id[state.product_ids["giga_variant_price_fallback"]]["display_sku_count"] == 1
    assert by_id[state.product_ids["unsupported"]]["missing_price_count"] == 0
    assert by_id[state.product_ids["unsupported"]]["missing_warehouse_count"] == 0

    one_cte = build_tiktok_classification_cte(product_ids=[state.product_ids["unsupported"]])
    async with environment.session_factory() as db:
        one_rows = (await db.execute(select(one_cte))).mappings().all()
    assert [int(row["product_id"]) for row in one_rows] == [state.product_ids["unsupported"]]


async def test_real_asgi_api(environment, state: FixtureState) -> None:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 41340))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unfiltered = await client.get(
            "/api/products",
            params={"data_source_id": state.tiktok_data_source_id, "page_size": 100},
        )
        assert unfiltered.status_code == 200, unfiltered.text
        payload = unfiltered.json()
        items_by_id = {int(item["id"]): item for item in payload["items"]}
        assert payload["total"] == len(state.tiktok_product_ids), payload
        assert set(items_by_id) == set(state.tiktok_product_ids), payload

        expected_main = {
            "failed": "failed",
            "draft": "draft",
            "missing_required_info": "missing_required_info",
            "unsupported": "unsupported",
        }
        for key, expected_status in expected_main.items():
            product_id = state.product_ids[key]
            item = items_by_id[product_id]
            assert item["sales_channel"] == "tiktok", item
            assert item["channel_status"] == expected_status, item
            assert item["channel_capabilities"] == {
                "export_supported": False,
                "publish_supported": False,
            }, item

            detail = await client.get(f"/api/tiktok/products/{product_id}")
            assert detail.status_code == 200, detail.text
            detail_payload = detail.json()
            assert detail_payload["status"] == expected_status, (key, detail_payload)

        unsupported_item = items_by_id[state.product_ids["unsupported"]]
        assert unsupported_item["channel_status_label"] == "资料已齐 · 导出暂未接入", unsupported_item
        assert unsupported_item["channel_status_reason"] == "TikTok 导出/发布尚未接入", unsupported_item
        unsupported_detail = await client.get(f"/api/tiktok/products/{state.product_ids['unsupported']}")
        assert unsupported_detail.json()["skus"][0]["purchase_price"] == 12.5, unsupported_detail.json()
        assert unsupported_detail.json()["skus"][0]["warehouse_inventory"][0]["quantity"] == 0

        variant_detail = await client.get(f"/api/tiktok/products/{state.product_ids['variant_gigaprice']}")
        assert variant_detail.status_code == 200, variant_detail.text
        assert variant_detail.json()["status"] == "unsupported", variant_detail.json()
        assert variant_detail.json()["skus"][0]["purchase_price"] == 6.25, variant_detail.json()

        malformed_detail = await client.get(f"/api/tiktok/products/{state.product_ids['malformed_variant_price']}")
        assert malformed_detail.status_code == 200, malformed_detail.text
        assert malformed_detail.json()["status"] == "missing_required_info", malformed_detail.json()

        for key in (
            "variants_object",
            "variants_scalar",
            "variants_empty",
            "warehouse_invalid",
            "warehouse_object",
            "warehouse_scalar",
            "warehouse_empty",
            "warehouse_non_object",
            "warehouse_missing_code",
            "warehouse_missing_quantity",
            "warehouse_bad_quantity",
        ):
            response = await client.get(f"/api/tiktok/products/{state.product_ids[key]}")
            assert response.status_code == 200, (key, response.text)
            assert response.json()["status"] == items_by_id[state.product_ids[key]]["channel_status"], (
                key,
                response.json(),
                items_by_id[state.product_ids[key]],
            )
            if key.startswith("warehouse_"):
                assert response.json()["skus"][0]["warehouse_inventory"] == [], (key, response.json())
                assert "分仓库存" in response.json()["skus"][0]["missing_fields"], (key, response.json())

        for status in CHANNEL_STATUSES:
            first_page = await client.get(
                "/api/products",
                params={
                    "data_source_id": state.tiktok_data_source_id,
                    "channel_status": status,
                    "page": 1,
                    "page_size": 1,
                },
            )
            assert first_page.status_code == 200, first_page.text
            first_payload = first_page.json()
            assert first_payload["total"] >= 1, (status, first_payload)
            assert len(first_payload["items"]) == 1, (status, first_payload)
            assert first_payload["items"][0]["channel_status"] == status, (status, first_payload)
            if first_payload["total"] > 1:
                second_page = await client.get(
                    "/api/products",
                    params={
                        "data_source_id": state.tiktok_data_source_id,
                        "channel_status": status,
                        "page": 2,
                        "page_size": 1,
                    },
                )
                assert second_page.status_code == 200, second_page.text
                assert second_page.json()["total"] == first_payload["total"], (status, second_page.json())
                assert second_page.json()["items"][0]["channel_status"] == status, (status, second_page.json())

        overview = await client.get(
            "/api/products/overview",
            params={"data_source_id": state.tiktok_data_source_id},
        )
        assert overview.status_code == 200, overview.text
        overview_payload = overview.json()
        expected_counts = {status: 0 for status in CHANNEL_STATUSES}
        for item in payload["items"]:
            expected_counts[item["channel_status"]] += 1
        assert overview_payload["channel_status_counts"] == expected_counts, overview_payload
        assert overview_payload["total_products"] == sum(expected_counts.values()), overview_payload

        bad_queries = (
            {"channel_status": "unsupported"},
            {"channel_status": "unsupported", "data_source_id": 99999999},
            {"channel_status": "unsupported", "data_source_id": state.amazon_data_source_id},
            {
                "channel_status": "unsupported",
                "data_source_id": state.tiktok_data_source_id,
                "work_status": "failed",
            },
        )
        for params in bad_queries:
            response = await client.get("/api/products", params=params)
            assert response.status_code == 400, (params, response.status_code, response.text)

        mixed = await client.get("/api/products", params={"page_size": 100})
        assert mixed.status_code == 200, mixed.text
        for item in mixed.json()["items"]:
            assert item["channel_status"] is None, item
            assert item["channel_status_label"] is None, item
            assert item["channel_status_reason"] is None, item
            assert item["channel_capabilities"] is None, item

        amazon = await client.get(
            "/api/products",
            params={"data_source_id": state.amazon_data_source_id, "page_size": 100},
        )
        assert amazon.status_code == 200, amazon.text
        assert amazon.json()["items"][0]["sales_channel"] == "amazon", amazon.json()
        assert amazon.json()["items"][0]["channel_status"] is None, amazon.json()
        assert amazon.json()["items"][0]["channel_capabilities"] is None, amazon.json()


async def run() -> None:
    test_contract_files()
    async with isolated_r1_mysql(ROOT) as environment:
        state = await _seed_fixtures(environment)
        await test_qa_p1_counterexamples(environment, state)
        await test_sku_canonicalization_counterexamples(environment, state)
        await test_canonical_collision_counterexamples(environment, state)
        await test_mirror_review_counterexamples(environment, state)
        await test_cte_classification(environment, state)
        await test_real_asgi_api(environment, state)
        print(f"R1 TikTok isolated MySQL/API checks passed: {environment.database_name}")


def main() -> int:
    try:
        asyncio.run(run())
    except R1MysqlNotConfigured as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
