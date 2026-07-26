#!/usr/bin/env python3
"""Executable read-only Legacy inventory and fixture restore verification.

Despite the historical command name, this R1 slice performs no migration apply.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from integration_hardening.common import (  # noqa: E402
    ContractError,
    canonical_json_bytes,
    canonical_sha256_hex,
)
from integration_hardening.database_source_manifest import (  # noqa: E402
    parse_and_verify_database_source_manifest,
    verify_backup_sha256_binding,
)
from integration_hardening.legacy_inventory import (  # noqa: E402
    LegacyInventoryError,
    build_legacy_inventory,
    verify_inventory_records,
)
from integration_hardening.legacy_backup_sanitizer import (  # noqa: E402
    LegacyBackupSanitizationError,
    scan_mysql_dump,
)
from integration_hardening.legacy_inventory_fixture import (  # noqa: E402
    FIXTURE_ID,
    build_fixture_sql,
)
from integration_hardening.legacy_inventory_mysql import (  # noqa: E402
    LegacyInventoryExecutionError,
    LegacyInventoryVerificationError,
    LocalMySQL,
    ProtectedSchemaReservation,
    build_historical_archive_source_manifest,
    build_source_manifest,
    build_verification_snapshot,
    cleanup_reserved_schemas,
    create_reserved_schema,
    expect_contract_failure,
    reserve_protected_schemas,
    verify_manifest_and_backup,
    verify_source_restore,
)
from integration_hardening.legacy_run_evidence import (  # noqa: E402
    ALLOWED_DATABASE_ENDPOINT,
    ALLOWED_SUBPROCESSES,
    CommandObservations,
    LegacyRunEvidenceError,
    SOURCE_FILE_RELATIVE_PATHS,
    build_source_identity,
    snapshot_directory,
    validate_evidence_output_path,
    verify_zero_side_effect_deltas,
    write_private_evidence,
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
    LegacyBackupSanitizationError,
)


BACKUP_SCOPE = "historical_archive_restore_inventory"
_BACKUP_PROGRESS_PHASES = (
    "preflight",
    "source_import",
    "source_inventory",
    "canonical_dump",
    "target_import",
    "verification",
    "cleanup",
    "evidence_write",
    "completed",
)
_LOWER_SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
_LOWER_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
_BACKUP_FAILURE_MESSAGES = {
    "backup_path_invalid": "backup path must be an absolute regular non-symlink file",
    "backup_hash_mismatch": "backup SHA-256 does not match the explicit expected digest",
    "backup_changed_during_run": "backup file changed during preflight",
    "unsafe_backup_sql": "backup SQL failed the offline safety policy",
    "forbidden_database_endpoint": "database endpoint must be 127.0.0.1:3306",
    "invalid_auth_transport": "passwordless local authentication requires explicit authorization",
    "candidate_source_not_clean": "candidate SHA must match a clean Git HEAD",
    "evidence_path_unsafe": "evidence output path failed the private external-path policy",
    "backup_inventory_not_implemented": "backup inventory database execution is not implemented",
    "invalid_tool_path": "mysql tools must be explicit absolute executable files",
    "invalid_cli": "backup inventory arguments failed validation",
    "protected_schema_collision": "generated protected schema already exists",
    "source_restore_failed": "protected backup restore or canonical dump failed",
    "required_table_missing": "backup is missing a required legacy table",
    "unsupported_legacy_shape": "backup legacy columns are not safely supported",
    "source_target_snapshot_mismatch": "source and target snapshots differ",
    "inventory_digest_mismatch": "source and target inventory digests differ",
    "task_sentinel_changed": "task or Step 10 side-effect sentinel changed",
    "cleanup_failed": "protected schema or temporary resource cleanup failed",
    "evidence_write_failed": "private evidence could not be written and verified",
}


class BackupInventoryPreflightError(RuntimeError):
    """Stable preflight failure without private SQL, records, or subprocess stderr."""

    def __init__(self, error_code: str, phase: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.phase = phase


def _emit_backup_progress(phase: str) -> None:
    if phase not in _BACKUP_PROGRESS_PHASES:
        raise ValueError("unknown backup inventory progress phase")
    try:
        sys.stderr.write(f"backup_inventory phase={phase}\n")
        sys.stderr.flush()
    except Exception:
        return


def build_backup_failure_summary(
    *,
    error_code: str,
    phase: str,
    cleanup_success: bool,
    primary_error_code: str | None = None,
    unsafe_detail: str = "",
) -> dict[str, Any]:
    """Return the only failure fields permitted on backup-mode stdout."""

    del unsafe_detail
    if type(error_code) is not str or _SAFE_TOKEN_RE.fullmatch(error_code) is None:
        error_code = "invalid_cli"
    if type(phase) is not str or _SAFE_TOKEN_RE.fullmatch(phase) is None:
        phase = "preflight"
    summary = {
        "status": "failed",
        "scope": BACKUP_SCOPE,
        "error_code": error_code,
        "phase": phase,
        "cleanup_success": cleanup_success is True,
        "message": _BACKUP_FAILURE_MESSAGES.get(error_code, "backup inventory failed"),
    }
    if (
        error_code == "cleanup_failed"
        and cleanup_success is not True
        and primary_error_code is not None
    ):
        if (
            type(primary_error_code) is not str
            or _SAFE_TOKEN_RE.fullmatch(primary_error_code) is None
        ):
            primary_error_code = "invalid_cli"
        summary["primary_error_code"] = primary_error_code
        summary["cleanup_failed"] = True
    return summary


def _backup_stat_identity(file_stat: os.stat_result) -> tuple[int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


class OpenedSanitizedBackup:
    """One read-only descriptor shared by sanitizer, future import, and final rehash."""

    def __init__(
        self,
        *,
        path: Path,
        stream: BinaryIO,
        initial_stat: os.stat_result,
        sanitizer_result: dict[str, Any],
    ) -> None:
        self.path = path
        self.stream = stream
        self.initial_stat = initial_stat
        self.sanitizer_result = sanitizer_result
        self.expected_backup_sha256 = sanitizer_result["backup_sha256"]

    def _verify_metadata_and_path(self) -> None:
        try:
            descriptor_stat = os.fstat(self.stream.fileno())
            path_stat = self.path.lstat()
        except (OSError, ValueError) as exc:
            raise LegacyBackupSanitizationError("backup changed during run") from exc
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or _backup_stat_identity(descriptor_stat)
            != _backup_stat_identity(self.initial_stat)
            or (path_stat.st_dev, path_stat.st_ino)
            != (self.initial_stat.st_dev, self.initial_stat.st_ino)
        ):
            raise LegacyBackupSanitizationError("backup changed during run")

    def rewind_for_import(self) -> BinaryIO:
        self._verify_metadata_and_path()
        try:
            self.stream.seek(0)
        except (OSError, ValueError) as exc:
            raise LegacyBackupSanitizationError("backup changed during run") from exc
        return self.stream

    def verify_unchanged(self) -> dict[str, Any]:
        self._verify_metadata_and_path()
        digest = hashlib.sha256()
        try:
            self.stream.seek(0)
            while True:
                chunk = self.stream.read(64 * 1024)
                if chunk == b"":
                    break
                if type(chunk) is not bytes:
                    raise LegacyBackupSanitizationError("backup changed during run")
                digest.update(chunk)
        except (OSError, ValueError) as exc:
            raise LegacyBackupSanitizationError("backup changed during run") from exc
        self._verify_metadata_and_path()
        if digest.hexdigest() != self.expected_backup_sha256:
            raise LegacyBackupSanitizationError("backup changed during run")
        self.stream.seek(0)
        return {
            "backup_sha256": digest.hexdigest(),
            "size_bytes": self.initial_stat.st_size,
            "device": self.initial_stat.st_dev,
            "inode": self.initial_stat.st_ino,
            "mtime_ns": self.initial_stat.st_mtime_ns,
        }


@contextmanager
def open_sanitized_backup(
    backup_path: Path,
    *,
    expected_backup_sha256: str,
    target_mysql_version: str,
) -> Iterator[OpenedSanitizedBackup]:
    """Open, sanitize, and retain one non-symlink backup descriptor."""

    backup_path = Path(backup_path)
    if not backup_path.is_absolute():
        raise LegacyBackupSanitizationError("backup path must be absolute")
    try:
        path_stat = backup_path.lstat()
    except OSError as exc:
        raise LegacyBackupSanitizationError("backup path is invalid") from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise LegacyBackupSanitizationError("backup path must not be a symbolic link")
    if not stat.S_ISREG(path_stat.st_mode):
        raise LegacyBackupSanitizationError("backup path must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(backup_path, flags)
    except OSError as exc:
        raise LegacyBackupSanitizationError("backup path is invalid") from exc
    stream = os.fdopen(descriptor, "rb", closefd=True)
    try:
        descriptor_stat = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino)
            != (descriptor_stat.st_dev, descriptor_stat.st_ino)
        ):
            raise LegacyBackupSanitizationError("backup changed during run")
        sanitizer_result = scan_mysql_dump(
            stream,
            expected_backup_sha256=expected_backup_sha256,
            target_mysql_version=target_mysql_version,
        )
        opened = OpenedSanitizedBackup(
            path=backup_path,
            stream=stream,
            initial_stat=descriptor_stat,
            sanitizer_result=sanitizer_result,
        )
        opened._verify_metadata_and_path()
        stream.seek(0)
        yield opened
    finally:
        stream.close()


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
    reservations: list[ProtectedSchemaReservation] = []
    source_reservation: ProtectedSchemaReservation | None = None
    target_reservation: ProtectedSchemaReservation | None = None
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
        reservations = reserve_protected_schemas(
            mysql,
            (source_schema, target_schema),
        )
        source_reservation, target_reservation = reservations

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
                create_reserved_schema(mysql, source_reservation)
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

                create_reserved_schema(mysql, target_reservation)
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
        cleanup_details = {
            "success": True,
            "owned_schemas": [],
            "dropped_schemas": [],
            "residual_schemas": [],
            "cleanup_errors": [],
            "protected_schemas_after": [],
            "reservations": [],
        }
        if mysql is not None:
            cleanup_details = cleanup_reserved_schemas(mysql, reservations)
        owned_schemas = cleanup_details["owned_schemas"]
        cleanup_errors = list(cleanup_details["cleanup_errors"])
        residual_generated = cleanup_details["residual_schemas"]
        after_schemas = cleanup_details["protected_schemas_after"]
        creation_attempted_schemas = sorted(
            reservation.schema
            for reservation in reservations
            if reservation.creation_attempted
        )
        create_returned_success_schemas = sorted(
            reservation.schema
            for reservation in reservations
            if reservation.create_returned_success
        )
        observed_present_schemas = sorted(
            reservation.schema
            for reservation in reservations
            if reservation.observed_present
        )
        cleanup_attempted = any(
            reservation.cleanup_attempted for reservation in reservations
        )
        skipped_schemas = sorted(
            schema
            for schema in (source_schema, target_schema)
            if schema not in owned_schemas
        )
        temporary_directory_removed = temp_directory_path is None or not temp_directory_path.exists()
        if not temporary_directory_removed:
            cleanup_errors.append("temporary_directory_not_removed")
        cleanup = {
            "attempted": cleanup_attempted,
            "source_schema_created": bool(
                source_reservation and source_reservation.create_returned_success
            ),
            "target_schema_created": bool(
                target_reservation and target_reservation.create_returned_success
            ),
            "source_schema_observed_present": bool(
                source_reservation and source_reservation.observed_present
            ),
            "target_schema_observed_present": bool(
                target_reservation and target_reservation.observed_present
            ),
            "creation_attempted_schemas": creation_attempted_schemas,
            "create_returned_success_schemas": create_returned_success_schemas,
            "observed_present_schemas": observed_present_schemas,
            "owned_schemas": owned_schemas,
            "dropped_schemas": cleanup_details["dropped_schemas"],
            "skipped_schemas": skipped_schemas,
            "generated_schema_residuals": residual_generated,
            "protected_schemas_before": before_schemas,
            "protected_schemas_after": after_schemas,
            "cleanup_errors": cleanup_errors,
            "schema_reservations": cleanup_details["reservations"],
            "success": not cleanup_errors and not residual_generated,
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


def _explicit_executable(path_value: str, *, expected_name: str) -> Path:
    if type(path_value) is not str:
        raise BackupInventoryPreflightError("invalid_tool_path", "cli_preflight")
    path = Path(path_value)
    if not path.is_absolute():
        raise BackupInventoryPreflightError("invalid_tool_path", "cli_preflight")
    try:
        resolved = path.resolve(strict=True)
        resolved_stat = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise BackupInventoryPreflightError(
            "invalid_tool_path", "cli_preflight"
        ) from exc
    if (
        resolved.name != expected_name
        or not stat.S_ISREG(resolved_stat.st_mode)
        or not os.access(resolved, os.X_OK)
    ):
        raise BackupInventoryPreflightError("invalid_tool_path", "cli_preflight")
    return resolved


def _validate_backup_inventory_args(args: argparse.Namespace) -> None:
    if not getattr(args, "backup_inventory", False):
        raise BackupInventoryPreflightError("invalid_cli", "cli_preflight")
    if getattr(args, "allow_passwordless_local", False) is not True:
        raise BackupInventoryPreflightError("invalid_auth_transport", "auth_preflight")
    if args.host != "127.0.0.1" or args.port != 3306:
        raise BackupInventoryPreflightError(
            "forbidden_database_endpoint", "endpoint_preflight"
        )
    if type(args.user) is not str or not args.user or any(
        character.isspace() for character in args.user
    ):
        raise BackupInventoryPreflightError("invalid_auth_transport", "auth_preflight")
    if type(args.candidate_sha) is not str or _LOWER_SHA1_RE.fullmatch(
        args.candidate_sha
    ) is None:
        raise BackupInventoryPreflightError(
            "candidate_source_not_clean", "candidate_preflight"
        )
    if type(args.expected_backup_sha256) is not str or _LOWER_SHA256_RE.fullmatch(
        args.expected_backup_sha256
    ) is None:
        raise BackupInventoryPreflightError("backup_hash_mismatch", "backup_preflight")
    if not Path(args.backup_path).is_absolute():
        raise BackupInventoryPreflightError("backup_path_invalid", "backup_preflight")
    if not Path(args.evidence_output).is_absolute():
        raise BackupInventoryPreflightError("evidence_path_unsafe", "evidence_preflight")
    args.mysql_binary = str(_explicit_executable(args.mysql_binary, expected_name="mysql"))
    args.mysqldump_binary = str(
        _explicit_executable(args.mysqldump_binary, expected_name="mysqldump")
    )


def _backup_sanitizer_error_code(error: LegacyBackupSanitizationError) -> str:
    message = str(error).lower()
    if "changed" in message:
        return "backup_changed_during_run"
    if "sha-256" in message or "digest" in message:
        return "backup_hash_mismatch"
    if "path" in message or "regular file" in message or "symbolic link" in message:
        return "backup_path_invalid"
    return "unsafe_backup_sql"


def _backup_execution_error_code(error: Exception, *, phase: str) -> str:
    message = str(error).lower()
    if isinstance(error, BackupInventoryPreflightError):
        return error.error_code
    if isinstance(error, LegacyBackupSanitizationError):
        return _backup_sanitizer_error_code(error)
    if isinstance(error, LegacyRunEvidenceError):
        if phase == "candidate_preflight":
            return "candidate_source_not_clean"
        if phase in {"evidence_preflight", "evidence_write"}:
            return (
                "evidence_write_failed"
                if phase == "evidence_write"
                else "evidence_path_unsafe"
            )
        if phase == "side_effect_verification":
            return "task_sentinel_changed"
    if "protected_schema_collision" in message:
        return "protected_schema_collision"
    if "required_table_missing" in message:
        return "required_table_missing"
    if "unsupported_legacy_shape" in message:
        return "unsupported_legacy_shape"
    if "task_sentinel_changed" in message or phase == "side_effect_verification":
        return "task_sentinel_changed"
    if "restored legacy facts differ" in message or phase == "snapshot_verification":
        return "source_target_snapshot_mismatch"
    if "inventory" in message or phase == "inventory_verification":
        return "inventory_digest_mismatch"
    return "source_restore_failed"


def run_backup_inventory(
    args: argparse.Namespace,
    *,
    repo_root: Path = ROOT,
    source_files: Iterable[str] = SOURCE_FILE_RELATIVE_PATHS,
) -> dict[str, Any]:
    """Restore one sanitized historical archive and prove a read-only inventory."""

    observations = CommandObservations()
    mysql: LocalMySQL | None = None
    reservations: list[ProtectedSchemaReservation] = []
    temp_directory_path: Path | None = None
    failure: Exception | None = None
    failure_phase = "cli_preflight"
    evidence_payload: dict[str, Any] | None = None
    protected_before: list[str] = []
    cleanup = {
        "success": True,
        "owned_schemas": [],
        "dropped_schemas": [],
        "skipped_schemas": [],
        "residual_schemas": [],
        "cleanup_errors": [],
        "protected_schemas_after": [],
        "reservations": [],
        "temporary_directory_removed": True,
    }

    _emit_backup_progress("preflight")
    try:
        _validate_backup_inventory_args(args)
        failure_phase = "candidate_preflight"
        source_identity = build_source_identity(
            repo_root,
            supplied_candidate_sha=args.candidate_sha,
            source_files=source_files,
            observer=observations,
            require_clean=True,
        )
        failure_phase = "evidence_preflight"
        evidence_output = validate_evidence_output_path(
            repo_root,
            Path(args.evidence_output),
            observer=observations,
        )

        failure_phase = "server_preflight"
        mysql = LocalMySQL(
            mysql_binary=args.mysql_binary,
            mysqldump_binary=args.mysqldump_binary,
            host=args.host,
            port=args.port,
            user=args.user,
            command_observer=observations.observe,
        )
        server_facts = mysql.server_facts()
        protected_before = mysql.list_protected_schemas()
        nonce = uuid.uuid4().hex[:16]
        source_schema = f"fbm_pipeline_ih_{nonce}_source"
        target_schema = f"fbm_pipeline_ih_{nonce}_target"
        failure_phase = "schema_reservation"
        reservations = reserve_protected_schemas(
            mysql,
            (source_schema, target_schema),
        )
        source_reservation, target_reservation = reservations

        failure_phase = "backup_preflight"
        with open_sanitized_backup(
            Path(args.backup_path),
            expected_backup_sha256=args.expected_backup_sha256,
            target_mysql_version=server_facts["server_version"],
        ) as opened_backup:
            with tempfile.TemporaryDirectory(
                prefix="fbm_pipeline_ih_historical_"
            ) as temp_dir:
                temp_directory_path = Path(temp_dir)
                canonical_backup_path = temp_directory_path / "canonical.sql"
                isolated_data_dir = temp_directory_path / "data"
                step10_dir = isolated_data_dir / "amazon_templates"
                step10_dir.mkdir(parents=True)
                (step10_dir / "sentinel.keep").write_text(
                    "historical inventory must not create Step 10 output\n",
                    encoding="utf-8",
                )
                step10_before = snapshot_directory(step10_dir)
                previous_data_dir = os.environ.get("DATA_DIR")
                had_data_dir = "DATA_DIR" in os.environ
                os.environ["DATA_DIR"] = str(isolated_data_dir)
                try:
                    failure_phase = "source_import"
                    _emit_backup_progress("source_import")
                    create_reserved_schema(mysql, source_reservation)
                    mysql.import_backup_stream(
                        source_schema,
                        opened_backup.rewind_for_import(),
                    )
                    raw_backup = opened_backup.verify_unchanged()

                    failure_phase = "source_read"
                    _emit_backup_progress("source_inventory")
                    source_read = mysql.read_dataset_with_profile(source_schema)
                    compatibility_profile = source_read["compatibility_profile"]
                    source_dataset = source_read["dataset"]
                    source_snapshot = build_verification_snapshot(source_dataset)
                    source_task_before = mysql.table_state_snapshot(
                        source_schema,
                        ("task_runs", "task_steps"),
                    )

                    failure_phase = "inventory_verification"
                    source_inventory = build_legacy_inventory(source_dataset)
                    verify_inventory_records(
                        source_inventory["records"],
                        expected_sha256=source_inventory["records_sha256"],
                        expected_count=source_inventory["inventory_record_count"],
                    )

                    failure_phase = "canonical_dump"
                    _emit_backup_progress("canonical_dump")
                    canonical_backup = mysql.dump_schema_streaming(
                        source_schema,
                        canonical_backup_path,
                    )
                    manifest = build_historical_archive_source_manifest(
                        source_schema=source_schema,
                        historical_archive_sha256=raw_backup["backup_sha256"],
                        server_facts=server_facts,
                        verification_snapshot=source_snapshot,
                        backup_path=canonical_backup_path,
                        backup_sha256=canonical_backup["backup_sha256"],
                        tool_version=canonical_backup["tool_version"],
                    )
                    manifest_evidence = verify_manifest_and_backup(
                        manifest,
                        canonical_backup_path,
                    )

                    failure_phase = "target_import"
                    _emit_backup_progress("target_import")
                    create_reserved_schema(mysql, target_reservation)
                    with canonical_backup_path.open("rb") as canonical_stream:
                        mysql.import_backup_stream(target_schema, canonical_stream)

                    failure_phase = "target_read"
                    _emit_backup_progress("verification")
                    target_read = mysql.read_dataset_with_profile(
                        target_schema,
                        expected_profile=compatibility_profile,
                    )
                    target_dataset = target_read["dataset"]
                    target_snapshot = build_verification_snapshot(target_dataset)
                    target_task_before = mysql.table_state_snapshot(
                        target_schema,
                        ("task_runs", "task_steps"),
                    )

                    failure_phase = "snapshot_verification"
                    restore_verification = verify_source_restore(
                        source_snapshot,
                        target_snapshot,
                    )

                    failure_phase = "inventory_verification"
                    target_inventory = build_legacy_inventory(target_dataset)
                    verify_inventory_records(
                        target_inventory["records"],
                        expected_sha256=target_inventory["records_sha256"],
                        expected_count=target_inventory["inventory_record_count"],
                    )
                    if source_inventory != target_inventory:
                        raise LegacyInventoryVerificationError(
                            "inventory_digest_mismatch: source and target inventory differ"
                        )

                    failure_phase = "side_effect_verification"
                    source_task_after = mysql.table_state_snapshot(
                        source_schema,
                        ("task_runs", "task_steps"),
                    )
                    target_task_after = mysql.table_state_snapshot(
                        target_schema,
                        ("task_runs", "task_steps"),
                    )
                    if not (
                        source_task_before
                        == source_task_after
                        == target_task_before
                        == target_task_after
                    ):
                        raise LegacyInventoryVerificationError(
                            "task_sentinel_changed: source and target task states differ"
                        )
                    step10_after = snapshot_directory(step10_dir)
                    source_side_effects = verify_zero_side_effect_deltas(
                        task_state_before=source_task_before,
                        task_state_after=source_task_after,
                        step10_before=step10_before,
                        step10_after=step10_after,
                    )
                    target_side_effects = verify_zero_side_effect_deltas(
                        task_state_before=target_task_before,
                        task_state_after=target_task_after,
                        step10_before=step10_before,
                        step10_after=step10_after,
                    )

                    evidence_payload = {
                        "scope": BACKUP_SCOPE,
                        "candidate": source_identity,
                        "mysql": {
                            "endpoint": ALLOWED_DATABASE_ENDPOINT,
                            **server_facts,
                        },
                        "backup": {
                            "historical_archive": raw_backup,
                            "sanitizer": opened_backup.sanitizer_result,
                            "canonical_dump": canonical_backup,
                        },
                        "compatibility_profile": compatibility_profile,
                        "source_manifest": {
                            "body": manifest,
                            "source_manifest_sha256": manifest_evidence[
                                "source_manifest_sha256"
                            ],
                            "detached_digest": manifest_evidence[
                                "manifest_digest_bytes"
                            ].decode("ascii"),
                        },
                        "restore": {
                            "source_snapshot": source_snapshot,
                            "target_snapshot": target_snapshot,
                            "verification": restore_verification,
                        },
                        "inventory": source_inventory,
                        "target_inventory": {
                            "classification_counts": target_inventory[
                                "classification_counts"
                            ],
                            "inventory_record_count": target_inventory[
                                "inventory_record_count"
                            ],
                            "records_sha256": target_inventory["records_sha256"],
                        },
                        "side_effects": {
                            "source": source_side_effects,
                            "target": target_side_effects,
                        },
                        "execution_boundary": {
                            "allowed_subprocesses": sorted(ALLOWED_SUBPROCESSES),
                            "allowed_database_endpoint": ALLOWED_DATABASE_ENDPOINT,
                            "observed": observations.snapshot(),
                        },
                    }
                finally:
                    if had_data_dir:
                        assert previous_data_dir is not None
                        os.environ["DATA_DIR"] = previous_data_dir
                    else:
                        os.environ.pop("DATA_DIR", None)
    except Exception as exc:
        failure = exc
    finally:
        _emit_backup_progress("cleanup")
        temporary_directory_removed = (
            temp_directory_path is None or not temp_directory_path.exists()
        )
        if mysql is not None and reservations:
            try:
                cleanup = cleanup_reserved_schemas(mysql, reservations)
            except Exception as cleanup_error:
                cleanup = {
                    **cleanup,
                    "success": False,
                    "cleanup_errors": [
                        f"cleanup:{type(cleanup_error).__name__}"
                    ],
                }
        cleanup["temporary_directory_removed"] = temporary_directory_removed
        cleanup["protected_schemas_before"] = protected_before
        cleanup["success"] = bool(
            cleanup.get("success") and temporary_directory_removed
        )
        if not temporary_directory_removed:
            cleanup.setdefault("cleanup_errors", []).append(
                "temporary_directory_not_removed"
            )

    if not cleanup["success"]:
        primary_error_code = None
        if failure is not None:
            primary_phase = (
                failure.phase
                if isinstance(failure, BackupInventoryPreflightError)
                else failure_phase
            )
            primary_error_code = _backup_execution_error_code(
                failure,
                phase=primary_phase,
            )
        raise LegacyInventoryRunFailure(
            build_backup_failure_summary(
                error_code="cleanup_failed",
                phase="cleanup",
                cleanup_success=False,
                primary_error_code=primary_error_code,
            )
        ) from None
    if failure is not None:
        failure_phase = (
            failure.phase
            if isinstance(failure, BackupInventoryPreflightError)
            else failure_phase
        )
        raise LegacyInventoryRunFailure(
            build_backup_failure_summary(
                error_code=_backup_execution_error_code(
                    failure,
                    phase=failure_phase,
                ),
                phase=failure_phase,
                cleanup_success=True,
            )
        ) from None
    if evidence_payload is None:
        raise LegacyInventoryRunFailure(
            build_backup_failure_summary(
                error_code="source_restore_failed",
                phase="inventory_verification",
                cleanup_success=True,
            )
        ) from None

    evidence_payload["cleanup"] = cleanup
    failure_phase = "evidence_write"
    _emit_backup_progress("evidence_write")
    try:
        final_evidence_output = validate_evidence_output_path(
            repo_root,
            Path(args.evidence_output),
            observer=observations,
        )
        evidence_payload["execution_boundary"]["observed"] = observations.snapshot()
        evidence_write = write_private_evidence(
            repo_root,
            final_evidence_output,
            evidence_payload,
            observer=observations,
            prevalidated_output_path=final_evidence_output,
        )
    except Exception as exc:
        raise LegacyInventoryRunFailure(
            build_backup_failure_summary(
                error_code=_backup_execution_error_code(
                    exc,
                    phase=failure_phase,
                ),
                phase=failure_phase,
                cleanup_success=True,
            )
        ) from None

    _emit_backup_progress("completed")
    return {
        "status": "completed",
        "scope": BACKUP_SCOPE,
        "classification_counts": evidence_payload["inventory"][
            "classification_counts"
        ],
        "inventory_record_count": evidence_payload["inventory"][
            "inventory_record_count"
        ],
        "backup_sha256": evidence_payload["backup"]["historical_archive"][
            "backup_sha256"
        ],
        "canonical_dump_sha256": evidence_payload["backup"]["canonical_dump"][
            "backup_sha256"
        ],
        "source_snapshot_sha256": canonical_sha256_hex(
            evidence_payload["restore"]["source_snapshot"]
        ),
        "target_snapshot_sha256": canonical_sha256_hex(
            evidence_payload["restore"]["target_snapshot"]
        ),
        "records_sha256": evidence_payload["inventory"]["records_sha256"],
        "evidence_sha256": evidence_write["evidence_sha256"],
        "cleanup_success": True,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run protected non-empty Legacy inventory backup/restore verification."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture-e2e", action="store_true")
    mode.add_argument("--backup-inventory", action="store_true")
    parser.add_argument("--backup-path")
    parser.add_argument("--expected-backup-sha256")
    parser.add_argument("--evidence-output")
    parser.add_argument("--mysql-binary", default="/opt/homebrew/bin/mysql")
    parser.add_argument("--mysqldump-binary", default="/opt/homebrew/bin/mysqldump")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--candidate-sha", default="")
    parser.add_argument("--allow-passwordless-local", action="store_true")
    args = parser.parse_args(argv)
    if args.backup_inventory:
        explicit_options = {token.split("=", 1)[0] for token in argv if token.startswith("--")}
        required_options = (
            "--backup-path",
            "--expected-backup-sha256",
            "--evidence-output",
            "--candidate-sha",
            "--mysql-binary",
            "--mysqldump-binary",
            "--host",
            "--port",
            "--user",
            "--allow-passwordless-local",
        )
        missing = [option for option in required_options if option not in explicit_options]
        if missing:
            parser.error(
                "--backup-inventory requires explicit arguments: " + ", ".join(missing)
            )
        if _LOWER_SHA1_RE.fullmatch(args.candidate_sha or "") is None:
            parser.error("--candidate-sha must be 40 lowercase hexadecimal characters")
        if _LOWER_SHA256_RE.fullmatch(args.expected_backup_sha256 or "") is None:
            parser.error(
                "--expected-backup-sha256 must be 64 lowercase hexadecimal characters"
            )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        summary = run_backup_inventory(args) if args.backup_inventory else run_fixture_e2e(args)
    except LegacyInventoryRunFailure as exc:
        print(json.dumps(exc.summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
