#!/usr/bin/env python3
"""Snapshot startup host/tokens, validate remote transport, then exec startup."""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import os
from pathlib import Path
import secrets
import sys

from dotenv import dotenv_values


TOKEN_KEYS = ("DEV_API_WRITE_TOKEN", "API_DEV_TOKEN")
DEFAULT_FRONTEND_HOST = "127.0.0.1"
MAX_TOKEN_BYTES = 4096
INVALID_REMOTE_TOKEN_MESSAGE = "remote startup token format or length is invalid"
STARTUP_PROOF_FD_ENV = "FBM_STARTUP_ENV_PROOF_FD"
STARTUP_PROOF_NONCE_ENV = "FBM_STARTUP_ENV_PROOF_NONCE"


def read_startup_snapshot(env_file: Path) -> dict[str, str]:
    values = dotenv_values(env_file, encoding="utf-8") if env_file.is_file() else {}
    frontend_host = str(values.get("FRONTEND_HOST") or "").strip() or DEFAULT_FRONTEND_HOST
    return {
        "FRONTEND_HOST": frontend_host,
        **{key: str(values.get(key) or "").strip() for key in TOKEN_KEYS},
    }


def is_loopback_host(value: str) -> bool:
    host = str(value or "").strip().lower()
    if host.startswith("["):
        closing_bracket = host.find("]")
        if closing_bracket > 0:
            host = host[1:closing_bracket]
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


def validate_remote_token_transport(tokens: dict[str, str]) -> None:
    encoded = {key: tokens[key].encode("utf-8") for key in TOKEN_KEYS}
    if any(
        not 1 <= len(value) <= MAX_TOKEN_BYTES
        or any(byte < 0x21 or byte > 0x7E for byte in value)
        for value in encoded.values()
    ) or not hmac.compare_digest(encoded["DEV_API_WRITE_TOKEN"], encoded["API_DEV_TOKEN"]):
        raise ValueError(INVALID_REMOTE_TOKEN_MESSAGE)


def _command_from_args(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        command = command[1:]
    if (
        len(command) != 1
        or Path(command[0]).name != "start.sh"
    ):
        raise ValueError("validated startup continuation is required")
    return command


def _exec_validated_startup(command: list[str], child_env: dict[str, str]) -> None:
    proof_nonce = secrets.token_urlsafe(32)
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, f"{proof_nonce}\n".encode("ascii"))
    finally:
        os.close(write_fd)
    os.set_inheritable(read_fd, True)
    child_env[STARTUP_PROOF_FD_ENV] = str(read_fd)
    child_env[STARTUP_PROOF_NONCE_ENV] = proof_nonce
    try:
        os.execvpe(command[0], command, child_env)
    finally:
        os.close(read_fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        command = _command_from_args(args.command)
        snapshot = read_startup_snapshot(args.env_file)
        if not is_loopback_host(snapshot["FRONTEND_HOST"]):
            validate_remote_token_transport(snapshot)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    child_env = os.environ.copy()
    child_env.update(snapshot)
    _exec_validated_startup(command, child_env)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
