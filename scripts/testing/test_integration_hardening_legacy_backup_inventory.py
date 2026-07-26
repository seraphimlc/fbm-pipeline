#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from integration_hardening.common import canonical_json_bytes  # noqa: E402
from integration_hardening import legacy_backup_sanitizer  # noqa: E402
from integration_hardening import legacy_inventory_mysql  # noqa: E402
from integration_hardening import legacy_migration  # noqa: E402
from integration_hardening import legacy_run_evidence  # noqa: E402


SQL_MODE_NORMALIZE = (
    b"/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;\n"
)
SQL_MODE_RESTORE = b"/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;\n"
SAFE_BACKUP = (
    SQL_MODE_NORMALIZE
    + b"CREATE TABLE `products` (`id` int NOT NULL);\n"
    + b"INSERT INTO `products` VALUES (1);\n"
    + SQL_MODE_RESTORE
)


class FailingProgressStream(StringIO):
    def __init__(self, *, phase: str, operation: str) -> None:
        super().__init__()
        self.phase_line = f"backup_inventory phase={phase}\n"
        self.operation = operation
        self.last_write = ""

    def write(self, text: str) -> int:
        self.last_write = text
        if self.operation == "write" and text == self.phase_line:
            raise OSError("forced progress write failure")
        return super().write(text)

    def flush(self) -> None:
        if self.operation == "flush" and self.last_write == self.phase_line:
            raise OSError("forced progress flush failure")
        super().flush()


# B1 test list (pure, no MySQL connection):
# - CLI modes are exclusive and backup mode requires every explicit safety input
# - passwordless local authentication is explicit, never inferred
# - backup runtime source identity includes the sanitizer and requires a clean exact HEAD
# - backup preflight rejects relative/symlink inputs and holds one stable read-only FD
# - in-place mutation or path replacement is detected before a successful result
# - evidence stays outside every Git worktree and uses 0700 parent / 0600 no-clobber file
# - evidence digest covers the exact canonical bytes on disk and never contains itself
# - backup mode completes all pure preflight then fails closed before any DB call
# - failure stdout contains only stable compact fields and never raw private detail
# - success stdout remains exactly one final compact JSON line


def _run_git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _init_repo(repo: Path) -> str:
    repo.mkdir()
    (repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "fixture@example.invalid")
    _run_git(repo, "config", "user.name", "Fixture")
    _run_git(repo, "add", "source.py")
    _run_git(repo, "commit", "-m", "fixture")
    return _run_git(repo, "rev-parse", "HEAD")


def _required_callable(module: object, name: str):
    value = getattr(module, name, None)
    if not callable(value):
        raise AssertionError(f"required callable is missing: {module.__name__}.{name}")
    return value


class LegacyBackupInventoryPureTests(unittest.TestCase):
    def test_success_cli_stdout_is_exactly_one_compact_json_line(self) -> None:
        summary = {
            "cleanup_success": True,
            "scope": "historical_archive_restore_inventory",
            "status": "completed",
        }
        stdout = StringIO()
        stderr = StringIO()
        with mock.patch.object(
            legacy_migration,
            "parse_args",
            return_value=SimpleNamespace(backup_inventory=True),
        ), mock.patch.object(
            legacy_migration,
            "run_backup_inventory",
            return_value=summary,
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(legacy_migration.main(["--backup-inventory"]), 0)
        expected = json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(stdout.getvalue(), expected + "\n")
        self.assertEqual(stdout.getvalue().splitlines(), [expected])

    def test_cleanup_progress_write_failure_preserves_primary_error_and_cleanup(
        self,
    ) -> None:
        args = SimpleNamespace(
            candidate_sha="a" * 40,
            evidence_output="/private/evidence.json",
            host="127.0.0.1",
            mysql_binary="/opt/homebrew/bin/mysql",
            mysqldump_binary="/opt/homebrew/bin/mysqldump",
            port=3306,
            user="root",
        )
        mysql = SimpleNamespace(
            server_facts=lambda: {
                "server_version": "8.0.0",
                "server_uuid": "0" * 32,
            },
            list_protected_schemas=lambda: [],
        )
        reservations = [SimpleNamespace(schema="source"), SimpleNamespace(schema="target")]
        cleanup_calls: list[tuple[object, object]] = []

        def cleanup_reserved_schemas(mysql_arg, reservations_arg):
            cleanup_calls.append((mysql_arg, reservations_arg))
            return {
                "success": True,
                "owned_schemas": ["source", "target"],
                "dropped_schemas": ["target", "source"],
                "skipped_schemas": [],
                "residual_schemas": [],
                "cleanup_errors": [],
                "protected_schemas_after": [],
                "reservations": [],
            }

        progress = FailingProgressStream(phase="cleanup", operation="write")
        patches = (
            mock.patch.object(legacy_migration, "_validate_backup_inventory_args"),
            mock.patch.object(
                legacy_migration,
                "build_source_identity",
                return_value={"candidate_sha": args.candidate_sha},
            ),
            mock.patch.object(
                legacy_migration,
                "validate_evidence_output_path",
                return_value=Path(args.evidence_output),
            ),
            mock.patch.object(legacy_migration, "LocalMySQL", return_value=mysql),
            mock.patch.object(
                legacy_migration,
                "reserve_protected_schemas",
                return_value=reservations,
            ),
            mock.patch.object(
                legacy_migration,
                "open_sanitized_backup",
                side_effect=legacy_migration.LegacyInventoryExecutionError(
                    "forced primary restore failure"
                ),
            ),
            mock.patch.object(
                legacy_migration,
                "cleanup_reserved_schemas",
                side_effect=cleanup_reserved_schemas,
            ),
        )
        with ExitStack() as stack:
            stack.enter_context(redirect_stderr(progress))
            for patch in patches:
                stack.enter_context(patch)
            with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                legacy_migration.run_backup_inventory(args)

        self.assertEqual(cleanup_calls, [(mysql, reservations)])
        self.assertEqual(caught.exception.summary["phase"], "backup_preflight")
        self.assertEqual(caught.exception.summary["error_code"], "source_restore_failed")
        self.assertTrue(caught.exception.summary["cleanup_success"])

    def test_primary_and_cleanup_failure_preserve_stable_primary_error_code(
        self,
    ) -> None:
        args = SimpleNamespace(
            candidate_sha="a" * 40,
            evidence_output="/private/evidence.json",
            host="127.0.0.1",
            mysql_binary="/opt/homebrew/bin/mysql",
            mysqldump_binary="/opt/homebrew/bin/mysqldump",
            port=3306,
            user="root",
        )
        mysql = SimpleNamespace(
            server_facts=lambda: {
                "server_version": "8.0.0",
                "server_uuid": "0" * 32,
            },
            list_protected_schemas=lambda: [],
        )
        reservations = [SimpleNamespace(schema="source"), SimpleNamespace(schema="target")]
        cleanup = {
            "success": False,
            "owned_schemas": ["source", "target"],
            "dropped_schemas": ["source"],
            "skipped_schemas": [],
            "residual_schemas": ["target"],
            "cleanup_errors": ["cleanup:forced"],
            "protected_schemas_after": ["target"],
            "reservations": [],
        }
        patches = (
            mock.patch.object(legacy_migration, "_validate_backup_inventory_args"),
            mock.patch.object(
                legacy_migration,
                "build_source_identity",
                return_value={"candidate_sha": args.candidate_sha},
            ),
            mock.patch.object(
                legacy_migration,
                "validate_evidence_output_path",
                return_value=Path(args.evidence_output),
            ),
            mock.patch.object(legacy_migration, "LocalMySQL", return_value=mysql),
            mock.patch.object(
                legacy_migration,
                "reserve_protected_schemas",
                return_value=reservations,
            ),
            mock.patch.object(
                legacy_migration,
                "open_sanitized_backup",
                side_effect=legacy_migration.LegacyInventoryExecutionError(
                    "password=private B000000001 ITEM-PRIVATE"
                ),
            ),
            mock.patch.object(
                legacy_migration,
                "cleanup_reserved_schemas",
                return_value=cleanup,
            ),
        )
        with ExitStack() as stack:
            stack.enter_context(redirect_stderr(StringIO()))
            for patch in patches:
                stack.enter_context(patch)
            with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                legacy_migration.run_backup_inventory(args)

        self.assertEqual(
            caught.exception.summary,
            {
                "status": "failed",
                "scope": "historical_archive_restore_inventory",
                "error_code": "cleanup_failed",
                "phase": "cleanup",
                "cleanup_success": False,
                "message": "protected schema or temporary resource cleanup failed",
                "primary_error_code": "source_restore_failed",
                "cleanup_failed": True,
            },
        )
        rendered = canonical_json_bytes(caught.exception.summary).decode("utf-8")
        for private_value in ("private", "B000000001", "ITEM-PRIVATE"):
            self.assertNotIn(private_value, rendered)

    def test_cleanup_failure_without_primary_keeps_compact_cleanup_summary(self) -> None:
        summary = legacy_migration.build_backup_failure_summary(
            error_code="cleanup_failed",
            phase="cleanup",
            cleanup_success=False,
        )
        self.assertEqual(
            summary,
            {
                "status": "failed",
                "scope": "historical_archive_restore_inventory",
                "error_code": "cleanup_failed",
                "phase": "cleanup",
                "cleanup_success": False,
                "message": "protected schema or temporary resource cleanup failed",
            },
        )

    def test_completed_progress_flush_failure_cannot_reverse_published_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="legacy_progress_success_") as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            candidate_sha = _init_repo(repo)
            backup_path = root / "archive.sql"
            backup_path.write_bytes(SAFE_BACKUP)
            evidence_parent = root / "evidence"
            evidence_parent.mkdir(mode=0o700)
            evidence_output = evidence_parent / "result.json"
            args = SimpleNamespace(
                backup_path=str(backup_path),
                candidate_sha=candidate_sha,
                evidence_output=str(evidence_output),
                expected_backup_sha256=hashlib.sha256(SAFE_BACKUP).hexdigest(),
                host="127.0.0.1",
                mysql_binary="/opt/homebrew/bin/mysql",
                mysqldump_binary="/opt/homebrew/bin/mysqldump",
                port=3306,
                user="root",
            )
            dataset = {"products": []}
            inventory = {
                "classification_counts": {},
                "inventory_record_count": 0,
                "records": [],
                "records_sha256": "1" * 64,
            }
            task_state = {
                "task_runs": {"presence": "absent"},
                "task_steps": {"presence": "absent"},
            }

            class SuccessfulMySQL:
                def server_facts(self):
                    return {"server_version": "8.0.0", "server_uuid": "0" * 32}

                def list_protected_schemas(self):
                    return []

                def import_backup_stream(self, schema, stream):
                    stream.read()

                def read_dataset_with_profile(self, schema, expected_profile=None):
                    return {
                        "compatibility_profile": {"mode": "synthetic"},
                        "dataset": dataset,
                    }

                def table_state_snapshot(self, schema, tables):
                    return task_state

                def dump_schema_streaming(self, schema, output_path):
                    output_path.write_bytes(b"canonical dump\n")
                    return {
                        "backup_sha256": hashlib.sha256(
                            b"canonical dump\n"
                        ).hexdigest(),
                        "size_bytes": len(b"canonical dump\n"),
                        "tool_version": "mysqldump synthetic",
                    }

            opened_backup = SimpleNamespace(
                sanitizer_result={"target_mysql_version": "8.0.0"},
                rewind_for_import=lambda: BytesIO(SAFE_BACKUP),
                verify_unchanged=lambda: {
                    "backup_sha256": hashlib.sha256(SAFE_BACKUP).hexdigest()
                },
            )
            opened_context = mock.MagicMock()
            opened_context.__enter__.return_value = opened_backup
            opened_context.__exit__.return_value = False
            reservations = [
                SimpleNamespace(schema="source"),
                SimpleNamespace(schema="target"),
            ]
            progress = FailingProgressStream(phase="completed", operation="flush")
            cleanup = {
                "success": True,
                "owned_schemas": ["source", "target"],
                "dropped_schemas": ["target", "source"],
                "skipped_schemas": [],
                "residual_schemas": [],
                "cleanup_errors": [],
                "protected_schemas_after": [],
                "reservations": [],
            }
            patches = (
                mock.patch.object(legacy_migration, "_validate_backup_inventory_args"),
                mock.patch.object(
                    legacy_migration,
                    "build_source_identity",
                    return_value={"candidate_sha": candidate_sha},
                ),
                mock.patch.object(
                    legacy_migration,
                    "LocalMySQL",
                    return_value=SuccessfulMySQL(),
                ),
                mock.patch.object(
                    legacy_migration,
                    "reserve_protected_schemas",
                    return_value=reservations,
                ),
                mock.patch.object(legacy_migration, "create_reserved_schema"),
                mock.patch.object(
                    legacy_migration,
                    "open_sanitized_backup",
                    return_value=opened_context,
                ),
                mock.patch.object(
                    legacy_migration,
                    "build_verification_snapshot",
                    return_value={"snapshot": "stable"},
                ),
                mock.patch.object(
                    legacy_migration,
                    "build_legacy_inventory",
                    return_value=inventory,
                ),
                mock.patch.object(legacy_migration, "verify_inventory_records"),
                mock.patch.object(
                    legacy_migration,
                    "build_historical_archive_source_manifest",
                    return_value={"manifest": "synthetic"},
                ),
                mock.patch.object(
                    legacy_migration,
                    "verify_manifest_and_backup",
                    return_value={
                        "source_manifest_sha256": "2" * 64,
                        "manifest_digest_bytes": b"3" * 64,
                    },
                ),
                mock.patch.object(
                    legacy_migration,
                    "verify_source_restore",
                    return_value={"verified": True},
                ),
                mock.patch.object(
                    legacy_migration,
                    "verify_zero_side_effect_deltas",
                    return_value={"verified": True},
                ),
                mock.patch.object(
                    legacy_migration,
                    "cleanup_reserved_schemas",
                    return_value=cleanup,
                ),
            )
            with ExitStack() as stack:
                stack.enter_context(redirect_stderr(progress))
                for patch in patches:
                    stack.enter_context(patch)
                summary = legacy_migration.run_backup_inventory(
                    args,
                    repo_root=repo,
                    source_files=("source.py",),
                )

            self.assertEqual(summary["status"], "completed")
            self.assertTrue(summary["cleanup_success"])
            self.assertTrue(evidence_output.is_file())
            self.assertEqual(evidence_output.stat().st_mode & 0o777, 0o600)

    def _backup_argv(
        self,
        *,
        backup: Path,
        evidence: Path,
        candidate_sha: str,
        mysql_binary: Path,
        mysqldump_binary: Path,
        allow_passwordless: bool = True,
    ) -> list[str]:
        argv = [
            "--backup-inventory",
            "--backup-path",
            str(backup),
            "--expected-backup-sha256",
            hashlib.sha256(SAFE_BACKUP).hexdigest(),
            "--evidence-output",
            str(evidence),
            "--candidate-sha",
            candidate_sha,
            "--mysql-binary",
            str(mysql_binary),
            "--mysqldump-binary",
            str(mysqldump_binary),
            "--host",
            "127.0.0.1",
            "--port",
            "3306",
            "--user",
            "root",
        ]
        if allow_passwordless:
            argv.append("--allow-passwordless-local")
        return argv

    def test_cli_requires_exactly_one_mode_and_all_backup_safety_inputs(self) -> None:
        parse_args = legacy_migration.parse_args
        for argv in (
            [],
            ["--fixture-e2e", "--backup-inventory"],
            ["--backup-inventory"],
        ):
            with self.subTest(argv=argv), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    parse_args(argv)

        fixture = parse_args(["--fixture-e2e"])
        self.assertTrue(fixture.fixture_e2e)
        self.assertFalse(fixture.backup_inventory)

        with tempfile.TemporaryDirectory(prefix="legacy_backup_cli_") as temp_dir:
            root = Path(temp_dir)
            argv = self._backup_argv(
                backup=root / "archive.sql",
                evidence=root / "evidence.json",
                candidate_sha="a" * 40,
                mysql_binary=root / "mysql",
                mysqldump_binary=root / "mysqldump",
            )
            parsed = parse_args(argv)
            self.assertTrue(parsed.backup_inventory)
            self.assertFalse(parsed.fixture_e2e)
            self.assertTrue(parsed.allow_passwordless_local)

    def test_cli_requires_explicit_passwordless_local_auth(self) -> None:
        with tempfile.TemporaryDirectory(prefix="legacy_backup_auth_") as temp_dir:
            root = Path(temp_dir)
            argv = self._backup_argv(
                backup=root / "archive.sql",
                evidence=root / "evidence.json",
                candidate_sha="a" * 40,
                mysql_binary=root / "mysql",
                mysqldump_binary=root / "mysqldump",
                allow_passwordless=False,
            )
            stderr = StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                legacy_migration.parse_args(argv)
            self.assertIn("--allow-passwordless-local", stderr.getvalue())

    def test_explicit_executable_resolves_homebrew_symlink_and_rejects_unsafe_targets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="legacy_backup_tools_") as temp_dir:
            root = Path(temp_dir)
            cellar_bin = root / "Cellar" / "mysql" / "9.6.0" / "bin"
            cellar_bin.mkdir(parents=True)
            mysql_target = cellar_bin / "mysql"
            mysqldump_target = cellar_bin / "mysqldump"
            for target in (mysql_target, mysqldump_target):
                target.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
                target.chmod(0o700)
            homebrew_bin = root / "homebrew" / "bin"
            homebrew_bin.mkdir(parents=True)
            mysql_entry = homebrew_bin / "mysql"
            mysqldump_entry = homebrew_bin / "mysqldump"
            mysql_entry.symlink_to(mysql_target)
            mysqldump_entry.symlink_to(mysqldump_target)

            resolved = legacy_migration._explicit_executable(
                str(mysql_entry),
                expected_name="mysql",
            )
            self.assertEqual(resolved, mysql_target.resolve(strict=True))

            args = legacy_migration.parse_args(
                self._backup_argv(
                    backup=root / "archive.sql",
                    evidence=root / "evidence.json",
                    candidate_sha="a" * 40,
                    mysql_binary=mysql_entry,
                    mysqldump_binary=mysqldump_entry,
                )
            )
            legacy_migration._validate_backup_inventory_args(args)
            self.assertEqual(Path(args.mysql_binary), mysql_target.resolve(strict=True))
            self.assertEqual(
                Path(args.mysqldump_binary),
                mysqldump_target.resolve(strict=True),
            )

            dangling = homebrew_bin / "dangling" / "mysql"
            dangling.parent.mkdir()
            dangling.symlink_to(root / "missing" / "mysql")
            wrong_target = root / "mysql-real"
            wrong_target.write_text("#!/bin/sh\n", encoding="utf-8")
            wrong_target.chmod(0o700)
            wrong_name_entry = homebrew_bin / "wrong-name" / "mysql"
            wrong_name_entry.parent.mkdir()
            wrong_name_entry.symlink_to(wrong_target)
            nonexec_target = root / "nonexec" / "mysql"
            nonexec_target.parent.mkdir()
            nonexec_target.write_text("#!/bin/sh\n", encoding="utf-8")
            nonexec_target.chmod(0o600)
            nonexec_entry = homebrew_bin / "nonexec" / "mysql"
            nonexec_entry.parent.mkdir()
            nonexec_entry.symlink_to(nonexec_target)

            for label, entry in (
                ("dangling", dangling),
                ("wrong basename", wrong_name_entry),
                ("non-executable", nonexec_entry),
            ):
                with self.subTest(label=label), self.assertRaises(
                    legacy_migration.BackupInventoryPreflightError
                ):
                    legacy_migration._explicit_executable(
                        str(entry),
                        expected_name="mysql",
                    )

    def test_cyclic_executable_symlink_returns_compact_failure_without_raw_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="legacy_backup_tool_cycle_") as temp_dir:
            root = Path(temp_dir)
            first = root / "first" / "mysql"
            second = root / "second" / "mysql"
            first.parent.mkdir()
            second.parent.mkdir()
            first.symlink_to(second)
            second.symlink_to(first)
            mysqldump = root / "mysqldump"
            mysqldump.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            mysqldump.chmod(0o700)
            args = legacy_migration.parse_args(
                self._backup_argv(
                    backup=root / "archive.sql",
                    evidence=root / "evidence.json",
                    candidate_sha="a" * 40,
                    mysql_binary=first,
                    mysqldump_binary=mysqldump,
                )
            )

            with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                legacy_migration.run_backup_inventory(args, repo_root=root)
            self.assertEqual(
                caught.exception.summary,
                {
                    "status": "failed",
                    "scope": "historical_archive_restore_inventory",
                    "error_code": "invalid_tool_path",
                    "phase": "cli_preflight",
                    "cleanup_success": True,
                    "message": "mysql tools must be explicit absolute executable files",
                },
            )
            rendered = canonical_json_bytes(caught.exception.summary).decode("utf-8")
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("RuntimeError", rendered)

    def test_backup_source_identity_requires_clean_exact_head_and_binds_sanitizer(self) -> None:
        self.assertIn(
            "scripts/integration_hardening/legacy_backup_sanitizer.py",
            legacy_run_evidence.SOURCE_FILE_RELATIVE_PATHS,
        )
        with tempfile.TemporaryDirectory(prefix="legacy_backup_source_") as temp_dir:
            repo = Path(temp_dir) / "repo"
            head_sha = _init_repo(repo)
            identity = legacy_run_evidence.build_source_identity(
                repo,
                supplied_candidate_sha=head_sha,
                source_files=("source.py",),
                require_clean=True,
            )
            self.assertEqual(identity["source_state"], "clean")
            with self.assertRaisesRegex(
                legacy_run_evidence.LegacyRunEvidenceError,
                "does not equal actual HEAD",
            ):
                legacy_run_evidence.build_source_identity(
                    repo,
                    supplied_candidate_sha="0" * 40,
                    source_files=("source.py",),
                    require_clean=True,
                )

            (repo / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(
                legacy_run_evidence.LegacyRunEvidenceError,
                "clean",
            ):
                legacy_run_evidence.build_source_identity(
                    repo,
                    supplied_candidate_sha=head_sha,
                    source_files=("source.py",),
                    require_clean=True,
                )

    def test_opened_backup_rejects_relative_or_symlink_and_uses_one_stable_fd(self) -> None:
        open_sanitized_backup = _required_callable(
            legacy_migration,
            "open_sanitized_backup",
        )
        digest = hashlib.sha256(SAFE_BACKUP).hexdigest()
        with tempfile.TemporaryDirectory(prefix="legacy_backup_fd_") as temp_dir:
            root = Path(temp_dir)
            backup = root / "archive.sql"
            backup.write_bytes(SAFE_BACKUP)
            link = root / "archive-link.sql"
            link.symlink_to(backup)

            with self.assertRaisesRegex(
                legacy_backup_sanitizer.LegacyBackupSanitizationError,
                "absolute",
            ):
                with open_sanitized_backup(
                    Path("archive.sql"),
                    expected_backup_sha256=digest,
                    target_mysql_version="8.0.46",
                ):
                    self.fail("relative backup path must fail before yielding")
            with self.assertRaisesRegex(
                legacy_backup_sanitizer.LegacyBackupSanitizationError,
                "symlink|symbolic",
            ):
                with open_sanitized_backup(
                    link,
                    expected_backup_sha256=digest,
                    target_mysql_version="8.0.46",
                ):
                    self.fail("backup symlink must fail before yielding")
            with self.assertRaisesRegex(
                legacy_backup_sanitizer.LegacyBackupSanitizationError,
                "SHA-256|digest",
            ):
                with open_sanitized_backup(
                    backup,
                    expected_backup_sha256="0" * 64,
                    target_mysql_version="8.0.46",
                ):
                    self.fail("wrong backup digest must fail before yielding")

            with open_sanitized_backup(
                backup,
                expected_backup_sha256=digest,
                target_mysql_version="8.0.46",
            ) as opened:
                original_fd = opened.stream.fileno()
                replacement = root / "replacement.sql"
                replacement.write_bytes(SAFE_BACKUP.replace(b"(1)", b"(2)"))
                os.replace(replacement, backup)
                self.assertEqual(opened.stream.fileno(), original_fd)
                opened.stream.seek(0)
                self.assertEqual(opened.stream.read(), SAFE_BACKUP)
                with self.assertRaisesRegex(
                    legacy_backup_sanitizer.LegacyBackupSanitizationError,
                    "changed",
                ):
                    opened.rewind_for_import()

    def test_opened_backup_detects_in_place_mutation(self) -> None:
        open_sanitized_backup = _required_callable(
            legacy_migration,
            "open_sanitized_backup",
        )
        digest = hashlib.sha256(SAFE_BACKUP).hexdigest()
        with tempfile.TemporaryDirectory(prefix="legacy_backup_mutation_") as temp_dir:
            backup = Path(temp_dir) / "archive.sql"
            backup.write_bytes(SAFE_BACKUP)
            with open_sanitized_backup(
                backup,
                expected_backup_sha256=digest,
                target_mysql_version="8.0.46",
            ) as opened:
                with backup.open("r+b") as mutation:
                    mutation.seek(SAFE_BACKUP.index(b"(1)") + 1)
                    mutation.write(b"2")
                    mutation.flush()
                    os.fsync(mutation.fileno())
                with self.assertRaisesRegex(
                    legacy_backup_sanitizer.LegacyBackupSanitizationError,
                    "changed",
                ):
                    opened.verify_unchanged()

    def test_private_evidence_is_external_canonical_no_clobber_and_mode_0600(self) -> None:
        write_private_evidence = _required_callable(
            legacy_run_evidence,
            "write_private_evidence",
        )
        payload = {
            "scope": "historical_archive_restore_inventory",
            "records": [{"item_code": "PRIVATE-ITEM", "amazon_asin": "B000000001"}],
        }
        with tempfile.TemporaryDirectory(prefix="legacy_evidence_repo_") as repo_temp, tempfile.TemporaryDirectory(
            prefix="legacy_evidence_external_"
        ) as external_temp:
            repo = Path(repo_temp) / "repo"
            _init_repo(repo)
            external_parent = Path(external_temp)
            external_parent.chmod(0o700)
            output = external_parent / "evidence.json"
            observations = legacy_run_evidence.CommandObservations()
            safe_output = legacy_run_evidence.validate_evidence_output_path(
                repo,
                output,
                observer=observations,
            )
            observed_before_write = observations.snapshot()

            result = write_private_evidence(
                repo,
                output,
                payload,
                observer=observations,
                prevalidated_output_path=safe_output,
            )
            expected_bytes = canonical_json_bytes(payload)
            self.assertEqual(output.read_bytes(), expected_bytes)
            self.assertEqual(
                result["evidence_sha256"],
                hashlib.sha256(expected_bytes).hexdigest(),
            )
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertNotIn("evidence_sha256", payload)
            self.assertEqual(observations.snapshot(), observed_before_write)
            with self.assertRaisesRegex(
                legacy_run_evidence.LegacyRunEvidenceError,
                "exists|clobber",
            ):
                write_private_evidence(
                    repo,
                    output,
                    payload,
                    prevalidated_output_path=safe_output,
                )

    def test_private_evidence_rereads_same_descriptor_and_rejects_write_corruption(
        self,
    ) -> None:
        payload = {
            "scope": "historical_archive_restore_inventory",
            "records": [{"item_code": "PRIVATE-ITEM", "amazon_asin": "B000000001"}],
        }
        actual_write = os.write

        def corrupting_write(descriptor: int, data: bytes) -> int:
            corrupted = b"X" + data[1:] if data else data
            return actual_write(descriptor, corrupted)

        with tempfile.TemporaryDirectory(prefix="legacy_evidence_corrupt_repo_") as repo_temp, tempfile.TemporaryDirectory(
            prefix="legacy_evidence_corrupt_external_"
        ) as external_temp:
            repo = Path(repo_temp) / "repo"
            _init_repo(repo)
            external_parent = Path(external_temp)
            external_parent.chmod(0o700)
            output = external_parent / "evidence.json"
            safe_output = legacy_run_evidence.validate_evidence_output_path(repo, output)
            with mock.patch.object(
                legacy_run_evidence.os,
                "write",
                side_effect=corrupting_write,
            ):
                with self.assertRaisesRegex(
                    legacy_run_evidence.LegacyRunEvidenceError,
                    "verify|match|corrupt",
                ):
                    legacy_run_evidence.write_private_evidence(
                        repo,
                        output,
                        payload,
                        prevalidated_output_path=safe_output,
                    )
            self.assertFalse(output.exists())
            self.assertEqual(list(external_parent.iterdir()), [])
            retry_output = legacy_run_evidence.validate_evidence_output_path(repo, output)
            legacy_run_evidence.write_private_evidence(
                repo,
                output,
                payload,
                prevalidated_output_path=retry_output,
            )
        self._assert_private_evidence_failures_remove_owned_artifacts_and_allow_retry()
        self._assert_private_evidence_publish_collisions_preserve_foreign_final()

    def _assert_private_evidence_failures_remove_owned_artifacts_and_allow_retry(self) -> None:
        payload = {
            "scope": "historical_archive_restore_inventory",
            "records": [{"item_code": "PRIVATE-ITEM", "amazon_asin": "B000000001"}],
        }
        actual_fsync = os.fsync
        actual_read = os.read
        actual_unlink = os.unlink

        for failure_mode in (
            "file_fsync",
            "reread_mismatch",
            "parent_fsync",
            "unlink",
        ):
            with self.subTest(failure_mode=failure_mode), tempfile.TemporaryDirectory(
                prefix=f"legacy_evidence_{failure_mode}_repo_"
            ) as repo_temp, tempfile.TemporaryDirectory(
                prefix=f"legacy_evidence_{failure_mode}_external_"
            ) as external_temp:
                repo = Path(repo_temp) / "repo"
                _init_repo(repo)
                external_parent = Path(external_temp)
                external_parent.chmod(0o700)
                output = external_parent / "evidence.json"
                safe_output = legacy_run_evidence.validate_evidence_output_path(
                    repo,
                    output,
                )
                failed = False

                def failing_fsync(descriptor: int) -> None:
                    nonlocal failed
                    descriptor_mode = os.fstat(descriptor).st_mode
                    should_fail = (
                        failure_mode == "file_fsync" and stat.S_ISREG(descriptor_mode)
                    ) or (
                        failure_mode == "parent_fsync" and stat.S_ISDIR(descriptor_mode)
                    )
                    if should_fail and not failed:
                        failed = True
                        raise OSError(f"forced {failure_mode}")
                    actual_fsync(descriptor)

                def mismatching_read(descriptor: int, size: int) -> bytes:
                    nonlocal failed
                    data = actual_read(descriptor, size)
                    if failure_mode == "reread_mismatch" and data and not failed:
                        failed = True
                        return b"X" + data[1:]
                    return data

                def failing_unlink(path, *unlink_args, **unlink_kwargs):
                    nonlocal failed
                    if failure_mode == "unlink" and not failed:
                        failed = True
                        raise OSError("forced unlink")
                    return actual_unlink(path, *unlink_args, **unlink_kwargs)

                with mock.patch.object(
                    legacy_run_evidence.os,
                    "fsync",
                    side_effect=failing_fsync,
                ), mock.patch.object(
                    legacy_run_evidence.os,
                    "read",
                    side_effect=mismatching_read,
                ), mock.patch.object(
                    legacy_run_evidence.os,
                    "unlink",
                    side_effect=failing_unlink,
                ):
                    with self.assertRaises(legacy_run_evidence.LegacyRunEvidenceError):
                        legacy_run_evidence.write_private_evidence(
                            repo,
                            output,
                            payload,
                            prevalidated_output_path=safe_output,
                        )
                self.assertTrue(failed)
                self.assertFalse(output.exists())
                self.assertEqual(list(external_parent.iterdir()), [])
                retry_output = legacy_run_evidence.validate_evidence_output_path(
                    repo,
                    output,
                )
                legacy_run_evidence.write_private_evidence(
                    repo,
                    output,
                    payload,
                    prevalidated_output_path=retry_output,
                )

    def _assert_private_evidence_publish_collisions_preserve_foreign_final(self) -> None:
        payload = {"scope": "historical_archive_restore_inventory", "records": []}
        raced_bytes = b"foreign-raced-evidence\n"
        with tempfile.TemporaryDirectory(prefix="legacy_evidence_collision_repo_") as repo_temp, tempfile.TemporaryDirectory(
            prefix="legacy_evidence_collision_external_"
        ) as external_temp:
            repo = Path(repo_temp) / "repo"
            _init_repo(repo)
            external_parent = Path(external_temp)
            external_parent.chmod(0o700)
            output = external_parent / "evidence.json"
            safe_output = legacy_run_evidence.validate_evidence_output_path(repo, output)

            def racing_link(*args, **kwargs):
                output.write_bytes(raced_bytes)
                raise FileExistsError("forced publish collision")

            with mock.patch.object(
                legacy_run_evidence.os,
                "link",
                side_effect=racing_link,
            ):
                with self.assertRaisesRegex(
                    legacy_run_evidence.LegacyRunEvidenceError,
                    "exists|clobber|publish",
                ):
                    legacy_run_evidence.write_private_evidence(
                        repo,
                        output,
                        payload,
                        prevalidated_output_path=safe_output,
                    )
            self.assertEqual(output.read_bytes(), raced_bytes)
            self.assertEqual(list(external_parent.iterdir()), [output])
            output.unlink()
            retry_output = legacy_run_evidence.validate_evidence_output_path(repo, output)
            legacy_run_evidence.write_private_evidence(
                repo,
                output,
                payload,
                prevalidated_output_path=retry_output,
            )

        with tempfile.TemporaryDirectory(prefix="legacy_evidence_preexisting_repo_") as repo_temp, tempfile.TemporaryDirectory(
            prefix="legacy_evidence_preexisting_external_"
        ) as external_temp:
            repo = Path(repo_temp) / "repo"
            _init_repo(repo)
            external_parent = Path(external_temp)
            external_parent.chmod(0o700)
            output = external_parent / "evidence.json"
            safe_output = legacy_run_evidence.validate_evidence_output_path(repo, output)
            output.write_bytes(raced_bytes)
            with self.assertRaisesRegex(
                legacy_run_evidence.LegacyRunEvidenceError,
                "exists|clobber",
            ):
                legacy_run_evidence.write_private_evidence(
                    repo,
                    output,
                    payload,
                    prevalidated_output_path=safe_output,
                )
            self.assertEqual(output.read_bytes(), raced_bytes)
            self.assertEqual(list(external_parent.iterdir()), [output])

    def test_private_evidence_rejects_any_worktree_symlink_or_nonprivate_parent(self) -> None:
        validate_evidence_output_path = _required_callable(
            legacy_run_evidence,
            "validate_evidence_output_path",
        )
        with tempfile.TemporaryDirectory(prefix="legacy_evidence_paths_") as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            _init_repo(repo)
            sibling = root / "sibling-worktree"
            _run_git(repo, "worktree", "add", "-b", "sibling", str(sibling))

            for worktree in (repo, sibling):
                parent = worktree / "private"
                parent.mkdir(mode=0o700)
                with self.subTest(worktree=worktree):
                    with self.assertRaisesRegex(
                        legacy_run_evidence.LegacyRunEvidenceError,
                        "worktree",
                    ):
                        validate_evidence_output_path(repo, parent / "evidence.json")

            external = root / "external"
            external.mkdir(mode=0o700)
            validate_evidence_output_path(repo, external / "evidence.json")
            external.chmod(0o755)
            with self.assertRaisesRegex(
                legacy_run_evidence.LegacyRunEvidenceError,
                "0700",
            ):
                validate_evidence_output_path(repo, external / "evidence.json")

            real_parent = root / "real-parent"
            real_parent.mkdir(mode=0o700)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(
                legacy_run_evidence.LegacyRunEvidenceError,
                "symlink|symbolic",
            ):
                validate_evidence_output_path(repo, linked_parent / "evidence.json")

    def test_backup_mode_runs_pure_preflight_then_fails_closed_at_database_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="legacy_backup_preflight_") as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            candidate_sha = _init_repo(repo)
            backup = root / "archive.sql"
            backup.write_bytes(SAFE_BACKUP)
            evidence_parent = root / "evidence"
            evidence_parent.mkdir(mode=0o700)
            mysql_binary = root / "mysql"
            mysqldump_binary = root / "mysqldump"
            for executable in (mysql_binary, mysqldump_binary):
                executable.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
                executable.chmod(0o700)
            args = legacy_migration.parse_args(
                self._backup_argv(
                    backup=backup,
                    evidence=evidence_parent / "evidence.json",
                    candidate_sha=candidate_sha,
                    mysql_binary=mysql_binary,
                    mysqldump_binary=mysqldump_binary,
                )
            )

            with self.assertRaises(legacy_migration.LegacyInventoryRunFailure) as caught:
                legacy_migration.run_backup_inventory(
                    args,
                    repo_root=repo,
                    source_files=("source.py",),
                )
            self.assertEqual(
                caught.exception.summary,
                {
                    "status": "failed",
                    "scope": "historical_archive_restore_inventory",
                    "error_code": "source_restore_failed",
                    "phase": "server_preflight",
                    "cleanup_success": True,
                    "message": "protected backup restore or canonical dump failed",
                },
            )
            self.assertFalse((evidence_parent / "evidence.json").exists())

    def test_compact_failure_summary_never_echoes_private_detail(self) -> None:
        build_failure = _required_callable(
            legacy_migration,
            "build_backup_failure_summary",
        )
        private_detail = (
            "mysql: Access denied password=secret ASIN B000000001 item_code PRIVATE-ITEM"
        )
        summary = build_failure(
            error_code="unsafe_backup_sql",
            phase="backup_preflight",
            cleanup_success=True,
            unsafe_detail=private_detail,
        )
        rendered = canonical_json_bytes(summary).decode("utf-8")
        self.assertEqual(
            set(summary),
            {
                "status",
                "scope",
                "error_code",
                "phase",
                "cleanup_success",
                "message",
            },
        )
        for private_value in ("secret", "B000000001", "PRIVATE-ITEM", "Access denied"):
            self.assertNotIn(private_value, rendered)
        self.assertEqual(summary["message"], "backup SQL failed the offline safety policy")

    def test_compatibility_profile_accepts_native_or_all_absent_workflow_columns(self) -> None:
        required = legacy_inventory_mysql.INVENTORY_TABLE_COLUMNS
        native_columns = {table: set(columns) for table, columns in required.items()}
        native = legacy_inventory_mysql.build_legacy_compatibility_profile(native_columns)
        self.assertEqual(native["products_workflow_columns"]["mode"], "native")
        self.assertEqual(native["task_tables"]["mode"], "absent")

        historical_columns = {
            table: set(columns) for table, columns in required.items()
        }
        workflow_columns = {"workflow_node", "workflow_status", "workflow_error"}
        historical_columns["products"] -= workflow_columns
        historical = legacy_inventory_mysql.build_legacy_compatibility_profile(
            historical_columns
        )
        self.assertEqual(
            historical["products_workflow_columns"],
            {
                "mode": "absent_as_null",
                "present": [],
                "missing": sorted(workflow_columns),
            },
        )
        self.assertEqual(len(historical["profile_sha256"]), 64)
        self.assertNotEqual(native["profile_sha256"], historical["profile_sha256"])

    def test_compatibility_profile_rejects_partial_workflow_or_required_column_loss(
        self,
    ) -> None:
        required = legacy_inventory_mysql.INVENTORY_TABLE_COLUMNS
        partial = {table: set(columns) for table, columns in required.items()}
        partial["products"].remove("workflow_error")
        with self.assertRaisesRegex(
            legacy_inventory_mysql.LegacyInventoryVerificationError,
            "unsupported_legacy_shape",
        ):
            legacy_inventory_mysql.build_legacy_compatibility_profile(partial)

        missing_identity = {table: set(columns) for table, columns in required.items()}
        missing_identity["amazon_stylesnap_candidates"].remove("item_code")
        with self.assertRaisesRegex(
            legacy_inventory_mysql.LegacyInventoryVerificationError,
            "unsupported_legacy_shape",
        ):
            legacy_inventory_mysql.build_legacy_compatibility_profile(missing_identity)

    def test_task_absence_sentinel_differs_from_existing_empty_tables(self) -> None:
        absent = legacy_inventory_mysql.build_task_table_absence_snapshot()
        present = legacy_inventory_mysql.build_task_table_state_snapshot(
            {"task_runs": [], "task_steps": []}
        )
        self.assertTrue(all(item["presence"] == "absent" for item in absent.values()))
        self.assertTrue(all(item["presence"] == "present" for item in present.values()))
        verified = legacy_run_evidence.verify_zero_side_effect_deltas(
            task_state_before=absent,
            task_state_after=absent,
            step10_before=[],
            step10_after=[],
        )
        self.assertEqual(verified["task_tables"]["changed_tables"], [])
        with self.assertRaisesRegex(
            legacy_run_evidence.LegacyRunEvidenceError,
            "state mutation",
        ):
            legacy_run_evidence.verify_zero_side_effect_deltas(
                task_state_before=absent,
                task_state_after=present,
                step10_before=[],
                step10_after=[],
            )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        LegacyBackupInventoryPureTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"OK: {result.testsRun} legacy backup inventory pure test(s)")
    raise SystemExit(0 if result.wasSuccessful() else 1)
