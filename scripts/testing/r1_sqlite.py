"""Isolated on-disk SQLite environment shared by backend and browser tests."""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True)
class R1SqliteEnvironment:
    database_name: str
    database_url: str
    data_dir: Path
    session_factory: async_sessionmaker[AsyncSession]

    async def reset_schema(self) -> None:
        """Keep integration cases independent, including UPC allocation order."""
        from app.database import Base, engine

        if str(require_isolated_sqlite()) != self.database_name or str(engine.url) != self.database_url:
            raise RuntimeError("refusing to reset a non-test database")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        # IDs restart at one; cached files must not impersonate a later case's output.
        for name in ("exports", "products"):
            artifact_dir = self.data_dir / name
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir)


def require_isolated_sqlite() -> Path:
    """Validate inherited test paths before importing application settings."""
    if os.environ.get("R1_SQLITE_WRAPPER_ACTIVE") != "1":
        raise RuntimeError("use scripts/testing/run_with_r1_sqlite.py -- <command>")
    data_dir = Path(os.environ["DATA_DIR"]).resolve(strict=True)
    database = Path(os.environ["SQLITE_DATABASE_PATH"]).resolve(strict=True)
    if (
        os.environ.get("DATABASE_BACKEND") != "sqlite"
        or database.parent != data_dir
        or database.name != "test.db"
        or not data_dir.name.startswith("fbm-pipeline-r1-sqlite-")
        or os.environ.get("R1_SQLITE_WRAPPER_DATABASE") != str(database)
        or os.environ.get("DATABASE_URL") != f"sqlite+aiosqlite:///{database}"
    ):
        raise RuntimeError("refusing a non-isolated SQLite test database")
    return database


@asynccontextmanager
async def isolated_r1_sqlite(repo_root: Path) -> AsyncIterator[R1SqliteEnvironment]:
    if any(name == "app" or name.startswith("app.") for name in sys.modules):
        raise RuntimeError("isolated_r1_sqlite must run before importing any app module")
    with TemporaryDirectory(prefix="fbm-pipeline-r1-sqlite-") as temporary:
        data_dir = Path(temporary).resolve()
        database = data_dir / "test.db"
        database_url = f"sqlite+aiosqlite:///{database}"
        overrides = {
            "DATABASE_BACKEND": "sqlite",
            "SQLITE_DATABASE_PATH": str(database),
            "DATABASE_URL": database_url,
            "DATA_DIR": str(data_dir),
            "PRODUCT_BASE_DIR": str(data_dir / "products"),
            "STARTUP_RUN_DB_MAINTENANCE": "false",
            "STARTUP_RUN_BACKFILLS": "false",
            "STARTUP_RECOVER_TASKS": "false",
            "STARTUP_KICK_TASK_RUNTIME": "false",
            "TASK_RUNTIME_AUTO_WAKE_ENABLED": "false",
            "AMAZON_SEARCH_PAGE_ADAPTER": "unconfigured",
            "AMAZON_SEARCH_ENABLE_REAL_BROWSER": "false",
            "AMAZON_LISTING_DETAIL_ADAPTER": "unconfigured",
            "AMAZON_LISTING_DETAIL_ENABLE_REAL_BROWSER": "false",
            "LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS": "false",
            "LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS": "false",
            "R1_SQLITE_WRAPPER_ACTIVE": "1",
            "R1_SQLITE_WRAPPER_DATABASE": str(database),
        }
        previous = {key: os.environ.get(key) for key in overrides}
        app_engine = None
        try:
            os.environ.update(overrides)
            sys.path.insert(0, str(repo_root / "backend"))
            from app.database import async_session, engine, init_db
            from app.config import settings

            app_engine = engine
            if not settings.is_sqlite or str(engine.url) != database_url:
                raise RuntimeError("application engine escaped the isolated SQLite environment")
            await init_db()
            require_isolated_sqlite()
            yield R1SqliteEnvironment(str(database), database_url, data_dir, async_session)
        finally:
            if app_engine is not None:
                await app_engine.dispose()
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
