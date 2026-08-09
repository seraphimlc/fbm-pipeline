"""Isolated smoke test for the restart-only local SQLite database mode."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="fbm-sqlite-mode-") as raw_dir:
        database_path = Path(raw_dir) / "fbm-pipeline.db"
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["SQLITE_DATABASE_PATH"] = str(database_path)
        # The SQLite mode must not need a usable remote MySQL connection.
        os.environ.pop("DATABASE_URL", None)
        sys.path.insert(0, str(BACKEND_DIR))

        from app.config import settings
        from app.database import Base, engine, init_db

        assert settings.is_sqlite
        assert settings.effective_database_url == f"sqlite+aiosqlite:///{database_path}"
        assert settings.PIPELINE_MAX_CONCURRENCY == 1
        assert settings.APLUS_CONCURRENCY == 1

        await init_db()
        await init_db()  # The local schema initialization is repeatable.

        async with engine.connect() as connection:
            foreign_keys = await connection.exec_driver_sql("PRAGMA foreign_keys")
            table_names = await connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
            assert foreign_keys.scalar_one() == 1
            assert set(Base.metadata.tables).issubset({row[0] for row in table_names})

        await engine.dispose()
        assert database_path.is_file()

        # A real FastAPI lifespan must also work with an empty local database.
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200, response.text
            config_response = client.get("/api/config")
            assert config_response.status_code == 200, config_response.text
            assert config_response.json()["database_backend"] == "sqlite"
            assert config_response.json()["sqlite_database_path"] == str(database_path)

    print("sqlite database mode smoke test passed")


if __name__ == "__main__":
    asyncio.run(main())
