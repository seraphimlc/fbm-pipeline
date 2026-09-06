#!/usr/bin/env python3
"""Focused fail-closed checks for run_with_r1_sqlite.py."""

from __future__ import annotations

import asyncio
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "testing" / "run_with_r1_sqlite.py"
DATABASE_PATTERN = re.compile(r"R1_SQLITE_WRAPPER_DATABASE=(.+)")
DATA_DIR_PATTERN = re.compile(r"R1_SQLITE_WRAPPER_DATA_DIR=(.+)")
MARKER_ENV_NAMES = (
    "R1_PROJECT_RULES_DB_MARKER",
    "R1_PROJECT_RULES_DB_MARKER_NONCE",
    "R1_PROJECT_RULES_COMMAND_ID",
)


def _run_wrapper(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )


def _created_resources(result: subprocess.CompletedProcess[str]) -> tuple[str, Path]:
    output = f"{result.stdout}\n{result.stderr}"
    database_match = DATABASE_PATTERN.search(output)
    data_dir_match = DATA_DIR_PATTERN.search(output)
    if not database_match or not data_dir_match:
        raise AssertionError(output)
    return database_match.group(1), Path(data_dir_match.group(1).strip())


def _assert_resources_cleaned(database_name: str, data_dir: Path) -> None:
    assert not Path(database_name).exists(), database_name
    assert not data_dir.exists(), data_dir


def _fake_make(directory: Path) -> Path:
    executable = directory / "make"
    executable.write_text(
        """#!{python}
import json
import os
from pathlib import Path

mode = os.environ.get('R1_FAKE_MARKER_MODE', 'markerless')
sentinel = os.environ.get('R1_FAKE_MAKE_SENTINEL')
marker_env = {{
    name: os.environ.get(name)
    for name in (
        'R1_PROJECT_RULES_DB_MARKER',
        'R1_PROJECT_RULES_DB_MARKER_NONCE',
        'R1_PROJECT_RULES_COMMAND_ID',
    )
}}
if sentinel:
    Path(sentinel).write_text(json.dumps(marker_env, sort_keys=True), encoding='utf-8')
if mode != 'markerless' and all(marker_env.values()):
    marker = {{
        'wrapper_active': True,
        'database_name': os.environ['R1_SQLITE_WRAPPER_DATABASE'],
        'database_check': True,
        'nonce': os.environ['R1_PROJECT_RULES_DB_MARKER_NONCE'],
        'command_id': os.environ['R1_PROJECT_RULES_COMMAND_ID'],
    }}
    if mode == 'wrong_nonce':
        marker['nonce'] = 'wrong-nonce'
    elif mode == 'wrong_database':
        marker['database_name'] = marker['database_name'] + '_wrong'
    elif mode == 'wrong_command':
        marker['command_id'] = 'wrong-command'
    Path(os.environ['R1_PROJECT_RULES_DB_MARKER']).write_text(
        json.dumps(marker, sort_keys=True),
        encoding='utf-8',
    )
raise SystemExit(0)
""".format(python=sys.executable),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _load_wrapper_module():
    sys.path.insert(0, str(WRAPPER.parent))
    spec = importlib.util.spec_from_file_location("r1_sqlite_wrapper_focused", WRAPPER)
    if spec is None or spec.loader is None:
        raise AssertionError("failed to load run_with_r1_sqlite.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness-only", action="store_true", help="Run isolation checks without the broad project-rules integration")
    args = parser.parse_args()
    base_env = os.environ.copy()
    # Hostile inherited settings must never select the application database.
    base_env.update({
        "DATABASE_BACKEND": "mysql",
        "DATABASE_URL": "mysql+asyncmy://unused@127.0.0.1:1/do_not_connect",
        "SQLITE_DATABASE_PATH": "/do-not-use/business.db",
    })
    missing_env_result = _run_wrapper(["--", sys.executable, "-c", "pass"], base_env)
    assert missing_env_result.returncode == 0, missing_env_result
    _assert_resources_cleaned(*_created_resources(missing_env_result))

    missing_command_result = _run_wrapper([], base_env)
    assert missing_command_result.returncode != 0, missing_command_result
    assert "usage: run_with_r1_sqlite.py -- <command...>" in missing_command_result.stderr, missing_command_result.stderr

    child_failure = _run_wrapper(["--", sys.executable, "-c", "raise SystemExit(7)"], base_env)
    assert child_failure.returncode == 7, (child_failure.returncode, child_failure.stdout, child_failure.stderr)
    failed_database, failed_data_dir = _created_resources(child_failure)
    _assert_resources_cleaned(failed_database, failed_data_dir)

    marker_writer = """
import os
for name in (
    'R1_PROJECT_RULES_DB_MARKER',
    'R1_PROJECT_RULES_DB_MARKER_NONCE',
    'R1_PROJECT_RULES_COMMAND_ID',
):
    assert name not in os.environ, (name, os.environ.get(name))
"""
    unrelated_script_argv = _run_wrapper(
        ["--", sys.executable, "-c", marker_writer, "scripts/test_project_rules.py"],
        base_env,
    )
    assert unrelated_script_argv.returncode == 0, unrelated_script_argv
    assert "R1_SQLITE_PROJECT_RULES_DB_MARKER_VERIFIED" not in unrelated_script_argv.stdout
    unrelated_database, unrelated_data_dir = _created_resources(unrelated_script_argv)
    _assert_resources_cleaned(unrelated_database, unrelated_data_dir)

    wrapper_module = _load_wrapper_module()
    with TemporaryDirectory(prefix="r1-wrapper-marker-validation-") as marker_directory:
        marker_path = Path(marker_directory) / "marker.json"
        assert wrapper_module._verified_project_rules_marker(
            marker_path,
            database_name="fbm_pipeline_r1_validation",
            nonce="a" * 64,
            command_id="make:test-project-rules:v1",
        ) is False
        valid_marker = {
            "wrapper_active": True,
            "database_name": "fbm_pipeline_r1_validation",
            "database_check": True,
            "nonce": "a" * 64,
            "command_id": "make:test-project-rules:v1",
        }
        for invalid_mode in ("wrong_nonce", "wrong_database", "wrong_command"):
            invalid_marker = dict(valid_marker)
            if invalid_mode == "wrong_nonce":
                invalid_marker["nonce"] = "wrong-nonce"
            elif invalid_mode == "wrong_database":
                invalid_marker["database_name"] = "fbm_pipeline_r1_wrong"
            else:
                invalid_marker["command_id"] = "wrong-command"
            marker_path.write_text(json.dumps(invalid_marker, sort_keys=True), encoding="utf-8")
            assert wrapper_module._verified_project_rules_marker(
                marker_path,
                database_name="fbm_pipeline_r1_validation",
                nonce="a" * 64,
                command_id="make:test-project-rules:v1",
            ) is False, invalid_mode

    with TemporaryDirectory(prefix="r1-wrapper-fake-make-") as fake_directory:
        fake_directory_path = Path(fake_directory)
        fake_make = _fake_make(fake_directory_path)

        absolute_sentinel = fake_directory_path / "absolute-sentinel.json"
        absolute_env = base_env.copy()
        absolute_env["R1_FAKE_MARKER_MODE"] = "valid"
        absolute_env["R1_FAKE_MAKE_SENTINEL"] = str(absolute_sentinel)
        absolute_fake = _run_wrapper(["--", str(fake_make), "test-project-rules"], absolute_env)
        assert absolute_fake.returncode == 0, absolute_fake
        assert "R1_SQLITE_PROJECT_RULES_DB_MARKER_VERIFIED" not in absolute_fake.stdout
        absolute_marker_env = json.loads(absolute_sentinel.read_text(encoding="utf-8"))
        assert all(absolute_marker_env.get(name) is None for name in MARKER_ENV_NAMES), absolute_marker_env
        absolute_database, absolute_data_dir = _created_resources(absolute_fake)
        _assert_resources_cleaned(absolute_database, absolute_data_dir)

        path_sentinel = fake_directory_path / "path-sentinel.json"
        path_env = base_env.copy()
        path_env["PATH"] = f"{fake_directory_path}{os.pathsep}{path_env.get('PATH', '')}"
        path_env["R1_FAKE_MARKER_MODE"] = "valid"
        path_env["R1_FAKE_MAKE_SENTINEL"] = str(path_sentinel)
        if not args.harness_only:
            trusted_literal_make = _run_wrapper(["--", "make", "test-project-rules"], path_env)
            assert trusted_literal_make.returncode == 0, trusted_literal_make
            assert "R1_SQLITE_PROJECT_RULES_DB_MARKER_VERIFIED" in trusted_literal_make.stdout
            assert not path_sentinel.exists(), path_sentinel
            trusted_database, trusted_data_dir = _created_resources(trusted_literal_make)
            _assert_resources_cleaned(trusted_database, trusted_data_dir)

    nonexistent = _run_wrapper(["--", str(ROOT / "tmp" / "r1-command-does-not-exist")], base_env)
    assert nonexistent.returncode == 127, (nonexistent.returncode, nonexistent.stdout, nonexistent.stderr)
    assert "command executable not found" in nonexistent.stderr
    missing_database, missing_data_dir = _created_resources(nonexistent)
    _assert_resources_cleaned(missing_database, missing_data_dir)

    child_check = """
import asyncio
import os
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    database_url = os.environ['DATABASE_URL']
    expected = os.environ['R1_SQLITE_WRAPPER_DATABASE']
    assert os.environ['R1_SQLITE_WRAPPER_ACTIVE'] == '1'
    assert Path(sys.executable).resolve() == (Path.cwd() / 'backend/.venv/bin/python').resolve()
    assert make_url(database_url).database == expected
    assert Path(os.environ['DATA_DIR']).is_dir()
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            actual = (await connection.execute(text('PRAGMA database_list'))).one()[2]
        assert actual == expected, (actual, expected)
    finally:
        await engine.dispose()
    print(f'R1_WRAPPER_CHILD_DB_OK={actual}')

asyncio.run(main())
"""
    child_success = _run_wrapper(["--", "python3", "-c", "import sys\n" + child_check], base_env)
    assert child_success.returncode == 0, (child_success.returncode, child_success.stdout, child_success.stderr)
    success_database, success_data_dir = _created_resources(child_success)
    assert f"R1_WRAPPER_CHILD_DB_OK={success_database}" in child_success.stdout, child_success.stdout
    _assert_resources_cleaned(success_database, success_data_dir)

    print("R1 SQLite wrapper fail-closed checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
