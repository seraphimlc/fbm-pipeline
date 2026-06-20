from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import Text as SAText, text
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    # Ensure all ORM models are registered on Base.metadata before create_all.
    from app import models as _models  # noqa: F401

    async with engine.begin() as conn:
        if conn.dialect.name not in {"mysql", "mariadb"}:
            raise RuntimeError("fbm-pipeline now requires MySQL. Set DATABASE_URL to a mysql+asyncmy connection string.")
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_mysql_product_data_source_columns(conn)
        await _ensure_mysql_product_source_columns_and_indexes(conn)
        await _ensure_mysql_product_workflow_columns(conn)
        await _ensure_mysql_product_image_selection_columns(conn)
        await _ensure_mysql_catalog_export_columns(conn)
        await _ensure_mysql_task_run_action_columns(conn)
        await _ensure_mysql_longtext_columns(conn)
        await _ensure_mysql_giga_relation_columns(conn)
        await _ensure_mysql_giga_store_scoped_unique_indexes(conn)
        await _ensure_mysql_hot_path_indexes(conn)


async def _ensure_mysql_longtext_columns(conn) -> None:
    """Use LONGTEXT for JSON/raw HTML/text blobs when running on MySQL."""
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, SAText):
                current_type = await _mysql_column_type(conn, table.name, column.name)
                if current_type == "longtext":
                    continue
                nullable = "NULL" if column.nullable else "NOT NULL"
                await conn.execute(text(
                    f"ALTER TABLE `{table.name}` MODIFY COLUMN `{column.name}` LONGTEXT {nullable}"
                ))


async def _mysql_column_exists(conn, table_name: str, column_name: str) -> bool:
    result = await conn.execute(text(f"SHOW COLUMNS FROM `{table_name}` LIKE :column_name"), {"column_name": column_name})
    return result.first() is not None


async def _mysql_column_type(conn, table_name: str, column_name: str) -> str | None:
    result = await conn.execute(
        text("""
            SELECT DATA_TYPE
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
        """),
        {"table_name": table_name, "column_name": column_name},
    )
    value = result.scalar_one_or_none()
    return str(value).lower() if value else None


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


async def _ensure_mysql_catalog_export_columns(conn) -> None:
    for column_name, column_type in (
        ("exported_at", "DATETIME NULL"),
        ("export_task_id", "INTEGER NULL"),
        ("export_file_path", "LONGTEXT NULL"),
    ):
        if not await _mysql_column_exists(conn, "catalog_products", column_name):
            await conn.execute(text(f"ALTER TABLE `catalog_products` ADD COLUMN `{column_name}` {column_type}"))


async def _ensure_mysql_product_data_source_columns(conn) -> None:
    for column_name, column_type in (
        ("sales_channel", "VARCHAR(30) NULL"),
    ):
        if not await _mysql_column_exists(conn, "product_data_sources", column_name):
            await conn.execute(text(f"ALTER TABLE `product_data_sources` ADD COLUMN `{column_name}` {column_type}"))
    await conn.execute(text("""
        UPDATE `product_data_sources`
        SET `sales_channel` = COALESCE(`sales_channel`, 'amazon')
    """))


async def _ensure_mysql_task_run_action_columns(conn) -> None:
    for column_name, column_type in (
        ("dedupe_key", "VARCHAR(200) NULL"),
        ("correlation_key", "VARCHAR(200) NULL"),
        ("idempotency_key", "VARCHAR(200) NULL"),
        ("source_ref", "VARCHAR(200) NULL"),
        ("superseded_by_run_id", "INTEGER NULL"),
        ("superseded_at", "DATETIME NULL"),
        ("cancel_requested_at", "DATETIME NULL"),
        ("cancel_requested_by", "VARCHAR(100) NULL"),
        ("cancel_reason", "LONGTEXT NULL"),
    ):
        if not await _mysql_column_exists(conn, "task_runs", column_name):
            await conn.execute(text(f"ALTER TABLE `task_runs` ADD COLUMN `{column_name}` {column_type}"))
    if not await _mysql_constraint_exists(conn, "task_runs", "fk_task_runs_superseded_by_run_id"):
        await conn.execute(text("""
            ALTER TABLE `task_runs`
            ADD CONSTRAINT `fk_task_runs_superseded_by_run_id`
            FOREIGN KEY (`superseded_by_run_id`) REFERENCES `task_runs` (`id`)
        """))


async def _ensure_mysql_product_source_columns_and_indexes(conn) -> None:
    for column_name, column_type in (
        ("source_data_source_id", "INTEGER NULL"),
        ("source_site", "VARCHAR(20) NULL"),
        ("source_batch_id", "VARCHAR(100) NULL"),
    ):
        if not await _mysql_column_exists(conn, "products", column_name):
            await conn.execute(text(f"ALTER TABLE `products` ADD COLUMN `{column_name}` {column_type}"))
    await conn.execute(text("""
        UPDATE `products` p
        JOIN `product_data` pd ON pd.`product_id` = p.`id`
        SET p.`source_data_source_id` = CAST(JSON_UNQUOTE(JSON_EXTRACT(pd.`gigab2b_raw_snapshot`, '$.data_source_id')) AS UNSIGNED),
            p.`source_site` = JSON_UNQUOTE(JSON_EXTRACT(pd.`gigab2b_raw_snapshot`, '$.site')),
            p.`source_batch_id` = JSON_UNQUOTE(JSON_EXTRACT(pd.`gigab2b_raw_snapshot`, '$.batch_id'))
        WHERE p.`source_data_source_id` IS NULL
          AND pd.`gigab2b_raw_snapshot` IS NOT NULL
          AND JSON_VALID(pd.`gigab2b_raw_snapshot`)
          AND JSON_UNQUOTE(JSON_EXTRACT(pd.`gigab2b_raw_snapshot`, '$.data_source_id')) REGEXP '^[0-9]+$'
    """))


async def _ensure_mysql_product_workflow_columns(conn) -> None:
    for column_name, column_type in (
        ("workflow_node", "VARCHAR(80) NULL"),
        ("workflow_status", "VARCHAR(40) NULL"),
        ("workflow_error", "LONGTEXT NULL"),
        ("workflow_updated_at", "DATETIME NULL"),
    ):
        if not await _mysql_column_exists(conn, "products", column_name):
            await conn.execute(text(f"ALTER TABLE `products` ADD COLUMN `{column_name}` {column_type}"))


async def _ensure_mysql_product_image_selection_columns(conn) -> None:
    for column_name, column_type in (
        ("image_selection_analysis", "LONGTEXT NULL"),
        ("image_selected_at", "DATETIME NULL"),
    ):
        if not await _mysql_column_exists(conn, "product_images", column_name):
            await conn.execute(text(f"ALTER TABLE `product_images` ADD COLUMN `{column_name}` {column_type}"))


async def _ensure_mysql_hot_path_indexes(conn) -> None:
    indexes = (
        ("products", "ix_products_source_status_updated", ("source_data_source_id", "status", "current_step", "updated_at")),
        ("products", "ix_products_source_updated", ("source_data_source_id", "updated_at")),
        ("products", "ix_products_status_step_updated", ("status", "current_step", "updated_at")),
        ("catalog_products", "ix_catalog_confirmed_export_updated", ("confirmed_at", "exported_at", "updated_at")),
        ("catalog_products", "ix_catalog_confirmed_asin_status", ("confirmed_at", "amazon_asin", "asin_sync_status")),
        ("offline_tasks", "ix_offline_tasks_type_status_id", ("task_type", "status", "id")),
        ("offline_task_steps", "ix_offline_task_steps_task_id", ("task_id", "id")),
        ("task_runs", "ix_task_runs_type_status_id", ("task_type", "status", "id")),
        ("task_runs", "idx_task_runs_dedupe_key_status_created_at", ("dedupe_key", "status", "created_at")),
        ("task_runs", "idx_task_runs_correlation_key_created_at", ("correlation_key", "created_at")),
        ("task_runs", "idx_task_runs_idempotency_key", ("idempotency_key",)),
        ("task_runs", "idx_task_runs_task_type_status_created_at", ("task_type", "status", "created_at")),
        ("task_runs", "idx_task_runs_superseded_by_run_id", ("superseded_by_run_id",)),
        ("task_groups", "ix_task_groups_run_order", ("task_run_id", "sort_order", "id")),
        ("task_steps", "ix_task_steps_run_group_order", ("task_run_id", "task_group_id", "sort_order", "id")),
        ("task_steps", "ix_task_steps_ready_claim", ("status", "locked_until", "sort_order", "id")),
        ("task_step_events", "ix_task_step_events_run_created", ("task_run_id", "created_at", "id")),
        ("task_step_events", "ix_task_step_events_step_created", ("task_step_id", "created_at", "id")),
        ("amazon_competitor_search_candidates", "ix_amz_comp_search_product_rank", ("product_id", "search_rank", "id")),
        ("amazon_competitor_search_candidates", "ix_amz_comp_search_product_query", ("product_id", "search_query")),
        ("amazon_competitor_search_candidates", "ix_amz_comp_search_product_excluded", ("product_id", "is_excluded", "id")),
        ("amazon_competitor_search_candidates", "ix_amz_comp_search_asin", ("asin",)),
        ("amazon_competitor_search_candidates", "ix_amz_comp_search_task_run", ("task_run_id", "id")),
    )
    for table_name, index_name, columns in indexes:
        if await _mysql_index_exists(conn, table_name, index_name):
            continue
        columns_sql = ", ".join(f"`{column}`" for column in columns)
        await conn.execute(text(f"ALTER TABLE `{table_name}` ADD INDEX `{index_name}` ({columns_sql})"))


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
