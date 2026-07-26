#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from integration_hardening.legacy_inventory import (  # noqa: E402
    CLASS_AUDIT_ONLY,
    CLASS_CANDIDATES_WITHOUT_SELECTION,
    CLASS_REVIEW_REQUIRED,
    CLASS_SELECTED_CAPTURE_COMPLETE,
    CLASS_SELECTED_CAPTURE_INCOMPLETE,
    CLASS_WORKFLOW_INTERRUPTED,
    LegacyInventoryError,
    build_legacy_inventory,
    verify_inventory_records,
)
from integration_hardening.legacy_inventory_fixture import build_fixture_dataset  # noqa: E402
from integration_hardening.legacy_inventory_fixture import build_fixture_sql  # noqa: E402
from integration_hardening import legacy_inventory_mysql  # noqa: E402
from integration_hardening.legacy_inventory_mysql import (  # noqa: E402
    LegacyInventoryExecutionError,
    LocalMySQL,
)
from integration_hardening.legacy_run_evidence import (  # noqa: E402
    CommandObservations,
    LegacyRunEvidenceError,
    build_source_identity,
    snapshot_directory,
    verify_zero_side_effect_deltas,
)


EXPECTED_COUNTS = {
    CLASS_AUDIT_ONLY: 11,
    CLASS_CANDIDATES_WITHOUT_SELECTION: 1,
    CLASS_REVIEW_REQUIRED: 8,
    CLASS_SELECTED_CAPTURE_COMPLETE: 1,
    CLASS_SELECTED_CAPTURE_INCOMPLETE: 1,
    CLASS_WORKFLOW_INTERRUPTED: 3,
}
EXPECTED_REVIEW_REASONS = {
    "candidate_capture_identity_mismatch",
    "duplicate_candidate_asin",
    "multiple_selected_candidates",
    "orphan_capture",
    "product_competitor_asin_conflict",
    "product_match_ambiguous",
    "product_match_not_found",
}


class LegacyInventoryTests(unittest.TestCase):
    def test_full_classification_matrix_and_stable_digest(self) -> None:
        dataset = build_fixture_dataset()
        first = build_legacy_inventory(dataset)
        second = build_legacy_inventory(copy.deepcopy(dataset))

        self.assertEqual(first, second)
        self.assertEqual(first["classification_counts"], EXPECTED_COUNTS)
        self.assertEqual(first["source_row_count"], 33)
        self.assertEqual(first["inventory_record_count"], 25)
        self.assertEqual(len(first["inventory_digest_sha256"]), 64)
        self.assertEqual(first["records_sha256"], first["inventory_digest_sha256"])
        self.assertEqual(first["review_required_count"], 8)
        self.assertTrue(first["requires_manual_review"])
        review_reasons = {
            record["reason"]
            for record in first["records"]
            if record["classification"] == CLASS_REVIEW_REQUIRED
        }
        self.assertEqual(
            review_reasons,
            EXPECTED_REVIEW_REASONS | {"legacy_workflow_succeeded_without_candidate_rows"},
        )

    def test_source_rows_have_exactly_one_owner_with_multiple_sku_groups_for_one_product(self) -> None:
        dataset = build_fixture_dataset()
        dataset["amazon_stylesnap_candidates"].append(
            {
                "id": 399,
                "batch_id": "fixture-batch-1",
                "site": "US",
                "item_code": "ITEM-COMPLETE",
                "sku_code": "SKU-COMPLETE-SECOND",
                "rank": 1,
                "asin": "B000000099",
                "is_selected": 0,
                "selected_at": None,
                "capture_error": None,
                "captured_at": None,
            }
        )

        result = build_legacy_inventory(dataset)
        owned = [source_id for record in result["records"] for source_id in record["source_row_ids"]]
        self.assertEqual(len(owned), len(set(owned)))
        self.assertEqual(owned.count("workflow:101"), 1)
        candidate_groups = [
            record
            for record in result["records"]
            if record["source_identity"]["kind"] == "candidate_group"
            and record["source_identity"]["item_code"] == "ITEM-COMPLETE"
        ]
        self.assertEqual(len(candidate_groups), 2)
        self.assertTrue(all("workflow:101" not in record["source_row_ids"] for record in candidate_groups))

    def test_succeeded_without_candidates_is_always_manual_review(self) -> None:
        result = build_legacy_inventory(build_fixture_dataset())
        record = next(
            record
            for record in result["records"]
            if record["source_identity"] == {"kind": "workflow", "product_id": 107}
        )
        self.assertEqual(record["classification"], CLASS_REVIEW_REQUIRED)
        self.assertEqual(record["reason"], "legacy_workflow_succeeded_without_candidate_rows")
        self.assertTrue(record["requires_manual_review"])

    def test_irreversible_downstream_facts_force_audit_only(self) -> None:
        result = build_legacy_inventory(build_fixture_dataset())
        record = next(
            record
            for record in result["records"]
            if record["source_identity"].get("item_code") == "ITEM-PRESERVE"
        )
        self.assertEqual(record["classification"], CLASS_AUDIT_ONLY)
        self.assertEqual(record["reason"], "irreversible_downstream_facts_preserved_audit_only")
        self.assertNotEqual(record["classification"], CLASS_SELECTED_CAPTURE_COMPLETE)
        self.assertEqual(
            {fact["kind"] for fact in record["irreversible_downstream_facts"]},
            {
                "product_amazon_asin",
                "product_aplus_external_evidence",
                "amazon_template_output",
                "catalog_amazon_asin",
                "catalog_manual_confirmation",
                "catalog_export_history",
                "catalog_aplus_external_evidence",
                "aplus_upload_success",
            },
        )

    def test_current_competitor_conflict_remains_review_with_downstream_facts(self) -> None:
        result = build_legacy_inventory(build_fixture_dataset())
        record = next(
            record
            for record in result["records"]
            if record["source_identity"].get("item_code") == "ITEM-CONFLICT"
        )
        self.assertEqual(record["classification"], CLASS_REVIEW_REQUIRED)
        self.assertEqual(record["reason"], "product_competitor_asin_conflict")
        self.assertEqual(
            [fact["kind"] for fact in record["irreversible_downstream_facts"]],
            ["catalog_export_history"],
        )

    def test_template_fill_summary_only_forces_audit_only(self) -> None:
        dataset = build_fixture_dataset()
        data = next(row for row in dataset["product_data"] if row["product_id"] == 101)
        data["amazon_template_fill_summary"] = '{"filled": 7}'
        result = build_legacy_inventory(dataset)
        record = next(
            record
            for record in result["records"]
            if record["source_identity"].get("item_code") == "ITEM-COMPLETE"
        )
        self.assertEqual(record["classification"], CLASS_AUDIT_ONLY)
        template_fact = next(
            fact
            for fact in record["irreversible_downstream_facts"]
            if fact["kind"] == "amazon_template_output"
        )
        self.assertEqual(template_fact["fill_summary"], '{"filled": 7}')

    def test_template_warnings_only_force_audit_only(self) -> None:
        dataset = build_fixture_dataset()
        data = next(row for row in dataset["product_data"] if row["product_id"] == 101)
        data["amazon_template_warnings"] = '["manual review"]'
        result = build_legacy_inventory(dataset)
        record = next(
            record
            for record in result["records"]
            if record["source_identity"].get("item_code") == "ITEM-COMPLETE"
        )
        self.assertEqual(record["classification"], CLASS_AUDIT_ONLY)
        template_fact = next(
            fact
            for fact in record["irreversible_downstream_facts"]
            if fact["kind"] == "amazon_template_output"
        )
        self.assertEqual(template_fact["warnings"], '["manual review"]')

    def test_catalog_confirmed_at_only_forces_audit_only(self) -> None:
        dataset = build_fixture_dataset()
        dataset["catalog_products"].append(
            {
                "id": 603,
                "source_product_id": 101,
                "amazon_asin": None,
                "confirmed_at": "2026-07-24 09:00:00",
                "exported_at": None,
                "export_task_id": None,
                "export_file_path": None,
                "aplus_upload_status": "not_uploaded",
                "aplus_uploaded_at": None,
                "aplus_upload_error": None,
            }
        )
        result = build_legacy_inventory(dataset)
        record = next(
            record
            for record in result["records"]
            if record["source_identity"].get("item_code") == "ITEM-COMPLETE"
        )
        self.assertEqual(record["classification"], CLASS_AUDIT_ONLY)
        self.assertIn(
            "catalog_manual_confirmation",
            {fact["kind"] for fact in record["irreversible_downstream_facts"]},
        )

    def test_orphaned_successful_aplus_items_force_workflow_manual_review(self) -> None:
        dataset = build_fixture_dataset()
        dataset["aplus_upload_items"].extend(
            [
                {
                    "id": 502,
                    "catalog_product_id": 999,
                    "product_id": 104,
                    "amazon_asin": "B0ORPHAN104",
                    "item_code": "ITEM-PENDING",
                    "status": "success",
                    "finished_at": "2026-07-24 13:00:00",
                },
                {
                    "id": 503,
                    "catalog_product_id": 601,
                    "product_id": 105,
                    "amazon_asin": "B0MISMATCH5",
                    "item_code": "ITEM-PROCESSING",
                    "status": "success",
                    "finished_at": "2026-07-24 13:05:00",
                },
            ]
        )
        baseline = build_legacy_inventory(build_fixture_dataset())
        result = build_legacy_inventory(dataset)
        for product_id in (104, 105):
            record = next(
                record
                for record in result["records"]
                if record["source_identity"] == {"kind": "workflow", "product_id": product_id}
            )
            self.assertEqual(record["classification"], CLASS_REVIEW_REQUIRED)
            self.assertEqual(record["reason"], "aplus_upload_item_attribution_conflict")
            self.assertTrue(record["requires_manual_review"])
        self.assertEqual(result["review_required_count"], baseline["review_required_count"] + 2)
        self.assertNotEqual(result["records_sha256"], baseline["records_sha256"])

    def test_successful_aplus_item_with_missing_product_has_review_record(self) -> None:
        dataset = build_fixture_dataset()
        dataset["aplus_upload_items"].append(
            {
                "id": 504,
                "catalog_product_id": 601,
                "product_id": 999,
                "amazon_asin": "B0NOPRODUCT",
                "item_code": "ITEM-MISSING-PRODUCT",
                "status": "success",
                "finished_at": "2026-07-24 13:10:00",
            }
        )
        baseline = build_legacy_inventory(build_fixture_dataset())
        result = build_legacy_inventory(dataset)
        matching_records = [
            record
            for record in result["records"]
            if record["source_identity"]
            == {"kind": "aplus_attribution_conflict", "aplus_upload_item_id": 504}
        ]
        self.assertEqual(len(matching_records), 1)
        record = matching_records[0]
        self.assertEqual(record["classification"], CLASS_REVIEW_REQUIRED)
        self.assertEqual(record["reason"], "aplus_upload_item_attribution_conflict")
        self.assertEqual(record["source_row_ids"], [])
        self.assertTrue(record["requires_manual_review"])
        self.assertEqual(result["review_required_count"], baseline["review_required_count"] + 1)
        self.assertEqual(result["source_row_count"], baseline["source_row_count"])
        self.assertEqual(
            result["source_row_ownership_sha256"], baseline["source_row_ownership_sha256"]
        )
        self.assertNotEqual(result["records_sha256"], baseline["records_sha256"])
        self.assertEqual(result, build_legacy_inventory(copy.deepcopy(dataset)))

    def test_records_digest_detects_record_or_hash_tamper(self) -> None:
        result = build_legacy_inventory(build_fixture_dataset())
        verify_inventory_records(
            result["records"],
            expected_sha256=result["records_sha256"],
            expected_count=result["inventory_record_count"],
        )
        tampered = copy.deepcopy(result["records"])
        tampered[0]["reason"] = "tampered"
        with self.assertRaisesRegex(LegacyInventoryError, "SHA256"):
            verify_inventory_records(
                tampered,
                expected_sha256=result["records_sha256"],
                expected_count=result["inventory_record_count"],
            )
        with self.assertRaisesRegex(LegacyInventoryError, "SHA256"):
            verify_inventory_records(
                result["records"],
                expected_sha256="0" * 64,
                expected_count=result["inventory_record_count"],
            )

    def test_source_identity_tracks_clean_tracked_untracked_and_rejects_fake_sha(self) -> None:
        with tempfile.TemporaryDirectory(prefix="legacy_source_identity_") as temp_dir:
            repo = Path(temp_dir)
            source = repo / "source.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            commands = (
                ["git", "init"],
                ["git", "config", "user.email", "fixture@example.invalid"],
                ["git", "config", "user.name", "Fixture"],
                ["git", "add", "source.py"],
                ["git", "commit", "-m", "fixture"],
            )
            for argv in commands:
                result = subprocess.run(argv, cwd=repo, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

            clean = build_source_identity(repo, source_files=("source.py",))
            self.assertEqual(clean["source_state"], "clean")
            self.assertEqual(clean["status_paths"], [])
            self.assertEqual(clean["source_files"][0]["path"], "source.py")

            source.write_text("VALUE = 2\n", encoding="utf-8")
            tracked = build_source_identity(repo, source_files=("source.py",))
            self.assertEqual(tracked["source_state"], "dirty_review_candidate")
            self.assertEqual(tracked["status_summary"]["tracked_changes"], 1)
            self.assertIn("source.py", tracked["status_paths"])

            (repo / "untracked.txt").write_text("sentinel\n", encoding="utf-8")
            untracked = build_source_identity(repo, source_files=("source.py",))
            self.assertEqual(untracked["status_summary"]["untracked_paths"], 1)
            self.assertIn("untracked.txt", untracked["status_paths"])
            with self.assertRaisesRegex(LegacyRunEvidenceError, "does not equal actual HEAD"):
                build_source_identity(
                    repo,
                    supplied_candidate_sha="0" * 40,
                    source_files=("source.py",),
                )

    def test_side_effect_observation_fails_for_process_task_or_output_mutation(self) -> None:
        observer = CommandObservations()
        observer.observe(["git", "status"])
        observer.observe(
            ["/opt/homebrew/bin/mysql", "--host=127.0.0.1", "--port=3306"]
        )
        snapshot = observer.snapshot()
        self.assertEqual(snapshot["process_names"], ["git", "mysql"])
        self.assertEqual(snapshot["database_endpoints"], ["127.0.0.1:3306"])
        with self.assertRaisesRegex(LegacyRunEvidenceError, "forbidden subprocess"):
            observer.observe(["curl", "https://example.invalid"])

        task_state = legacy_inventory_mysql.build_task_table_state_snapshot(
            {
                "task_runs": [{"id": 801, "title": "legacy inventory sentinel"}],
                "task_steps": [{"id": 901, "task_run_id": 801}],
            }
        )
        task_state_with_insert = legacy_inventory_mysql.build_task_table_state_snapshot(
            {
                "task_runs": [
                    {"id": 801, "title": "legacy inventory sentinel"},
                    {"id": 802, "title": "unexpected task"},
                ],
                "task_steps": [{"id": 901, "task_run_id": 801}],
            }
        )
        sentinel = [
            {
                "relative_path": "sentinel.keep",
                "entry_type": "file",
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
        ]
        verified = verify_zero_side_effect_deltas(
            task_state_before=task_state,
            task_state_after=copy.deepcopy(task_state),
            step10_before=sentinel,
            step10_after=copy.deepcopy(sentinel),
        )
        self.assertEqual(verified["task_tables"]["deltas"], {"task_runs": 0, "task_steps": 0})
        with self.assertRaisesRegex(LegacyRunEvidenceError, "state mutation"):
            verify_zero_side_effect_deltas(
                task_state_before=task_state,
                task_state_after=task_state_with_insert,
                step10_before=sentinel,
                step10_after=sentinel,
            )
        with self.assertRaisesRegex(LegacyRunEvidenceError, "Step 10 output mutation"):
            verify_zero_side_effect_deltas(
                task_state_before=task_state,
                task_state_after=task_state,
                step10_before=sentinel,
                step10_after=sentinel
                + [
                    {
                        "relative_path": "new.xlsx",
                        "entry_type": "file",
                        "size_bytes": 1,
                        "sha256": "1" * 64,
                    }
                ],
            )

    def test_task_table_state_detects_same_count_content_changes(self) -> None:
        build_snapshot = getattr(
            legacy_inventory_mysql, "build_task_table_state_snapshot", None
        )
        self.assertIsNotNone(
            build_snapshot,
            "deterministic TaskRun/TaskStep state snapshot is required",
        )
        before = build_snapshot(
            {
                "task_runs": [{"id": 801, "title": "legacy inventory sentinel"}],
                "task_steps": [{"id": 901, "task_run_id": 801}],
            }
        )
        unchanged = build_snapshot(
            {
                "task_runs": [{"id": 801, "title": "legacy inventory sentinel"}],
                "task_steps": [{"id": 901, "task_run_id": 801}],
            }
        )
        sentinel = [
            {
                "relative_path": "sentinel.keep",
                "entry_type": "file",
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
        ]
        verified = verify_zero_side_effect_deltas(
            task_state_before=before,
            task_state_after=unchanged,
            step10_before=sentinel,
            step10_after=copy.deepcopy(sentinel),
        )
        self.assertEqual(verified["task_tables"]["changed_tables"], [])
        self.assertEqual(
            verified["task_tables"]["state_sha256_before"],
            verified["task_tables"]["state_sha256_after"],
        )

        changed_states = (
            build_snapshot(
                {
                    "task_runs": [{"id": 801, "title": "tampered title"}],
                    "task_steps": [{"id": 901, "task_run_id": 801}],
                }
            ),
            build_snapshot(
                {
                    "task_runs": [{"id": 801, "title": "legacy inventory sentinel"}],
                    "task_steps": [{"id": 902, "task_run_id": 801}],
                }
            ),
            build_snapshot(
                {
                    "task_runs": [
                        {"id": 801, "title": "legacy inventory sentinel"},
                        {"id": 802, "title": "unexpected task"},
                    ],
                    "task_steps": [{"id": 901, "task_run_id": 801}],
                }
            ),
        )
        for changed in changed_states:
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(
                    LegacyRunEvidenceError, "TaskRun/TaskStep state mutation"
                ):
                    verify_zero_side_effect_deltas(
                        task_state_before=before,
                        task_state_after=changed,
                        step10_before=sentinel,
                        step10_after=sentinel,
                    )

    def test_step10_snapshot_records_directories_and_rejects_symlinks_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="legacy_step10_snapshot_") as temp_dir:
            root = Path(temp_dir)
            sentinel_path = root / "sentinel.keep"
            sentinel_path.write_text("sentinel\n", encoding="utf-8")
            baseline = snapshot_directory(root)
            self.assertEqual(baseline, snapshot_directory(root))
            self.assertEqual(
                baseline,
                [
                    {
                        "relative_path": "sentinel.keep",
                        "entry_type": "file",
                        "size_bytes": 9,
                        "sha256": hashlib.sha256(b"sentinel\n").hexdigest(),
                    }
                ],
            )
            stable_task_state = legacy_inventory_mysql.build_task_table_state_snapshot(
                {"task_runs": [], "task_steps": []}
            )

            (root / "empty").mkdir()
            with self.assertRaisesRegex(LegacyRunEvidenceError, "Step 10 output mutation"):
                verify_zero_side_effect_deltas(
                    task_state_before=stable_task_state,
                    task_state_after=stable_task_state,
                    step10_before=baseline,
                    step10_after=snapshot_directory(root),
                )
            (root / "empty").rmdir()

            (root / "new.xlsx").write_text("new\n", encoding="utf-8")
            with self.assertRaisesRegex(LegacyRunEvidenceError, "Step 10 output mutation"):
                verify_zero_side_effect_deltas(
                    task_state_before=stable_task_state,
                    task_state_after=stable_task_state,
                    step10_before=baseline,
                    step10_after=snapshot_directory(root),
                )
            (root / "new.xlsx").unlink()

            sentinel_path.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(LegacyRunEvidenceError, "Step 10 output mutation"):
                verify_zero_side_effect_deltas(
                    task_state_before=stable_task_state,
                    task_state_after=stable_task_state,
                    step10_before=baseline,
                    step10_after=snapshot_directory(root),
                )
            sentinel_path.write_text("sentinel\n", encoding="utf-8")

            file_link = root / "file-link"
            file_link.symlink_to(sentinel_path)
            with self.assertRaisesRegex(LegacyRunEvidenceError, "symbolic link"):
                snapshot_directory(root)
            file_link.unlink()

            target_dir = root / "target-dir"
            target_dir.mkdir()
            directory_link = root / "directory-link"
            directory_link.symlink_to(target_dir, target_is_directory=True)
            with self.assertRaisesRegex(LegacyRunEvidenceError, "symbolic link"):
                snapshot_directory(root)

    def test_exact_product_matching_does_not_fall_back_to_item_code(self) -> None:
        dataset = build_fixture_dataset()
        product = next(row for row in dataset["products"] if row["id"] == 101)
        product["source_batch_id"] = "different-batch"
        result = build_legacy_inventory(dataset)
        complete = next(
            record
            for record in result["records"]
            if record["source_identity"].get("item_code") == "ITEM-COMPLETE"
        )
        self.assertEqual(complete["classification"], CLASS_REVIEW_REQUIRED)
        self.assertEqual(complete["reason"], "product_match_not_found")
        self.assertEqual(complete["candidate_product_ids"], [])

    def test_nfkc_and_whitespace_normalization_is_deterministic(self) -> None:
        dataset = build_fixture_dataset()
        candidate = dataset["amazon_stylesnap_candidates"][0]
        candidate["item_code"] = "  ＩＴＥＭ－ＣＯＭＰＬＥＴＥ  "
        result = build_legacy_inventory(dataset)
        record = next(
            record
            for record in result["records"]
            if record["source_identity"].get("item_code") == "ITEM-COMPLETE"
        )
        self.assertEqual(record["classification"], CLASS_SELECTED_CAPTURE_COMPLETE)
        self.assertEqual(record["candidate_product_ids"], [101])

    def test_unreadable_input_is_failed_not_review_required(self) -> None:
        dataset = build_fixture_dataset()
        dataset["amazon_stylesnap_candidates"][0]["rank"] = "one"
        with self.assertRaisesRegex(LegacyInventoryError, "rank: expected integer"):
            build_legacy_inventory(dataset)

    def test_source_identity_and_checksum_ignore_input_order(self) -> None:
        dataset = build_fixture_dataset()
        first = build_legacy_inventory(dataset)
        for rows in dataset.values():
            rows.reverse()
        second = build_legacy_inventory(dataset)
        self.assertEqual(first, second)

    def test_mysql_execution_rejects_nonlocal_or_unprotected_targets(self) -> None:
        with self.assertRaisesRegex(ValueError, "protected fbm_pipeline_ih"):
            build_fixture_sql("fbm_pipeline")
        fixture_sql = build_fixture_sql("fbm_pipeline_ih_0123456789abcdef_source")
        self.assertNotIn("CREATE DATABASE", fixture_sql.upper())
        self.assertNotIn("DROP DATABASE", fixture_sql.upper())
        with self.assertRaisesRegex(LegacyInventoryExecutionError, "host 127.0.0.1"):
            LocalMySQL(
                mysql_binary="/opt/homebrew/bin/mysql",
                mysqldump_binary="/opt/homebrew/bin/mysqldump",
                host="db.example.com",
            )

    def test_mysql_sql_consumers_disable_client_commands_without_affecting_mysqldump(
        self,
    ) -> None:
        client = LocalMySQL(
            mysql_binary="/opt/homebrew/bin/mysql",
            mysqldump_binary="/opt/homebrew/bin/mysqldump",
        )
        observed: list[tuple[list[str], bytes | None]] = []
        observed_environments: list[dict[str, str]] = []

        def record_run(
            argv: list[str],
            *args: object,
            **kwargs: object,
        ) -> subprocess.CompletedProcess[bytes]:
            input_bytes = kwargs.get("input")
            self.assertTrue(input_bytes is None or isinstance(input_bytes, bytes))
            observed.append((list(argv), input_bytes))
            observed_environments.append(dict(kwargs.get("env", {})))
            stdout = b""
            if Path(argv[0]).name == "mysql" and "--execute" in argv:
                stdout = b"1\n"
            elif Path(argv[0]).name == "mysqldump":
                stdout = b"mysqldump  Ver 9.6.0\n" if "--version" in argv else b"dump\n"
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

        source_schema = "fbm_pipeline_ih_0123456789abcdef_source"
        target_schema = "fbm_pipeline_ih_0123456789abcdef_target"
        fixture_sql = "CREATE TABLE `fixture_table` (`id` bigint);"
        imported_sql = b"CREATE TABLE `restored_table` (`id` bigint);"
        executed_sql = "SELECT COUNT(*) FROM `restored_table`;"

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            import_path = temporary_path / "import.sql"
            dump_path = temporary_path / "dump.sql"
            import_path.write_bytes(imported_sql)

            with mock.patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "mysql://application.invalid/private",
                    "MYSQL_PWD": "private-password",
                    "MYSQL_TEST_LOGIN_FILE": "/private/login-path.cnf",
                },
            ), mock.patch("subprocess.run", side_effect=record_run):
                self.assertEqual(client.query_lines("SELECT 1"), ["1"])
                client.load_fixture(source_schema, fixture_sql)
                client.import_backup(target_schema, import_path)
                client.execute_in_schema(target_schema, executed_sql)
                client.dump_schema(source_schema, dump_path)

        for argv, _ in observed:
            self.assertEqual(argv.count("--no-defaults"), 1)
            self.assertEqual(argv.count("--no-login-paths"), 1)
        for environment in observed_environments:
            self.assertNotIn("DATABASE_URL", environment)
            self.assertNotIn("MYSQL_PWD", environment)
            self.assertNotIn("MYSQL_TEST_LOGIN_FILE", environment)

        mysql_calls = [
            (argv, input_bytes)
            for argv, input_bytes in observed
            if Path(argv[0]).name == "mysql"
        ]
        self.assertEqual(
            [input_bytes for _, input_bytes in mysql_calls],
            [None, fixture_sql.encode("utf-8"), imported_sql, executed_sql.encode("utf-8")],
        )
        for argv, _ in mysql_calls:
            self.assertEqual(argv.count("--commands=OFF"), 1)
            self.assertEqual(argv.count("--disable-named-commands"), 1)

        mysqldump_calls = [
            argv for argv, _ in observed if Path(argv[0]).name == "mysqldump"
        ]
        self.assertEqual(len(mysqldump_calls), 2)
        for argv in mysqldump_calls:
            self.assertNotIn("--commands=OFF", argv)
            self.assertNotIn("--disable-named-commands", argv)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LegacyInventoryTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"OK: {result.testsRun} legacy inventory focused test(s)")
    raise SystemExit(0 if result.wasSuccessful() else 1)
