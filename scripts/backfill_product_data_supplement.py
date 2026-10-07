#!/usr/bin/env python3
"""Explicitly authorized enrichment of active products, with a recoverable backup."""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def main(args):
    if not args.apply:
        raise SystemExit("Pass --apply to persist supplement results")
    args.output.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{args.database.resolve()}?mode=ro", uri=True)
    backup = args.output / "before-backfill.db"
    if not backup.exists():
        with sqlite3.connect(backup) as target:
            source.backup(target)
    ids = [r[0] for r in source.execute("select p.id from products p where not exists(select 1 from product_blacklist b where b.product_id=p.id) order by p.id")]
    source.close()
    os.environ.update(DATABASE_BACKEND="sqlite", SQLITE_DATABASE_PATH=str(args.database.resolve()))
    from app.services.product_data_supplement import run_data_supplement
    semaphore = asyncio.Semaphore(args.concurrency)
    records = []
    async def one(pid):
        async with semaphore:
            try:
                report = await run_data_supplement(pid, use_ai=not args.rules_only)
                result = {"product_id": pid, "status": report["status"], "model_calls": report["model_calls"],
                          "blocking_fields": report["blocking_fields"], "error": report["error"]}
            except Exception as exc:
                result = {"product_id": pid, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
            records.append(result)
            (args.output / "progress.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
            print(json.dumps({"finished": len(records), "total": len(ids), **result}, ensure_ascii=False), flush=True)
    await asyncio.gather(*(one(pid) for pid in ids))
    summary = {"total": len(ids), "completed": sum(r["status"] == "completed" for r in records),
               "failed": sum(r["status"] != "completed" for r in records), "records": records}
    (args.output / "backfill-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/fbm-pipeline.db")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument("--concurrency", type=int, default=2)
    asyncio.run(main(parser.parse_args()))
