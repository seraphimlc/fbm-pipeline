#!/usr/bin/env python3
"""R1 remote Vite/FastAPI mutating-request guard checks with real processes."""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryFile
from typing import Iterator
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
STANDARD_DENIAL = {
    "code": "REMOTE_DEV_READ_ONLY",
    "detail": "当前是远程只读访问",
}


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> object:
        return json.loads(self.body.decode("utf-8"))


def _redact(value: str, secret_values: tuple[str, ...]) -> str:
    redacted = value
    for secret_value in secret_values:
        if secret_value:
            redacted = redacted.replace(secret_value, "<redacted>")
    return redacted


def _free_port(host: str = "0.0.0.0") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def _non_loopback_ipv4() -> str:
    candidates: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            candidates.add(str(item[4][0]))
    except OSError:
        pass
    for destination in (("192.0.2.1", 9), ("198.51.100.1", 9)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(destination)
                candidates.add(str(probe.getsockname()[0]))
        except OSError:
            continue
    usable = []
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if (
            address.version == 4
            and not address.is_loopback
            and not address.is_unspecified
            and not address.is_link_local
            and not address.is_multicast
        ):
            usable.append(str(address))
    if not usable:
        raise RuntimeError("no deterministic non-loopback local IPv4 address is available")
    return sorted(usable, key=ipaddress.ip_address)[0]


def _request(
    host: str,
    port: int,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    source_address: str | None = None,
    timeout: float = 5.0,
) -> HttpResult:
    connection = http.client.HTTPConnection(
        host,
        port,
        timeout=timeout,
        source_address=(source_address, 0) if source_address else None,
    )
    try:
        request_body = body
        if request_body is None and method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            request_body = b"{}"
        request_headers = dict(headers or {})
        if request_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=request_body, headers=request_headers)
        response = connection.getresponse()
        response_body = response.read()
        return HttpResult(
            status=response.status,
            headers={key.lower(): value for key, value in response.getheaders()},
            body=response_body,
        )
    finally:
        connection.close()


def _process_output(
    process: subprocess.Popen[str],
    log_file,
    secret_values: tuple[str, ...],
) -> str:
    log_file.flush()
    log_file.seek(0)
    return _redact(f"exit={process.poll()}\n{log_file.read()[-16000:]}", secret_values)


def _wait_for_http(
    host: str,
    port: int,
    path: str,
    process: subprocess.Popen[str],
    log_file,
    secret_values: tuple[str, ...],
    *,
    source_address: str | None = None,
    timeout: float = 60.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not started"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"process exited before {host}:{port}{path} became ready\n"
                f"{_process_output(process, log_file, secret_values)}"
            )
        try:
            response = _request(
                host,
                port,
                path,
                source_address=source_address,
                timeout=1.0,
            )
            if response.status < 500:
                return
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.1)
    raise RuntimeError(
        f"timed out waiting for {host}:{port}{path}: {last_error}\n"
        f"{_process_output(process, log_file, secret_values)}"
    )


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


class _CountingProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], backend_port: int):
        super().__init__(server_address, _CountingProxyHandler)
        self.backend_port = backend_port
        self._count = 0
        self._count_lock = threading.Lock()

    def record_call(self) -> None:
        with self._count_lock:
            self._count += 1

    @property
    def call_count(self) -> int:
        with self._count_lock:
            return self._count


class _CountingProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self) -> None:
        server = self.server
        assert isinstance(server, _CountingProxyServer)
        content_length = int(self.headers.get("Content-Length") or 0)
        request_body = self.rfile.read(content_length) if content_length else None
        request_headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"connection", "content-length", "host", "transfer-encoding"}
        }
        if request_body is not None:
            request_headers["Content-Length"] = str(len(request_body))
        server.record_call()
        connection = http.client.HTTPConnection("127.0.0.1", server.backend_port, timeout=10)
        try:
            connection.request(
                self.command,
                self.path,
                body=request_body,
                headers=request_headers,
            )
            upstream = connection.getresponse()
            response_body = upstream.read()
            self.send_response(upstream.status)
            for key, value in upstream.getheaders():
                if key.lower() not in {"connection", "content-length", "transfer-encoding"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response_body)
        finally:
            connection.close()

    do_DELETE = _forward
    do_GET = _forward
    do_HEAD = _forward
    do_OPTIONS = _forward
    do_PATCH = _forward
    do_POST = _forward
    do_PUT = _forward

    def log_message(self, _format: str, *_args: object) -> None:
        return


@dataclass
class RunningStack:
    backend_port: int
    frontend_port: int
    frontend_root: Path
    non_loopback_address: str
    proxy: _CountingProxyServer
    vite_mode: str | None = None

    @property
    def upstream_count(self) -> int:
        return self.proxy.call_count

    def backend_count(self) -> int:
        response = _request(
            "127.0.0.1",
            self.backend_port,
            "/api/r1-remote-guard/count",
            source_address="127.0.0.1",
        )
        assert response.status == 200, response.body
        payload = response.json()
        assert isinstance(payload, dict)
        return int(payload["count"])


@contextlib.contextmanager
def _running_stack(
    temp_dir: Path,
    *,
    non_loopback_address: str,
    vite_token: str,
    api_token: str,
    secret_values: tuple[str, ...],
    vite_mode: str | None = None,
    frontend_env_token: str | None = None,
    process_vite_overrides: bool = False,
) -> Iterator[RunningStack]:
    backend_port = _free_port()
    proxy_port = _free_port("127.0.0.1")
    frontend_port = _free_port()
    child_env = os.environ.copy()
    child_env.update({
        "API_DEV_TOKEN": api_token,
        "DATABASE_BACKEND": "sqlite",
        "SQLITE_DATABASE_PATH": str(temp_dir / "remote-guard.db"),
        "DATABASE_URL": f"sqlite+aiosqlite:///{temp_dir / 'remote-guard.db'}",
        "DATA_DIR": str(temp_dir / "data"),
        "DEV_API_WRITE_TOKEN": vite_token,
        "PYTHONUNBUFFERED": "1",
        "STARTUP_KICK_TASK_RUNTIME": "false",
        "STARTUP_RECOVER_TASKS": "false",
        "STARTUP_RUN_BACKFILLS": "false",
        "STARTUP_RUN_DB_MAINTENANCE": "false",
    })
    frontend_root = FRONTEND
    if vite_mode is None:
        child_env.update({
            "VITE_BACKEND_URL": f"http://127.0.0.1:{proxy_port}",
            "VITE_FRONTEND_PORT": str(frontend_port),
        })
    else:
        frontend_root = temp_dir / "frontend-mode-env"
        frontend_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FRONTEND / "vite.config.ts", frontend_root / "vite.config.ts")
        shutil.copy2(FRONTEND / "dev-api-write-guard.ts", frontend_root / "dev-api-write-guard.ts")
        (frontend_root / "index.html").write_text(
            '<!doctype html><html><body><div id="root">R1</div></body></html>\n',
            encoding="utf-8",
        )
        os.symlink(FRONTEND / "node_modules", frontend_root / "node_modules", target_is_directory=True)
        file_backend_url = "http://127.0.0.1:1" if process_vite_overrides else f"http://127.0.0.1:{proxy_port}"
        file_frontend_port = "1" if process_vite_overrides else str(frontend_port)
        (frontend_root / f".env.{vite_mode}").write_text(
            "\n".join([
                f"VITE_BACKEND_URL={file_backend_url}",
                f"VITE_FRONTEND_PORT={file_frontend_port}",
                f"DEV_API_WRITE_TOKEN={frontend_env_token or ''}",
                f"VITE_DEV_API_WRITE_TOKEN={frontend_env_token or ''}",
                "",
            ]),
            encoding="utf-8",
        )
        if process_vite_overrides:
            child_env.update({
                "VITE_BACKEND_URL": f"http://127.0.0.1:{proxy_port}",
                "VITE_FRONTEND_PORT": str(frontend_port),
            })
        else:
            child_env.pop("VITE_BACKEND_URL", None)
            child_env.pop("VITE_FRONTEND_PORT", None)
            child_env.pop("FRONTEND_PORT", None)
    backend_process: subprocess.Popen[str] | None = None
    frontend_process: subprocess.Popen[str] | None = None
    proxy: _CountingProxyServer | None = None
    proxy_thread: threading.Thread | None = None
    with TemporaryFile(mode="w+", encoding="utf-8") as backend_log, TemporaryFile(
        mode="w+", encoding="utf-8"
    ) as frontend_log:
        try:
            backend_process = subprocess.Popen(
                [
                    str(BACKEND / ".venv" / "bin" / "uvicorn"),
                    "scripts.testing.r1_remote_guard_probe:create_app",
                    "--factory",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(backend_port),
                    "--log-level",
                    "warning",
                ],
                cwd=ROOT,
                env=child_env,
                stdout=backend_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            _wait_for_http(
                "127.0.0.1",
                backend_port,
                "/api/r1-remote-guard/health",
                backend_process,
                backend_log,
                secret_values,
                source_address="127.0.0.1",
            )

            proxy = _CountingProxyServer(("127.0.0.1", proxy_port), backend_port)
            proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
            proxy_thread.start()

            vite_command = [
                str(FRONTEND / "node_modules" / ".bin" / "vite"),
                "--host",
                "0.0.0.0",
                "--strictPort",
            ]
            if vite_mode is None:
                vite_command.extend(["--port", str(frontend_port)])
            else:
                vite_command.extend(["--mode", vite_mode])
            frontend_process = subprocess.Popen(
                vite_command,
                cwd=frontend_root,
                env=child_env,
                stdout=frontend_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            _wait_for_http(
                non_loopback_address,
                frontend_port,
                "/",
                frontend_process,
                frontend_log,
                secret_values,
                source_address=non_loopback_address,
                timeout=15.0,
            )
            yield RunningStack(
                backend_port=backend_port,
                frontend_port=frontend_port,
                frontend_root=frontend_root,
                non_loopback_address=non_loopback_address,
                proxy=proxy,
                vite_mode=vite_mode,
            )
        finally:
            _stop_process(frontend_process)
            if proxy is not None:
                proxy.shutdown()
                proxy.server_close()
            if proxy_thread is not None:
                proxy_thread.join(timeout=5)
            _stop_process(backend_process)
            leaked_logs: list[str] = []
            for label, log_file in (("FastAPI", backend_log), ("Vite", frontend_log)):
                log_file.flush()
                log_file.seek(0)
                raw_log = log_file.read()
                if any(secret_value and secret_value in raw_log for secret_value in secret_values):
                    leaked_logs.append(label)
            if leaked_logs:
                raise AssertionError(f"secret leaked into process logs: {', '.join(leaked_logs)}")


def _assert_denied(response: HttpResult, label: str) -> None:
    assert response.status == 403, f"{label}: expected 403, got {response.status}: {response.body!r}"
    assert response.json() == STANDARD_DENIAL, f"{label}: {response.body!r}"


def _assert_success(response: HttpResult, label: str) -> None:
    assert response.status == 200, f"{label}: expected 200, got {response.status}: {response.body!r}"
    payload = response.json()
    assert isinstance(payload, dict) and payload.get("ok") is True, f"{label}: {payload!r}"


def _remote_vite_request(
    stack: RunningStack,
    *,
    headers: dict[str, str] | None = None,
    path: str = "/api/r1-remote-guard/probe",
    method: str = "POST",
) -> HttpResult:
    return _request(
        stack.non_loopback_address,
        stack.frontend_port,
        path,
        method=method,
        headers=headers,
        source_address=stack.non_loopback_address,
    )


def _direct_remote_backend_request(
    stack: RunningStack,
    *,
    headers: dict[str, str] | None = None,
) -> HttpResult:
    return _request(
        stack.non_loopback_address,
        stack.backend_port,
        "/api/r1-remote-guard/probe",
        method="POST",
        headers=headers,
        source_address=stack.non_loopback_address,
    )


def _test_backend_address_helpers() -> None:
    code = r'''
from types import SimpleNamespace
from app import main

assert main._normalize_client_host("127.0.0.9") == "127.0.0.9"
assert main._normalize_client_host("::ffff:127.0.0.9") == "127.0.0.9"
assert main._normalize_client_host("[::1]") == "::1"
assert main._is_local_client(SimpleNamespace(host="127.255.1.2"))
assert main._is_local_client(SimpleNamespace(host="::ffff:127.0.0.1"))
assert main._is_local_client(SimpleNamespace(host="[::1]"))
assert not main._is_local_client(SimpleNamespace(host="2001:db8::7"))
'''
    env = os.environ.copy()
    env.update(
        {
            "STARTUP_RUN_DB_MAINTENANCE": "false",
        }
    )
    result = subprocess.run(
        [
            str(BACKEND / ".venv" / "bin" / "python"),
            str(ROOT / "scripts/testing/run_with_r1_sqlite.py"), "--",
            str(BACKEND / ".venv" / "bin" / "python"), "-c", code,
        ],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _test_frontend_guard_units() -> None:
    result = subprocess.run(
        ["node", "--experimental-strip-types", "scripts/test-dev-api-write-guard.mjs"],
        cwd=FRONTEND,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _test_startup_env_helper_units() -> None:
    code = r'''
from scripts.read_startup_env import is_loopback_host

for value in (
    "localhost",
    "LOCALHOST",
    "127.0.0.1",
    "127.83.4.5",
    "::1",
    "[::1]",
    "0:0:0:0:0:0:0:1",
    "::ffff:127.0.0.1",
    "[::ffff:127.44.5.6]",
):
    assert is_loopback_host(value), value

for value in ("", "0.0.0.0", "192.0.2.10", "2001:db8::1", "[2001:db8::1]", "invalid-host"):
    assert not is_loopback_host(value), value
'''
    result = subprocess.run(
        [str(BACKEND / ".venv" / "bin" / "python"), "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _write_fake_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _prepare_start_fixture(
    temp_dir: Path,
    env_text: str,
    *,
    expected_token: str,
    expected_frontend_host: str,
    parent_token: str,
    parent_frontend_host: str,
    mutate_before_env_text: str | None = None,
    mutate_after_env_text: str | None = None,
) -> tuple[Path, Path, dict[str, str]]:
    fixture_root = temp_dir / f"start-fixture-{secrets.token_hex(4)}"
    (fixture_root / "scripts").mkdir(parents=True)
    (fixture_root / "backend" / ".venv" / "bin").mkdir(parents=True)
    (fixture_root / "frontend" / "node_modules").mkdir(parents=True)
    fake_bin = fixture_root / "fake-bin"
    fake_bin.mkdir()
    shutil.copy2(ROOT / "scripts" / "start.sh", fixture_root / "scripts" / "start.sh")
    env_helper = ROOT / "scripts" / "read_startup_env.py"
    if env_helper.is_file():
        shutil.copy2(env_helper, fixture_root / "scripts" / "read_startup_env.py")
    env_file = fixture_root / "backend" / ".env"
    env_file.write_text(env_text, encoding="utf-8")
    before_mutation = fixture_root / "mutate-before.env"
    after_mutation = fixture_root / "mutate-after.env"
    if mutate_before_env_text is not None:
        before_mutation.write_text(mutate_before_env_text, encoding="utf-8")
    if mutate_after_env_text is not None:
        after_mutation.write_text(mutate_after_env_text, encoding="utf-8")
    python_hook = fixture_root / "python-hook"
    python_hook.mkdir()
    (python_hook / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "_real_execvpe = os.execvpe\n"
        "\n"
        "def _mutating_execvpe(file, args, env):\n"
        "    source = os.environ.get('R1_START_MUTATE_AFTER_FILE')\n"
        "    target = os.environ.get('R1_START_ENV_FILE')\n"
        "    if source and target:\n"
        "        Path(target).write_bytes(Path(source).read_bytes())\n"
        "    return _real_execvpe(file, args, env)\n"
        "\n"
        "os.execvpe = _mutating_execvpe\n",
        encoding="utf-8",
    )
    (fixture_root / "backend" / ".venv" / "bin" / "activate").write_text("# test no-op\n", encoding="utf-8")
    marker = fixture_root / "child-marker.log"
    _write_fake_executable(
        fixture_root / "backend" / ".venv" / "bin" / "python",
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  */read_startup_env.py)\n"
        "    printf 'dotenv-parser\\n' >> \"$R1_START_MARKER\"\n"
        "    if [ -n \"$R1_START_MUTATE_BEFORE_FILE\" ]; then\n"
        "      cp \"$R1_START_MUTATE_BEFORE_FILE\" \"$R1_START_ENV_FILE\"\n"
        "    fi\n"
        "    exec \"$R1_REAL_BACKEND_PYTHON\" \"$@\"\n"
        "    ;;\n"
        "  -m)\n"
        "    printf 'database\\n' >> \"$R1_START_MARKER\"\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        "printf 'unexpected-python\\n' >> \"$R1_START_MARKER\"\n"
        "exit 1\n",
    )
    _write_fake_executable(
        fake_bin / "python",
        "#!/bin/sh\nprintf 'database:path-python\\n' >> \"$R1_START_MARKER\"\nexit 0\n",
    )
    _write_fake_executable(
        fake_bin / "uvicorn",
        "#!/bin/sh\n"
        "if [ \"$API_DEV_TOKEN\" = \"$R1_EXPECTED_TOKEN\" ]; then state=expected; "
        "elif [ -z \"$API_DEV_TOKEN\" ]; then state=empty; else state=unexpected; fi\n"
        "printf 'uvicorn:token-%s\\n' \"$state\" >> \"$R1_START_MARKER\"\n"
        "while :; do sleep 1; done\n",
    )
    _write_fake_executable(
        fake_bin / "npx",
        "#!/bin/sh\n"
        "if [ \"$DEV_API_WRITE_TOKEN\" = \"$R1_EXPECTED_TOKEN\" ]; then state=expected; "
        "elif [ -z \"$DEV_API_WRITE_TOKEN\" ]; then state=empty; else state=unexpected; fi\n"
        "printf 'npx:token-%s\\n' \"$state\" >> \"$R1_START_MARKER\"\n"
        "host=\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = --host ]; then shift; host=\"${1:-}\"; fi\n"
        "  shift\n"
        "done\n"
        "if [ \"$host\" = \"$R1_EXPECTED_FRONTEND_HOST\" ]; then host_state=expected; else host_state=unexpected; fi\n"
        "printf 'npx:host-%s:%s\\n' \"$host_state\" \"$host\" >> \"$R1_START_MARKER\"\n"
        "while :; do sleep 1; done\n",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"
    env["PYTHONPATH"] = f"{python_hook}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["API_DEV_TOKEN"] = parent_token
    env["DEV_API_WRITE_TOKEN"] = parent_token
    env["FRONTEND_HOST"] = parent_frontend_host
    env["FBM_STARTUP_ENV_PROOF_FD"] = "9999"
    env["FBM_STARTUP_ENV_PROOF_NONCE"] = "parent-spoofed-proof"
    env["R1_EXPECTED_TOKEN"] = expected_token
    env["R1_EXPECTED_FRONTEND_HOST"] = expected_frontend_host
    env["R1_REAL_BACKEND_PYTHON"] = str(BACKEND / ".venv" / "bin" / "python")
    env["R1_START_ENV_FILE"] = str(env_file)
    env["R1_START_MARKER"] = str(marker)
    if mutate_before_env_text is not None:
        env["R1_START_MUTATE_BEFORE_FILE"] = str(before_mutation)
    if mutate_after_env_text is not None:
        env["R1_START_MUTATE_AFTER_FILE"] = str(after_mutation)
    return fixture_root, marker, env


def _run_start_fail_fast(
    temp_dir: Path,
    env_text: str,
    *,
    parent_token: str,
    secret_values: tuple[str, ...],
    parent_frontend_host: str = "127.0.0.1",
    mutate_before_env_text: str | None = None,
    mutate_after_env_text: str | None = None,
    initial_args: tuple[str, ...] = (),
) -> None:
    fixture_root, marker, env = _prepare_start_fixture(
        temp_dir,
        env_text,
        expected_token="",
        expected_frontend_host="",
        parent_token=parent_token,
        parent_frontend_host=parent_frontend_host,
        mutate_before_env_text=mutate_before_env_text,
        mutate_after_env_text=mutate_after_env_text,
    )
    process = subprocess.Popen(
        [str(fixture_root / "scripts" / "start.sh"), *initial_args],
        cwd=fixture_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    timed_out = False
    try:
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            timed_out = True
            output = ""
    finally:
        _stop_process(process)
        if timed_out and process.stdout is not None:
            output += process.stdout.read()
    assert not timed_out, "remote invalid-token start did not fail before child startup"
    assert process.returncode != 0, "remote invalid-token start unexpectedly succeeded"
    marker_text = marker.read_text(encoding="utf-8") if marker.exists() else ""
    assert marker_text.count("dotenv-parser\n") == 1, marker_text
    for forbidden_marker in ("database", "uvicorn", "npx", "unexpected-python"):
        assert forbidden_marker not in marker_text, marker_text
    assert "remote startup token format or length is invalid" in output
    assert not any(secret_value and secret_value in output for secret_value in secret_values)


def _run_start_success(
    temp_dir: Path,
    env_text: str,
    *,
    expected_token: str,
    expected_frontend_host: str,
    parent_token: str,
    secret_values: tuple[str, ...],
    parent_frontend_host: str = "203.0.113.19",
    mutate_before_env_text: str | None = None,
    mutate_after_env_text: str | None = None,
    initial_args: tuple[str, ...] = (),
) -> None:
    fixture_root, marker, env = _prepare_start_fixture(
        temp_dir,
        env_text,
        expected_token=expected_token,
        expected_frontend_host=expected_frontend_host,
        parent_token=parent_token,
        parent_frontend_host=parent_frontend_host,
        mutate_before_env_text=mutate_before_env_text,
        mutate_after_env_text=mutate_after_env_text,
    )
    process = subprocess.Popen(
        [str(fixture_root / "scripts" / "start.sh"), *initial_args],
        cwd=fixture_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        marker_text = ""
        while time.monotonic() < deadline:
            if marker.exists():
                marker_text = marker.read_text(encoding="utf-8")
                if (
                    marker_text.count("dotenv-parser\n") == 1
                    and "database\n" in marker_text
                    and "uvicorn:token-expected\n" in marker_text
                    and "npx:token-expected\n" in marker_text
                    and f"npx:host-expected:{expected_frontend_host}\n" in marker_text
                ):
                    break
            if process.poll() is not None:
                break
            time.sleep(0.05)
        assert marker_text.count("dotenv-parser\n") == 1, marker_text
        assert "database\n" in marker_text, marker_text
        assert "database:path-python" not in marker_text, marker_text
        assert "uvicorn:token-expected\n" in marker_text, marker_text
        assert "npx:token-expected\n" in marker_text, marker_text
        assert f"npx:host-expected:{expected_frontend_host}\n" in marker_text, marker_text
    finally:
        _stop_process(process)
    output = process.stdout.read() if process.stdout is not None else ""
    assert not any(secret_value and secret_value in output for secret_value in secret_values)


def _test_start_script(temp_dir: Path, token_a: str, token_b: str) -> None:
    base = "BACKEND_HOST=127.0.0.1\nBACKEND_PORT=8190\nFRONTEND_PORT=3190\n"
    _run_start_fail_fast(
        temp_dir,
        base + "FRONTEND_HOST=0.0.0.0\nDEV_API_WRITE_TOKEN=\nAPI_DEV_TOKEN=\n",
        parent_token=token_b,
        secret_values=(token_a, token_b),
        initial_args=("--fbm-startup-env-ready",),
    )
    _run_start_fail_fast(
        temp_dir,
        base + f"FRONTEND_HOST=0.0.0.0\nDEV_API_WRITE_TOKEN={token_a}\nAPI_DEV_TOKEN={token_b}\n",
        parent_token=token_a,
        secret_values=(token_a, token_b),
    )
    _run_start_fail_fast(
        temp_dir,
        base + 'FRONTEND_HOST=0.0.0.0\nDEV_API_WRITE_TOKEN="   "\nAPI_DEV_TOKEN=\'  \'\n',
        parent_token=token_b,
        secret_values=(token_a, token_b),
    )
    _run_start_fail_fast(
        temp_dir,
        base + f"FRONTEND_HOST=0.0.0.0\nDEV_API_WRITE_TOKEN='{token_a}'\nAPI_DEV_TOKEN=\n",
        parent_token=token_b,
        secret_values=(token_a, token_b),
    )
    _run_start_success(
        temp_dir,
        base + "FRONTEND_HOST=[::1]\nDEV_API_WRITE_TOKEN=\nAPI_DEV_TOKEN=\n",
        expected_token="",
        expected_frontend_host="[::1]",
        parent_token=token_b,
        secret_values=(token_a, token_b),
    )
    local_invalid_token = "local token with space"
    _run_start_success(
        temp_dir,
        base
        + "FRONTEND_HOST=127.0.0.1\n"
        + f"DEV_API_WRITE_TOKEN='{local_invalid_token}'\n"
        + f"API_DEV_TOKEN='{local_invalid_token}'\n",
        expected_token=local_invalid_token,
        expected_frontend_host="127.0.0.1",
        parent_token=token_b,
        secret_values=(token_a, token_b, local_invalid_token),
    )
    decoded_token = f"{token_a}#decoded"
    _run_start_success(
        temp_dir,
        base
        + "FRONTEND_HOST=0.0.0.0\n"
        + f"DEV_API_WRITE_TOKEN='  {decoded_token}  ' # frontend token\n"
        + f'API_DEV_TOKEN="  {decoded_token}  " # backend token\n',
        expected_token=decoded_token,
        expected_frontend_host="0.0.0.0",
        parent_token=token_b,
        secret_values=(token_a, token_b),
    )
    interpolated_token = f"{token_a}#interpolated"
    _run_start_success(
        temp_dir,
        base
        + "FRONTEND_HOST=0.0.0.0\n"
        + f"TOKEN_SEED={token_a}\n"
        + 'DEV_API_WRITE_TOKEN="${TOKEN_SEED}#interpolated"\n'
        + 'API_DEV_TOKEN="${TOKEN_SEED}#interpolated"\n',
        expected_token=interpolated_token,
        expected_frontend_host="0.0.0.0",
        parent_token=token_b,
        secret_values=(token_a, token_b),
    )

    invalid_remote_tokens = (
        f"{token_a}\\nsecond-line",
        f"{token_a}\\rsecond-line",
        "中文令牌",
        "visible\tcontrol",
        "visible\x7fdel",
        "internal space",
        "A" * 4097,
        "B" * 17000,
    )
    for invalid_token in invalid_remote_tokens:
        _run_start_fail_fast(
            temp_dir,
            base
            + "FRONTEND_HOST=0.0.0.0\n"
            + f'DEV_API_WRITE_TOKEN="{invalid_token}"\n'
            + f'API_DEV_TOKEN="{invalid_token}"\n',
            parent_token=token_b,
            secret_values=(token_a, token_b, invalid_token),
        )

    for boundary_token in ("~", "Z" * 4096):
        _run_start_success(
            temp_dir,
            base
            + "FRONTEND_HOST=0.0.0.0\n"
            + f"DEV_API_WRITE_TOKEN={boundary_token}\n"
            + f"API_DEV_TOKEN={boundary_token}\n",
            expected_token=boundary_token,
            expected_frontend_host="0.0.0.0",
            parent_token=token_b,
            secret_values=(token_a, token_b, boundary_token),
        )

    race_invalid_token = "snapshot token with space"
    loopback_invalid = (
        base
        + "FRONTEND_HOST=127.0.0.1\n"
        + f"DEV_API_WRITE_TOKEN='{race_invalid_token}'\n"
        + f"API_DEV_TOKEN='{race_invalid_token}'\n"
    )
    remote_invalid = (
        base
        + "FRONTEND_HOST=0.0.0.0\n"
        + f"DEV_API_WRITE_TOKEN='{race_invalid_token}'\n"
        + f"API_DEV_TOKEN='{race_invalid_token}'\n"
    )
    remote_valid = (
        base
        + "FRONTEND_HOST=0.0.0.0\n"
        + f"DEV_API_WRITE_TOKEN={token_a}\n"
        + f"API_DEV_TOKEN={token_a}\n"
    )
    _run_start_fail_fast(
        temp_dir,
        loopback_invalid,
        parent_token=token_b,
        secret_values=(token_a, token_b, race_invalid_token),
        mutate_before_env_text=remote_invalid,
    )
    _run_start_success(
        temp_dir,
        loopback_invalid,
        expected_token=race_invalid_token,
        expected_frontend_host="127.0.0.1",
        parent_token=token_b,
        secret_values=(token_a, token_b, race_invalid_token),
        mutate_after_env_text=remote_invalid,
    )
    _run_start_success(
        temp_dir,
        remote_invalid,
        expected_token=race_invalid_token,
        expected_frontend_host="127.0.0.1",
        parent_token=token_b,
        secret_values=(token_a, token_b, race_invalid_token),
        mutate_before_env_text=loopback_invalid,
    )
    _run_start_success(
        temp_dir,
        remote_valid,
        expected_token=token_a,
        expected_frontend_host="0.0.0.0",
        parent_token=token_b,
        secret_values=(token_a, token_b, race_invalid_token),
        mutate_after_env_text=loopback_invalid,
    )


def _scan_build_for_secret(secret_values: tuple[str, ...]) -> None:
    env = os.environ.copy()
    env["DEV_API_WRITE_TOKEN"] = secret_values[0]
    with TemporaryFile(mode="w+", encoding="utf-8") as build_log:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=FRONTEND,
            env=env,
            stdout=build_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        build_log.flush()
        build_log.seek(0)
        raw_log = build_log.read()
        assert not any(secret_value and secret_value in raw_log for secret_value in secret_values)
        assert result.returncode == 0, _redact(raw_log[-16000:], secret_values)
    leaked_files = []
    for path in (FRONTEND / "dist").rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            if any(secret_value.encode("utf-8") in content for secret_value in secret_values):
                leaked_files.append(str(path.relative_to(FRONTEND)))
    assert not leaked_files, f"secret leaked into frontend build: {leaked_files}"


def _scan_browser_visible_modules(stack: RunningStack, secret_values: tuple[str, ...]) -> None:
    paths = [
        "/",
        "/@vite/client",
        "/dev-api-write-guard.ts",
        "/vite.config.ts",
        "/@fs/" + quote(str(stack.frontend_root / "dev-api-write-guard.ts"), safe="/:"),
        "/@fs/" + quote(str(stack.frontend_root / "vite.config.ts"), safe="/:"),
    ]
    if stack.vite_mode is not None:
        paths.append(f"/.env.{stack.vite_mode}")
    for path in paths:
        response = _remote_vite_request(stack, path=path, method="GET")
        assert response.status in {200, 304, 403, 404}, f"module probe {path}: {response.status}"
        assert not any(secret_value.encode("utf-8") in response.body for secret_value in secret_values), path


def _test_vite_mode_env_compatibility(
    temp_dir: Path,
    non_loopback_address: str,
    process_token: str,
    frontend_env_token: str,
    secret_values: tuple[str, ...],
) -> None:
    for label, process_vite_overrides in (
        ("mode-only", False),
        ("process-over-mode", True),
    ):
        with _running_stack(
            temp_dir / f"vite-env-{label}",
            non_loopback_address=non_loopback_address,
            vite_token=process_token,
            api_token=process_token,
            secret_values=secret_values,
            vite_mode=f"r1-{label}",
            frontend_env_token=frontend_env_token,
            process_vite_overrides=process_vite_overrides,
        ) as stack:
            _assert_denied(
                _remote_vite_request(stack, headers={"X-FBM-Dev-Token": frontend_env_token}),
                f"{label} frontend env token must not authorize",
            )
            assert stack.upstream_count == 0
            assert stack.backend_count() == 0
            _assert_success(
                _remote_vite_request(stack, headers={"X-FBM-Dev-Token": process_token}),
                f"{label} process token",
            )
            assert stack.upstream_count == 1
            assert stack.backend_count() == 1
            _scan_browser_visible_modules(stack, secret_values)


def _test_matching_tokens(
    temp_dir: Path,
    non_loopback_address: str,
    token_a: str,
    wrong_token: str,
    secret_values: tuple[str, ...],
) -> None:
    with _running_stack(
        temp_dir / "matching",
        non_loopback_address=non_loopback_address,
        vite_token=token_a,
        api_token=token_a,
        secret_values=secret_values,
    ) as stack:
        assert stack.upstream_count == 0
        assert stack.backend_count() == 0
        for label, headers in (
            ("missing Vite token", {}),
            ("empty Vite token", {"X-FBM-Dev-Token": ""}),
            ("wrong Vite token", {"X-FBM-Dev-Token": wrong_token}),
            ("spoofed XFF", {"X-Forwarded-For": "127.0.0.1"}),
        ):
            _assert_denied(_remote_vite_request(stack, headers=headers), label)
            assert stack.upstream_count == 0, label
            assert stack.backend_count() == 0, label

        _assert_success(
            _remote_vite_request(stack, headers={"X-FBM-Dev-Token": token_a}),
            "matching remote token",
        )
        assert stack.upstream_count == 1
        assert stack.backend_count() == 1

        local_response = _request(
            "127.0.0.1",
            stack.frontend_port,
            "/api/r1-remote-guard/probe",
            method="POST",
            source_address="127.0.0.1",
        )
        _assert_success(local_response, "loopback Vite write without token")
        assert stack.upstream_count == 2
        assert stack.backend_count() == 2

        _assert_denied(
            _request(
                "127.0.0.1",
                stack.backend_port,
                "/api/r1-remote-guard/probe",
                method="POST",
                headers={"X-FBM-Proxy-Client": "remote"},
                source_address="127.0.0.1",
            ),
            "loopback backend socket with remote marker",
        )
        assert stack.backend_count() == 2

        _assert_denied(
            _direct_remote_backend_request(
                stack,
                headers={"X-Forwarded-For": "127.0.0.1", "Forwarded": "for=127.0.0.1"},
            ),
            "direct remote backend spoofed forwarding headers",
        )
        _assert_denied(
            _direct_remote_backend_request(stack, headers={"X-FBM-Dev-Token": wrong_token}),
            "direct remote backend wrong token",
        )
        assert stack.upstream_count == 2
        assert stack.backend_count() == 2
        _assert_success(
            _direct_remote_backend_request(stack, headers={"Authorization": f"Bearer {token_a}"}),
            "direct remote backend correct token",
        )
        assert stack.upstream_count == 2
        assert stack.backend_count() == 3
        _scan_browser_visible_modules(stack, secret_values)


def _test_credential_precedence(
    temp_dir: Path,
    non_loopback_address: str,
    token: str,
    wrong_token: str,
    secret_values: tuple[str, ...],
) -> None:
    with _running_stack(
        temp_dir / "credential-precedence",
        non_loopback_address=non_loopback_address,
        vite_token=token,
        api_token=token,
        secret_values=secret_values,
    ) as stack:
        wrong_header_correct_bearer = {
            "Authorization": f"Bearer {token}",
            "X-FBM-Dev-Token": wrong_token,
        }
        correct_header_wrong_bearer = {
            "Authorization": f"Bearer {wrong_token}",
            "X-FBM-Dev-Token": token,
        }
        empty_header_correct_bearer = {
            "Authorization": f"Bearer {token}",
            "X-FBM-Dev-Token": "   ",
        }

        _assert_denied(
            _remote_vite_request(stack, headers=wrong_header_correct_bearer),
            "Vite wrong header must override correct bearer",
        )
        assert stack.upstream_count == 0
        assert stack.backend_count() == 0
        _assert_success(
            _remote_vite_request(stack, headers=correct_header_wrong_bearer),
            "Vite correct header must override wrong bearer",
        )
        _assert_success(
            _remote_vite_request(stack, headers=empty_header_correct_bearer),
            "Vite empty header must fall back to bearer",
        )
        assert stack.upstream_count == 2
        assert stack.backend_count() == 2

        _assert_denied(
            _direct_remote_backend_request(stack, headers=wrong_header_correct_bearer),
            "FastAPI wrong header must override correct bearer",
        )
        assert stack.upstream_count == 2
        assert stack.backend_count() == 2
        _assert_success(
            _direct_remote_backend_request(stack, headers=correct_header_wrong_bearer),
            "FastAPI correct header must override wrong bearer",
        )
        _assert_success(
            _direct_remote_backend_request(stack, headers=empty_header_correct_bearer),
            "FastAPI empty header must fall back to bearer",
        )
        assert stack.upstream_count == 2
        assert stack.backend_count() == 4


def _test_unconfigured_vite(
    temp_dir: Path,
    non_loopback_address: str,
    api_token: str,
    secret_values: tuple[str, ...],
) -> None:
    with _running_stack(
        temp_dir / "unconfigured-vite",
        non_loopback_address=non_loopback_address,
        vite_token="",
        api_token=api_token,
        secret_values=secret_values,
    ) as stack:
        _assert_denied(
            _remote_vite_request(stack, headers={"X-FBM-Dev-Token": api_token}),
            "manually started remote Vite without configured token",
        )
        assert stack.upstream_count == 0
        assert stack.backend_count() == 0


def _test_mismatched_tokens(
    temp_dir: Path,
    non_loopback_address: str,
    token_a: str,
    token_b: str,
    wrong_token: str,
    secret_values: tuple[str, ...],
) -> None:
    with _running_stack(
        temp_dir / "mismatched",
        non_loopback_address=non_loopback_address,
        vite_token=token_a,
        api_token=token_b,
        secret_values=secret_values,
    ) as stack:
        response = _remote_vite_request(stack, headers={"X-FBM-Dev-Token": token_a})
        _assert_denied(response, "mismatched backend token")
        assert stack.upstream_count == 1
        assert stack.backend_count() == 0

        _assert_denied(_direct_remote_backend_request(stack), "mismatched direct missing token")
        _assert_denied(
            _direct_remote_backend_request(stack, headers={"X-FBM-Dev-Token": wrong_token}),
            "mismatched direct wrong token",
        )
        assert stack.upstream_count == 1
        assert stack.backend_count() == 0
        _assert_success(
            _direct_remote_backend_request(stack, headers={"X-FBM-Dev-Token": token_b}),
            "mismatched direct correct backend token",
        )
        assert stack.upstream_count == 1
        assert stack.backend_count() == 1


def main() -> int:
    token_a = secrets.token_urlsafe(48)
    token_b = secrets.token_urlsafe(48)
    wrong_token = secrets.token_urlsafe(48)
    secret_values = (token_a, token_b, wrong_token)
    non_loopback_address = _non_loopback_ipv4()
    with tempfile.TemporaryDirectory(prefix="fbm-r1-remote-guard-") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        _test_frontend_guard_units()
        _test_startup_env_helper_units()
        _test_backend_address_helpers()
        _test_start_script(temp_dir, token_a, token_b)
        _test_vite_mode_env_compatibility(
            temp_dir,
            non_loopback_address,
            token_a,
            token_b,
            secret_values,
        )
        _test_matching_tokens(temp_dir, non_loopback_address, token_a, wrong_token, secret_values)
        _test_credential_precedence(
            temp_dir,
            non_loopback_address,
            token_a,
            wrong_token,
            secret_values,
        )
        _test_mismatched_tokens(
            temp_dir,
            non_loopback_address,
            token_a,
            token_b,
            wrong_token,
            secret_values,
        )
        _test_unconfigured_vite(temp_dir, non_loopback_address, token_a, secret_values)
        _scan_build_for_secret(secret_values)
    print("R1 remote Vite/FastAPI write-guard checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"R1 remote guard checks failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
