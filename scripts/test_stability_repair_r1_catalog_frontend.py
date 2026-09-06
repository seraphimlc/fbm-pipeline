#!/usr/bin/env python3
"""R1 Batch 2b catalog-export real API browser checks on isolated SQLite."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.testing.r1_sqlite import isolated_r1_sqlite


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _process_output(process: subprocess.Popen, log_file) -> str:
    log_file.flush()
    log_file.seek(0)
    output = log_file.read()
    return f"exit={process.poll()}\n{output[-12000:]}"


def _wait_for_http(url: str, process: subprocess.Popen, log_file, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not started"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process exited before {url} became ready\n{_process_output(process, log_file)}")
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}\n{_process_output(process, log_file)}")


def _stop_process(process: subprocess.Popen | None, *, process_group: bool = False) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if process_group:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            if process_group:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)


def _malformed_catalog_response_payload(category: str) -> dict:
    return {
        "status": {"nested": "done"},
        "artifact_available": {"nested": True},
        "requested_count": {"nested": 10},
        "success_count": [1],
        "skipped_count": {"nested": 1},
        "failed_count": "8",
        "report_count": [10],
        "filename": {"nested": "unsafe.zip"},
        "reason": ["unsafe reason"],
        "categories": [{"nested": "unsafe"}, category],
        "rows": [
            None,
            7,
            {
                "catalog_id": 72001,
                "product_id": {"nested": 1},
                "item_code": {"nested": "unsafe"},
                "seller_sku": ["unsafe"],
                "category": {"nested": category},
                "status": {"nested": "exported"},
                "reason": ["unsafe"],
                "template_file": {"nested": "unsafe.xlsm"},
                "output_file": ["unsafe.xlsx"],
            },
            {"catalog_id": 72002, "status": "exported", "reason": "duplicate first"},
            {"catalog_id": 72002, "status": "skipped", "reason": "duplicate second"},
            {"catalog_id": None, "product_id": None, "status": None, "reason": None},
            {"catalog_id": None, "product_id": None, "status": None, "reason": None},
            {"item_code": "A/B", "status": "failed", "reason": "slash code"},
            {"item_code": "A B", "status": "failed", "reason": "space code"},
            {"item_code": "商品-甲", "status": "failed", "reason": "Unicode 行"},
            {"catalog_id": (2 ** 53), "status": "exported", "reason": "ok unsafe id"},
            {"catalog_id": 72003, "item_code": "\ud800", "status": "exported", "reason": "ok surrogate code"},
            {"catalog_id": 72004, "item_code": "SAFE", "status": "exported", "reason": "\ud800"},
            {
                "catalog_id": 72005,
                "item_code": {"nested": "unsafe"},
                "status": "exported",
                "reason": "ok nested field",
            },
            {"catalog_id": 72006, "item_code": "BAD-STATUS", "status": "done", "reason": "ok invalid status"},
        ],
    }


async def _seed_catalog_frontend_fixtures(environment) -> dict[str, object]:
    from app.models import OfflineTask, OfflineTaskStep, TaskGroup, TaskRun, TaskStep
    from app.services.offline_tasks import _catalog_export_result_payload

    artifact = environment.data_dir / "exports" / "r1-catalog-frontend-partial.zip"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(artifact, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("fixture.txt", "R1 catalog frontend real API download")
    artifact_bytes = artifact.read_bytes()
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    artifact_size = len(artifact_bytes)

    partial_reason = "已有真实 Amazon ASIN，保护门跳过"
    failed_reason = "缺少必填字段：item_name"
    partial_catalog_ids = [91001, 91002, 91003]
    failed_catalog_ids = [92001, 92002]
    now = datetime.now()
    partial_payload = _catalog_export_result_payload(
        category="R1 Catalog Frontend Category",
        categories=["R1 Catalog Frontend Category"],
        template_name="R1_FRONTEND.xlsm",
        template_path="/fixture/R1_FRONTEND.xlsm",
        catalog_ids=partial_catalog_ids,
        report_rows=[
            {
                "商品资料ID": partial_catalog_ids[0],
                "商品ID": 191001,
                "商品Code": "R1-FRONTEND-EXPORTED",
                "Seller SKU": "R1-SKU-EXPORTED",
                "类目": "R1 Catalog Frontend Category",
                "状态": "已导出",
                "原因": "模板校验通过并写入文件",
                "模板文件": "R1_FRONTEND.xlsm",
                "导出文件": "R1_FRONTEND.xlsx",
            },
            {
                "商品资料ID": partial_catalog_ids[1],
                "商品ID": 191002,
                "商品Code": "R1-FRONTEND-SKIPPED",
                "Seller SKU": "R1-SKU-SKIPPED",
                "类目": "R1 Catalog Frontend Category",
                "状态": "已跳过",
                "原因": partial_reason,
                "模板文件": "R1_FRONTEND.xlsm",
                "导出文件": None,
            },
            {
                "商品资料ID": partial_catalog_ids[2],
                "商品ID": 191003,
                "商品Code": "R1-FRONTEND-FAILED",
                "Seller SKU": "R1-SKU-FAILED",
                "类目": "R1 Catalog Frontend Category",
                "状态": "失败",
                "原因": "模板字段校验失败：brand_name",
                "模板文件": "R1_FRONTEND.xlsm",
                "导出文件": None,
            },
        ],
        created_at=now,
        filename=artifact.name,
        file_path=str(artifact),
        file_size=artifact_size,
    )
    failed_payload = _catalog_export_result_payload(
        category="R1 Catalog Frontend Failed Category",
        categories=["R1 Catalog Frontend Failed Category"],
        template_name="R1_FRONTEND_FAILED.xlsm",
        template_path="/fixture/R1_FRONTEND_FAILED.xlsm",
        catalog_ids=failed_catalog_ids,
        report_rows=[
            {
                "商品资料ID": failed_catalog_ids[0],
                "商品ID": 192001,
                "商品Code": "R1-FRONTEND-HARD-FAILED",
                "Seller SKU": None,
                "类目": "R1 Catalog Frontend Failed Category",
                "状态": "失败",
                "原因": failed_reason,
                "模板文件": "R1_FRONTEND_FAILED.xlsm",
                "导出文件": None,
            },
            {
                "商品资料ID": failed_catalog_ids[1],
                "商品ID": 192002,
                "商品Code": "R1-FRONTEND-HARD-FAILED-2",
                "Seller SKU": None,
                "类目": "R1 Catalog Frontend Failed Category",
                "状态": "失败",
                "原因": "模板文件不存在",
                "模板文件": None,
                "导出文件": None,
            },
        ],
        created_at=now,
    )
    historical_missing_rows_payload = {
        "status": "failed",
        "artifact_available": False,
        "requested_count": 1,
        "success_count": 0,
        "exported_count": 0,
        "skipped_count": 0,
        "failed_count": 1,
        "report_count": 0,
        "catalog_product_ids": [93001],
        "category": "R1 Catalog Frontend Historical Category",
        "categories": ["R1 Catalog Frontend Historical Category"],
        "reason": "历史导出结果未保存逐商品明细",
    }
    malformed_payload = _malformed_catalog_response_payload("R1 Catalog Frontend Malformed Category")
    unsafe_category = "R1 Catalog Frontend Unsafe Valid Artifact Category"
    unsafe_payload = {
        "status": "done",
        "artifact_available": True,
        "requested_count": 1,
        "success_count": 1,
        "exported_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
        "report_count": 1,
        "filename": artifact.name,
        "file_path": str(artifact),
        "file_size": artifact_size,
        "category": unsafe_category,
        "categories": [unsafe_category],
        "catalog_product_ids": [2 ** 53],
        "rows": [{
            "catalog_id": 2 ** 53,
            "product_id": 194001,
            "item_code": "R1-FRONTEND-UNSAFE-ID",
            "category": unsafe_category,
            "status": "exported",
            "reason": "raw payload claims success",
        }],
    }
    legacy_category = "R1 Catalog Frontend Legacy Done Category"
    legacy_done_payload = {
        "status": "done",
        "requested_count": 1,
        "success_count": 1,
        "exported_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
        "report_count": 1,
        "filename": artifact.name,
        "file_path": str(artifact),
        "file_size": artifact_size,
        "category": legacy_category,
        "categories": [legacy_category],
        "catalog_product_ids": [94001],
        "rows": [{
            "catalog_id": 94001,
            "product_id": 194001,
            "item_code": "R1-FRONTEND-LEGACY-DONE",
            "category": legacy_category,
            "status": "exported",
            "reason": "legacy local artifact without availability flag",
        }],
    }
    if partial_payload["status"] != "partial_failed" or failed_payload["status"] != "failed":
        raise AssertionError((partial_payload, failed_payload))

    async with environment.session_factory() as db:
        fixture_rows: list[tuple[TaskRun, dict, str]] = []
        for suffix, status, payload, progress_total in (
            ("Partial", "partial_failed", partial_payload, 3),
            ("Failed", "failed", failed_payload, 2),
            ("Historical Missing Rows", "failed", historical_missing_rows_payload, 1),
            ("Malformed Response", "failed", malformed_payload, len(malformed_payload["rows"])),
            ("Unsafe Valid Artifact", "succeeded", unsafe_payload, 1),
            ("Legacy Done", "succeeded", legacy_done_payload, 1),
        ):
            raw_payload_json = json.dumps(
                payload,
                ensure_ascii=suffix == "Malformed Response",
            )
            run = TaskRun(
                task_type="catalog_export",
                title=f"R1 Catalog Frontend {suffix}",
                status=status,
                payload_json=json.dumps({"catalog_product_ids": payload.get("catalog_product_ids", [])}),
                summary_json=raw_payload_json,
                created_by="r1_catalog_frontend",
                started_at=now,
                finished_at=now,
            )
            db.add(run)
            await db.flush()
            group = TaskGroup(
                task_run_id=run.id,
                group_key="export_file",
                title=f"R1 Catalog Frontend {suffix}",
                status=status,
                progress_current=progress_total,
                progress_total=progress_total,
                summary_json=raw_payload_json,
                started_at=now,
                finished_at=now,
            )
            db.add(group)
            await db.flush()
            db.add(TaskStep(
                task_run_id=run.id,
                task_group_id=group.id,
                step_key=f"catalog_export_template_{suffix.lower().replace(' ', '_')}",
                step_type="catalog_export_template",
                status=status,
                result_json=raw_payload_json,
                progress_current=progress_total,
                progress_total=progress_total,
                attempt_count=1,
                max_attempts=1,
                started_at=now,
                finished_at=now,
            ))
            fixture_rows.append((run, payload, suffix))
        malformed_offline_task = OfflineTask(
            task_type="catalog_export",
            title="R1 Catalog Frontend Malformed OfflineTask",
            status="failed",
            total_steps=1,
            failed_steps=1,
            result_json=json.dumps({"status": "failed"}),
            created_by="r1_catalog_frontend",
            started_at=now,
            finished_at=now,
        )
        db.add(malformed_offline_task)
        await db.flush()
        db.add(OfflineTaskStep(
            task_id=malformed_offline_task.id,
            step_type="catalog_export_template",
            title="R1 Catalog Frontend Malformed OfflineTask step",
            status="failed",
            progress_current=len(malformed_payload["rows"]),
            progress_total=len(malformed_payload["rows"]),
            result_json=json.dumps(malformed_payload, ensure_ascii=True),
            started_at=now,
            finished_at=now,
        ))
        unsafe_offline_task = OfflineTask(
            task_type="catalog_export",
            title="R1 Catalog Frontend Unsafe Valid Artifact OfflineTask",
            status="done",
            total_steps=1,
            success_steps=1,
            result_json=json.dumps(unsafe_payload),
            created_by="r1_catalog_frontend",
            started_at=now,
            finished_at=now,
        )
        db.add(unsafe_offline_task)
        await db.flush()
        db.add(OfflineTaskStep(
            task_id=unsafe_offline_task.id,
            step_type="catalog_export_template",
            title="R1 Catalog Frontend Unsafe Valid Artifact OfflineTask step",
            status="done",
            progress_current=1,
            progress_total=1,
            result_json=json.dumps(unsafe_payload),
            started_at=now,
            finished_at=now,
        ))
        await db.commit()

        partial_run = fixture_rows[0][0]
        failed_run = fixture_rows[1][0]
        historical_missing_rows_run = fixture_rows[2][0]
        malformed_run = fixture_rows[3][0]
        unsafe_run = fixture_rows[4][0]
        legacy_done_run = fixture_rows[5][0]
        return {
            "partial_run_id": int(partial_run.id),
            "failed_run_id": int(failed_run.id),
            "historical_missing_rows_run_id": int(historical_missing_rows_run.id),
            "malformed_run_id": int(malformed_run.id),
            "malformed_offline_task_id": int(malformed_offline_task.id),
            "unsafe_run_id": int(unsafe_run.id),
            "unsafe_offline_task_id": int(unsafe_offline_task.id),
            "unsafe_category": unsafe_category,
            "legacy_done_run_id": int(legacy_done_run.id),
            "malformed_row_count": len(malformed_payload["rows"]),
            "partial_skipped_row_ordinal": 2,
            "failed_row_ordinal": 1,
            "partial_reason": partial_reason,
            "failed_reason": failed_reason,
            "artifact_filename": artifact.name,
            "artifact_sha256": artifact_sha256,
            "artifact_size": artifact_size,
        }


async def run() -> None:
    async with isolated_r1_sqlite(ROOT) as environment:
        backend_port = _free_loopback_port()
        frontend_port = _free_loopback_port()
        backend_url = f"http://127.0.0.1:{backend_port}"
        frontend_url = f"http://127.0.0.1:{frontend_port}"
        child_env = os.environ.copy()
        child_env.update({
            "PYTHONUNBUFFERED": "1",
            "BACKEND_PORT": str(backend_port),
            "VITE_BACKEND_URL": backend_url,
            "VITE_FRONTEND_PORT": str(frontend_port),
        })
        backend_process = None
        frontend_process = None
        with TemporaryFile(mode="w+", encoding="utf-8") as backend_log, TemporaryFile(
            mode="w+", encoding="utf-8"
        ) as frontend_log:
            try:
                backend_process = subprocess.Popen(
                    [
                        str(BACKEND / ".venv" / "bin" / "uvicorn"),
                        "app.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(backend_port),
                        "--lifespan",
                        "off",
                        "--log-level",
                        "info",
                    ],
                    cwd=BACKEND,
                    env=child_env,
                    stdout=backend_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                _wait_for_http(
                    f"{backend_url}/api/task-runs?view=all&task_type=catalog_export&page_size=1",
                    backend_process,
                    backend_log,
                    timeout=120.0,
                )
                fixture_state = await _seed_catalog_frontend_fixtures(environment)
                state_path = environment.data_dir / "catalog-frontend-state.json"
                state_path.write_text(json.dumps({
                    **fixture_state,
                    "backend_base_url": backend_url,
                    "frontend_base_url": frontend_url,
                    "output_dir": str(environment.data_dir / "playwright-output"),
                }), encoding="utf-8")
                child_env["R1_CATALOG_FRONTEND_STATE"] = str(state_path)
                frontend_process = subprocess.Popen(
                    [
                        "npm",
                        "run",
                        "dev",
                        "--",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(frontend_port),
                        "--strictPort",
                    ],
                    cwd=FRONTEND,
                    env=child_env,
                    stdout=frontend_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                _wait_for_http(f"{frontend_url}/task-runs", frontend_process, frontend_log)

                result = subprocess.run(
                    [
                        str(FRONTEND / "node_modules" / ".bin" / "playwright"),
                        "test",
                        "--config=playwright.catalog.r1.config.ts",
                    ],
                    cwd=FRONTEND,
                    env=child_env,
                    text=True,
                    capture_output=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    raise AssertionError(
                        "catalog frontend Playwright failed\n"
                        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\n"
                        f"backend:\n{_process_output(backend_process, backend_log)}\n"
                        f"frontend:\n{_process_output(frontend_process, frontend_log)}"
                    )
                print(result.stdout.strip())
                print(f"R1 catalog frontend real API checks passed: {environment.database_name}")
            finally:
                _stop_process(frontend_process, process_group=True)
                _stop_process(backend_process)


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
