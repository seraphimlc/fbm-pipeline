"""Re-exec standalone database tests under the isolated SQLite wrapper."""

import os
from pathlib import Path
import sys


def ensure_sqlite_test_process(script: str) -> None:
    from testing.r1_sqlite import require_isolated_sqlite

    if os.environ.get("R1_SQLITE_WRAPPER_ACTIVE") == "1":
        require_isolated_sqlite()
        return
    wrapper = Path(__file__).with_name("run_with_r1_sqlite.py")
    os.execv(sys.executable, [sys.executable, str(wrapper), "--", sys.executable, str(Path(script).resolve()), *sys.argv[1:]])
