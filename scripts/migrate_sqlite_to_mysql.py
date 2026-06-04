#!/usr/bin/env python3
"""Migrate the local SQLite database into a MySQL database.

The script is intentionally conservative:
- It creates the target database if needed.
- It refuses to write into non-empty target tables unless --replace is passed.
- It never modifies the source SQLite database.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine, inspect, text
from sqlalchemy import Text as SAText

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base  # noqa: E402
from app.models import *  # noqa: F401,F403,E402


DEFAULT_SQLITE = REPO_ROOT / "data" / "fbm.db"
DEFAULT_MYSQL_URL = "mysql+pymysql://root@127.0.0.1:3306/fbm_pipeline?charset=utf8mb4"


def _mysql_server_url(database_url: str) -> tuple[str, str]:
    parsed = urlsplit(database_url)
    database = parsed.path.lstrip("/")
    if not database:
        raise SystemExit("MySQL URL must include a database name")
    return urlunsplit((parsed.scheme, parsed.netloc, "", parsed.query, parsed.fragment)), database


def _ensure_charset(database_url: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("charset", "utf8mb4")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _target_has_data(engine, table_names: list[str]) -> list[tuple[str, int]]:
    non_empty: list[tuple[str, int]] = []
    with engine.connect() as conn:
        existing = set(inspect(conn).get_table_names())
        for table_name in table_names:
            if table_name not in existing:
                continue
            count = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar_one()
            if count:
                non_empty.append((table_name, int(count)))
    return non_empty


def _row_count(engine, table_name: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`")).scalar_one())


def _ensure_mysql_longtext_columns(engine) -> None:
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            for column in table.columns:
                if isinstance(column.type, SAText):
                    nullable = "NULL" if column.nullable else "NOT NULL"
                    conn.execute(text(
                        f"ALTER TABLE `{table.name}` MODIFY COLUMN `{column.name}` LONGTEXT {nullable}"
                    ))


def migrate(sqlite_path: Path, mysql_url: str, *, replace: bool = False) -> None:
    sqlite_path = sqlite_path.expanduser().resolve()
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    mysql_url = _ensure_charset(mysql_url)
    server_url, database = _mysql_server_url(mysql_url)
    server_engine = create_engine(server_url, future=True)
    with server_engine.begin() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
    server_engine.dispose()

    source_engine = create_engine(f"sqlite:///{sqlite_path}", future=True)
    target_engine = create_engine(mysql_url, future=True)
    tables = list(Base.metadata.sorted_tables)
    table_names = [table.name for table in tables]

    Base.metadata.create_all(target_engine)
    _ensure_mysql_longtext_columns(target_engine)

    non_empty = _target_has_data(target_engine, table_names)
    if non_empty and not replace:
        preview = ", ".join(f"{name}={count}" for name, count in non_empty[:10])
        raise SystemExit(
            "Target MySQL tables are not empty; refusing to continue. "
            f"Use --replace to clear them first. Non-empty: {preview}"
        )

    with target_engine.begin() as target:
        target.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        if replace:
            for table in reversed(tables):
                target.execute(text(f"DELETE FROM `{table.name}`"))
                target.execute(text(f"ALTER TABLE `{table.name}` AUTO_INCREMENT = 1"))

        with source_engine.connect() as source:
            for table in tables:
                rows = source.execute(table.select().order_by(table.c.id if "id" in table.c else text("1"))).mappings().all()
                if rows:
                    target.execute(table.insert(), [dict(row) for row in rows])
                print(f"{table.name}: {len(rows)}")

        target.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    mismatches: list[str] = []
    for table in tables:
        source_count = _row_count(source_engine, table.name)
        target_count = _row_count(target_engine, table.name)
        if source_count != target_count:
            mismatches.append(f"{table.name}: sqlite={source_count}, mysql={target_count}")

    source_engine.dispose()
    target_engine.dispose()
    if mismatches:
        raise SystemExit("Migration finished with count mismatches:\n" + "\n".join(mismatches))
    print("Migration finished successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate fbm-pipeline SQLite data to MySQL.")
    parser.add_argument("--sqlite", default=os.environ.get("SQLITE_PATH", str(DEFAULT_SQLITE)))
    parser.add_argument("--mysql-url", default=os.environ.get("MYSQL_URL", DEFAULT_MYSQL_URL))
    parser.add_argument("--replace", action="store_true", help="Truncate target tables before copying.")
    args = parser.parse_args()
    migrate(Path(args.sqlite), args.mysql_url, replace=args.replace)


if __name__ == "__main__":
    main()
