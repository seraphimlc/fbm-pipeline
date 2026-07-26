#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr
import json
import hashlib
from io import StringIO
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON = "/usr/bin/python3"
MYSQL = "/opt/homebrew/bin/mysql"
MYSQLDUMP = "/opt/homebrew/bin/mysqldump"
COMMAND = ROOT / "scripts" / "integration_hardening" / "legacy_migration.py"
BACKUP_PROGRESS_LINES = [
    "backup_inventory phase=preflight",
    "backup_inventory phase=source_import",
    "backup_inventory phase=source_inventory",
    "backup_inventory phase=canonical_dump",
    "backup_inventory phase=target_import",
    "backup_inventory phase=verification",
    "backup_inventory phase=cleanup",
    "backup_inventory phase=evidence_write",
    "backup_inventory phase=completed",
]
sys.path.insert(0, str(ROOT / "scripts"))

from integration_hardening import legacy_migration  # noqa: E402
from integration_hardening import legacy_inventory_mysql  # noqa: E402
from integration_hardening.common import canonical_json_bytes  # noqa: E402
from integration_hardening.legacy_inventory_mysql import (  # noqa: E402
    LegacyInventoryExecutionError,
    LegacyInventoryVerificationError,
    LocalMySQL,
)
from integration_hardening.legacy_run_evidence import (  # noqa: E402
    LegacyRunEvidenceError,
    verify_zero_side_effect_deltas,
)
from integration_hardening.legacy_inventory_fixture import (  # noqa: E402
    _sql_literal,
    build_fixture_dataset,
)


def fixture_args() -> argparse.Namespace:
    return argparse.Namespace(
        fixture_e2e=True,
        mysql_binary=MYSQL,
        mysqldump_binary=MYSQLDUMP,
        host="127.0.0.1",
        port=3306,
        user="root",
        candidate_sha="",
    )


def protected_schemas() -> list[str]:
    result = subprocess.run(
        [
            MYSQL,
            "--no-defaults",
            "--no-login-paths",
            "--protocol=TCP",
            "--host=127.0.0.1",
            "--port=3306",
            "--user=root",
            "--batch",
            "--raw",
            "--skip-column-names",
            "--execute",
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
            "WHERE SCHEMA_NAME REGEXP '^fbm_pipeline_ih_[0-9a-f]{16}_(source|target)$' "
            "ORDER BY SCHEMA_NAME",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={
            key: value
            for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
            if (value := os.environ.get(key)) is not None
        },
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return [line for line in result.stdout.splitlines() if line]


def local_mysql() -> LocalMySQL:
    return LocalMySQL(
        mysql_binary=MYSQL,
        mysqldump_binary=MYSQLDUMP,
        host="127.0.0.1",
        port=3306,
        user="root",
    )


def init_candidate_repo(repo: Path) -> str:
    repo.mkdir()
    (repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    commands = (
        ["git", "init"],
        ["git", "config", "user.email", "fixture@example.invalid"],
        ["git", "config", "user.name", "Fixture"],
        ["git", "add", "source.py"],
        ["git", "commit", "-m", "fixture"],
    )
    for argv in commands:
        result = subprocess.run(argv, cwd=repo, text=True, capture_output=True)
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def synthetic_historical_backup_sql() -> bytes:
    dataset = build_fixture_dataset()
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
        ),
        "product_data": legacy_inventory_mysql.INVENTORY_TABLE_COLUMNS["product_data"],
        "catalog_products": legacy_inventory_mysql.INVENTORY_TABLE_COLUMNS[
            "catalog_products"
        ],
        "aplus_upload_items": legacy_inventory_mysql.INVENTORY_TABLE_COLUMNS[
            "aplus_upload_items"
        ],
        "amazon_stylesnap_candidates": legacy_inventory_mysql.INVENTORY_TABLE_COLUMNS[
            "amazon_stylesnap_candidates"
        ],
        "amazon_listing_captures": legacy_inventory_mysql.INVENTORY_TABLE_COLUMNS[
            "amazon_listing_captures"
        ],
    }
    create_statements = {
        "products": (
            "CREATE TABLE `products` (`id` BIGINT NOT NULL PRIMARY KEY, "
            "`gigab2b_product_id` VARCHAR(50), `competitor_asin` VARCHAR(20), "
            "`amazon_asin` VARCHAR(20), `aplus_upload_status` VARCHAR(20), "
            "`aplus_uploaded_at` DATETIME, `aplus_upload_error` TEXT, "
            "`source_batch_id` VARCHAR(100), `source_site` VARCHAR(20)) ENGINE=InnoDB"
        ),
        "product_data": (
            "CREATE TABLE `product_data` (`id` BIGINT NOT NULL PRIMARY KEY, "
            "`product_id` BIGINT NOT NULL, `item_code` VARCHAR(100), "
            "`amazon_template_path` TEXT, `amazon_template_generated_at` DATETIME, "
            "`amazon_template_fill_summary` TEXT, `amazon_template_warnings` TEXT) ENGINE=InnoDB"
        ),
        "catalog_products": (
            "CREATE TABLE `catalog_products` (`id` BIGINT NOT NULL PRIMARY KEY, "
            "`source_product_id` BIGINT NOT NULL, `amazon_asin` VARCHAR(20), "
            "`confirmed_at` DATETIME, `exported_at` DATETIME, `export_task_id` BIGINT, "
            "`export_file_path` TEXT, `aplus_upload_status` VARCHAR(20), "
            "`aplus_uploaded_at` DATETIME, `aplus_upload_error` TEXT) ENGINE=InnoDB"
        ),
        "aplus_upload_items": (
            "CREATE TABLE `aplus_upload_items` (`id` BIGINT NOT NULL PRIMARY KEY, "
            "`catalog_product_id` BIGINT NOT NULL, `product_id` BIGINT NOT NULL, "
            "`amazon_asin` VARCHAR(20), `item_code` VARCHAR(100), "
            "`status` VARCHAR(20) NOT NULL, `finished_at` DATETIME) ENGINE=InnoDB"
        ),
        "amazon_stylesnap_candidates": (
            "CREATE TABLE `amazon_stylesnap_candidates` (`id` BIGINT NOT NULL PRIMARY KEY, "
            "`batch_id` VARCHAR(100) NOT NULL, `site` VARCHAR(20) NOT NULL, "
            "`item_code` VARCHAR(100) NOT NULL, `sku_code` VARCHAR(100) NOT NULL, "
            "`rank` INT NOT NULL, `asin` VARCHAR(20) NOT NULL, "
            "`is_selected` TINYINT NOT NULL, `selected_at` DATETIME, "
            "`capture_error` TEXT, `captured_at` DATETIME) ENGINE=InnoDB"
        ),
        "amazon_listing_captures": (
            "CREATE TABLE `amazon_listing_captures` (`id` BIGINT NOT NULL PRIMARY KEY, "
            "`selected_candidate_id` BIGINT NOT NULL, `batch_id` VARCHAR(100) NOT NULL, "
            "`site` VARCHAR(20) NOT NULL, `item_code` VARCHAR(100) NOT NULL, "
            "`sku_code` VARCHAR(100) NOT NULL, `asin` VARCHAR(20) NOT NULL, "
            "`capture_status` VARCHAR(30) NOT NULL, `capture_error` TEXT, "
            "`captured_at` DATETIME) ENGINE=InnoDB"
        ),
    }
    statements = [
        "/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */"
    ]
    for table in legacy_inventory_mysql.REQUIRED_TABLES:
        statements.append(f"DROP TABLE IF EXISTS `{table}`")
        statements.append(create_statements[table])
        columns = columns_by_table[table]
        values_sql = ",\n".join(
            "(" + ", ".join(_sql_literal(row[column]) for column in columns) + ")"
            for row in dataset[table]
        )
        statements.append(f"INSERT INTO `{table}` VALUES\n{values_sql}")
    statements.append("/*!40101 SET SQL_MODE=@OLD_SQL_MODE */")
    return (";\n".join(statements) + ";\n").encode("utf-8")


def backup_inventory_args(
    *,
    backup_path: Path,
    evidence_output: Path,
    candidate_sha: str,
) -> argparse.Namespace:
    return legacy_migration.parse_args(
        [
            "--backup-inventory",
            "--backup-path",
            str(backup_path),
            "--expected-backup-sha256",
            hashlib.sha256(backup_path.read_bytes()).hexdigest(),
            "--evidence-output",
            str(evidence_output),
            "--candidate-sha",
            candidate_sha,
            "--mysql-binary",
            MYSQL,
            "--mysqldump-binary",
            MYSQLDUMP,
            "--host",
            "127.0.0.1",
            "--port",
            "3306",
            "--user",
            "root",
            "--allow-passwordless-local",
        ]
    )


class FlushRecordingStringIO(StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


class LegacyInventoryMySQLE2ETests(unittest.TestCase):
    def test_synthetic_historical_backup_runner_succeeds_twice_with_private_evidence(
        self,
    ) -> None:
        before = protected_schemas()
        with tempfile.TemporaryDirectory(prefix="legacy_backup_runner_") as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            candidate_sha = init_candidate_repo(repo)
            backup_path = root / "historical.sql"
            backup_path.write_bytes(synthetic_historical_backup_sql())
            evidence_parent = root / "evidence"
            evidence_parent.mkdir(mode=0o700)
            summaries = []
            evidences = []
            for index in range(2):
                evidence_output = evidence_parent / f"run-{index}.json"
                actual_run = subprocess.run
                captured_processes: list[str] = []
                captured_clients: list[tuple[list[str], dict[str, str]]] = []
                progress = FlushRecordingStringIO()

                def recording_run(argv, *call_args, **call_kwargs):
                    if isinstance(argv, list) and argv:
                        captured_processes.append(Path(argv[0]).name)
                        if Path(argv[0]).name in {"mysql", "mysqldump"}:
                            captured_clients.append(
                                (list(argv), dict(call_kwargs.get("env", {})))
                            )
                    return actual_run(argv, *call_args, **call_kwargs)

                with redirect_stderr(progress), mock.patch(
                    "subprocess.run",
                    side_effect=recording_run,
                ):
                    summary = legacy_migration.run_backup_inventory(
                        backup_inventory_args(
                            backup_path=backup_path,
                            evidence_output=evidence_output,
                            candidate_sha=candidate_sha,
                        ),
                        repo_root=repo,
                        source_files=("source.py",),
                    )
                self.assertEqual(progress.getvalue().splitlines(), BACKUP_PROGRESS_LINES)
                self.assertEqual(progress.flush_count, len(BACKUP_PROGRESS_LINES))
                for private_fragment in (
                    str(root),
                    str(backup_path),
                    str(evidence_output),
                    "fbm_pipeline_ih_",
                    "records",
                    "B000000001",
                    "ITEM-COMPLETE",
                    "password",
                    "credential",
                    "Access denied",
                ):
                    self.assertNotIn(private_fragment, progress.getvalue())
                self.assertTrue(captured_clients)
                for argv, environment in captured_clients:
                    self.assertEqual(argv.count("--no-defaults"), 1)
                    self.assertEqual(argv.count("--no-login-paths"), 1)
                    self.assertNotIn("DATABASE_URL", environment)
                    self.assertNotIn("MYSQL_PWD", environment)
                    self.assertNotIn("MYSQL_TEST_LOGIN_FILE", environment)
                summaries.append(summary)
                evidences.append(json.loads(evidence_output.read_text(encoding="utf-8")))
                self.assertEqual(evidence_output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(
                    evidences[-1]["execution_boundary"]["observed"][
                        "process_counts"
                    ],
                    dict(sorted(Counter(captured_processes).items())),
                )

            self.assertEqual(
                summaries[0]["classification_counts"],
                summaries[1]["classification_counts"],
            )
            self.assertEqual(summaries[0]["records_sha256"], summaries[1]["records_sha256"])
            self.assertEqual(
                summaries[0]["source_snapshot_sha256"],
                summaries[1]["source_snapshot_sha256"],
            )
            for summary, evidence in zip(summaries, evidences):
                self.assertEqual(summary["status"], "completed")
                self.assertEqual(summary["scope"], "historical_archive_restore_inventory")
                self.assertTrue(summary["cleanup_success"])
                self.assertEqual(
                    evidence["compatibility_profile"]["products_workflow_columns"]["mode"],
                    "absent_as_null",
                )
                self.assertEqual(
                    evidence["mysql"]["server_version"],
                    evidence["backup"]["sanitizer"]["target_mysql_version"],
                )
                self.assertEqual(
                    hashlib.sha256(canonical_json_bytes(evidence)).hexdigest(),
                    summary["evidence_sha256"],
                )
                rendered_summary = json.dumps(summary, sort_keys=True)
                self.assertNotIn("B000000001", rendered_summary)
                self.assertNotIn("ITEM-COMPLETE", rendered_summary)
        self.assertEqual(protected_schemas(), before)

    def test_historical_shape_profile_maps_missing_workflow_to_null_and_tracks_task_absence(
        self,
    ) -> None:
        mysql = local_mysql()
        before = protected_schemas()
        schema = f"fbm_pipeline_ih_{uuid.uuid4().hex[:16]}_source"
        reservations = legacy_inventory_mysql.reserve_protected_schemas(mysql, (schema,))
        reservation = reservations[0]
        legacy_inventory_mysql.create_reserved_schema(mysql, reservation)
        try:
            from integration_hardening.legacy_inventory_fixture import build_fixture_sql

            mysql.load_fixture(schema, build_fixture_sql(schema))
            mysql.execute_in_schema(
                schema,
                "ALTER TABLE `products` DROP COLUMN `workflow_node`, "
                "DROP COLUMN `workflow_status`, DROP COLUMN `workflow_error`; "
                "DROP TABLE `task_steps`; DROP TABLE `task_runs`;",
            )
            read = mysql.read_dataset_with_profile(schema)
            profile = read["compatibility_profile"]
            self.assertEqual(
                profile["products_workflow_columns"]["mode"],
                "absent_as_null",
            )
            self.assertTrue(
                all(
                    product["workflow_node"] is None
                    and product["workflow_status"] is None
                    and product["workflow_error"] is None
                    for product in read["dataset"]["products"]
                )
            )
            absent = mysql.table_state_snapshot(schema, ("task_runs", "task_steps"))
            self.assertTrue(
                all(item["presence"] == "absent" for item in absent.values())
            )
            mysql.execute_in_schema(
                schema,
                "CREATE TABLE `task_runs` (`id` BIGINT PRIMARY KEY, `title` VARCHAR(200)); "
                "CREATE TABLE `task_steps` (`id` BIGINT PRIMARY KEY, `task_run_id` BIGINT);",
            )
            present = mysql.table_state_snapshot(schema, ("task_runs", "task_steps"))
            with self.assertRaises(LegacyRunEvidenceError):
                verify_zero_side_effect_deltas(
                    task_state_before=absent,
                    task_state_after=present,
                    step10_before=[],
                    step10_after=[],
                )
        finally:
            cleanup = legacy_inventory_mysql.cleanup_reserved_schemas(mysql, reservations)
        self.assertTrue(cleanup["success"], cleanup)
        self.assertEqual(protected_schemas(), before)

    def test_partial_workflow_and_other_required_column_loss_fail_closed(self) -> None:
        mysql = local_mysql()
        before = protected_schemas()
        schema = f"fbm_pipeline_ih_{uuid.uuid4().hex[:16]}_source"
        reservations = legacy_inventory_mysql.reserve_protected_schemas(mysql, (schema,))
        legacy_inventory_mysql.create_reserved_schema(mysql, reservations[0])
        try:
            from integration_hardening.legacy_inventory_fixture import build_fixture_sql

            mysql.load_fixture(schema, build_fixture_sql(schema))
            mysql.execute_in_schema(schema, "ALTER TABLE `products` DROP COLUMN `workflow_error`;")
            with self.assertRaisesRegex(
                LegacyInventoryVerificationError,
                "unsupported_legacy_shape",
            ):
                mysql.compatibility_profile(schema)
            mysql.execute_in_schema(
                schema,
                "ALTER TABLE `products` DROP COLUMN `workflow_node`, "
                "DROP COLUMN `workflow_status`;",
            )
            self.assertEqual(
                mysql.compatibility_profile(schema)["products_workflow_columns"]["mode"],
                "absent_as_null",
            )
            mysql.execute_in_schema(schema, "ALTER TABLE `products` DROP COLUMN `source_site`;")
            with self.assertRaisesRegex(
                LegacyInventoryVerificationError,
                "unsupported_legacy_shape",
            ):
                mysql.compatibility_profile(schema)
        finally:
            cleanup = legacy_inventory_mysql.cleanup_reserved_schemas(mysql, reservations)
        self.assertTrue(cleanup["success"], cleanup)
        self.assertEqual(protected_schemas(), before)

    def test_create_server_success_client_error_is_reconciled_and_cleaned(self) -> None:
        mysql = local_mysql()
        before = protected_schemas()
        schema = f"fbm_pipeline_ih_{uuid.uuid4().hex[:16]}_source"
        reservations = legacy_inventory_mysql.reserve_protected_schemas(mysql, (schema,))
        reservation = reservations[0]
        actual_create = mysql.create_empty_schema

        def create_then_disconnect(created_schema: str) -> None:
            self.assertTrue(reservation.creation_attempted)
            actual_create(created_schema)
            raise LegacyInventoryExecutionError("forced client disconnect")

        with mock.patch.object(mysql, "create_empty_schema", side_effect=create_then_disconnect):
            with self.assertRaisesRegex(
                LegacyInventoryExecutionError,
                "forced client disconnect",
            ):
                legacy_inventory_mysql.create_reserved_schema(mysql, reservation)
        self.assertTrue(reservation.creation_attempted)
        self.assertFalse(reservation.create_returned_success)
        self.assertTrue(reservation.reconciliation_succeeded)
        self.assertTrue(reservation.observed_present)
        cleanup = legacy_inventory_mysql.cleanup_reserved_schemas(mysql, reservations)
        self.assertTrue(cleanup["success"], cleanup)
        self.assertEqual(protected_schemas(), before)

    def test_reconciliation_failure_still_authorizes_owned_cleanup(self) -> None:
        mysql = local_mysql()
        before = protected_schemas()
        schema = f"fbm_pipeline_ih_{uuid.uuid4().hex[:16]}_target"
        reservations = legacy_inventory_mysql.reserve_protected_schemas(mysql, (schema,))
        reservation = reservations[0]
        actual_create = mysql.create_empty_schema

        def create_then_disconnect(created_schema: str) -> None:
            self.assertTrue(reservation.creation_attempted)
            actual_create(created_schema)
            raise LegacyInventoryExecutionError("primary create result unknown")

        with mock.patch.object(mysql, "create_empty_schema", side_effect=create_then_disconnect), mock.patch.object(
            mysql,
            "list_protected_schemas",
            side_effect=LegacyInventoryExecutionError("forced reconciliation failure"),
        ):
            with self.assertRaisesRegex(
                LegacyInventoryExecutionError,
                "primary create result unknown",
            ):
                legacy_inventory_mysql.create_reserved_schema(mysql, reservation)
        self.assertTrue(reservation.creation_attempted)
        self.assertFalse(reservation.reconciliation_succeeded)
        cleanup = legacy_inventory_mysql.cleanup_reserved_schemas(mysql, reservations)
        self.assertTrue(cleanup["success"], cleanup)
        self.assertEqual(protected_schemas(), before)

    def test_fixture_runner_source_create_unknown_result_is_owned_and_cleaned(self) -> None:
        mysql = local_mysql()
        before = protected_schemas()
        nonce = "a11ce00000000001"
        source_schema = f"fbm_pipeline_ih_{nonce}_source"
        target_schema = f"fbm_pipeline_ih_{nonce}_target"
        actual_create = LocalMySQL.create_empty_schema

        def source_create_then_disconnect(client: LocalMySQL, schema: str) -> None:
            actual_create(client, schema)
            if schema == source_schema:
                raise LegacyInventoryExecutionError("source create result unknown")

        try:
            with mock.patch.object(
                legacy_migration.uuid,
                "uuid4",
                return_value=SimpleNamespace(hex=nonce),
            ), mock.patch.object(
                LocalMySQL,
                "create_empty_schema",
                new=source_create_then_disconnect,
            ):
                with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                    legacy_migration.run_fixture_e2e(fixture_args())
            cleanup = caught.exception.summary["cleanup"]
            self.assertEqual(cleanup["creation_attempted_schemas"], [source_schema])
            self.assertEqual(cleanup["create_returned_success_schemas"], [])
            self.assertEqual(cleanup["observed_present_schemas"], [source_schema])
            self.assertEqual(cleanup["owned_schemas"], [source_schema])
            self.assertEqual(cleanup["generated_schema_residuals"], [])
            self.assertEqual(cleanup["cleanup_errors"], [])
            self.assertNotIn(source_schema, protected_schemas())
            self.assertNotIn(target_schema, protected_schemas())
        finally:
            for schema in (target_schema, source_schema):
                if schema in protected_schemas():
                    mysql.drop_schema(schema)
        self.assertEqual(protected_schemas(), before)

    def test_fixture_runner_target_create_unknown_result_is_owned_and_cleaned(self) -> None:
        mysql = local_mysql()
        before = protected_schemas()
        nonce = "b22ce00000000001"
        source_schema = f"fbm_pipeline_ih_{nonce}_source"
        target_schema = f"fbm_pipeline_ih_{nonce}_target"
        actual_create = LocalMySQL.create_empty_schema

        def target_create_then_disconnect(client: LocalMySQL, schema: str) -> None:
            actual_create(client, schema)
            if schema == target_schema:
                raise LegacyInventoryExecutionError("target create result unknown")

        try:
            with mock.patch.object(
                legacy_migration.uuid,
                "uuid4",
                return_value=SimpleNamespace(hex=nonce),
            ), mock.patch.object(
                LocalMySQL,
                "create_empty_schema",
                new=target_create_then_disconnect,
            ):
                with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                    legacy_migration.run_fixture_e2e(fixture_args())
            cleanup = caught.exception.summary["cleanup"]
            self.assertEqual(
                cleanup["creation_attempted_schemas"],
                [source_schema, target_schema],
            )
            self.assertEqual(
                cleanup["create_returned_success_schemas"],
                [source_schema],
            )
            self.assertEqual(
                cleanup["observed_present_schemas"],
                [source_schema, target_schema],
            )
            self.assertEqual(cleanup["owned_schemas"], [source_schema, target_schema])
            self.assertEqual(cleanup["generated_schema_residuals"], [])
            self.assertEqual(cleanup["cleanup_errors"], [])
            self.assertNotIn(source_schema, protected_schemas())
            self.assertNotIn(target_schema, protected_schemas())
        finally:
            for schema in (target_schema, source_schema):
                if schema in protected_schemas():
                    mysql.drop_schema(schema)
        self.assertEqual(protected_schemas(), before)

    def test_collision_is_never_reserved_and_cleanup_failure_is_reported(self) -> None:
        mysql = local_mysql()
        before = protected_schemas()
        collision = f"fbm_pipeline_ih_{uuid.uuid4().hex[:16]}_source"
        owned_nonce = uuid.uuid4().hex[:16]
        owned_source = f"fbm_pipeline_ih_{owned_nonce}_source"
        owned_target = f"fbm_pipeline_ih_{owned_nonce}_target"
        mysql.create_empty_schema(collision)
        try:
            with self.assertRaisesRegex(
                LegacyInventoryVerificationError,
                "protected_schema_collision",
            ):
                legacy_inventory_mysql.reserve_protected_schemas(mysql, (collision,))
            self.assertIn(collision, protected_schemas())

            reservations = legacy_inventory_mysql.reserve_protected_schemas(
                mysql,
                (owned_source, owned_target),
            )
            for reservation in reservations:
                legacy_inventory_mysql.create_reserved_schema(mysql, reservation)
            actual_drop = mysql.drop_schema
            drop_order: list[str] = []

            def fail_target_cleanup(schema: str) -> None:
                drop_order.append(schema)
                if schema == owned_target:
                    raise LegacyInventoryExecutionError("forced cleanup failure")
                actual_drop(schema)

            with mock.patch.object(
                mysql,
                "drop_schema",
                side_effect=fail_target_cleanup,
            ):
                cleanup = legacy_inventory_mysql.cleanup_reserved_schemas(
                    mysql,
                    reservations,
                )
            self.assertFalse(cleanup["success"])
            self.assertEqual(drop_order, [owned_target, owned_source])
            self.assertEqual(cleanup["residual_schemas"], [owned_target])
            self.assertIn(collision, protected_schemas())
        finally:
            for schema in (owned_target, owned_source, collision):
                if schema in protected_schemas():
                    mysql.drop_schema(schema)
        self.assertEqual(protected_schemas(), before)

    def test_nonempty_backup_restore_inventory_negative_checks_and_cleanup(self) -> None:
        before = protected_schemas()
        result = subprocess.run(
            [
                PYTHON,
                "-B",
                str(COMMAND),
                "--fixture-e2e",
                "--mysql-binary",
                MYSQL,
                "--mysqldump-binary",
                MYSQLDUMP,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["scope"], "legacy_inventory_fixture_verification_only")
        self.assertTrue(summary["source_restore_verification"]["verified"])
        self.assertEqual(summary["source_restore_verification"]["table_count"], 6)
        self.assertEqual(summary["source_restore_verification"]["projection_count"], 6)
        self.assertEqual(summary["classification_counts"]["review_required"], 8)
        self.assertEqual(summary["classification_counts"]["audit_only"], 11)
        self.assertEqual(summary["source_row_count"], 33)
        self.assertEqual(summary["inventory_record_count"], 25)
        self.assertEqual(summary["review_required_count"], 8)
        self.assertTrue(summary["requires_manual_review"])
        self.assertTrue(summary["repeat_stability"])
        self.assertTrue(all(summary["negative_checks"].values()))
        self.assertTrue(
            summary["negative_checks"]["template_metadata_restore_checksum_difference_failed_closed"]
        )
        self.assertTrue(
            summary["negative_checks"]["catalog_confirmed_restore_checksum_difference_failed_closed"]
        )
        for key in (
            "task_run_same_count_update_failed_closed",
            "task_step_same_count_replace_failed_closed",
            "task_run_insert_failed_closed",
        ):
            self.assertTrue(summary["negative_checks"][key])
        self.assertEqual(
            summary["side_effect_expectations"]["allowed_subprocesses"],
            ["git", "mysql", "mysqldump"],
        )
        records_hash = hashlib.sha256(
            json.dumps(
                summary["records"],
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(records_hash, summary["records_sha256"])
        workflow_107 = next(
            record
            for record in summary["records"]
            if record["source_identity"] == {"kind": "workflow", "product_id": 107}
        )
        expected_source_id = "workflow:" + hashlib.sha256(
            b'{"product_id":107}'
        ).hexdigest()
        self.assertEqual(workflow_107["source_id"], expected_source_id)
        self.assertEqual(
            workflow_107["reason"], "legacy_workflow_succeeded_without_candidate_rows"
        )
        self.assertTrue(workflow_107["requires_manual_review"])

        git_status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        expected_source_state = "dirty_review_candidate" if git_status else "clean"
        self.assertEqual(summary["source_identity"]["source_state"], expected_source_state)
        self.assertEqual(summary["source_identity"]["status_summary"]["entry_count"], len(git_status))
        self.assertEqual(len(summary["source_identity"]["source_files"]), 9)
        self.assertTrue(
            all(len(item["sha256"]) == 64 for item in summary["source_identity"]["source_files"])
        )

        observed = summary["side_effect_observations"]
        self.assertNotIn("external_network_endpoints", observed)
        self.assertNotIn("browser_processes", observed)
        self.assertEqual(
            summary["side_effect_expectations"]["static_review_only"],
            {
                "browser_runtime_monitoring": {"observed": False, "basis": "static_review_only"},
                "external_network_runtime_monitoring": {
                    "observed": False,
                    "basis": "static_review_only",
                },
            },
        )
        self.assertEqual(observed["commands"]["process_names"], ["git", "mysql", "mysqldump"])
        self.assertEqual(observed["commands"]["database_endpoints"], ["127.0.0.1:3306"])
        self.assertEqual(
            observed["task_tables"]["deltas"], {"task_runs": 0, "task_steps": 0}
        )
        self.assertEqual(observed["task_tables"]["changed_tables"], [])
        self.assertEqual(
            observed["task_tables"]["state_sha256_before"],
            observed["task_tables"]["state_sha256_after"],
        )
        for table in ("task_runs", "task_steps"):
            self.assertEqual(observed["task_tables"]["before"][table]["row_count"], 1)
            self.assertEqual(
                len(
                    observed["task_tables"]["before"][table][
                        "canonical_checksum_sha256"
                    ]
                ),
                64,
            )
        self.assertEqual(observed["step10_outputs"]["added_paths"], [])
        self.assertEqual(observed["step10_outputs"]["removed_paths"], [])
        self.assertEqual(observed["step10_outputs"]["changed_paths"], [])
        self.assertTrue(observed["isolated_data_dir"])
        self.assertEqual(summary["cleanup"]["generated_schema_residuals"], [])
        self.assertEqual(
            summary["cleanup"]["owned_schemas"],
            summary["cleanup"]["dropped_schemas"],
        )
        self.assertEqual(summary["cleanup"]["skipped_schemas"], [])
        self.assertEqual(summary["cleanup"]["cleanup_errors"], [])
        self.assertEqual(protected_schemas(), before)

    def test_fake_candidate_sha_failure_still_reports_cleanup_outcome(self) -> None:
        result = subprocess.run(
            [
                PYTHON,
                "-B",
                str(COMMAND),
                "--fixture-e2e",
                "--candidate-sha",
                "0" * 40,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "failed")
        self.assertIn("does not equal actual HEAD", summary["error"])
        self.assertIn("cleanup", summary)
        self.assertFalse(summary["cleanup"]["attempted"])
        self.assertTrue(summary["cleanup"]["temporary_directory_removed"])
        self.assertEqual(summary["cleanup"]["cleanup_errors"], [])
        self.assertNotIn("external_network_endpoints", summary["side_effect_observations"])
        self.assertNotIn("browser_processes", summary["side_effect_observations"])

    def test_external_subprocess_probe_matches_reported_process_evidence(self) -> None:
        actual_run = subprocess.run
        captured_processes: list[str] = []

        def recording_run(argv, *args, **kwargs):
            if isinstance(argv, list) and argv:
                captured_processes.append(Path(argv[0]).name)
            return actual_run(argv, *args, **kwargs)

        before = protected_schemas()
        with mock.patch("subprocess.run", side_effect=recording_run):
            summary = legacy_migration.run_fixture_e2e(fixture_args())
        independently_observed = dict(sorted(Counter(captured_processes).items()))
        self.assertEqual(
            summary["side_effect_observations"]["commands"]["process_counts"],
            independently_observed,
        )
        self.assertEqual(set(independently_observed), {"git", "mysql", "mysqldump"})
        self.assertEqual(protected_schemas(), before)

    def test_failure_after_schema_creation_cleans_schemas_and_temp(self) -> None:
        before = protected_schemas()
        with mock.patch.object(
            legacy_migration,
            "build_legacy_inventory",
            side_effect=LegacyInventoryVerificationError("forced inventory failure"),
        ):
            with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                legacy_migration.run_fixture_e2e(fixture_args())
        summary = caught.exception.summary
        self.assertEqual(summary["status"], "failed")
        self.assertIn("forced inventory failure", summary["error"])
        self.assertTrue(summary["cleanup"]["attempted"])
        self.assertTrue(summary["cleanup"]["source_schema_created"])
        self.assertTrue(summary["cleanup"]["target_schema_created"])
        self.assertEqual(summary["cleanup"]["generated_schema_residuals"], [])
        self.assertEqual(summary["cleanup"]["cleanup_errors"], [])
        self.assertTrue(summary["cleanup"]["temporary_directory_removed"])
        self.assertEqual(protected_schemas(), before)

    def test_fixed_nonce_collision_never_drops_preexisting_schema(self) -> None:
        nonce = "c0111de000000001"
        source_schema = f"fbm_pipeline_ih_{nonce}_source"
        target_schema = f"fbm_pipeline_ih_{nonce}_target"
        mysql = local_mysql()
        if source_schema in protected_schemas() or target_schema in protected_schemas():
            self.skipTest("fixed collision nonce is already present and must not be deleted")
        created_collision = False
        try:
            mysql.create_empty_schema(source_schema)
            created_collision = True
            mysql.execute_in_schema(
                source_schema,
                "CREATE TABLE `ownership_sentinel` (`id` BIGINT PRIMARY KEY); "
                "INSERT INTO `ownership_sentinel` (`id`) VALUES (1);",
            )
            with mock.patch.object(
                legacy_migration.uuid,
                "uuid4",
                return_value=SimpleNamespace(hex=nonce),
            ):
                with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                    legacy_migration.run_fixture_e2e(fixture_args())
            self.assertIn(source_schema, protected_schemas())
            self.assertEqual(
                mysql.query_lines(
                    f"SELECT COUNT(*) FROM `{source_schema}`.`ownership_sentinel`"
                ),
                ["1"],
            )
            cleanup = caught.exception.summary["cleanup"]
            self.assertEqual(cleanup["owned_schemas"], [])
            self.assertEqual(cleanup["dropped_schemas"], [])
            self.assertEqual(
                cleanup["skipped_schemas"],
                [source_schema, target_schema],
            )
            self.assertEqual(cleanup["generated_schema_residuals"], [])
            self.assertEqual(cleanup["cleanup_errors"], [])
            self.assertIn(source_schema, cleanup["protected_schemas_after"])
        finally:
            if created_collision and source_schema in protected_schemas():
                mysql.drop_schema(source_schema)

    def test_source_fixture_load_failure_cleans_only_owned_source_schema(self) -> None:
        nonce = "50a2ce1000000001"
        source_schema = f"fbm_pipeline_ih_{nonce}_source"
        target_schema = f"fbm_pipeline_ih_{nonce}_target"
        before = protected_schemas()
        actual_run = LocalMySQL._run

        def failing_fixture_load(client, argv, *, input_bytes=None, timeout=60):
            sql = input_bytes.decode("utf-8", errors="ignore") if input_bytes else ""
            if f"CREATE TABLE `{source_schema}`.`products`" in sql:
                if sql.lstrip().startswith("CREATE DATABASE"):
                    allocation_sql = sql.split(";", 1)[0] + ";"
                    actual_run(
                        client,
                        argv,
                        input_bytes=allocation_sql.encode("utf-8"),
                        timeout=timeout,
                    )
                raise LegacyInventoryExecutionError("forced source fixture load failure")
            return actual_run(client, argv, input_bytes=input_bytes, timeout=timeout)

        with mock.patch.object(
            legacy_migration.uuid,
            "uuid4",
            return_value=SimpleNamespace(hex=nonce),
        ), mock.patch.object(LocalMySQL, "_run", new=failing_fixture_load):
            with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                legacy_migration.run_fixture_e2e(fixture_args())
        cleanup = caught.exception.summary["cleanup"]
        self.assertIn("forced source fixture load failure", caught.exception.summary["error"])
        self.assertEqual(cleanup.get("owned_schemas"), [source_schema])
        self.assertEqual(cleanup.get("dropped_schemas"), [source_schema])
        self.assertEqual(cleanup.get("skipped_schemas"), [target_schema])
        self.assertTrue(cleanup["source_schema_created"])
        self.assertFalse(cleanup["target_schema_created"])
        self.assertEqual(cleanup["generated_schema_residuals"], [])
        self.assertEqual(protected_schemas(), before)

    def test_target_restore_load_failure_cleans_both_owned_schemas(self) -> None:
        nonce = "7a2e700000000001"
        source_schema = f"fbm_pipeline_ih_{nonce}_source"
        target_schema = f"fbm_pipeline_ih_{nonce}_target"
        before = protected_schemas()
        actual_run = LocalMySQL._run

        def failing_target_import(client, argv, *, input_bytes=None, timeout=60):
            if argv[-1:] == [target_schema] and input_bytes:
                raise LegacyInventoryExecutionError("forced target restore load failure")
            return actual_run(client, argv, input_bytes=input_bytes, timeout=timeout)

        with mock.patch.object(
            legacy_migration.uuid,
            "uuid4",
            return_value=SimpleNamespace(hex=nonce),
        ), mock.patch.object(LocalMySQL, "_run", new=failing_target_import):
            with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                legacy_migration.run_fixture_e2e(fixture_args())
        cleanup = caught.exception.summary["cleanup"]
        self.assertIn("forced target restore load failure", caught.exception.summary["error"])
        self.assertEqual(cleanup.get("owned_schemas"), [source_schema, target_schema])
        self.assertEqual(cleanup.get("dropped_schemas"), [source_schema, target_schema])
        self.assertEqual(cleanup.get("skipped_schemas"), [])
        self.assertTrue(cleanup["source_schema_created"])
        self.assertTrue(cleanup["target_schema_created"])
        self.assertEqual(cleanup["generated_schema_residuals"], [])
        self.assertEqual(protected_schemas(), before)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LegacyInventoryMySQLE2ETests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"OK: {result.testsRun} legacy inventory MySQL E2E test(s)")
    raise SystemExit(0 if result.wasSuccessful() else 1)
