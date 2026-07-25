from __future__ import annotations

import hashlib
import json
from typing import Any


class ContractError(ValueError):
    """Raised when integration-hardening input violates its contract."""


MAX_CANONICAL_NESTING_DEPTH = 64


def _validate_canonical_value(
    value: Any,
    *,
    path: str,
    active_containers: set[int],
    nesting_depth: int,
) -> None:
    if value is None or type(value) in (bool, int):
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ContractError(f"{path}: string contains a Unicode surrogate") from exc
        return
    if type(value) is list:
        if nesting_depth >= MAX_CANONICAL_NESTING_DEPTH:
            raise ContractError(
                f"{path}: canonical JSON nesting depth exceeds {MAX_CANONICAL_NESTING_DEPTH}"
            )
        identity = id(value)
        if identity in active_containers:
            raise ContractError(f"{path}: cyclic arrays are not supported")
        active_containers.add(identity)
        try:
            for index, item in enumerate(value):
                _validate_canonical_value(
                    item,
                    path=f"{path}[{index}]",
                    active_containers=active_containers,
                    nesting_depth=nesting_depth + 1,
                )
        finally:
            active_containers.remove(identity)
        return
    if type(value) is dict:
        if nesting_depth >= MAX_CANONICAL_NESTING_DEPTH:
            raise ContractError(
                f"{path}: canonical JSON nesting depth exceeds {MAX_CANONICAL_NESTING_DEPTH}"
            )
        identity = id(value)
        if identity in active_containers:
            raise ContractError(f"{path}: cyclic objects are not supported")
        active_containers.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ContractError(f"{path}: object keys must be strings")
                _validate_canonical_value(
                    key,
                    path=f"{path}.<key>",
                    active_containers=active_containers,
                    nesting_depth=nesting_depth + 1,
                )
                _validate_canonical_value(
                    item,
                    path=f"{path}.{key}",
                    active_containers=active_containers,
                    nesting_depth=nesting_depth + 1,
                )
        finally:
            active_containers.remove(identity)
        return
    if isinstance(value, float):
        raise ContractError(f"{path}: floats and non-finite numbers are not supported")
    raise ContractError(f"{path}: unsupported JSON value type {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic compact UTF-8 JSON without altering Unicode strings."""

    _validate_canonical_value(
        value,
        path="$",
        active_containers=set(),
        nesting_depth=0,
    )
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return text.encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ContractError(f"cannot encode canonical JSON: {exc}") from exc


def canonical_sha256_hex(value: Any) -> str:
    """Return the lowercase SHA-256 digest of canonical JSON bytes."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
