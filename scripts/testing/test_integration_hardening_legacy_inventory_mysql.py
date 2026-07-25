#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
import hashlib
import subprocess
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON = "/usr/bin/python3"
MYSQL = "/opt/homebrew/bin/mysql"
MYSQLDUMP = "/opt/homebrew/bin/mysqldump"
COMMAND = ROOT / "scripts" / "integration_hardening" / "legacy_migration.py"
sys.path.insert(0, str(ROOT / "scripts"))

from integration_hardening import legacy_migration  # noqa: E402
from integration_hardening.legacy_inventory_mysql import (  # noqa: E402
    LegacyInventoryExecutionError,
    LegacyInventoryVerificationError,
    LocalMySQL,
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


class LegacyInventoryMySQLE2ETests(unittest.TestCase):
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
        self.assertEqual(len(summary["source_identity"]["source_files"]), 8)
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
