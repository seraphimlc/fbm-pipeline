from __future__ import annotations

from typing import Any


def build_initial_fill(mapping: dict[str, Any]) -> dict[str, Any]:
    return dict(mapping.get("fixed_values", {}))

