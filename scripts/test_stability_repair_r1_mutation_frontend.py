#!/usr/bin/env python3
"""R1 remote mutation UX coverage through a real non-loopback Vite guard."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

from test_stability_repair_r1_remote_guard import (
    FRONTEND,
    _non_loopback_ipv4,
    _running_stack,
)


def main() -> int:
    non_loopback_address = _non_loopback_ipv4()
    vite_token = secrets.token_urlsafe(48)
    api_token = secrets.token_urlsafe(48)
    secret_values = (vite_token, api_token)
    with tempfile.TemporaryDirectory(prefix="fbm-r1-mutation-frontend-") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        with _running_stack(
            temp_dir / "stack",
            non_loopback_address=non_loopback_address,
            vite_token=vite_token,
            api_token=api_token,
            secret_values=secret_values,
        ) as stack:
            state_file = temp_dir / "playwright-state.json"
            state_file.write_text(
                json.dumps(
                    {
                        "frontend_base_url": (
                            f"http://{stack.non_loopback_address}:{stack.frontend_port}"
                        ),
                        "output_dir": str(temp_dir / "playwright-output"),
                    }
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.pop("R1_MUTATION_PARTIAL", None)
            env["R1_MUTATION_FRONTEND_STATE"] = str(state_file)
            grep_pattern = env.get("R1_MUTATION_FRONTEND_GREP", "").strip()
            command = [
                "npx",
                "playwright",
                "test",
                "--config=playwright.mutation.r1.config.ts",
            ]
            if grep_pattern:
                env["R1_MUTATION_PARTIAL"] = "1"
                command.extend(["--grep", grep_pattern])
            result = subprocess.run(
                command,
                cwd=FRONTEND,
                env=env,
                text=True,
                capture_output=True,
            )
            assert result.returncode == 0, (
                result.stdout
                + result.stderr
                + f"\nupstream_count={stack.upstream_count} backend_count={stack.backend_count()}"
            )
            assert stack.upstream_count == 0, stack.upstream_count
            assert stack.backend_count() == 0, stack.backend_count()
    print("R1 remote mutation frontend checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
