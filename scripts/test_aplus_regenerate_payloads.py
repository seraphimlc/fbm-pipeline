"""A+ regeneration on an isolated cutover DB; no provider calls or real assets."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import AsyncMock, patch

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from testing.r1_sqlite_bootstrap import ensure_sqlite_test_process

if __name__ == "__main__":
    ensure_sqlite_test_process(__file__)

sys.path.insert(0, str(ROOT / "backend"))
from app.database import Base, engine, async_session
from app.models import Product, ProductData, ProductAplus
from app.api import products as api
from app.api.schemas import AplusRegenerateRequest
from app.pipeline import step8_aplus_script as step8, step9_aplus_image as step9
from app.services.product_payloads import hydrate_product_sections, load_section, write_section
from app.services.aplus_regenerate import _set_module_regen_metadata, _set_product_regen_status
from testing.r1_sqlite import require_isolated_sqlite


async def main() -> None:
    database = require_isolated_sqlite()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO schema_migrations VALUES ('product_large_fields_v1')"))

    images = [{"position": n, "status": "done", "url": f"old-{n}"} for n in range(1, 6)]
    scripts = {"scripts": [{"module_position": n} for n in range(1, 6)]}
    async with async_session() as db:
        product = Product(gigab2b_url="https://fixture.invalid/regeneration", status="pending_review")
        product.data = ProductData(title="Fixture cabinet", material_dir=str(database.parent / "assets"))
        product.aplus = ProductAplus(aplus_status="done", aplus_image_count=5)
        db.add(product)
        await db.flush()
        product_id = product.id
        for section, payload in (("aplus_plan", {"modules": []}), ("aplus_script", scripts), ("aplus_assets", images)):
            await write_section(db, product_id=product_id, section=section, payload=payload)
        await db.commit()

    # Both API validations must reach queue operations with NULL legacy columns.
    with patch.object(api, "create_regenerate_task", AsyncMock(return_value=SimpleNamespace(id=123, status="queued"))) as enqueue:
        async with async_session() as db:
            result = await api.regenerate_aplus_module(product_id, AplusRegenerateRequest(module_position=2, reason="Fix proportions"), db)
        assert result["task_id"] == 123
        enqueue.assert_awaited_once_with(product_id, 2, "Fix proportions")
    with patch.object(api, "retry_latest_regenerate_tasks", AsyncMock(return_value=[SimpleNamespace(id=124, module_position=2)])) as retry:
        async with async_session() as db:
            result = await api.retry_aplus_regenerate_tasks(product_id, db)
        assert result["task_ids"] == [124]
        retry.assert_awaited_once_with(product_id)

    # Stop before paid LLM calls, after checking each entry restored its inputs.
    class InputsLoaded(Exception):
        pass

    async def check_inputs(db, product, sections):
        await hydrate_product_sections(db, product, sections)
        assert json.loads(product.aplus.aplus_scripts) == scripts
        assert json.loads(product.aplus.aplus_plan) == {"modules": []}
        assert {"source", "listing", "image_analysis", "image_selection"} <= set(sections)
        raise InputsLoaded

    for operation, args in (
        (step8.diagnose_aplus_regeneration_feedback, (product_id, 2, "Fix proportions")),
        (step8.regenerate_aplus_module_script, (product_id, 2, "Fix proportions")),
    ):
        with patch.object(step8, "hydrate_product_sections", check_inputs):
            try:
                await operation(*args)
            except InputsLoaded:
                pass
            else:
                raise AssertionError(f"{operation.__name__} did not restore canonical inputs")

    # Exercise the image replacement and real repository write: preserve peers.
    replacement = {"position": 2, "status": "done", "url": "new-2"}
    with patch.object(step9, "_generate_single_image", AsyncMock(return_value=replacement)):
        await step9.regenerate_aplus_module_image(product_id, 2)
    async with async_session() as db:
        record = await load_section(db, product_id, "aplus_assets")
        saved = json.loads(record.payload_json)
        assert len(saved) == 5
        assert saved[1]["url"] == "new-2"
        assert [item for item in saved if item["position"] != 2] == [item for item in images if item["position"] != 2]
        aplus = await db.get(ProductAplus, 1)
        assert aplus.aplus_image_count == 5
        assert aplus.aplus_scripts is None and aplus.aplus_images is None
        saved[1]["status"] = "failed"
        await write_section(db, product_id=product_id, section="aplus_assets", payload=saved)
        await db.commit()
    await _set_product_regen_status(product_id, "done")
    async with async_session() as db:
        aplus = await db.get(ProductAplus, 1)
        assert aplus.aplus_status == "regen_failed", "one successful module must not hide another failed module"
    async with async_session() as db:
        await write_section(db, product_id=product_id, section="aplus_assets", payload=[])
        await db.commit()
    for state, expected in (("queued", "queued"), ("image_running", "running"), ("failed", "failed")):
        await _set_module_regen_metadata(product_id, 2, state)
        async with async_session() as db:
            record = await load_section(db, product_id, "aplus_assets")
            saved = json.loads(record.payload_json)
            assert len(saved) == 1 and saved[0]["position"] == 2
            assert saved[0]["regeneration_status"] == expected
    await engine.dispose()
    print("PASS: regeneration/retry APIs, diagnosis/script inputs, and five-image preservation")


if __name__ == "__main__":
    asyncio.run(main())
