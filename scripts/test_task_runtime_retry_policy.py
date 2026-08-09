from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.task_runtime.retry_policy import is_transient_task_error  # noqa: E402


def main() -> None:
    for value in (
        "APITimeoutError: request timed out",
        "RemoteProtocolError: Server disconnected without sending a response",
        "RuntimeError: unable to perform operation on <TCPTransport closed=True reading=False>; the handler is closed",
        "HTTP 429 rate limit exceeded",
        "InternalServerError: Error code: 502 - {'error': {'message': 'Upstream request failed', 'type': 'upstream_error'}}",
        "OperationalError: Lost connection to MySQL server during query",
    ):
        assert is_transient_task_error(value), value
    for value in (
        "AutoImageSelectionError: VLM 自动选图低置信度，需人工纠偏",
        "adapter_not_configured",
        "CompetitorVisualMatchError: 视觉初筛 Top 候选不足: 0",
    ):
        assert not is_transient_task_error(value), value


if __name__ == "__main__":
    main()
