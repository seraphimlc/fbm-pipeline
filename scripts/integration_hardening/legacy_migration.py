#!/usr/bin/env python3
"""Executable read-only Legacy inventory and fixture restore verification.

Despite the historical command name, this R1 slice performs no migration apply.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from integration_hardening.common import ContractError, canonical_json_bytes  # noqa: E402
from integration_hardening.database_source_manifest import (  # noqa: E402
    parse_and_verify_database_source_manifest,
    verify_backup_sha256_binding,
)
from integration_hardening.legacy_inventory import (  # noqa: E402
    LegacyInventoryError,
    build_legacy_inventory,
    verify_inventory_records,
)
from integration_hardening.legacy_inventory_fixture import (  # noqa: E402
    FIXTURE_ID,
    build_fixture_sql,
)
from integration_hardening.legacy_inventory_mysql import (  # noqa: E402
    LegacyInventoryExecutionError,
    LegacyInventoryVerificationError,
    LocalMySQL,
    build_source_manifest,
    build_verification_snapshot,
    expect_contract_failure,
    verify_manifest_and_backup,
    verify_source_restore,
)
from integration_hardening.legacy_run_evidence import (  # noqa: E402
    ALLOWED_DATABASE_ENDPOINT,
    ALLOWED_SUBPROCESSES,
    CommandObservations,
    LegacyRunEvidenceError,
    build_source_identity,
    snapshot_directory,
    verify_zero_side_effect_deltas,
)


class LegacyInventoryRunFailure(RuntimeError):
    """Carries a JSON-safe failure summary after cleanup was attempted."""

    def __init__(self, summary: dict) -> None:
        super().__init__(summary.get("error", "legacy inventory run failed"))
        self.summary = summary


RUN_ERRORS = (
    ContractError,
    LegacyInventoryError,
    LegacyInventoryExecutionError,
    LegacyInventoryVerificationError,
    LegacyRunEvidenceError,
)


def _expect_evidence_failure(callable_object, *, label: str) -> None:
    try:
        callable_object()
    except LegacyRunEvidenceError:
        return
    raise LegacyInventoryVerificationError(f"negative check did not fail closed: {label}")


def run_fixture_e2e(args: argparse.Namespace) -> dict:
    observations = CommandObservations()
    mysql: LocalMySQL | None = None
    nonce = uuid.uuid4().hex[:16]
    source_schema = f"fbm_pipeline_ih_{nonce}_source"
    target_schema = f"fbm_pipeline_ih_{nonce}_target"
    database_copy_id = f"{FIXTURE_ID}-{nonce}"
    before_schemas: list[str] = []
    owned_schemas: list[str] = []
    source_created = False
    target_created = False
    temp_directory_path: Path | None = None
    source_identity: dict | None = None
    side_effect_evidence: dict | None = None
    summary: dict | None = None
    failure: Exception | None = None

    try:
        source_identity = build_source_identity(
            ROOT,
            supplied_candidate_sha=args.candidate_sha,
            observer=observations,
        )
        mysql = LocalMySQL(
            mysql_binary=args.mysql_binary,
            mysqldump_binary=args.mysqldump_binary,
            host=args.host,
            port=args.port,
            user=args.user,
            command_observer=observations.observe,
        )
        before_schemas = mysql.list_protected_schemas()

        with tempfile.TemporaryDirectory(prefix="fbm_pipeline_ih_legacy_") as temp_dir:
            temp_directory_path = Path(temp_dir)
            backup_path = temp_directory_path / "legacy.sql"
            isolated_data_dir = temp_directory_path / "data"
            step10_dir = isolated_data_dir / "amazon_templates"
            step10_dir.mkdir(parents=True)
            (step10_dir / "sentinel.keep").write_text(
                "legacy inventory must not create Step 10 output\n", encoding="utf-8"
            )
            step10_before = snapshot_directory(step10_dir)
            previous_data_dir = os.environ.get("DATA_DIR")
            had_data_dir = "DATA_DIR" in os.environ
            os.environ["DATA_DIR"] = str(isolated_data_dir)
            try:
                mysql.create_empty_schema(source_schema)
                owned_schemas.append(source_schema)
                source_created = True
                mysql.load_fixture(source_schema, build_fixture_sql(source_schema))
                source_dataset = mysql.read_dataset(source_schema)
                source_snapshot = build_verification_snapshot(source_dataset)

                backup = mysql.dump_schema(source_schema, backup_path)
                manifest = build_source_manifest(
                    source_schema=source_schema,
                    database_copy_id=database_copy_id,
                    server_facts=mysql.server_facts(),
                    verification_snapshot=source_snapshot,
                    backup_path=backup_path,
                    backup_sha256=backup["backup_sha256"],
                    tool_version=backup["tool_version"],
                )
                manifest_evidence = verify_manifest_and_backup(manifest, backup_path)

                mysql.create_empty_schema(target_schema)
                owned_schemas.append(target_schema)
                target_created = True
                mysql.import_backup(target_schema, backup_path)
                restored_dataset = mysql.read_dataset(target_schema)
                restored_snapshot = build_verification_snapshot(restored_dataset)
                restore_verification = verify_source_restore(source_snapshot, restored_snapshot)
                task_state_before = mysql.table_state_snapshot(
                    target_schema, ("task_runs", "task_steps")
                )

                first_inventory = build_legacy_inventory(restored_dataset)
                verify_inventory_records(
                    first_inventory["records"],
                    expected_sha256=first_inventory["records_sha256"],
                    expected_count=first_inventory["inventory_record_count"],
                )
                second_inventory = build_legacy_inventory(mysql.read_dataset(target_schema))
                if first_inventory != second_inventory:
                    raise LegacyInventoryVerificationError(
                        "two consecutive inventory runs produced different output"
                    )

                wrong_hash = "0" * 64
                if wrong_hash == backup["backup_sha256"]:
                    wrong_hash = "f" * 64
                expect_contract_failure(
                    lambda: verify_backup_sha256_binding(manifest, wrong_hash),
                    label="wrong_backup_hash",
                )

                tampered = copy.deepcopy(manifest)
                tampered["source"]["source_schema"] = source_schema.replace("_source", "_target")
                expect_contract_failure(
                    lambda: parse_and_verify_database_source_manifest(
                        canonical_json_bytes(tampered),
                        manifest_evidence["manifest_digest_bytes"],
                    ),
                    label="manifest_tamper",
                )

                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `amazon_stylesnap_candidates` "
                    "SET `asin`='B777777777' WHERE `id`=301;",
                )
                expect_contract_failure(
                    lambda: verify_source_restore(
                        source_snapshot,
                        build_verification_snapshot(mysql.read_dataset(target_schema)),
                    ),
                    label="restore_checksum_difference",
                )
                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `amazon_stylesnap_candidates` "
                    "SET `asin`='B000000001' WHERE `id`=301;",
                )
                verify_source_restore(
                    source_snapshot,
                    build_verification_snapshot(mysql.read_dataset(target_schema)),
                )

                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `catalog_products` SET `export_file_path`='/tampered/output.xlsx' "
                    "WHERE `id`=601;",
                )
                expect_contract_failure(
                    lambda: verify_source_restore(
                        source_snapshot,
                        build_verification_snapshot(mysql.read_dataset(target_schema)),
                    ),
                    label="downstream_restore_checksum_difference",
                )
                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `catalog_products` "
                    "SET `export_file_path`='/fixture/export/ITEM-PRESERVE.xlsx' WHERE `id`=601;",
                )
                verify_source_restore(
                    source_snapshot,
                    build_verification_snapshot(mysql.read_dataset(target_schema)),
                )

                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `product_data` SET `amazon_template_fill_summary`="
                    "'{\"tampered\":true}' WHERE `id`=214;",
                )
                expect_contract_failure(
                    lambda: verify_source_restore(
                        source_snapshot,
                        build_verification_snapshot(mysql.read_dataset(target_schema)),
                    ),
                    label="template_metadata_restore_checksum_difference",
                )
                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `product_data` SET `amazon_template_fill_summary`="
                    "'{\"filled\": 12}' WHERE `id`=214;",
                )
                verify_source_restore(
                    source_snapshot,
                    build_verification_snapshot(mysql.read_dataset(target_schema)),
                )

                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `catalog_products` SET `confirmed_at`='2026-07-24 15:00:00' "
                    "WHERE `id`=601;",
                )
                expect_contract_failure(
                    lambda: verify_source_restore(
                        source_snapshot,
                        build_verification_snapshot(mysql.read_dataset(target_schema)),
                    ),
                    label="catalog_confirmed_restore_checksum_difference",
                )
                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `catalog_products` SET `confirmed_at`='2026-07-24 11:45:00' "
                    "WHERE `id`=601;",
                )
                verify_source_restore(
                    source_snapshot,
                    build_verification_snapshot(mysql.read_dataset(target_schema)),
                )

                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `task_runs` SET `title`='tampered title' WHERE `id`=801;",
                )
                _expect_evidence_failure(
                    lambda: verify_zero_side_effect_deltas(
                        task_state_before=task_state_before,
                        task_state_after=mysql.table_state_snapshot(
                            target_schema, ("task_runs", "task_steps")
                        ),
                        step10_before=step10_before,
                        step10_after=snapshot_directory(step10_dir),
                    ),
                    label="task_run_same_count_update",
                )
                mysql.execute_in_schema(
                    target_schema,
                    "UPDATE `task_runs` SET `title`='legacy inventory sentinel' WHERE `id`=801;",
                )

                mysql.execute_in_schema(
                    target_schema,
                    "DELETE FROM `task_steps` WHERE `id`=901; "
                    "INSERT INTO `task_steps` (`id`, `task_run_id`) VALUES (902, 801);",
                )
                _expect_evidence_failure(
                    lambda: verify_zero_side_effect_deltas(
                        task_state_before=task_state_before,
                        task_state_after=mysql.table_state_snapshot(
                            target_schema, ("task_runs", "task_steps")
                        ),
                        step10_before=step10_before,
                        step10_after=snapshot_directory(step10_dir),
                    ),
                    label="task_step_same_count_replace",
                )
                mysql.execute_in_schema(
                    target_schema,
                    "DELETE FROM `task_steps` WHERE `id`=902; "
                    "INSERT INTO `task_steps` (`id`, `task_run_id`) VALUES (901, 801);",
                )

                mysql.execute_in_schema(
                    target_schema,
                    "INSERT INTO `task_runs` (`id`, `title`) VALUES (802, 'unexpected task');",
                )
                _expect_evidence_failure(
                    lambda: verify_zero_side_effect_deltas(
                        task_state_before=task_state_before,
                        task_state_after=mysql.table_state_snapshot(
                            target_schema, ("task_runs", "task_steps")
                        ),
                        step10_before=step10_before,
                        step10_after=snapshot_directory(step10_dir),
                    ),
                    label="task_run_insert",
                )
                mysql.execute_in_schema(target_schema, "DELETE FROM `task_runs` WHERE `id`=802;")
                verify_zero_side_effect_deltas(
                    task_state_before=task_state_before,
                    task_state_after=mysql.table_state_snapshot(
                        target_schema, ("task_runs", "task_steps")
                    ),
                    step10_before=step10_before,
                    step10_after=snapshot_directory(step10_dir),
                )

                mysql.execute_in_schema(target_schema, "DROP TABLE `amazon_listing_captures`;")
                expect_contract_failure(
                    lambda: mysql.read_dataset(target_schema),
                    label="missing_required_table",
                )

                task_state_after = mysql.table_state_snapshot(
                    target_schema, ("task_runs", "task_steps")
                )
                step10_after = snapshot_directory(step10_dir)
                side_effect_evidence = verify_zero_side_effect_deltas(
                    task_state_before=task_state_before,
                    task_state_after=task_state_after,
                    step10_before=step10_before,
                    step10_after=step10_after,
                )
                side_effect_evidence.update(
                    {
                        "isolated_data_dir": True,
                    }
                )

                summary = {
                    "status": "completed",
                    "scope": "legacy_inventory_fixture_verification_only",
                    "candidate_sha": source_identity["head_sha"],
                    "source_identity": source_identity,
                    "fixture_id": FIXTURE_ID,
                    "database_copy_id": database_copy_id,
                    "source_restore_verification": restore_verification,
                    "source_manifest_sha256": manifest_evidence["source_manifest_sha256"],
                    "backup_sha256": manifest_evidence["backup_sha256"],
                    "classification_counts": first_inventory["classification_counts"],
                    "review_required_count": first_inventory["review_required_count"],
                    "requires_manual_review": first_inventory["requires_manual_review"],
                    "source_row_count": first_inventory["source_row_count"],
                    "source_row_ownership_sha256": first_inventory[
                        "source_row_ownership_sha256"
                    ],
                    "inventory_record_count": first_inventory["inventory_record_count"],
                    "records": first_inventory["records"],
                    "records_sha256": first_inventory["records_sha256"],
                    "inventory_digest_sha256": first_inventory["inventory_digest_sha256"],
                    "repeat_stability": True,
                    "negative_checks": {
                        "wrong_backup_hash_failed_closed": True,
                        "manifest_tamper_failed_closed": True,
                        "missing_table_failed_closed": True,
                        "restore_checksum_difference_failed_closed": True,
                        "downstream_restore_checksum_difference_failed_closed": True,
                        "template_metadata_restore_checksum_difference_failed_closed": True,
                        "catalog_confirmed_restore_checksum_difference_failed_closed": True,
                        "task_run_same_count_update_failed_closed": True,
                        "task_step_same_count_replace_failed_closed": True,
                        "task_run_insert_failed_closed": True,
                    },
                    "side_effect_expectations": {
                        "allowed_subprocesses": sorted(ALLOWED_SUBPROCESSES),
                        "database_endpoint": ALLOWED_DATABASE_ENDPOINT,
                        "task_runs_delta": 0,
                        "task_steps_delta": 0,
                        "step10_output_delta": 0,
                        "static_review_only": {
                            "browser_runtime_monitoring": {
                                "observed": False,
                                "basis": "static_review_only",
                            },
                            "external_network_runtime_monitoring": {
                                "observed": False,
                                "basis": "static_review_only",
                            },
                        },
                    },
                }
            finally:
                if had_data_dir:
                    os.environ["DATA_DIR"] = previous_data_dir or ""
                else:
                    os.environ.pop("DATA_DIR", None)
    except Exception as exc:
        failure = exc
    finally:
        cleanup_errors = []
        cleanup_attempted = bool(owned_schemas)
        after_schemas: list[str] = []
        dropped_schemas: list[str] = []
        skipped_schemas = sorted(
            schema for schema in (source_schema, target_schema) if schema not in owned_schemas
        )
        if mysql is not None:
            for schema in reversed(owned_schemas):
                try:
                    mysql.drop_schema(schema)
                    dropped_schemas.append(schema)
                except Exception as exc:
                    cleanup_errors.append(f"{schema}:{type(exc).__name__}")
            try:
                after_schemas = mysql.list_protected_schemas()
            except Exception as exc:
                cleanup_errors.append(f"list_after:{type(exc).__name__}")
        residual_generated = [schema for schema in owned_schemas if schema in after_schemas]
        temporary_directory_removed = temp_directory_path is None or not temp_directory_path.exists()
        if not temporary_directory_removed:
            cleanup_errors.append("temporary_directory_not_removed")
        cleanup = {
            "attempted": cleanup_attempted,
            "source_schema_created": source_created,
            "target_schema_created": target_created,
            "owned_schemas": sorted(owned_schemas),
            "dropped_schemas": sorted(dropped_schemas),
            "skipped_schemas": skipped_schemas,
            "generated_schema_residuals": residual_generated,
            "protected_schemas_before": before_schemas,
            "protected_schemas_after": after_schemas,
            "cleanup_errors": cleanup_errors,
            "temporary_directory_removed": temporary_directory_removed,
        }
        if (cleanup_errors or residual_generated) and failure is None:
            failure = LegacyInventoryExecutionError(f"legacy inventory cleanup failed: {cleanup}")

    command_evidence = observations.snapshot()
    if side_effect_evidence is None:
        side_effect_evidence = {
            "task_tables": {"observed": False},
            "step10_outputs": {"observed": False},
            "isolated_data_dir": temp_directory_path is not None,
        }
    side_effect_evidence["commands"] = command_evidence

    if failure is not None:
        failure_summary = {
            "status": "failed",
            "scope": "legacy_inventory_fixture_verification_only",
            "error_type": type(failure).__name__,
            "error": str(failure),
            "source_identity": source_identity,
            "side_effect_observations": side_effect_evidence,
            "cleanup": cleanup,
        }
        raise LegacyInventoryRunFailure(failure_summary)
    if summary is None:
        raise LegacyInventoryRunFailure(
            {
                "status": "failed",
                "scope": "legacy_inventory_fixture_verification_only",
                "error_type": "LegacyInventoryExecutionError",
                "error": "legacy inventory run produced no summary",
                "source_identity": source_identity,
                "side_effect_observations": side_effect_evidence,
                "cleanup": cleanup,
            }
        )
    summary["side_effect_observations"] = side_effect_evidence
    summary["cleanup"] = cleanup
    return summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run protected non-empty Legacy inventory backup/restore verification."
    )
    parser.add_argument("--fixture-e2e", action="store_true", required=True)
    parser.add_argument("--mysql-binary", default="/opt/homebrew/bin/mysql")
    parser.add_argument("--mysqldump-binary", default="/opt/homebrew/bin/mysqldump")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--candidate-sha", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        summary = run_fixture_e2e(args)
    except LegacyInventoryRunFailure as exc:
        print(json.dumps(exc.summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
