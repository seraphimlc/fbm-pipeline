"""Protected local-MySQL execution support for Legacy inventory evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import ContractError, canonical_json_bytes, canonical_sha256_hex
from .database_source_manifest import (
    DATABASE_SOURCE_MANIFEST_GENERATION,
    DATABASE_SOURCE_MANIFEST_SCHEMA,
    LEGACY_PROJECTION_VERSION,
    database_source_manifest_sha256,
    detached_database_source_manifest_digest,
    parse_and_verify_database_source_manifest,
    serialize_database_source_manifest_body,
    verify_backup_sha256_binding,
)
from .legacy_inventory import (
    LEGACY_WORKFLOW_NODES,
    LEGACY_WORKFLOW_STATUSES,
    LegacyInventoryError,
    build_legacy_inventory,
    normalize_legacy_dataset,
)


class LegacyInventoryExecutionError(RuntimeError):
    """Raised when a protected local MySQL command cannot complete safely."""


class LegacyInventoryVerificationError(RuntimeError):
    """Raised when source and restored legacy facts differ."""


PROTECTED_SCHEMA_RE = re.compile(r"fbm_pipeline_ih_[0-9a-f]{16}_(?:source|target)\Z")
REQUIRED_TABLES = (
    "aplus_upload_items",
    "amazon_listing_captures",
    "amazon_stylesnap_candidates",
    "catalog_products",
    "product_data",
    "products",
)
MANIFEST_TABLES = (
    "aplus_upload_items",
    "amazon_listing_captures",
    "amazon_stylesnap_candidates",
    "catalog_products",
    "product_data",
    "products",
)
PROJECTION_IDS = (
    "amazon_listing_captures",
    "amazon_stylesnap_candidates",
    "aplus_upload_items.success",
    "catalog_products.downstream",
    "product_data.matching_and_template",
    "products.workflow",
)
TASK_TABLE_COLUMNS = {
    "task_runs": ("id", "title"),
    "task_steps": ("id", "task_run_id"),
}


def _protected_schema(schema: str) -> str:
    if type(schema) is not str or PROTECTED_SCHEMA_RE.fullmatch(schema) is None:
        raise LegacyInventoryExecutionError(
            "schema must use the exact protected fbm_pipeline_ih_<nonce>_source|target form"
        )
    return schema


def _executable(path: str, *, name: str) -> str:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or candidate.name != name
        or not candidate.is_file()
        or not os.access(candidate, os.X_OK)
    ):
        raise LegacyInventoryExecutionError(f"{name} must be an absolute executable file")
    return str(candidate)


class LocalMySQL:
    """CLI-only client fixed to local TCP and protected temporary schemas."""

    def __init__(
        self,
        *,
        mysql_binary: str,
        mysqldump_binary: str,
        host: str = "127.0.0.1",
        port: int = 3306,
        user: str = "root",
        command_observer: Any = None,
    ) -> None:
        if host != "127.0.0.1":
            raise LegacyInventoryExecutionError("legacy inventory fixture requires host 127.0.0.1")
        if type(port) is not int or port != 3306:
            raise LegacyInventoryExecutionError("legacy inventory fixture requires local port 3306")
        if type(user) is not str or not user or any(character.isspace() for character in user):
            raise LegacyInventoryExecutionError("mysql user must be a non-empty token")
        self.mysql_binary = _executable(mysql_binary, name="mysql")
        self.mysqldump_binary = _executable(mysqldump_binary, name="mysqldump")
        self.host = host
        self.port = port
        self.user = user
        self.command_observer = command_observer

    def _connection_argv(self, executable: str) -> list[str]:
        return [
            executable,
            "--no-defaults",
            "--protocol=TCP",
            f"--host={self.host}",
            f"--port={self.port}",
            f"--user={self.user}",
        ]

    def _run(
        self,
        argv: list[str],
        *,
        input_bytes: bytes | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[bytes]:
        if any("password" in token.lower() or "credential" in token.lower() for token in argv):
            raise LegacyInventoryExecutionError("credentials are forbidden in legacy inventory argv")
        if self.command_observer is not None:
            self.command_observer(argv)
        result = subprocess.run(
            argv,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                key: value
                for key, value in os.environ.items()
                if key not in {"DATABASE_URL", "MYSQL_PWD", "MYSQL_TEST_LOGIN_FILE"}
            },
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise LegacyInventoryExecutionError(
                f"local MySQL command failed with exit {result.returncode}: {stderr[:500]}"
            )
        return result

    def query_lines(self, sql: str) -> list[str]:
        argv = self._connection_argv(self.mysql_binary) + [
            "--batch",
            "--raw",
            "--skip-column-names",
            "--execute",
            sql,
        ]
        result = self._run(argv)
        text = result.stdout.decode("utf-8", errors="strict")
        return [line for line in text.splitlines() if line]

    def execute_sql(self, sql: str) -> None:
        argv = self._connection_argv(self.mysql_binary)
        self._run(argv, input_bytes=sql.encode("utf-8"))

    def list_protected_schemas(self) -> list[str]:
        rows = self.query_lines(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
            "WHERE SCHEMA_NAME REGEXP '^fbm_pipeline_ih_[0-9a-f]{16}_(source|target)$' "
            "ORDER BY SCHEMA_NAME"
        )
        return rows

    def server_facts(self) -> dict[str, str]:
        rows = self.query_lines("SELECT VERSION(), @@server_uuid")
        if len(rows) != 1 or "\t" not in rows[0]:
            raise LegacyInventoryExecutionError("unable to read local MySQL server facts")
        version, server_uuid = rows[0].split("\t", 1)
        return {"server_version": version, "server_uuid": server_uuid.lower()}

    def create_empty_schema(self, schema: str) -> None:
        schema = _protected_schema(schema)
        self.execute_sql(
            f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        )

    def load_fixture(self, schema: str, fixture_sql: str) -> None:
        schema = _protected_schema(schema)
        if type(fixture_sql) is not str or not fixture_sql.strip():
            raise LegacyInventoryExecutionError("fixture load SQL must be non-empty")
        if re.search(r"\b(?:CREATE|DROP)\s+(?:DATABASE|SCHEMA)\b", fixture_sql, re.IGNORECASE):
            raise LegacyInventoryExecutionError(
                "fixture load SQL must not allocate or drop a database schema"
            )
        self.execute_sql(fixture_sql)

    def drop_schema(self, schema: str) -> None:
        schema = _protected_schema(schema)
        self.execute_sql(f"DROP DATABASE IF EXISTS `{schema}`;")

    def table_names(self, schema: str) -> list[str]:
        schema = _protected_schema(schema)
        rows = self.query_lines(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA = '{schema}' ORDER BY TABLE_NAME"
        )
        return rows

    def table_state_snapshot(self, schema: str, tables: tuple[str, ...]) -> dict[str, Any]:
        schema = _protected_schema(schema)
        if set(tables) != set(TASK_TABLE_COLUMNS):
            raise LegacyInventoryExecutionError(
                "task state snapshot requires task_runs and task_steps"
            )
        actual_tables = set(self.table_names(schema))
        missing = sorted(set(tables) - actual_tables)
        if missing:
            raise LegacyInventoryVerificationError(f"side-effect sentinel tables missing: {missing}")
        rows_by_table: dict[str, list[dict[str, Any]]] = {}
        for table in sorted(tables):
            columns = TASK_TABLE_COLUMNS[table]
            json_fields = ", ".join(f"'{column}', `{column}`" for column in columns)
            query = (
                f"SELECT JSON_OBJECT({json_fields}) FROM `{schema}`.`{table}` ORDER BY `id`"
            )
            parsed_rows = []
            for line in self.query_lines(query):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LegacyInventoryExecutionError(
                        f"{table}: MySQL returned invalid task-state JSON row"
                    ) from exc
                parsed_rows.append(row)
            rows_by_table[table] = parsed_rows
        return build_task_table_state_snapshot(rows_by_table)

    def read_dataset(self, schema: str) -> dict[str, list[dict[str, Any]]]:
        schema = _protected_schema(schema)
        actual_tables = self.table_names(schema)
        missing = sorted(set(REQUIRED_TABLES) - set(actual_tables))
        if missing:
            raise LegacyInventoryVerificationError(f"required legacy fixture tables missing: {missing}")
        queries = {
            "products": (
                "SELECT JSON_OBJECT("
                "'id', id, 'gigab2b_product_id', gigab2b_product_id, "
                "'competitor_asin', competitor_asin, 'amazon_asin', amazon_asin, "
                "'aplus_upload_status', aplus_upload_status, "
                "'aplus_uploaded_at', aplus_uploaded_at, "
                "'aplus_upload_error', aplus_upload_error, "
                "'source_batch_id', source_batch_id, "
                "'source_site', source_site, 'workflow_node', workflow_node, "
                "'workflow_status', workflow_status, 'workflow_error', workflow_error) "
                f"FROM `{schema}`.`products` ORDER BY id"
            ),
            "product_data": (
                "SELECT JSON_OBJECT('id', id, 'product_id', product_id, 'item_code', item_code, "
                "'amazon_template_path', amazon_template_path, "
                "'amazon_template_generated_at', amazon_template_generated_at, "
                "'amazon_template_fill_summary', amazon_template_fill_summary, "
                "'amazon_template_warnings', amazon_template_warnings) "
                f"FROM `{schema}`.`product_data` ORDER BY id"
            ),
            "catalog_products": (
                "SELECT JSON_OBJECT('id', id, 'source_product_id', source_product_id, "
                "'amazon_asin', amazon_asin, 'confirmed_at', confirmed_at, "
                "'exported_at', exported_at, "
                "'export_task_id', export_task_id, 'export_file_path', export_file_path, "
                "'aplus_upload_status', aplus_upload_status, "
                "'aplus_uploaded_at', aplus_uploaded_at, "
                "'aplus_upload_error', aplus_upload_error) "
                f"FROM `{schema}`.`catalog_products` ORDER BY id"
            ),
            "aplus_upload_items": (
                "SELECT JSON_OBJECT('id', id, 'catalog_product_id', catalog_product_id, "
                "'product_id', product_id, 'amazon_asin', amazon_asin, "
                "'item_code', item_code, 'status', status, 'finished_at', finished_at) "
                f"FROM `{schema}`.`aplus_upload_items` ORDER BY id"
            ),
            "amazon_stylesnap_candidates": (
                "SELECT JSON_OBJECT("
                "'id', id, 'batch_id', batch_id, 'site', site, 'item_code', item_code, "
                "'sku_code', sku_code, 'rank', `rank`, 'asin', asin, "
                "'is_selected', is_selected, 'selected_at', selected_at, "
                "'capture_error', capture_error, 'captured_at', captured_at) "
                f"FROM `{schema}`.`amazon_stylesnap_candidates` ORDER BY id"
            ),
            "amazon_listing_captures": (
                "SELECT JSON_OBJECT("
                "'id', id, 'selected_candidate_id', selected_candidate_id, "
                "'batch_id', batch_id, 'site', site, 'item_code', item_code, "
                "'sku_code', sku_code, 'asin', asin, 'capture_status', capture_status, "
                "'capture_error', capture_error, 'captured_at', captured_at) "
                f"FROM `{schema}`.`amazon_listing_captures` ORDER BY id"
            ),
        }
        dataset: dict[str, list[dict[str, Any]]] = {}
        for table, query in queries.items():
            parsed_rows = []
            for line in self.query_lines(query):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LegacyInventoryExecutionError(
                        f"{table}: MySQL returned invalid JSON row"
                    ) from exc
                if type(row) is not dict:
                    raise LegacyInventoryExecutionError(f"{table}: MySQL JSON row is not an object")
                parsed_rows.append(row)
            dataset[table] = parsed_rows
        try:
            return normalize_legacy_dataset(dataset)
        except LegacyInventoryError as exc:
            raise LegacyInventoryExecutionError(str(exc)) from exc

    def dump_schema(self, schema: str, backup_path: Path) -> dict[str, str]:
        schema = _protected_schema(schema)
        argv = self._connection_argv(self.mysqldump_binary) + [
            "--single-transaction",
            "--set-gtid-purged=OFF",
            "--skip-comments",
            "--skip-dump-date",
            "--no-tablespaces",
            schema,
        ]
        result = self._run(argv, timeout=120)
        if not result.stdout:
            raise LegacyInventoryExecutionError("mysqldump produced an empty backup")
        backup_path.write_bytes(result.stdout)
        version = self._run([self.mysqldump_binary, "--version"]).stdout.decode(
            "utf-8", errors="strict"
        ).strip()
        return {
            "backup_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "tool_version": version,
        }

    def import_backup(self, schema: str, backup_path: Path) -> None:
        schema = _protected_schema(schema)
        argv = self._connection_argv(self.mysql_binary) + [schema]
        self._run(argv, input_bytes=backup_path.read_bytes(), timeout=120)

    def execute_in_schema(self, schema: str, sql: str) -> None:
        schema = _protected_schema(schema)
        argv = self._connection_argv(self.mysql_binary) + [schema]
        self._run(argv, input_bytes=sql.encode("utf-8"))


def _pk_bounds(rows: list[dict[str, Any]]) -> tuple[list[Any], list[Any]]:
    if not rows:
        return [None], [None]
    values = [row["id"] for row in rows]
    return [min(values)], [max(values)]


def build_task_table_state_snapshot(
    rows_by_table: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if type(rows_by_table) is not dict or set(rows_by_table) != set(TASK_TABLE_COLUMNS):
        raise LegacyInventoryVerificationError(
            "task state snapshot requires task_runs and task_steps"
        )
    snapshot: dict[str, Any] = {}
    for table in sorted(TASK_TABLE_COLUMNS):
        rows = rows_by_table[table]
        if type(rows) is not list:
            raise LegacyInventoryVerificationError(f"{table}: task state rows must be an array")
        expected_columns = set(TASK_TABLE_COLUMNS[table])
        normalized_rows = []
        seen_ids = set()
        for index, row in enumerate(rows):
            if type(row) is not dict or set(row) != expected_columns:
                raise LegacyInventoryVerificationError(
                    f"{table}[{index}]: task state row fields differ from fixture contract"
                )
            if type(row["id"]) is not int or row["id"] in seen_ids:
                raise LegacyInventoryVerificationError(
                    f"{table}[{index}].id: expected unique integer"
                )
            seen_ids.add(row["id"])
            if table == "task_runs" and type(row["title"]) is not str:
                raise LegacyInventoryVerificationError(
                    f"{table}[{index}].title: expected string"
                )
            if table == "task_steps" and type(row["task_run_id"]) is not int:
                raise LegacyInventoryVerificationError(
                    f"{table}[{index}].task_run_id: expected integer"
                )
            normalized_rows.append({column: row[column] for column in TASK_TABLE_COLUMNS[table]})
        normalized_rows.sort(key=lambda row: row["id"])
        ids = [row["id"] for row in normalized_rows]
        snapshot[table] = {
            "row_count": len(normalized_rows),
            "primary_key_min": min(ids) if ids else None,
            "primary_key_max": max(ids) if ids else None,
            "canonical_checksum_sha256": canonical_sha256_hex(normalized_rows),
        }
    return snapshot


def _workflow_projection(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "source_batch_id": row["source_batch_id"],
            "source_site": row["source_site"],
            "amazon_asin": row["amazon_asin"],
            "aplus_upload_status": row["aplus_upload_status"],
            "aplus_uploaded_at": row["aplus_uploaded_at"],
            "aplus_upload_error": row["aplus_upload_error"],
            "workflow_node": row["workflow_node"],
            "workflow_status": row["workflow_status"],
            "workflow_error": row["workflow_error"],
        }
        for row in products
        if row["workflow_node"] in LEGACY_WORKFLOW_NODES
        and row["workflow_status"] in LEGACY_WORKFLOW_STATUSES
    ]


def build_verification_snapshot(dataset: Any) -> dict[str, Any]:
    normalized = normalize_legacy_dataset(dataset)
    tables = {}
    for table in REQUIRED_TABLES:
        rows = normalized[table]
        primary_key_min, primary_key_max = _pk_bounds(rows)
        tables[table] = {
            "row_count": len(rows),
            "primary_key_min": primary_key_min,
            "primary_key_max": primary_key_max,
            "canonical_checksum_sha256": canonical_sha256_hex(rows),
        }
    projections = {
        "aplus_upload_items.success": [
            row for row in normalized["aplus_upload_items"] if row["status"] == "success"
        ],
        "amazon_listing_captures": normalized["amazon_listing_captures"],
        "amazon_stylesnap_candidates": normalized["amazon_stylesnap_candidates"],
        "catalog_products.downstream": normalized["catalog_products"],
        "product_data.matching_and_template": normalized["product_data"],
        "products.workflow": _workflow_projection(normalized["products"]),
    }
    return {
        "tables": tables,
        "projections": {
            projection_id: {
                "row_count": len(rows),
                "canonical_checksum_sha256": canonical_sha256_hex(rows),
            }
            for projection_id, rows in sorted(projections.items())
        },
    }


def verify_source_restore(source: dict[str, Any], restored: dict[str, Any]) -> dict[str, Any]:
    if source != restored:
        mismatches = []
        for scope in ("tables", "projections"):
            for key in sorted(set(source.get(scope, {})) | set(restored.get(scope, {}))):
                if source.get(scope, {}).get(key) != restored.get(scope, {}).get(key):
                    mismatches.append(f"{scope}.{key}")
        raise LegacyInventoryVerificationError(
            f"restored legacy facts differ from source: {mismatches}"
        )
    return {
        "verified": True,
        "table_count": len(source["tables"]),
        "projection_count": len(source["projections"]),
        "snapshot_sha256": canonical_sha256_hex(source),
    }


def build_source_manifest(
    *,
    source_schema: str,
    database_copy_id: str,
    server_facts: dict[str, str],
    verification_snapshot: dict[str, Any],
    backup_path: Path,
    backup_sha256: str,
    tool_version: str,
) -> dict[str, Any]:
    source_schema = _protected_schema(source_schema)
    archive_members = [
        {
            "relative_path": "database/legacy.sql",
            "size_bytes": backup_path.stat().st_size,
            "sha256": backup_sha256,
        }
    ]
    snapshot_position = {"kind": "fixture_copy", "value": database_copy_id}
    table_snapshots = []
    for table in MANIFEST_TABLES:
        facts = verification_snapshot["tables"][table]
        table_snapshots.append(
            {
                "table_name": table,
                "row_count": facts["row_count"],
                "primary_key_columns": ["id"],
                "primary_key_min": facts["primary_key_min"],
                "primary_key_max": facts["primary_key_max"],
                "canonical_checksum_sha256": facts["canonical_checksum_sha256"],
            }
        )
    projection_snapshots = []
    for projection_id in PROJECTION_IDS:
        facts = verification_snapshot["projections"][projection_id]
        projection_snapshots.append(
            {
                "projection_id": projection_id,
                "projection_version": LEGACY_PROJECTION_VERSION,
                "row_count": facts["row_count"],
                "canonical_checksum_sha256": facts["canonical_checksum_sha256"],
            }
        )
    body = {
        "schema": DATABASE_SOURCE_MANIFEST_SCHEMA,
        "generation": DATABASE_SOURCE_MANIFEST_GENERATION,
        "source": {
            "server_uuid": server_facts["server_uuid"],
            "server_version": server_facts["server_version"],
            "source_schema": source_schema,
            "snapshot_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        },
        "table_snapshots": sorted(table_snapshots, key=lambda item: item["table_name"]),
        "projection_snapshots": sorted(
            projection_snapshots, key=lambda item: item["projection_id"]
        ),
        "backup": {
            "dump_mode": "logical_single_transaction",
            "tool": {
                "name": "mysqldump",
                "version": tool_version,
                "argv_safe_summary": [
                    "mysqldump",
                    "--single-transaction",
                    "--set-gtid-purged=OFF",
                ],
            },
            "backup_sha256": backup_sha256,
            "archive_members": archive_members,
            "archive_member_manifest_sha256": canonical_sha256_hex(archive_members),
            "snapshot_position": dict(snapshot_position),
        },
        "consistency_proof": {
            "proof_mode": "fixture_quiesced_logical_backup",
            "manifest_snapshot_position": dict(snapshot_position),
            "writer_quiesced": True,
            "global_read_lock_held": False,
            "storage_snapshot_id": None,
        },
    }
    serialize_database_source_manifest_body(body)
    return body


def verify_manifest_and_backup(
    manifest: dict[str, Any], backup_path: Path
) -> dict[str, Any]:
    body_bytes = serialize_database_source_manifest_body(manifest)
    digest_bytes = detached_database_source_manifest_digest(manifest)
    parsed = parse_and_verify_database_source_manifest(body_bytes, digest_bytes)
    backup_sha256 = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    verify_backup_sha256_binding(parsed, backup_sha256)
    return {
        "source_manifest_sha256": database_source_manifest_sha256(parsed),
        "backup_sha256": backup_sha256,
        "manifest_body_bytes": body_bytes,
        "manifest_digest_bytes": digest_bytes,
    }


def expect_contract_failure(callable_object: Any, *, label: str) -> None:
    try:
        callable_object()
    except (ContractError, LegacyInventoryVerificationError):
        return
    raise LegacyInventoryVerificationError(f"negative check did not fail closed: {label}")
