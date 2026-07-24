"""Fail-closed isolated MySQL harness for FBM Pipeline R1 tests."""

from __future__ import annotations

import os
import re
import secrets
import sys
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


R1_DATABASE_PREFIX = "fbm_pipeline_r1_"
R1_DATABASE_PATTERN = re.compile(r"^fbm_pipeline_r1_[0-9]+_[a-f0-9]{8}$")


class R1MysqlNotConfigured(RuntimeError):
    """Raised when the explicit R1 admin connection is absent."""


@dataclass(frozen=True)
class R1MysqlEnvironment:
    database_name: str
    database_url: str
    data_dir: Path
    session_factory: async_sessionmaker[AsyncSession]


def _validated_admin_url() -> str:
    raw = str(os.environ.get("R1_TEST_MYSQL_ADMIN_URL") or "").strip()
    if not raw:
        raise R1MysqlNotConfigured(
            "R1_TEST_MYSQL_ADMIN_URL is required for isolated MySQL verification; "
            "the configured application DATABASE_URL is never used as a fallback"
        )
    url = make_url(raw)
    if url.drivername != "mysql+asyncmy":
        raise RuntimeError("R1_TEST_MYSQL_ADMIN_URL must use mysql+asyncmy")
    return raw


def _database_name() -> str:
    value = f"{R1_DATABASE_PREFIX}{os.getpid()}_{secrets.token_hex(4)}"
    if not R1_DATABASE_PATTERN.fullmatch(value):
        raise RuntimeError(f"refusing unsafe R1 database name: {value}")
    return value


@asynccontextmanager
async def isolated_r1_mysql(repo_root: Path) -> AsyncIterator[R1MysqlEnvironment]:
    """Create, initialize and finally drop an isolated R1 database.

    This must run before any ``app`` module import so settings, engine and paths
    cannot bind to the configured business database or data directory.
    """

    if any(name == "app" or name.startswith("app.") for name in sys.modules):
        raise RuntimeError("isolated_r1_mysql must run before importing any app module")

    admin_url_text = _validated_admin_url()
    admin_url = make_url(admin_url_text)
    database_name = _database_name()
    database_url = admin_url.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url_text, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    temporary_data = tempfile.TemporaryDirectory(prefix="fbm-pipeline-r1-")
    data_dir = Path(temporary_data.name).resolve()
    created = False
    app_engine = None
    previous_env: dict[str, str | None] = {}
    overrides = {
        "DATABASE_URL": database_url,
        "DATA_DIR": str(data_dir),
        "PRODUCT_BASE_DIR": str(data_dir / "products"),
        "STARTUP_RUN_DB_MAINTENANCE": "false",
        "STARTUP_RUN_BACKFILLS": "false",
        "STARTUP_RECOVER_TASKS": "false",
        "STARTUP_KICK_TASK_RUNTIME": "false",
        "AMAZON_SEARCH_PAGE_ADAPTER": "unconfigured",
        "AMAZON_SEARCH_ENABLE_REAL_BROWSER": "false",
        "LINGXING_LISTING_SYNC_ALLOW_REAL_EXTERNAL_CALLS": "false",
        "LINGXING_APLUS_ALLOW_REAL_EXTERNAL_CALLS": "false",
    }

    try:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            )
        created = True

        for key, value in overrides.items():
            previous_env[key] = os.environ.get(key)
            os.environ[key] = value

        backend = repo_root / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))

        from app.database import async_session, engine, init_db
        from app.config import settings

        configured_database = make_url(settings.DATABASE_URL).database
        if configured_database != database_name:
            raise RuntimeError(
                "R1 application settings database mismatch: "
                f"expected={database_name} actual={configured_database or '(none)'}"
            )

        app_engine = engine
        await init_db()
        yield R1MysqlEnvironment(
            database_name=database_name,
            database_url=database_url,
            data_dir=data_dir,
            session_factory=async_session,
        )
    finally:
        if app_engine is not None:
            await app_engine.dispose()
        for key, previous in previous_env.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        try:
            keep_database = str(os.environ.get("R1_KEEP_TEST_DB") or "").strip() == "1"
            if created and keep_database:
                print(f"R1_KEEP_TEST_DB=1 preserved isolated database: {database_name}", file=sys.stderr)
            elif created:
                if not R1_DATABASE_PATTERN.fullmatch(database_name):
                    raise RuntimeError(f"refusing to drop unsafe R1 database name: {database_name}")
                async with admin_engine.connect() as connection:
                    await connection.execute(text(f"DROP DATABASE `{database_name}`"))
        finally:
            await admin_engine.dispose()
            temporary_data.cleanup()
