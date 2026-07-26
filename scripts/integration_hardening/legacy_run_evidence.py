"""Trusted source identity and observed side-effect evidence for Legacy R1."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import uuid
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .common import canonical_json_bytes, canonical_sha256_hex


class LegacyRunEvidenceError(RuntimeError):
    """Raised when runtime evidence cannot prove the allowed execution boundary."""


SOURCE_FILE_RELATIVE_PATHS = (
    "scripts/integration_hardening/__init__.py",
    "scripts/integration_hardening/common.py",
    "scripts/integration_hardening/database_source_manifest.py",
    "scripts/integration_hardening/legacy_backup_sanitizer.py",
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
    require_clean: bool = False,
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
    if require_clean and status_entries:
        raise LegacyRunEvidenceError("candidate source must be a clean Git worktree")

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


def _git_worktree_roots(
    repo_root: Path,
    *,
    observer: CommandObservations | None = None,
) -> tuple[Path, ...]:
    output = _git(
        repo_root,
        ["worktree", "list", "--porcelain"],
        observer=observer,
    )
    roots = []
    for line in output.splitlines():
        if not line.startswith("worktree "):
            continue
        raw_path = line[len("worktree ") :]
        if not raw_path:
            raise LegacyRunEvidenceError("git returned an empty worktree path")
        roots.append(Path(raw_path).resolve(strict=True))
    if not roots:
        raise LegacyRunEvidenceError("git returned no worktree roots")
    return tuple(roots)


def validate_evidence_output_path(
    repo_root: Path,
    output_path: Path,
    *,
    observer: CommandObservations | None = None,
) -> Path:
    """Validate an absent private evidence path outside every Git worktree."""

    output_path = Path(output_path)
    if not output_path.is_absolute() or output_path.name in {"", ".", ".."}:
        raise LegacyRunEvidenceError("evidence output must be an absolute file path")
    parent = output_path.parent
    try:
        parent_stat = parent.lstat()
    except OSError as exc:
        raise LegacyRunEvidenceError("evidence parent must already exist") from exc
    if stat.S_ISLNK(parent_stat.st_mode):
        raise LegacyRunEvidenceError("evidence parent must not be a symbolic link")
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise LegacyRunEvidenceError("evidence parent must be a directory")
    if parent_stat.st_uid != os.getuid():
        raise LegacyRunEvidenceError("evidence parent must be owned by the current user")
    if stat.S_IMODE(parent_stat.st_mode) != 0o700:
        raise LegacyRunEvidenceError("evidence parent permissions must be exactly 0700")
    try:
        output_path.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise LegacyRunEvidenceError("unable to inspect evidence output path") from exc
    else:
        raise LegacyRunEvidenceError("evidence output already exists; clobber is forbidden")

    resolved_parent = parent.resolve(strict=True)
    resolved_output = resolved_parent / output_path.name
    for worktree_root in _git_worktree_roots(repo_root, observer=observer):
        try:
            resolved_output.relative_to(worktree_root)
        except ValueError:
            continue
        raise LegacyRunEvidenceError("evidence output must be outside every Git worktree")
    return resolved_output


def write_private_evidence(
    repo_root: Path,
    output_path: Path,
    payload: dict[str, Any],
    *,
    observer: CommandObservations | None = None,
    prevalidated_output_path: Path | None = None,
) -> dict[str, Any]:
    """Validate canonical bytes privately, then atomically publish without clobber."""

    if type(payload) is not dict:
        raise LegacyRunEvidenceError("evidence payload must be an object")
    if "evidence_sha256" in payload:
        raise LegacyRunEvidenceError("evidence payload must not contain its own digest")
    if prevalidated_output_path is None:
        safe_output = validate_evidence_output_path(
            repo_root,
            output_path,
            observer=observer,
        )
    else:
        safe_output = Path(prevalidated_output_path)
        if (
            not safe_output.is_absolute()
            or safe_output.name in {"", ".", ".."}
            or safe_output.name != Path(output_path).name
        ):
            raise LegacyRunEvidenceError("prevalidated evidence output path is invalid")
    payload_bytes = canonical_json_bytes(payload)
    parent_flags = os.O_RDONLY
    parent_flags |= getattr(os, "O_CLOEXEC", 0)
    parent_flags |= getattr(os, "O_DIRECTORY", 0)
    parent_flags |= getattr(os, "O_NOFOLLOW", 0)
    temporary_flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    temporary_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_descriptor = -1
    temporary_descriptor = -1
    temporary_name = f".{safe_output.name}.{uuid.uuid4().hex}.tmp"
    owned_inode: tuple[int, int] | None = None
    published = False
    completed = False

    def entry_stat(name: str) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def unlink_owned(name: str) -> bool:
        if owned_inode is None or parent_descriptor < 0:
            return True
        for _attempt in range(3):
            current = entry_stat(name)
            if current is None:
                return True
            if (current.st_dev, current.st_ino) != owned_inode:
                return False
            try:
                os.unlink(name, dir_fd=parent_descriptor)
                return True
            except FileNotFoundError:
                return True
            except OSError:
                continue
        return False

    def unlink_owned_once(name: str) -> None:
        current = entry_stat(name)
        if (
            current is None
            or owned_inode is None
            or (current.st_dev, current.st_ino) != owned_inode
        ):
            raise LegacyRunEvidenceError(
                "private evidence temporary ownership changed before unlink"
            )
        try:
            os.unlink(name, dir_fd=parent_descriptor)
        except OSError as exc:
            raise LegacyRunEvidenceError(
                "unable to remove private evidence temporary file"
            ) from exc

    try:
        parent_descriptor = os.open(safe_output.parent, parent_flags)
        parent_stat = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.getuid()
            or stat.S_IMODE(parent_stat.st_mode) != 0o700
        ):
            raise LegacyRunEvidenceError(
                "prevalidated evidence parent is no longer private"
            )
        if entry_stat(safe_output.name) is not None:
            raise LegacyRunEvidenceError(
                "evidence output already exists; clobber is forbidden"
            )

        temporary_descriptor = os.open(
            temporary_name,
            temporary_flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        os.fchmod(temporary_descriptor, 0o600)
        created_stat = os.fstat(temporary_descriptor)
        owned_inode = (created_stat.st_dev, created_stat.st_ino)
        offset = 0
        while offset < len(payload_bytes):
            written = os.write(temporary_descriptor, payload_bytes[offset:])
            if written <= 0:
                raise LegacyRunEvidenceError("unable to write complete evidence output")
            offset += written
        os.fsync(temporary_descriptor)
        actual_stat = os.fstat(temporary_descriptor)
        os.lseek(temporary_descriptor, 0, os.SEEK_SET)
        actual_chunks = []
        while True:
            chunk = os.read(temporary_descriptor, 64 * 1024)
            if chunk == b"":
                break
            actual_chunks.append(chunk)
        actual_bytes = b"".join(actual_chunks)
        if (
            not stat.S_ISREG(actual_stat.st_mode)
            or (actual_stat.st_dev, actual_stat.st_ino) != owned_inode
            or actual_stat.st_uid != os.getuid()
            or stat.S_IMODE(actual_stat.st_mode) != 0o600
            or actual_stat.st_size != len(payload_bytes)
            or actual_bytes != payload_bytes
        ):
            raise LegacyRunEvidenceError(
                "evidence output verification did not match canonical payload"
            )

        try:
            os.link(
                temporary_name,
                safe_output.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise LegacyRunEvidenceError(
                "evidence output already exists; clobber is forbidden"
            ) from exc
        published = True
        final_stat = entry_stat(safe_output.name)
        if final_stat is None or (final_stat.st_dev, final_stat.st_ino) != owned_inode:
            raise LegacyRunEvidenceError("evidence publish verification failed")
        os.fsync(parent_descriptor)
        unlink_owned_once(temporary_name)
        os.fsync(parent_descriptor)
        completed = True
        return {
            "evidence_sha256": hashlib.sha256(actual_bytes).hexdigest(),
            "size_bytes": actual_stat.st_size,
        }
    except LegacyRunEvidenceError:
        raise
    except OSError as exc:
        raise LegacyRunEvidenceError(
            "unable to write, verify, or publish private evidence output"
        ) from exc
    finally:
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        if parent_descriptor >= 0:
            if not completed:
                if published:
                    unlink_owned(safe_output.name)
                unlink_owned(temporary_name)
                try:
                    os.fsync(parent_descriptor)
                except OSError:
                    pass
            os.close(parent_descriptor)


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
