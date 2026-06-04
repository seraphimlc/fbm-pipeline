from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import Text as SAText, text
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name != "sqlite":
            if conn.dialect.name in {"mysql", "mariadb"}:
                await _ensure_mysql_longtext_columns(conn)
                await _ensure_mysql_giga_relation_columns(conn)
                await _ensure_mysql_giga_store_scoped_unique_indexes(conn)
            return
        result = await conn.execute(text("PRAGMA table_info(products)"))
        existing_product_columns = {row[1] for row in result.fetchall()}
        if "upc" not in existing_product_columns:
            await conn.execute(text("ALTER TABLE products ADD COLUMN upc VARCHAR(32)"))
        for column_name, column_type in (
            ("amazon_asin", "VARCHAR(20)"),
            ("asin_sync_status", "VARCHAR(20) DEFAULT 'not_synced'"),
            ("asin_synced_at", "DATETIME"),
            ("asin_sync_error", "TEXT"),
            ("amazon_product_status", "VARCHAR(100)"),
            ("amazon_product_status_synced_at", "DATETIME"),
            ("amazon_product_status_error", "TEXT"),
            ("aplus_upload_status", "VARCHAR(20) DEFAULT 'not_uploaded'"),
            ("aplus_uploaded_at", "DATETIME"),
            ("aplus_upload_error", "TEXT"),
        ):
            if column_name not in existing_product_columns:
                await conn.execute(text(f"ALTER TABLE products ADD COLUMN {column_name} {column_type}"))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS upc_pool_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upc VARCHAR(32) NOT NULL UNIQUE,
                status VARCHAR(20),
                source VARCHAR(50),
                product_id INTEGER,
                bound_item_code VARCHAR(100),
                bound_source_product_id VARCHAR(50),
                bound_source_url TEXT,
                bound_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_upc_pool_items_status_id
            ON upc_pool_items(status, id)
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS product_data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                platform VARCHAR(30),
                site VARCHAR(20) NOT NULL,
                country VARCHAR(20) NOT NULL,
                fulfillment_mode VARCHAR(30),
                api_base TEXT,
                client_id TEXT,
                client_secret TEXT,
                shipping_cost_mode VARCHAR(30),
                packing_fee FLOAT,
                inventory_mode VARCHAR(30),
                enabled INTEGER,
                remark TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_product_data_sources_platform_site
            ON product_data_sources(platform, site, enabled)
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS offline_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type VARCHAR(50) NOT NULL,
                title VARCHAR(200) NOT NULL,
                status VARCHAR(30),
                total_steps INTEGER,
                success_steps INTEGER,
                failed_steps INTEGER,
                running_steps INTEGER,
                created_by VARCHAR(100),
                payload_json TEXT,
                result_json TEXT,
                error_message TEXT,
                created_at DATETIME,
                started_at DATETIME,
                finished_at DATETIME,
                updated_at DATETIME
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_offline_tasks_type_status_id
            ON offline_tasks(task_type, status, id)
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS offline_task_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                step_type VARCHAR(50) NOT NULL,
                title VARCHAR(200) NOT NULL,
                status VARCHAR(30),
                data_source_id INTEGER,
                data_source_name VARCHAR(100),
                site VARCHAR(20),
                batch_id VARCHAR(100),
                progress_current INTEGER,
                progress_total INTEGER,
                payload_json TEXT,
                result_json TEXT,
                error_message TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(task_id) REFERENCES offline_tasks(id),
                FOREIGN KEY(data_source_id) REFERENCES product_data_sources(id)
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_offline_task_steps_task_id
            ON offline_task_steps(task_id, id)
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS product_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                label VARCHAR(200) NOT NULL,
                path TEXT NOT NULL,
                directory TEXT,
                metadata_json TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS catalog_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_product_id INTEGER NOT NULL UNIQUE,
                gigab2b_url TEXT NOT NULL,
                gigab2b_product_id VARCHAR(50),
                competitor_asin VARCHAR(20),
                amazon_asin VARCHAR(20),
                asin_sync_status VARCHAR(20) DEFAULT 'not_synced',
                asin_synced_at DATETIME,
                asin_sync_error TEXT,
                amazon_product_status VARCHAR(100),
                amazon_product_status_synced_at DATETIME,
                amazon_product_status_error TEXT,
                aplus_upload_status VARCHAR(20) DEFAULT 'not_uploaded',
                aplus_uploaded_at DATETIME,
                aplus_upload_error TEXT,
                upc VARCHAR(32),
                brand VARCHAR(100),
                item_code VARCHAR(100),
                title TEXT,
                leaf_category VARCHAR(200),
                stock INTEGER,
                stock_sync_status VARCHAR(20) DEFAULT 'not_synced',
                stock_synced_at DATETIME,
                stock_sync_error TEXT,
                status VARCHAR(30),
                confirmed_at DATETIME,
                imported_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(source_product_id) REFERENCES products(id)
            )
        """))

        result = await conn.execute(text("PRAGMA table_info(catalog_products)"))
        existing_catalog_columns = {row[1] for row in result.fetchall()}
        for column_name, column_type in (
            ("amazon_asin", "VARCHAR(20)"),
            ("asin_sync_status", "VARCHAR(20) DEFAULT 'not_synced'"),
            ("asin_synced_at", "DATETIME"),
            ("asin_sync_error", "TEXT"),
            ("amazon_product_status", "VARCHAR(100)"),
            ("amazon_product_status_synced_at", "DATETIME"),
            ("amazon_product_status_error", "TEXT"),
            ("aplus_upload_status", "VARCHAR(20) DEFAULT 'not_uploaded'"),
            ("aplus_uploaded_at", "DATETIME"),
            ("aplus_upload_error", "TEXT"),
            ("confirmed_at", "DATETIME"),
            ("stock", "INTEGER"),
            ("stock_sync_status", "VARCHAR(20) DEFAULT 'not_synced'"),
            ("stock_synced_at", "DATETIME"),
            ("stock_sync_error", "TEXT"),
        ):
            if column_name not in existing_catalog_columns:
                await conn.execute(text(f"ALTER TABLE catalog_products ADD COLUMN {column_name} {column_type}"))

        await conn.execute(text("""
            UPDATE catalog_products
            SET confirmed_at = COALESCE(imported_at, CURRENT_TIMESTAMP)
            WHERE confirmed_at IS NULL
              AND source_product_id IN (
                  SELECT id FROM products WHERE status = 'completed'
              )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asin_sync_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store VARCHAR(100),
                status VARCHAR(20),
                total_count INTEGER,
                success_count INTEGER,
                not_found_count INTEGER,
                failed_count INTEGER,
                skipped_count INTEGER,
                created_at DATETIME,
                started_at DATETIME,
                finished_at DATETIME,
                error_message TEXT
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asin_sync_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                catalog_product_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                lookup_code VARCHAR(100),
                lookup_type VARCHAR(20),
                matched_code VARCHAR(100),
                amazon_asin VARCHAR(20),
                amazon_product_status VARCHAR(100),
                status VARCHAR(20),
                error_message TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                FOREIGN KEY(batch_id) REFERENCES asin_sync_batches(id),
                FOREIGN KEY(catalog_product_id) REFERENCES catalog_products(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """))
        result = await conn.execute(text("PRAGMA table_info(asin_sync_items)"))
        existing_asin_sync_item_columns = {row[1] for row in result.fetchall()}
        if "amazon_product_status" not in existing_asin_sync_item_columns:
            await conn.execute(text("ALTER TABLE asin_sync_items ADD COLUMN amazon_product_status VARCHAR(100)"))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS aplus_upload_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store VARCHAR(100),
                submit_for_approval INTEGER,
                status VARCHAR(20),
                total_count INTEGER,
                success_count INTEGER,
                failed_count INTEGER,
                skipped_count INTEGER,
                created_at DATETIME,
                started_at DATETIME,
                finished_at DATETIME,
                error_message TEXT
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS aplus_upload_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                catalog_product_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                amazon_asin VARCHAR(20),
                item_code VARCHAR(100),
                document_name VARCHAR(200),
                status VARCHAR(20),
                uploaded_images TEXT,
                lingxing_response TEXT,
                error_message TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                FOREIGN KEY(batch_id) REFERENCES aplus_upload_batches(id),
                FOREIGN KEY(catalog_product_id) REFERENCES catalog_products(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS inventory_sync_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status VARCHAR(20),
                total_count INTEGER,
                success_count INTEGER,
                unavailable_count INTEGER,
                failed_count INTEGER,
                skipped_count INTEGER,
                created_at DATETIME,
                started_at DATETIME,
                finished_at DATETIME,
                error_message TEXT
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS inventory_sync_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                catalog_product_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                gigab2b_product_id VARCHAR(50),
                item_code VARCHAR(100),
                old_stock INTEGER,
                new_stock INTEGER,
                availability_status VARCHAR(30),
                status VARCHAR(20),
                error_message TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                FOREIGN KEY(batch_id) REFERENCES inventory_sync_batches(id),
                FOREIGN KEY(catalog_product_id) REFERENCES catalog_products(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """))

        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS aplus_regenerate_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                module_position INTEGER NOT NULL,
                reason TEXT NOT NULL,
                status VARCHAR(30),
                stage VARCHAR(30),
                error_message TEXT,
                result_json TEXT,
                created_at DATETIME,
                started_at DATETIME,
                finished_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """))

        await conn.execute(text("""
            UPDATE products
            SET
                aplus_upload_status = (
                    SELECT
                        CASE
                            WHEN ai.status = 'success' AND COALESCE(ab.submit_for_approval, 1) = 1 THEN 'submitted'
                            WHEN ai.status = 'success' THEN 'draft_saved'
                            ELSE ai.status
                        END
                    FROM aplus_upload_items ai
                    LEFT JOIN aplus_upload_batches ab ON ab.id = ai.batch_id
                    WHERE ai.product_id = products.id
                      AND ai.status IN ('success', 'failed', 'skipped')
                    ORDER BY COALESCE(ai.finished_at, ai.started_at, ab.finished_at, ab.created_at) DESC
                    LIMIT 1
                ),
                aplus_uploaded_at = (
                    SELECT COALESCE(ai.finished_at, ai.started_at, ab.finished_at, ab.created_at)
                    FROM aplus_upload_items ai
                    LEFT JOIN aplus_upload_batches ab ON ab.id = ai.batch_id
                    WHERE ai.product_id = products.id
                      AND ai.status IN ('success', 'failed', 'skipped')
                    ORDER BY COALESCE(ai.finished_at, ai.started_at, ab.finished_at, ab.created_at) DESC
                    LIMIT 1
                ),
                aplus_upload_error = (
                    SELECT ai.error_message
                    FROM aplus_upload_items ai
                    LEFT JOIN aplus_upload_batches ab ON ab.id = ai.batch_id
                    WHERE ai.product_id = products.id
                      AND ai.status IN ('success', 'failed', 'skipped')
                    ORDER BY COALESCE(ai.finished_at, ai.started_at, ab.finished_at, ab.created_at) DESC
                    LIMIT 1
                )
            WHERE EXISTS (
                SELECT 1
                FROM aplus_upload_items ai
                WHERE ai.product_id = products.id
                  AND ai.status IN ('success', 'failed', 'skipped')
            )
        """))

        await conn.execute(text("""
            UPDATE catalog_products
            SET
                aplus_upload_status = (
                    SELECT
                        CASE
                            WHEN ai.status = 'success' AND COALESCE(ab.submit_for_approval, 1) = 1 THEN 'submitted'
                            WHEN ai.status = 'success' THEN 'draft_saved'
                            ELSE ai.status
                        END
                    FROM aplus_upload_items ai
                    LEFT JOIN aplus_upload_batches ab ON ab.id = ai.batch_id
                    WHERE ai.catalog_product_id = catalog_products.id
                      AND ai.status IN ('success', 'failed', 'skipped')
                    ORDER BY COALESCE(ai.finished_at, ai.started_at, ab.finished_at, ab.created_at) DESC
                    LIMIT 1
                ),
                aplus_uploaded_at = (
                    SELECT COALESCE(ai.finished_at, ai.started_at, ab.finished_at, ab.created_at)
                    FROM aplus_upload_items ai
                    LEFT JOIN aplus_upload_batches ab ON ab.id = ai.batch_id
                    WHERE ai.catalog_product_id = catalog_products.id
                      AND ai.status IN ('success', 'failed', 'skipped')
                    ORDER BY COALESCE(ai.finished_at, ai.started_at, ab.finished_at, ab.created_at) DESC
                    LIMIT 1
                ),
                aplus_upload_error = (
                    SELECT ai.error_message
                    FROM aplus_upload_items ai
                    LEFT JOIN aplus_upload_batches ab ON ab.id = ai.batch_id
                    WHERE ai.catalog_product_id = catalog_products.id
                      AND ai.status IN ('success', 'failed', 'skipped')
                    ORDER BY COALESCE(ai.finished_at, ai.started_at, ab.finished_at, ab.created_at) DESC
                    LIMIT 1
                )
            WHERE EXISTS (
                SELECT 1
                FROM aplus_upload_items ai
                WHERE ai.catalog_product_id = catalog_products.id
                  AND ai.status IN ('success', 'failed', 'skipped')
            )
        """))

        await conn.execute(text("""
            INSERT INTO catalog_products (
                source_product_id,
                gigab2b_url,
                gigab2b_product_id,
                competitor_asin,
                amazon_asin,
                asin_sync_status,
                asin_synced_at,
                asin_sync_error,
                amazon_product_status,
                amazon_product_status_synced_at,
                amazon_product_status_error,
                aplus_upload_status,
                aplus_uploaded_at,
                aplus_upload_error,
                upc,
                brand,
                item_code,
                title,
                leaf_category,
                status,
                imported_at,
                updated_at
            )
            SELECT
                p.id,
                p.gigab2b_url,
                p.gigab2b_product_id,
                p.competitor_asin,
                p.amazon_asin,
                COALESCE(p.asin_sync_status, 'not_synced'),
                p.asin_synced_at,
                p.asin_sync_error,
                p.amazon_product_status,
                p.amazon_product_status_synced_at,
                p.amazon_product_status_error,
                COALESCE(p.aplus_upload_status, 'not_uploaded'),
                p.aplus_uploaded_at,
                p.aplus_upload_error,
                p.upc,
                p.brand,
                pd.item_code,
                pd.title,
                pd.leaf_category,
                p.status,
                COALESCE(p.created_at, CURRENT_TIMESTAMP),
                COALESCE(p.updated_at, CURRENT_TIMESTAMP)
            FROM products p
            LEFT JOIN product_data pd ON pd.product_id = p.id
            WHERE NOT EXISTS (
                SELECT 1
                FROM catalog_products cp
                WHERE cp.source_product_id = p.id
            )
        """))

        result = await conn.execute(text("PRAGMA table_info(product_data)"))
        existing_columns = {row[1] for row in result.fetchall()}
        for column_name in (
            "pricing_detail",
            "listing_title_zh",
            "listing_bullets_zh",
            "listing_search_terms_zh",
            "listing_description",
            "listing_description_zh",
            "gigab2b_raw_snapshot",
            "amazon_template_path",
            "amazon_template_warnings",
            "amazon_template_fill_summary",
            "amazon_template_generated_at",
        ):
            if column_name not in existing_columns:
                await conn.execute(text(f"ALTER TABLE product_data ADD COLUMN {column_name} TEXT"))

        await conn.execute(text("""
            INSERT INTO product_files (
                product_id,
                file_type,
                label,
                path,
                directory,
                metadata_json,
                created_at,
                updated_at
            )
            SELECT
                pd.product_id,
                'amazon_import_template',
                'Amazon导入表格',
                pd.amazon_template_path,
                NULL,
                CASE
                    WHEN pd.amazon_template_warnings IS NOT NULL OR pd.amazon_template_fill_summary IS NOT NULL
                    THEN json_object(
                        'warnings',
                        CASE WHEN pd.amazon_template_warnings IS NOT NULL THEN json(pd.amazon_template_warnings) ELSE json('[]') END,
                        'fill_summary',
                        CASE WHEN pd.amazon_template_fill_summary IS NOT NULL THEN json(pd.amazon_template_fill_summary) ELSE NULL END
                    )
                    ELSE NULL
                END,
                COALESCE(pd.amazon_template_generated_at, CURRENT_TIMESTAMP),
                COALESCE(pd.amazon_template_generated_at, CURRENT_TIMESTAMP)
            FROM product_data pd
            WHERE pd.amazon_template_path IS NOT NULL
              AND pd.amazon_template_path != ''
              AND NOT EXISTS (
                SELECT 1
                FROM product_files pf
                WHERE pf.product_id = pd.product_id
                  AND pf.file_type = 'amazon_import_template'
                  AND pf.path = pd.amazon_template_path
              )
        """))

        async def ensure_columns(table_name: str, columns: tuple[tuple[str, str], ...]) -> None:
            result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
            existing = {row[1] for row in result.fetchall()}
            for column_name, column_type in columns:
                if column_name not in existing:
                    await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))

        await ensure_columns("product_data_sources", (
            ("platform", "VARCHAR(30)"),
            ("country", "VARCHAR(20)"),
            ("fulfillment_mode", "VARCHAR(30)"),
            ("api_base", "TEXT"),
            ("client_id", "TEXT"),
            ("client_secret", "TEXT"),
            ("shipping_cost_mode", "VARCHAR(30)"),
            ("packing_fee", "FLOAT"),
            ("inventory_mode", "VARCHAR(30)"),
            ("enabled", "INTEGER"),
            ("remark", "TEXT"),
            ("created_at", "DATETIME"),
            ("updated_at", "DATETIME"),
        ))
        await conn.execute(text("""
            UPDATE product_data_sources
            SET
                platform = COALESCE(platform, 'giga'),
                country = COALESCE(country, site),
                fulfillment_mode = COALESCE(fulfillment_mode, 'dropship'),
                shipping_cost_mode = COALESCE(shipping_cost_mode, 'giga_shipping_fee'),
                inventory_mode = COALESCE(inventory_mode, 'available_qty'),
                enabled = COALESCE(enabled, 1),
                created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
                updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
        """))

        await ensure_columns("giga_sync_batches", (
            ("data_source_id", "INTEGER"),
            ("data_source_name", "VARCHAR(100)"),
            ("fulfillment_mode", "VARCHAR(30)"),
        ))
        await ensure_columns("giga_raw_sku_details", (
            ("data_source_id", "INTEGER"),
        ))
        await ensure_columns("giga_items", (
            ("data_source_id", "INTEGER"),
            ("data_source_name", "VARCHAR(100)"),
            ("fulfillment_mode", "VARCHAR(30)"),
            ("parent_sku_code", "VARCHAR(100)"),
            ("sku_codes_json", "TEXT"),
            ("missing_related_skus_json", "TEXT"),
        ))
        await ensure_columns("giga_skus", (
            ("giga_item_id", "INTEGER"),
            ("data_source_id", "INTEGER"),
            ("data_source_name", "VARCHAR(100)"),
            ("fulfillment_mode", "VARCHAR(30)"),
            ("parent_sku_code", "VARCHAR(100)"),
            ("parentage", "VARCHAR(20)"),
            ("child_sequence", "INTEGER"),
            ("is_primary_child", "INTEGER"),
            ("attributes_json", "TEXT"),
            ("variation_attributes_json", "TEXT"),
        ))
        await conn.execute(text("""
            UPDATE giga_skus
            SET giga_item_id = (
                SELECT gi.id
                FROM giga_items gi
                WHERE gi.batch_id = giga_skus.batch_id
                  AND gi.site = giga_skus.site
                  AND COALESCE(gi.data_source_id, -1) = COALESCE(giga_skus.data_source_id, -1)
                  AND gi.item_code = giga_skus.item_code
                LIMIT 1
            )
            WHERE giga_item_id IS NULL
              AND item_code IS NOT NULL
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_giga_skus_giga_item_id
            ON giga_skus(giga_item_id)
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS giga_product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id VARCHAR(100) NOT NULL,
                site VARCHAR(20) NOT NULL,
                data_source_id INTEGER,
                item_code VARCHAR(100),
                sku_code VARCHAR(100) NOT NULL,
                image_url TEXT NOT NULL,
                local_path TEXT,
                image_type VARCHAR(50),
                sort_order INTEGER,
                url_hash VARCHAR(64),
                content_hash VARCHAR(64),
                file_size INTEGER,
                mime_type VARCHAR(100),
                download_status VARCHAR(30),
                error_message TEXT,
                source_platform VARCHAR(30),
                pulled_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_giga_product_images_batch_site_sku_url
            ON giga_product_images(batch_id, site, data_source_id, sku_code, image_url)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_giga_product_images_batch_site_item
            ON giga_product_images(batch_id, site, data_source_id, item_code)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_giga_product_images_status
            ON giga_product_images(download_status)
        """))
        await ensure_columns("giga_product_images", (
            ("data_source_id", "INTEGER"),
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS amazon_stylesnap_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id VARCHAR(100) NOT NULL,
                site VARCHAR(20) NOT NULL,
                item_code VARCHAR(100) NOT NULL,
                sku_code VARCHAR(100) NOT NULL,
                product_name TEXT,
                source_image_url TEXT,
                source_image_path TEXT,
                rank INTEGER NOT NULL,
                asin VARCHAR(20) NOT NULL,
                url TEXT,
                brand VARCHAR(200),
                seller VARCHAR(200),
                delivery VARCHAR(200),
                price VARCHAR(100),
                rating VARCHAR(100),
                category_rank TEXT,
                color VARCHAR(200),
                size VARCHAR(200),
                style VARCHAR(200),
                amazon_image_url TEXT,
                amazon_image_path TEXT,
                raw_snippet TEXT,
                raw_candidate_json TEXT,
                raw_capture_json TEXT,
                page_href TEXT,
                page_title TEXT,
                page_body_length INTEGER,
                capture_error TEXT,
                is_selected INTEGER,
                selected_at DATETIME,
                source_platform VARCHAR(30),
                captured_at DATETIME,
                imported_at DATETIME,
                updated_at DATETIME
            )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_amazon_stylesnap_candidate_identity
            ON amazon_stylesnap_candidates(batch_id, site, item_code, sku_code, rank, asin)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_amazon_stylesnap_candidates_item
            ON amazon_stylesnap_candidates(batch_id, site, item_code)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_amazon_stylesnap_candidates_asin
            ON amazon_stylesnap_candidates(asin)
        """))
        await ensure_columns("amazon_stylesnap_candidates", (
            ("source_image_url", "TEXT"),
            ("source_image_path", "TEXT"),
            ("amazon_image_url", "TEXT"),
            ("amazon_image_path", "TEXT"),
            ("raw_candidate_json", "TEXT"),
            ("raw_capture_json", "TEXT"),
            ("capture_error", "TEXT"),
            ("is_selected", "INTEGER"),
            ("selected_at", "DATETIME"),
        ))
        await conn.execute(text("""
            UPDATE amazon_stylesnap_candidates
            SET is_selected = 0
            WHERE is_selected IS NULL
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS amazon_listing_captures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                selected_candidate_id INTEGER NOT NULL,
                batch_id VARCHAR(100) NOT NULL,
                site VARCHAR(20) NOT NULL,
                item_code VARCHAR(100) NOT NULL,
                sku_code VARCHAR(100) NOT NULL,
                asin VARCHAR(20) NOT NULL,
                url TEXT,
                title TEXT,
                brand VARCHAR(200),
                seller VARCHAR(200),
                price VARCHAR(100),
                rating VARCHAR(100),
                review_count VARCHAR(100),
                availability TEXT,
                categories TEXT,
                leaf_category VARCHAR(200),
                category_rank TEXT,
                bullets_json TEXT,
                description TEXT,
                product_details_json TEXT,
                aplus_text TEXT,
                main_image_url TEXT,
                image_urls_json TEXT,
                raw_json TEXT,
                page_url TEXT,
                page_title TEXT,
                page_body_length INTEGER,
                capture_status VARCHAR(30),
                capture_error TEXT,
                source_platform VARCHAR(30),
                captured_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(selected_candidate_id) REFERENCES amazon_stylesnap_candidates(id)
            )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_amazon_listing_capture_candidate
            ON amazon_listing_captures(selected_candidate_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_amazon_listing_captures_batch_item
            ON amazon_listing_captures(batch_id, site, item_code)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_amazon_listing_captures_asin
            ON amazon_listing_captures(asin)
        """))
        await ensure_columns("giga_groups", (
            ("data_source_id", "INTEGER"),
            ("data_source_name", "VARCHAR(100)"),
            ("fulfillment_mode", "VARCHAR(30)"),
            ("parent_sku_code", "VARCHAR(100)"),
            ("missing_related_skus_json", "TEXT"),
            ("variation_keys_json", "TEXT"),
        ))
        await ensure_columns("giga_prices", (
            ("data_source_id", "INTEGER"),
            ("fulfillment_mode", "VARCHAR(30)"),
            ("shipping_cost_mode", "VARCHAR(30)"),
            ("packing_fee", "FLOAT"),
            ("task_id", "VARCHAR(100)"),
            ("pulled_at", "DATETIME"),
            ("effective_price", "FLOAT"),
            ("shipping_fee_min", "FLOAT"),
            ("shipping_fee_max", "FLOAT"),
            ("map_price", "FLOAT"),
            ("srp_price", "VARCHAR(100)"),
            ("future_map_price", "FLOAT"),
            ("exclusive_price_expire_time", "VARCHAR(100)"),
            ("promotion_from", "VARCHAR(100)"),
            ("promotion_to", "VARCHAR(100)"),
            ("purchase_limit", "VARCHAR(100)"),
            ("sku_available", "INTEGER"),
            ("seller_info_json", "TEXT"),
            ("spot_price_json", "TEXT"),
            ("rebates_price_json", "TEXT"),
            ("margin_price_json", "TEXT"),
            ("future_price_json", "TEXT"),
            ("raw_price_json", "TEXT"),
        ))
        await conn.execute(text("""
            UPDATE giga_prices
            SET effective_price = COALESCE(exclusive_price, discounted_price, price)
            WHERE effective_price IS NULL
        """))
        await conn.execute(text("""
            UPDATE giga_prices
            SET pulled_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            WHERE pulled_at IS NULL
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS giga_price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id VARCHAR(100) NOT NULL,
                site VARCHAR(20) NOT NULL,
                sku_code VARCHAR(100) NOT NULL,
                item_code VARCHAR(100),
                product_name TEXT,
                previous_batch_id VARCHAR(100),
                previous_effective_price FLOAT,
                current_effective_price FLOAT,
                previous_price FLOAT,
                current_price FLOAT,
                previous_exclusive_price FLOAT,
                current_exclusive_price FLOAT,
                previous_discounted_price FLOAT,
                current_discounted_price FLOAT,
                previous_shipping_fee FLOAT,
                current_shipping_fee FLOAT,
                change_type VARCHAR(30) NOT NULL,
                message TEXT NOT NULL,
                source_platform VARCHAR(30),
                created_at DATETIME
            )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_giga_price_alert_batch_site_sku_type
            ON giga_price_alerts(batch_id, site, sku_code, change_type)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_giga_price_alerts_batch_site
            ON giga_price_alerts(batch_id, site)
        """))
        await ensure_columns("giga_inventory", (
            ("data_source_id", "INTEGER"),
            ("fulfillment_mode", "VARCHAR(30)"),
            ("inventory_mode", "VARCHAR(30)"),
            ("task_id", "VARCHAR(100)"),
            ("stock_qty", "INTEGER"),
            ("pulled_at", "DATETIME"),
        ))
        await conn.execute(text("""
            UPDATE giga_inventory
            SET stock_qty = COALESCE(seller_available_inventory, total_buyer_available_inventory, 0)
            WHERE stock_qty IS NULL
        """))
        await conn.execute(text("""
            UPDATE giga_inventory
            SET pulled_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            WHERE pulled_at IS NULL
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS giga_inventory_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id VARCHAR(100) NOT NULL,
                site VARCHAR(20) NOT NULL,
                sku_code VARCHAR(100) NOT NULL,
                item_code VARCHAR(100),
                product_name TEXT,
                previous_batch_id VARCHAR(100),
                previous_stock_qty INTEGER,
                current_stock_qty INTEGER,
                previous_status VARCHAR(30),
                current_status VARCHAR(30),
                change_type VARCHAR(30) NOT NULL,
                message TEXT NOT NULL,
                source_platform VARCHAR(30),
                created_at DATETIME
            )
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_giga_inventory_alert_batch_site_sku_type
            ON giga_inventory_alerts(batch_id, site, sku_code, change_type)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_giga_inventory_alerts_batch_site
            ON giga_inventory_alerts(batch_id, site)
        """))
        await ensure_columns("giga_price_alerts", (
            ("data_source_id", "INTEGER"),
        ))
        await ensure_columns("giga_inventory_alerts", (
            ("data_source_id", "INTEGER"),
        ))


async def _ensure_mysql_longtext_columns(conn) -> None:
    """Use LONGTEXT for JSON/raw HTML/text blobs when running on MySQL."""
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, SAText):
                nullable = "NULL" if column.nullable else "NOT NULL"
                await conn.execute(text(
                    f"ALTER TABLE `{table.name}` MODIFY COLUMN `{column.name}` LONGTEXT {nullable}"
                ))


async def _mysql_column_exists(conn, table_name: str, column_name: str) -> bool:
    result = await conn.execute(text(f"SHOW COLUMNS FROM `{table_name}` LIKE :column_name"), {"column_name": column_name})
    return result.first() is not None


async def _mysql_index_exists(conn, table_name: str, index_name: str) -> bool:
    result = await conn.execute(text(f"SHOW INDEX FROM `{table_name}` WHERE Key_name = :index_name"), {"index_name": index_name})
    return result.first() is not None


async def _mysql_constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    result = await conn.execute(text("""
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND constraint_name = :constraint_name
        LIMIT 1
    """), {"table_name": table_name, "constraint_name": constraint_name})
    return result.first() is not None


async def _ensure_mysql_giga_relation_columns(conn) -> None:
    if not await _mysql_column_exists(conn, "giga_skus", "giga_item_id"):
        await conn.execute(text("ALTER TABLE `giga_skus` ADD COLUMN `giga_item_id` INTEGER NULL"))
    await conn.execute(text("""
        UPDATE `giga_skus` gs
        JOIN `giga_items` gi
          ON gi.`batch_id` = gs.`batch_id`
         AND gi.`site` = gs.`site`
         AND COALESCE(gi.`data_source_id`, -1) = COALESCE(gs.`data_source_id`, -1)
         AND gi.`item_code` = gs.`item_code`
        SET gs.`giga_item_id` = gi.`id`
        WHERE gs.`giga_item_id` IS NULL
          AND gs.`item_code` IS NOT NULL
    """))
    if not await _mysql_index_exists(conn, "giga_skus", "ix_giga_skus_giga_item_id"):
        await conn.execute(text("ALTER TABLE `giga_skus` ADD INDEX `ix_giga_skus_giga_item_id` (`giga_item_id`)"))
    if not await _mysql_constraint_exists(conn, "giga_skus", "fk_giga_skus_giga_item_id"):
        await conn.execute(text("""
            ALTER TABLE `giga_skus`
            ADD CONSTRAINT `fk_giga_skus_giga_item_id`
            FOREIGN KEY (`giga_item_id`) REFERENCES `giga_items` (`id`)
        """))


GIGA_STORE_SCOPED_UNIQUE_INDEXES = (
    ("giga_sync_batches", "uq_giga_sync_batches_batch_site", ("batch_id", "site", "data_source_id")),
    ("giga_raw_sku_details", "uq_giga_raw_sku_details_batch_site_sku", ("batch_id", "site", "data_source_id", "sku_code")),
    ("giga_items", "uq_giga_items_batch_site_item", ("batch_id", "site", "data_source_id", "item_code")),
    ("giga_skus", "uq_giga_skus_batch_site_sku", ("batch_id", "site", "data_source_id", "sku_code")),
    ("giga_product_images", "uq_giga_product_images_batch_site_sku_url_hash", ("batch_id", "site", "data_source_id", "sku_code", "url_hash")),
    ("giga_prices", "uq_giga_prices_batch_site_sku", ("batch_id", "site", "data_source_id", "sku_code")),
    ("giga_inventory", "uq_giga_inventory_batch_site_sku", ("batch_id", "site", "data_source_id", "sku_code")),
    ("giga_groups", "uq_giga_groups_batch_site_group", ("batch_id", "site", "data_source_id", "group_code")),
    ("giga_price_alerts", "uq_giga_price_alert_batch_site_sku_type", ("batch_id", "site", "data_source_id", "sku_code", "change_type")),
    ("giga_inventory_alerts", "uq_giga_inventory_alert_batch_site_sku_type", ("batch_id", "site", "data_source_id", "sku_code", "change_type")),
)


async def _ensure_mysql_giga_store_scoped_unique_indexes(conn) -> None:
    """Keep raw GIGA identity scoped by store so identical external codes never collide."""
    for table_name, index_name, expected_columns in GIGA_STORE_SCOPED_UNIQUE_INDEXES:
        result = await conn.execute(text(f"SHOW INDEX FROM `{table_name}` WHERE Key_name = :index_name"), {"index_name": index_name})
        rows = sorted(result.mappings().all(), key=lambda row: int(row["Seq_in_index"]))
        current_columns = tuple(str(row["Column_name"]) for row in rows)
        if current_columns == expected_columns:
            continue
        if rows:
            await conn.execute(text(f"ALTER TABLE `{table_name}` DROP INDEX `{index_name}`"))
        columns_sql = ", ".join(f"`{column}`" for column in expected_columns)
        await conn.execute(text(f"ALTER TABLE `{table_name}` ADD UNIQUE INDEX `{index_name}` ({columns_sql})"))
