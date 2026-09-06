"""Regression check for the offline SQLite large-field migration.

It operates on a disposable copy of the configured local database and never
writes ``data/fbm-pipeline.db``.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import settings
from app.migrations.product_large_fields import migrate, rollback, verify
from app.models import Product, ProductData
from app.services.product_payloads import (
    PRODUCT_LARGE_FIELDS_MIGRATION,
    SECTION_SPECS,
    persist_source_sections_from_projection,
)


def _copy(source: Path, root: Path, name: str) -> Path:
    target = root / name
    shutil.copy2(source, target)
    # The configured database may already be cut over. Recreate the migration-
    # before shape while preserving every legacy product row used as a fixture.
    conn = sqlite3.connect(target)
    try:
        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'product_large_fields_guard_%'"
        ).fetchall()
        for (trigger_name,) in triggers:
            conn.execute(f'DROP TRIGGER "{trigger_name}"')
        for spec in SECTION_SPECS.values():
            conn.execute(f'DROP TABLE IF EXISTS "{spec.model.__tablename__}"')
        conn.execute("DROP TABLE IF EXISTS product_large_field_migration_items")
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone():
            conn.execute(
                "DELETE FROM schema_migrations WHERE version=?",
                (PRODUCT_LARGE_FIELDS_MIGRATION,),
            )
        conn.commit()
    finally:
        conn.close()
    return target


def _first_mindset_reference(db_path: Path) -> tuple[int, dict[str, str]]:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT product_id,customer_mindset FROM product_data "
            "WHERE customer_mindset LIKE '%customer_mindset_local_file_ref_v1%' LIMIT 1"
        ).fetchone()
        assert row, "fixture has no local-file mindset reference"
        return int(row[0]), __import__("json").loads(row[1])
    finally:
        conn.close()


def _assert_failed_without_marker(target: Path, root: Path) -> None:
    try:
        migrate(target, root / "failed-backups")
    except (RuntimeError, ValueError):
        pass
    else:
        raise AssertionError("invalid migration fixture unexpectedly succeeded")
    conn = sqlite3.connect(target)
    try:
        marker_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if marker_table:
            assert conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=?",
                (PRODUCT_LARGE_FIELDS_MIGRATION,),
            ).fetchone() is None
    finally:
        conn.close()


async def _assert_new_product_source_persistence(target: Path) -> None:
    """A pending ProductData INSERT must not autoflush guarded blob columns."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{target}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    product_id: int | None = None
    try:
        async with session_factory() as db:
            @event.listens_for(db.sync_session, "before_flush")
            def _assert_legacy_source_columns_are_clear(session, _flush_context, _instances) -> None:
                for row in session.new:
                    if isinstance(row, ProductData):
                        assert all(
                            getattr(row, field) is None
                            for field in ("packages", "features", "description", "variants", "gigab2b_raw_snapshot")
                        )

            product = Product(
                gigab2b_url="migration-runtime-source-test",
                brand="migration-test",
                status="created",
                current_step=0,
            )
            db.add(product)
            await db.flush()
            product_id = int(product.id)
            data = ProductData(product_id=product_id, item_code="runtime-source-test")
            data.packages = json.dumps([{"code": "runtime-source-test"}])
            data.features = json.dumps(["feature"])
            data.description = "description"
            data.variants = json.dumps([{"sku": "runtime-source-test"}])
            data.gigab2b_raw_snapshot = json.dumps({"source": "runtime-test"})
            db.add(data)
            await persist_source_sections_from_projection(db, data)
            await db.commit()
    finally:
        await engine.dispose()

    assert product_id is not None
    conn = sqlite3.connect(target)
    try:
        legacy = conn.execute(
            "SELECT packages,features,description,variants,gigab2b_raw_snapshot "
            "FROM product_data WHERE product_id=?",
            (product_id,),
        ).fetchone()
        assert legacy == (None, None, None, None, None), legacy
        source = json.loads(
            conn.execute(
                "SELECT payload_json FROM product_source_payload WHERE product_id=?",
                (product_id,),
            ).fetchone()[0]
        )
        snapshot = json.loads(
            conn.execute(
                "SELECT payload_json FROM product_source_snapshot WHERE product_id=?",
                (product_id,),
            ).fetchone()[0]
        )
        assert source["features"] == ["feature"]
        assert snapshot == {"source": "runtime-test"}
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM product_data WHERE product_id=?", (product_id,))
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    source = settings.SQLITE_DATABASE_PATH
    if not source.is_file():
        raise RuntimeError(f"local SQLite database missing: {source}")
    with tempfile.TemporaryDirectory(prefix="fbm-large-fields-test-") as directory:
        root = Path(directory)
        target = _copy(source, root, "pipeline.db")
        backup = migrate(target, root / "backups")
        report = verify(target, strict=True)
        assert report["ok"], report
        assert len(report["sections"]) == 11
        conn = sqlite3.connect(target)
        try:
            assert conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (PRODUCT_LARGE_FIELDS_MIGRATION,)).fetchone()
            # A duplicate run preserves content revisions when hashes match.
            revision = conn.execute("SELECT content_revision FROM product_customer_mindset WHERE status='ready' LIMIT 1").fetchone()[0]
            try:
                conn.execute("UPDATE product_data SET customer_mindset='{}' WHERE customer_mindset IS NOT NULL LIMIT 1")
            except sqlite3.DatabaseError:
                pass
            else:
                raise AssertionError("legacy write guard did not reject customer_mindset update")
            conn.execute("PRAGMA foreign_keys=ON")
            insert_product = conn.execute("INSERT INTO products(gigab2b_url,brand,status,current_step,created_at,updated_at) VALUES('migration-insert-guard','migration-test','created',0,'now','now')").lastrowid
            try:
                conn.execute("INSERT INTO product_data(product_id,customer_mindset) VALUES(?, '{}')", (insert_product,))
            except sqlite3.DatabaseError:
                pass
            else:
                raise AssertionError("legacy write guard did not reject customer_mindset insert")
            conn.execute("INSERT INTO product_data(product_id,item_code) VALUES(?, 'guard-hot-field-ok')", (insert_product,))
            # Existing products have many non-cascading operational references;
            # prove the new 1:1 FK itself with an isolated product instead.
            cursor = conn.execute("INSERT INTO products(gigab2b_url,brand,status,current_step,created_at,updated_at) VALUES('migration-cascade-test','migration-test','created',0,'now','now')")
            product_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO product_source_payload(product_id,schema_version,content_revision,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (product_id, "test", 1, "ready", "now", "now"),
            )
            conn.execute("DELETE FROM products WHERE id=?", (product_id,))
            assert conn.execute("SELECT 1 FROM product_source_payload WHERE product_id=?", (product_id,)).fetchone() is None
            conn.execute("DELETE FROM product_data WHERE product_id=?", (insert_product,))
            conn.execute("DELETE FROM products WHERE id=?", (insert_product,))
        finally:
            conn.close()
        asyncio.run(_assert_new_product_source_persistence(target))
        migrate(target, root / "second-backup")
        conn = sqlite3.connect(target)
        try:
            assert conn.execute("SELECT content_revision FROM product_customer_mindset WHERE status='ready' LIMIT 1").fetchone()[0] == revision
        finally:
            conn.close()
        # Restore is exact and does not delete old fields or files.
        rollback(backup, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == hashlib.sha256(backup.read_bytes()).hexdigest()

        direct = _copy(source, root, "direct-json.db")
        product_id, reference = _first_mindset_reference(direct)
        body = Path(reference["path"]).read_text(encoding="utf-8")
        conn = sqlite3.connect(direct)
        try:
            conn.execute("UPDATE product_data SET customer_mindset=? WHERE product_id=?", (body, product_id))
            conn.commit()
        finally:
            conn.close()
        migrate(direct, root / "direct-backup")
        assert verify(direct, strict=True)["ok"]

        missing = _copy(source, root, "missing-mindset.db")
        product_id, reference = _first_mindset_reference(missing)
        reference["path"] = str(root / "does-not-exist.json")
        conn = sqlite3.connect(missing)
        try:
            conn.execute("UPDATE product_data SET customer_mindset=? WHERE product_id=?", (__import__("json").dumps(reference), product_id))
            conn.commit()
        finally:
            conn.close()
        _assert_failed_without_marker(missing, root)

        mismatch = _copy(source, root, "mindset-hash-mismatch.db")
        product_id, reference = _first_mindset_reference(mismatch)
        reference["sha256"] = "0" * 64
        conn = sqlite3.connect(mismatch)
        try:
            conn.execute("UPDATE product_data SET customer_mindset=? WHERE product_id=?", (__import__("json").dumps(reference), product_id))
            conn.commit()
        finally:
            conn.close()
        _assert_failed_without_marker(mismatch, root)

        invalid = _copy(source, root, "invalid-json.db")
        conn = sqlite3.connect(invalid)
        try:
            conn.execute("UPDATE product_data SET packages='{' WHERE product_id=(SELECT product_id FROM product_data LIMIT 1)")
            conn.commit()
        finally:
            conn.close()
        _assert_failed_without_marker(invalid, root)


if __name__ == "__main__":
    main()
