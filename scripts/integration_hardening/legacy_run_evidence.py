"""Trusted source identity and observed side-effect evidence for Legacy R1."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .common import canonical_sha256_hex


class LegacyRunEvidenceError(RuntimeError):
    """Raised when runtime evidence cannot prove the allowed execution boundary."""


SOURCE_FILE_RELATIVE_PATHS = (
    "scripts/integration_hardening/__init__.py",
    "scripts/integration_hardening/common.py",
    "scripts/integration_hardening/database_source_manifest.py",
    "scripts/integration_hardening/legacy_inventory.py",
    "scripts/integration_hardening/legacy_inventory_fixture.py",
    "scripts/integration_hardening/legacy_inventory_mysql.py",
    "scripts/integration_hardening/legacy_migration.py",
    "scripts/integration_hardening/legacy_run_evidence.py",
)
ALLOWED_SUBPROCESSES = frozenset({"git", "mysql", "mysqldump"})
ALLOWED_DATABASE_ENDPOINT = "127.0.0.1:3306"


class CommandObservations:
    """Observe and fail closed before every subprocess launched by the slice."""

    def __init__(self) -> None:
        self._processes: list[str] = []
        self._database_endpoints: list[str] = []

    def observe(self, argv: Any) -> None:
        if type(argv) is not list or not argv or any(type(token) is not str for token in argv):
            raise LegacyRunEvidenceError("subprocess argv must be a non-empty string array")
        process = Path(argv[0]).name
        if process not in ALLOWED_SUBPROCESSES:
            raise LegacyRunEvidenceError(f"forbidden subprocess observed: {process}")
        self._processes.append(process)
        host = next((token.split("=", 1)[1] for token in argv if token.startswith("--host=")), "")
        port = next((token.split("=", 1)[1] for token in argv if token.startswith("--port=")), "")
        if host or port:
            endpoint = f"{host}:{port}"
            if endpoint != ALLOWED_DATABASE_ENDPOINT:
                raise LegacyRunEvidenceError(f"forbidden database endpoint observed: {endpoint}")
            self._database_endpoints.append(endpoint)

    def snapshot(self) -> dict[str, Any]:
        process_counts = Counter(self._processes)
        return {
            "subprocess_count": len(self._processes),
            "process_counts": dict(sorted(process_counts.items())),
            "process_names": sorted(process_counts),
            "database_endpoints": sorted(set(self._database_endpoints)),
        }


def _git(
    repo_root: Path,
    arguments: list[str],
    *,
    observer: CommandObservations | None,
) -> str:
    argv = ["git", *arguments]
    if observer is not None:
        observer.observe(argv)
    result = subprocess.run(
        argv,
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise LegacyRunEvidenceError(
            f"git {' '.join(arguments[:2])} failed with exit {result.returncode}: "
            f"{result.stderr.strip()[:300]}"
        )
    return result.stdout


def _safe_source_path(repo_root: Path, relative_path: str) -> Path:
    if type(relative_path) is not str:
        raise LegacyRunEvidenceError("source file path must be a string")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise LegacyRunEvidenceError(f"unsafe source file path: {relative_path!r}")
    path = repo_root.joinpath(*pure.parts)
    if not path.is_file() or path.is_symlink():
        raise LegacyRunEvidenceError(f"source file must be a regular non-symlink file: {relative_path}")
    return path


def build_source_identity(
    repo_root: Path,
    *,
    supplied_candidate_sha: str = "",
    source_files: Iterable[str] = SOURCE_FILE_RELATIVE_PATHS,
    observer: CommandObservations | None = None,
) -> dict[str, Any]:
    """Bind the claim to actual HEAD, porcelain status and exact runtime source bytes."""

    repo_root = Path(repo_root).resolve()
    if not repo_root.is_dir():
        raise LegacyRunEvidenceError("repository root is not a directory")
    head_sha = _git(repo_root, ["rev-parse", "--verify", "HEAD"], observer=observer).strip()
    if len(head_sha) != 40 or any(character not in "0123456789abcdef" for character in head_sha):
        raise LegacyRunEvidenceError("actual HEAD is not a 40-character lowercase Git SHA-1 OID")
    if supplied_candidate_sha:
        if (
            len(supplied_candidate_sha) != 40
            or any(character not in "0123456789abcdef" for character in supplied_candidate_sha)
        ):
            raise LegacyRunEvidenceError(
                "candidate SHA must be a 40-character lowercase Git SHA-1 OID"
            )
        if supplied_candidate_sha != head_sha:
            raise LegacyRunEvidenceError("supplied candidate SHA does not equal actual HEAD")

    status_lines = [
        line
        for line in _git(
            repo_root,
            ["status", "--porcelain=v1", "--untracked-files=all"],
            observer=observer,
        ).splitlines()
        if line
    ]
    status_entries = []
    for line in status_lines:
        if len(line) < 4 or line[2] != " ":
            raise LegacyRunEvidenceError("git status returned an unreadable porcelain entry")
        status_entries.append({"status": line[:2], "path": line[3:]})
    tracked_changes = sum(entry["status"] != "??" for entry in status_entries)
    untracked_paths = sum(entry["status"] == "??" for entry in status_entries)

    source_hashes = []
    for relative_path in sorted(set(source_files)):
        path = _safe_source_path(repo_root, relative_path)
        source_hashes.append(
            {
                "path": relative_path,
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if not source_hashes:
        raise LegacyRunEvidenceError("at least one runtime source file must be bound")
    return {
        "head_sha": head_sha,
        "candidate_sha": head_sha,
        "source_state": "clean" if not status_entries else "dirty_review_candidate",
        "status_paths": [entry["path"] for entry in status_entries],
        "status_entries": status_entries,
        "status_summary": {
            "entry_count": len(status_entries),
            "tracked_changes": tracked_changes,
            "untracked_paths": untracked_paths,
        },
        "source_files": source_hashes,
    }


def snapshot_directory(root: Path) -> list[dict[str, Any]]:
    root = Path(root)
    try:
        root_stat = root.lstat()
    except FileNotFoundError as exc:
        raise LegacyRunEvidenceError(f"observed directory does not exist: {root}") from exc
    if stat.S_ISLNK(root_stat.st_mode):
        raise LegacyRunEvidenceError("observed output directory root is a symbolic link")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise LegacyRunEvidenceError(f"observed directory does not exist: {root}")
    snapshot: list[dict[str, Any]] = []

    def visit(directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise LegacyRunEvidenceError(
                f"unable to inspect observed output directory: {directory}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative_path = path.relative_to(root).as_posix()
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise LegacyRunEvidenceError(
                    f"unable to lstat observed output entry: {relative_path}"
                ) from exc
            if stat.S_ISLNK(entry_stat.st_mode):
                raise LegacyRunEvidenceError(
                    f"observed output directory contains a symbolic link: {relative_path}"
                )
            if stat.S_ISDIR(entry_stat.st_mode):
                snapshot.append(
                    {"relative_path": relative_path, "entry_type": "directory"}
                )
                visit(path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise LegacyRunEvidenceError(
                    f"observed output directory contains a non-regular entry: {relative_path}"
                )
            snapshot.append(
                {
                    "relative_path": relative_path,
                    "entry_type": "file",
                    "size_bytes": entry_stat.st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )

    visit(root)
    return snapshot


def verify_zero_side_effect_deltas(
    *,
    task_state_before: dict[str, Any],
    task_state_after: dict[str, Any],
    step10_before: list[dict[str, Any]],
    step10_after: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_tables = {"task_runs", "task_steps"}
    if set(task_state_before) != expected_tables or set(task_state_after) != expected_tables:
        raise LegacyRunEvidenceError("task side-effect observation requires task_runs and task_steps")
    deltas = {
        table: task_state_after[table]["row_count"] - task_state_before[table]["row_count"]
        for table in sorted(expected_tables)
    }
    changed_tables = sorted(
        table
        for table in expected_tables
        if task_state_before[table] != task_state_after[table]
    )
    state_sha256_before = canonical_sha256_hex(task_state_before)
    state_sha256_after = canonical_sha256_hex(task_state_after)
    if changed_tables:
        raise LegacyRunEvidenceError(
            "forbidden TaskRun/TaskStep state mutation observed: "
            f"changed_tables={changed_tables}, row_deltas={deltas}"
        )
    before_by_path = {item["relative_path"]: item for item in step10_before}
    after_by_path = {item["relative_path"]: item for item in step10_after}
    added = sorted(set(after_by_path) - set(before_by_path))
    removed = sorted(set(before_by_path) - set(after_by_path))
    changed = sorted(
        path
        for path in set(before_by_path) & set(after_by_path)
        if before_by_path[path] != after_by_path[path]
    )
    if added or removed or changed:
        raise LegacyRunEvidenceError(
            f"forbidden Step 10 output mutation observed: added={added}, removed={removed}, changed={changed}"
        )
    return {
        "task_tables": {
            "before": dict(sorted(task_state_before.items())),
            "after": dict(sorted(task_state_after.items())),
            "deltas": deltas,
            "changed_tables": changed_tables,
            "state_sha256_before": state_sha256_before,
            "state_sha256_after": state_sha256_after,
        },
        "step10_outputs": {
            "before_entry_count": len(step10_before),
            "after_entry_count": len(step10_after),
            "before_file_count": sum(
                item.get("entry_type", "file") == "file" for item in step10_before
            ),
            "after_file_count": sum(
                item.get("entry_type", "file") == "file" for item in step10_after
            ),
            "before_directory_count": sum(
                item.get("entry_type") == "directory" for item in step10_before
            ),
            "after_directory_count": sum(
                item.get("entry_type") == "directory" for item in step10_after
            ),
            "added_paths": added,
            "removed_paths": removed,
            "changed_paths": changed,
        },
    }
