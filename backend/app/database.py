from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
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
        result = await conn.execute(text("PRAGMA table_info(products)"))
        existing_product_columns = {row[1] for row in result.fetchall()}
        if "upc" not in existing_product_columns:
            await conn.execute(text("ALTER TABLE products ADD COLUMN upc VARCHAR(32)"))
        for column_name, column_type in (
            ("amazon_asin", "VARCHAR(20)"),
            ("asin_sync_status", "VARCHAR(20) DEFAULT 'not_synced'"),
            ("asin_synced_at", "DATETIME"),
            ("asin_sync_error", "TEXT"),
            ("aplus_upload_status", "VARCHAR(20) DEFAULT 'not_uploaded'"),
            ("aplus_uploaded_at", "DATETIME"),
            ("aplus_upload_error", "TEXT"),
        ):
            if column_name not in existing_product_columns:
                await conn.execute(text(f"ALTER TABLE products ADD COLUMN {column_name} {column_type}"))

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
                status VARCHAR(20),
                error_message TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                FOREIGN KEY(batch_id) REFERENCES asin_sync_batches(id),
                FOREIGN KEY(catalog_product_id) REFERENCES catalog_products(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """))

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
