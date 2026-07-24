#!/usr/bin/env python3
"""R1 TikTok real FastAPI/Vite/Chromium checks on isolated MySQL."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryFile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.test_stability_repair_r1_tiktok import _seed_fixtures
from scripts.testing.r1_mysql import R1MysqlNotConfigured, isolated_r1_mysql


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _process_output(process: subprocess.Popen, log_file) -> str:
    log_file.flush()
    log_file.seek(0)
    return f"exit={process.poll()}\n{log_file.read()[-12000:]}"


def _wait_for_http(url: str, process: subprocess.Popen, log_file, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not started"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process exited before {url} became ready\n{_process_output(process, log_file)}")
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}\n{_process_output(process, log_file)}")


def _stop_process(process: subprocess.Popen | None, *, process_group: bool = False) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if process_group:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            if process_group:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)


async def run() -> None:
    async with isolated_r1_mysql(ROOT) as environment:
        fixture_state = await _seed_fixtures(environment)
        backend_port = _free_loopback_port()
        frontend_port = _free_loopback_port()
        backend_url = f"http://127.0.0.1:{backend_port}"
        frontend_url = f"http://127.0.0.1:{frontend_port}"
        child_env = os.environ.copy()
        child_env.update({
            "PYTHONUNBUFFERED": "1",
            "BACKEND_PORT": str(backend_port),
            "VITE_BACKEND_URL": backend_url,
            "VITE_FRONTEND_PORT": str(frontend_port),
        })
        state_path = environment.data_dir / "tiktok-frontend-state.json"
        state_path.write_text(json.dumps({
            "backend_base_url": backend_url,
            "frontend_base_url": frontend_url,
            "output_dir": str(environment.data_dir / "playwright-output"),
            "tiktok_data_source_id": fixture_state.tiktok_data_source_id,
            "product_ids": fixture_state.product_ids,
            "pagination_tie_product_ids": fixture_state.pagination_tie_product_ids,
            "pagination_tie_timestamp": fixture_state.pagination_tie_timestamp,
        }), encoding="utf-8")
        child_env["R1_TIKTOK_FRONTEND_STATE"] = str(state_path)

        backend_process = None
        frontend_process = None
        with TemporaryFile(mode="w+", encoding="utf-8") as backend_log, TemporaryFile(
            mode="w+", encoding="utf-8"
        ) as frontend_log:
            try:
                backend_process = subprocess.Popen(
                    [
                        str(BACKEND / ".venv" / "bin" / "uvicorn"),
                        "app.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(backend_port),
                        "--lifespan",
                        "off",
                        "--log-level",
                        "info",
                    ],
                    cwd=BACKEND,
                    env=child_env,
                    stdout=backend_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                _wait_for_http(
                    f"{backend_url}/api/products?data_source_id={fixture_state.tiktok_data_source_id}&page_size=1",
                    backend_process,
                    backend_log,
                    timeout=120.0,
                )

                frontend_process = subprocess.Popen(
                    [
                        "npm",
                        "run",
                        "dev",
                        "--",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(frontend_port),
                        "--strictPort",
                    ],
                    cwd=FRONTEND,
                    env=child_env,
                    stdout=frontend_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                _wait_for_http(f"{frontend_url}/products", frontend_process, frontend_log)

                result = subprocess.run(
                    [
                        str(FRONTEND / "node_modules" / ".bin" / "playwright"),
                        "test",
                        "--config=playwright.tiktok.r1.config.ts",
                    ],
                    cwd=FRONTEND,
                    env=child_env,
                    text=True,
                    capture_output=True,
                    timeout=180,
                )
                if result.returncode != 0:
                    raise AssertionError(
                        "TikTok frontend Playwright failed\n"
                        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\n"
                        f"backend:\n{_process_output(backend_process, backend_log)}\n"
                        f"frontend:\n{_process_output(frontend_process, frontend_log)}"
                    )
                print(result.stdout.strip())
                print(f"R1 TikTok frontend real API checks passed: {environment.database_name}")
            finally:
                _stop_process(frontend_process, process_group=True)
                _stop_process(backend_process)


def main() -> int:
    try:
        asyncio.run(run())
    except R1MysqlNotConfigured as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
