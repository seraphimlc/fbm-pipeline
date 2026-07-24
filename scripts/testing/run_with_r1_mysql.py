#!/usr/bin/env python3
"""Run one command tree inside a fail-closed isolated R1 MySQL environment."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import sys

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_ENV = "R1_MYSQL_WRAPPER_BOOTSTRAPPED"
PROJECT_RULES_MARKER_ENV = "R1_PROJECT_RULES_DB_MARKER"
PROJECT_RULES_MARKER_NONCE_ENV = "R1_PROJECT_RULES_DB_MARKER_NONCE"
PROJECT_RULES_COMMAND_ENV = "R1_PROJECT_RULES_COMMAND_ID"
PROJECT_RULES_COMMAND_ID = "make:test-project-rules:v1"
WRAPPER_ACTIVE_ENV = "R1_MYSQL_WRAPPER_ACTIVE"
WRAPPER_DATABASE_ENV = "R1_MYSQL_WRAPPER_DATABASE"
TRUSTED_MAKE_CANDIDATES = (Path("/usr/bin/make"), Path("/bin/make"))


def _ensure_runtime_dependencies() -> None:
    if importlib.util.find_spec("sqlalchemy") is not None:
        return
    backend_python = ROOT / "backend" / ".venv" / "bin" / "python"
    if os.environ.get(BOOTSTRAP_ENV) == "1" or not backend_python.is_file():
        print(
            "BLOCKED: SQLAlchemy is unavailable and backend/.venv/bin/python cannot bootstrap the wrapper",
            file=sys.stderr,
        )
        raise SystemExit(2)
    bootstrap_env = os.environ.copy()
    bootstrap_env[BOOTSTRAP_ENV] = "1"
    os.execve(
        str(backend_python),
        [str(backend_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        bootstrap_env,
    )


_ensure_runtime_dependencies()

from r1_mysql import R1MysqlNotConfigured, _validated_admin_url, isolated_r1_mysql  # noqa: E402


def _command_from_argv(argv: list[str]) -> list[str]:
    if not argv or argv[0] != "--":
        raise ValueError("usage: run_with_r1_mysql.py -- <command...>")
    command = argv[1:]
    if not command:
        raise ValueError("run_with_r1_mysql.py requires a command after --")
    return command


def _project_rules_command_id(command: list[str]) -> str | None:
    if command == ["make", "test-project-rules"]:
        return PROJECT_RULES_COMMAND_ID
    return None


def _requires_project_rules_marker(command: list[str]) -> bool:
    return _project_rules_command_id(command) is not None


def _trusted_project_rules_command() -> list[str]:
    makefile = (ROOT / "Makefile").resolve(strict=True)
    for candidate in TRUSTED_MAKE_CANDIDATES:
        try:
            executable = candidate.resolve(strict=True)
        except OSError:
            continue
        if executable.is_file() and os.access(executable, os.X_OK):
            return [
                str(executable),
                "-C",
                str(ROOT),
                "-f",
                str(makefile),
                "test-project-rules",
            ]
    raise RuntimeError("trusted system make executable is unavailable; caller PATH fallback is forbidden")


async def _stop_owned_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except asyncio.TimeoutError:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


def _verified_project_rules_marker(
    marker_path: Path,
    *,
    database_name: str,
    nonce: str,
    command_id: str,
) -> bool:
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False
    return (
        marker.get("wrapper_active") is True
        and marker.get("database_name") == database_name
        and marker.get("database_check") is True
        and marker.get("nonce") == nonce
        and marker.get("command_id") == command_id
    )


async def _run(command: list[str]) -> int:
    async with isolated_r1_mysql(ROOT) as environment:
        project_rules_command_id = _project_rules_command_id(command)
        trusted_project_rules = project_rules_command_id is not None
        marker_nonce = secrets.token_hex(32) if trusted_project_rules else None
        marker_path = (
            environment.data_dir / f"project-rules-db-marker-{marker_nonce}.json"
            if marker_nonce is not None
            else None
        )
        child_command = _trusted_project_rules_command() if trusted_project_rules else command
        child_env = os.environ.copy()
        for marker_env_name in (
            PROJECT_RULES_MARKER_ENV,
            PROJECT_RULES_MARKER_NONCE_ENV,
            PROJECT_RULES_COMMAND_ENV,
        ):
            child_env.pop(marker_env_name, None)
        backend_venv = ROOT / "backend" / ".venv"
        backend_venv_bin = backend_venv / "bin"
        if not (backend_venv_bin / "python").is_file():
            raise RuntimeError("backend/.venv/bin/python is required for the isolated command tree")
        child_env.update({
            WRAPPER_ACTIVE_ENV: "1",
            WRAPPER_DATABASE_ENV: environment.database_name,
            "PATH": f"{backend_venv_bin}{os.pathsep}{child_env.get('PATH', '')}",
            "PYTHONUNBUFFERED": "1",
            "VIRTUAL_ENV": str(backend_venv),
        })
        if trusted_project_rules:
            assert marker_path is not None and marker_nonce is not None and project_rules_command_id is not None
            child_env.update({
                PROJECT_RULES_MARKER_ENV: str(marker_path),
                PROJECT_RULES_MARKER_NONCE_ENV: marker_nonce,
                PROJECT_RULES_COMMAND_ENV: project_rules_command_id,
            })
        print(f"R1_MYSQL_WRAPPER_DATABASE={environment.database_name}", flush=True)
        print(f"R1_MYSQL_WRAPPER_DATA_DIR={environment.data_dir}", flush=True)

        try:
            process = await asyncio.create_subprocess_exec(
                *child_command,
                cwd=ROOT,
                env=child_env,
                start_new_session=True,
            )
        except FileNotFoundError:
            print(f"BLOCKED: command executable not found: {child_command[0]}", file=sys.stderr)
            return 127
        loop = asyncio.get_running_loop()
        forwarded_signal: int | None = None

        def kill_if_still_running() -> None:
            if process.returncode is not None:
                return
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        def forward_signal(signum: int) -> None:
            nonlocal forwarded_signal
            if forwarded_signal is None:
                forwarded_signal = signum
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signum)
                except ProcessLookupError:
                    return
                loop.call_later(10, kill_if_still_running)

        installed_signals: list[int] = []
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                loop.add_signal_handler(signum, forward_signal, signum)
                installed_signals.append(signum)
            except (NotImplementedError, RuntimeError):
                continue

        try:
            return_code = await process.wait()
        except BaseException:
            await _stop_owned_process_group(process)
            raise
        finally:
            for signum in installed_signals:
                loop.remove_signal_handler(signum)

        if forwarded_signal is not None:
            return 128 + forwarded_signal
        if return_code < 0:
            return 128 + (-return_code)
        if return_code != 0:
            return return_code
        if trusted_project_rules:
            assert marker_path is not None and marker_nonce is not None and project_rules_command_id is not None
            if not _verified_project_rules_marker(
                marker_path,
                database_name=environment.database_name,
                nonce=marker_nonce,
                command_id=project_rules_command_id,
            ):
                print(
                    "BLOCKED: project rules exited 0 without the isolated MySQL DB marker",
                    file=sys.stderr,
                )
                return 3
            print("R1_MYSQL_PROJECT_RULES_DB_MARKER_VERIFIED", flush=True)
        return 0


def main() -> int:
    try:
        command = _command_from_argv(sys.argv[1:])
        _validated_admin_url()
        return asyncio.run(_run(command))
    except (R1MysqlNotConfigured, RuntimeError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
