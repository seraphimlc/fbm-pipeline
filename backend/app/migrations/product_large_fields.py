"""One-time SQLite migration for product large fields.

Run this only in the maintenance window, with API and workers stopped.  It is
intentionally a stdlib sqlite3 program so the backup and exclusive-lock
semantics are unambiguous and it cannot accidentally target MySQL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.pipeline.customer_mindset import load_customer_mindset
from app.services.product_payloads import PRODUCT_LARGE_FIELDS_MIGRATION, SECTION_SPECS, payload_hash


LEGACY_COLUMNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "source": ("product_data", ("packages", "features", "description", "variants")),
    "source_snapshot": ("product_data", ("gigab2b_raw_snapshot",)),
    "mindset": ("product_data", ("customer_mindset",)),
    "listing": ("product_data", ("listing_title", "listing_bullets", "listing_product_highlights", "listing_search_terms", "listing_title_zh", "listing_bullets_zh", "listing_product_highlights_zh", "listing_description", "listing_description_zh", "listing_search_terms_zh", "listing_check", "listing_primary_keyword", "listing_removed_keywords")),
    "image_analysis": ("product_images", ("image_analysis", "image_selling_points")),
    "image_selection": ("product_images", ("image_selection_analysis",)),
    "image_compliance": ("product_images", ("image_compliance_manifest",)),
    "aplus_plan": ("product_aplus", ("aplus_plan",)),
    "aplus_script": ("product_aplus", ("aplus_scripts",)),
    "aplus_assets": ("product_aplus", ("aplus_images",)),
    "export_artifact": ("product_data", ("amazon_template_path", "amazon_template_warnings", "amazon_template_fill_summary")),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _payload_for(section: str, row: sqlite3.Row) -> tuple[Any | None, dict[str, Any]]:
    table, columns = LEGACY_COLUMNS[section]
    values = {column: row[column] for column in columns}
    if not any(value not in (None, "") for value in values.values()):
        return None, {}
    if section == "mindset":
        try:
            payload = load_customer_mindset(values["customer_mindset"], required=True)
        except Exception as exc:  # noqa: BLE001 - surface as a strict migration result
            return None, {"error_code": f"mindset_unresolved:{type(exc).__name__}"}
        questions = payload.get("questions") if isinstance(payload, dict) else []
        quality = payload.get("quality") if isinstance(payload, dict) else {}
        return payload, {
            "question_count": len(questions) if isinstance(questions, list) else 0,
            "fixed_question_count": sum(1 for item in questions if isinstance(item, dict) and item.get("question_type") == "fixed"),
            "dynamic_question_count": sum(1 for item in questions if isinstance(item, dict) and item.get("question_type") == "dynamic"),
            "requires_review": int(bool(quality.get("requires_review"))) if isinstance(quality, dict) else 0,
        }
    if section in {"source", "listing", "image_analysis", "export_artifact"}:
        payload = {key: _parse_json(value) if key not in {"description", "listing_title", "listing_search_terms", "listing_title_zh", "listing_description", "listing_description_zh", "listing_search_terms_zh", "listing_primary_keyword", "amazon_template_path"} else value for key, value in values.items()}
    else:
        payload = _parse_json(next(iter(values.values())))
    extras: dict[str, Any] = {}
    if section == "image_analysis":
        extras = {"analysis_count": len(payload.get("image_analysis") or []) if isinstance(payload, dict) else 0, "model_name": row["vlm_model"] if "vlm_model" in row.keys() else None}
    elif section == "image_selection":
        extras = {"selected_count": len(payload.get("selected_images") or []) if isinstance(payload, dict) else 0}
    elif section in {"aplus_plan", "aplus_script"}:
        extras = {"summary": row["aplus_plan_summary" if section == "aplus_plan" else "aplus_scripts_summary"] if ("aplus_plan_summary" if section == "aplus_plan" else "aplus_scripts_summary") in row.keys() else None}
    elif section == "aplus_assets":
        extras = {"asset_count": row["aplus_image_count"] if "aplus_image_count" in row.keys() else 0}
    elif section == "export_artifact":
        warnings = payload.get("amazon_template_warnings") if isinstance(payload, dict) else None
        extras = {"artifact_path": values.get("amazon_template_path"), "warning_count": len(warnings) if isinstance(warnings, list) else 0}
    return payload, extras


def _create_control_tables(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT, details_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS product_large_field_migration_items (product_id INTEGER NOT NULL, section TEXT NOT NULL, source_sha256 TEXT, state TEXT NOT NULL, error_code TEXT, migrated_at TEXT NOT NULL, PRIMARY KEY(product_id, section))")


def _create_payload_tables(conn: sqlite3.Connection) -> None:
    # The SQL is generated from the canonical section map so all tables share the base contract.
    extras = {
        "mindset": "question_count INTEGER, fixed_question_count INTEGER, dynamic_question_count INTEGER, requires_review INTEGER, artifact_path TEXT",
        "image_analysis": "analysis_count INTEGER, model_name TEXT",
        "image_selection": "selected_count INTEGER",
        "aplus_plan": "summary TEXT",
        "aplus_script": "summary TEXT",
        "aplus_assets": "asset_count INTEGER",
        "export_artifact": "artifact_path TEXT, template_key TEXT, risk_level TEXT, warning_count INTEGER",
    }
    base = "product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE, payload_json TEXT, schema_version TEXT NOT NULL, content_revision INTEGER NOT NULL DEFAULT 1, input_fingerprint TEXT, content_sha256 TEXT, content_bytes INTEGER, status TEXT NOT NULL DEFAULT 'ready', source_task_run_id INTEGER, error_code TEXT, generated_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL"
    for section, spec in SECTION_SPECS.items():
        suffix = ", " + extras[section] if section in extras else ""
        conn.execute(f"CREATE TABLE IF NOT EXISTS {spec.model.__tablename__} ({base}{suffix})")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_product_export_artifact_risk_level ON product_export_artifact(risk_level)")


def _install_legacy_write_guards(conn: sqlite3.Connection) -> None:
    """Reject new or changed legacy blobs without blocking hot-field writes."""
    for section, (table, columns) in LEGACY_COLUMNS.items():
        for column in columns:
            update_trigger = f"product_large_fields_guard_{table}_{column}_update"
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {update_trigger} BEFORE UPDATE OF {column} ON {table} "
                f"WHEN NEW.{column} IS NOT OLD.{column} "
                f"BEGIN SELECT RAISE(ABORT, 'legacy large field is read-only; write {section} payload'); END"
            )
            insert_trigger = f"product_large_fields_guard_{table}_{column}_insert"
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {insert_trigger} BEFORE INSERT ON {table} "
                f"WHEN NEW.{column} IS NOT NULL "
                f"BEGIN SELECT RAISE(ABORT, 'legacy large field is read-only; write {section} payload'); END"
            )


def _source_rows(conn: sqlite3.Connection, section: str) -> list[sqlite3.Row]:
    table, _ = LEGACY_COLUMNS[section]
    return conn.execute(f"SELECT * FROM {table}").fetchall()


def preflight(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        raise RuntimeError(f"SQLite database does not exist: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"products", "product_data", "product_images", "product_aplus"}
        missing = sorted(required - tables)
        if missing:
            raise RuntimeError(f"missing required tables: {', '.join(missing)}")
        result = {"database": str(db_path), "products": conn.execute("SELECT count(*) FROM products").fetchone()[0], "sections": {}}
        for section in LEGACY_COLUMNS:
            result["sections"][section] = len(_source_rows(conn, section))
        return result
    finally:
        conn.close()


def _backup(conn: sqlite3.Connection, db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"{db_path.stem}.before-product-large-fields-{datetime.now().strftime('%Y%m%d%H%M%S%f')}.db"
    target = sqlite3.connect(destination)
    try:
        conn.backup(target)
    finally:
        target.close()
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    os.chmod(destination, 0o600)
    os.chmod(destination.with_suffix(destination.suffix + ".sha256"), 0o600)
    return destination


def migrate(db_path: Path, backup_dir: Path) -> Path:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    # sqlite3.Connection.backup() cannot progress while this same connection
    # owns an EXCLUSIVE write transaction.  The maintenance window has stopped
    # writers; checkpoint and take the backup first, then acquire EXCLUSIVE for
    # every schema/data mutation below.
    backup = _backup(conn, db_path, backup_dir)
    conn.execute("BEGIN EXCLUSIVE")
    try:
        _create_control_tables(conn)
        _create_payload_tables(conn)
        unresolved = 0
        for section, spec in SECTION_SPECS.items():
            for row in _source_rows(conn, section):
                payload, extras = _payload_for(section, row)
                target = spec.model.__tablename__
                if extras.get("error_code"):
                    unresolved += 1
                    conn.execute(f"INSERT INTO {target}(product_id,schema_version,status,error_code,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET status=excluded.status,error_code=excluded.error_code,updated_at=excluded.updated_at", (row["product_id"], spec.schema_version, "unresolved", extras["error_code"], _now(), _now()))
                    conn.execute("INSERT INTO product_large_field_migration_items VALUES(?,?,?,?,?,?) ON CONFLICT(product_id,section) DO UPDATE SET state=excluded.state,error_code=excluded.error_code,migrated_at=excluded.migrated_at", (row["product_id"], section, None, "unresolved", extras["error_code"], _now()))
                    continue
                if payload is None:
                    continue
                digest, bytes_count, serialized = payload_hash(payload)
                previous = conn.execute(f"SELECT content_sha256 FROM {target} WHERE product_id=?", (row["product_id"],)).fetchone()
                if previous and previous[0] == digest:
                    continue
                columns = ["product_id", "payload_json", "schema_version", "content_revision", "content_sha256", "content_bytes", "status", "generated_at", "created_at", "updated_at"]
                values: list[Any] = [row["product_id"], serialized, spec.schema_version, 1, digest, bytes_count, "ready", _now(), _now(), _now()]
                for key, value in extras.items():
                    if key != "error_code": columns.append(key); values.append(value)
                update = ", ".join(f"{name}=excluded.{name}" for name in columns if name not in {"product_id", "content_revision", "created_at"})
                conn.execute(f"INSERT INTO {target}({','.join(columns)}) VALUES({','.join('?' for _ in columns)}) ON CONFLICT(product_id) DO UPDATE SET {update}, content_revision={target}.content_revision + 1", values)
                conn.execute("INSERT INTO product_large_field_migration_items VALUES(?,?,?,?,?,?) ON CONFLICT(product_id,section) DO UPDATE SET source_sha256=excluded.source_sha256,state=excluded.state,error_code=NULL,migrated_at=excluded.migrated_at", (row["product_id"], section, digest, "ready", None, _now()))
        report = verify(conn, strict=True)
        if not report["ok"] or unresolved:
            raise RuntimeError("strict verification failed; migration marker was not written")
        _install_legacy_write_guards(conn)
        conn.execute("INSERT OR REPLACE INTO schema_migrations(version,applied_at,checksum,details_json) VALUES(?,?,?,?)", (PRODUCT_LARGE_FIELDS_MIGRATION, _now(), None, json.dumps(report, ensure_ascii=False)))
        conn.execute("COMMIT")
        return backup
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def verify(conn_or_path: sqlite3.Connection | Path, *, strict: bool) -> dict[str, Any]:
    close = not isinstance(conn_or_path, sqlite3.Connection)
    conn = sqlite3.connect(conn_or_path) if close else conn_or_path
    conn.row_factory = sqlite3.Row
    try:
        problems: list[str] = []
        sections: dict[str, Any] = {}
        for section, spec in SECTION_SPECS.items():
            table = spec.model.__tablename__
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                problems.append(f"missing {table}")
                continue
            bad_json = conn.execute(f"SELECT count(*) FROM {table} WHERE payload_json IS NOT NULL AND json_valid(payload_json)=0").fetchone()[0]
            unresolved = conn.execute(f"SELECT count(*) FROM {table} WHERE status='unresolved'").fetchone()[0]
            invalid_state = conn.execute(
                f"SELECT count(*) FROM {table} WHERE status NOT IN ('absent','processing','ready','failed','unresolved')"
            ).fetchone()[0]
            bad_schema = conn.execute(
                f"SELECT count(*) FROM {table} WHERE schema_version<>?", (spec.schema_version,)
            ).fetchone()[0]
            target_rows = conn.execute(
                f"SELECT product_id,payload_json,content_sha256,content_bytes,content_revision,status FROM {table}"
            ).fetchall()
            status_counts = {
                row[0]: row[1]
                for row in conn.execute(f"SELECT status,count(*) FROM {table} GROUP BY status").fetchall()
            }
            byte_total = sum(int(row[3] or 0) for row in target_rows)
            sections[section] = {
                "table": table,
                "rows": len(target_rows),
                "bytes": byte_total,
                "states": status_counts,
            }
            if bad_json:
                problems.append(f"{table}: invalid JSON={bad_json}")
            if invalid_state:
                problems.append(f"{table}: invalid state={invalid_state}")
            if bad_schema:
                problems.append(f"{table}: schema mismatch={bad_schema}")
            if strict and unresolved:
                problems.append(f"{table}: unresolved={unresolved}")

            target_by_product = {int(row[0]): row for row in target_rows}
            expected_count = 0
            for source_row in _source_rows(conn, section):
                try:
                    payload, extras = _payload_for(section, source_row)
                except Exception as exc:  # noqa: BLE001 - verification must report corrupt legacy input
                    problems.append(
                        f"{table}: source product {source_row['product_id']} invalid: {type(exc).__name__}"
                    )
                    continue
                if extras.get("error_code"):
                    if strict:
                        problems.append(
                            f"{table}: source product {source_row['product_id']} {extras['error_code']}"
                        )
                    continue
                if payload is None:
                    continue
                expected_count += 1
                target_row = target_by_product.get(int(source_row["product_id"]))
                if target_row is None:
                    problems.append(f"{table}: missing product {source_row['product_id']}")
                    continue
                digest, size, _ = payload_hash(payload)
                # Revision 1 is the migration copy. Later revisions are valid
                # canonical updates and must not be compared to frozen legacy data.
                if int(target_row[4] or 0) == 1 and (
                    target_row[2] != digest or int(target_row[3] or 0) != size
                ):
                    problems.append(f"{table}: source hash mismatch product {source_row['product_id']}")
            sections[section]["expected_source_rows"] = expected_count

            for target_row in target_rows:
                payload_json = target_row[1]
                if not payload_json:
                    if target_row[5] == "ready":
                        problems.append(f"{table}: ready row missing payload product {target_row[0]}")
                    continue
                encoded = payload_json.encode("utf-8")
                actual_digest = hashlib.sha256(encoded).hexdigest()
                if actual_digest != target_row[2] or len(encoded) != int(target_row[3] or 0):
                    problems.append(f"{table}: stored hash mismatch product {target_row[0]}")
        foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if foreign: problems.append(f"foreign_key_check={len(foreign)}")
        if integrity != "ok": problems.append(f"integrity_check={integrity}")
        if strict:
            expected_guards = 2 * sum(len(columns) for _, columns in LEGACY_COLUMNS.values())
            actual_guards = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'product_large_fields_guard_%'").fetchone()[0]
            # Guards are installed just before the marker.  Allow their absence
            # while migrate runs its pre-marker strict check.
            marker = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
            applied = marker and conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (PRODUCT_LARGE_FIELDS_MIGRATION,)).fetchone()
            if applied and actual_guards != expected_guards:
                problems.append(f"legacy write guards={actual_guards}/{expected_guards}")
        return {
            "ok": not problems,
            "problems": problems,
            "integrity": integrity,
            "foreign_key_violations": len(foreign),
            "sections": sections,
        }
    finally:
        if close: conn.close()


def rollback(backup: Path, db_path: Path) -> None:
    if not backup.is_file(): raise RuntimeError(f"backup not found: {backup}")
    expected = backup.with_suffix(backup.suffix + ".sha256")
    if expected.is_file() and expected.read_text(encoding="ascii").split()[0] != hashlib.sha256(backup.read_bytes()).hexdigest():
        raise RuntimeError("backup SHA-256 mismatch")
    shutil.copy2(backup, db_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "migrate", "verify", "rollback"))
    parser.add_argument("--db", type=Path, default=settings.SQLITE_DATABASE_PATH)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.command == "preflight": print(json.dumps(preflight(args.db), ensure_ascii=False, indent=2)); return 0
    if args.command == "migrate":
        if not args.confirm or not args.backup_dir: parser.error("migrate requires --backup-dir and --confirm")
        print(migrate(args.db, args.backup_dir)); return 0
    if args.command == "verify":
        report = verify(args.db, strict=args.strict); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["ok"] else 2
    if not args.backup: parser.error("rollback requires --backup")
    rollback(args.backup, args.db); return 0


if __name__ == "__main__":
    sys.exit(main())
