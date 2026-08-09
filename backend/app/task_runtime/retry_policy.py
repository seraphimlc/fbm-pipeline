"""Conservative classification for scheduler-owned automatic retries."""

from __future__ import annotations

import re


_TRANSIENT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:api)?timeout(?:error)?\b",
        r"\btimed out\b",
        r"\b(?:api)?connectionerror\b",
        r"\bremoteprotocolerror\b",
        r"\bconnection (?:reset|aborted|refused|error)\b",
        r"\b(?:tcp)?transport\s+closed(?:\s|=)",
        r"\btcptransport\s+closed(?:\s|=)",
        r"\bhandler is closed\b",
        r"\bconnection\s+closed\b",
        r"\bserver disconnected\b",
        r"\btemporarily unavailable\b",
        r"\b(?:rate limit|http 429|too many requests)\b",
        r"\bhttp 5\d\d\b",
        # The OpenAI-compatible client formats an upstream 5xx as
        # ``InternalServerError: Error code: 502 ... upstream_error`` rather
        # than ``HTTP 502``.  This is still an infrastructure failure and is
        # safe to retry within the step's existing attempt budget.
        r"\berror code:\s*5\d\d\b",
        r"\bupstream(?:_|\s)error\b",
        r"\bupstream request failed\b",
        r"\b(?:dns|network)\b",
        r"\blost connection to mysql\b",
    )
)


def is_transient_task_error(error: BaseException | str | None) -> bool:
    """Return true only for infrastructure errors safe to retry within max_attempts."""
    text = " ".join(str(error or "").split())
    return bool(text) and any(pattern.search(text) for pattern in _TRANSIENT_PATTERNS)
