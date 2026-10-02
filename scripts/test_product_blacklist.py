"""Permanent blacklist integration tests; isolated SQLite, no real products."""
import asyncio
from pathlib import Path
import sys

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from testing.r1_sqlite_bootstrap import ensure_sqlite_test_process
if __name__ == "__main__":
    ensure_sqlite_test_process(__file__)
sys.path.insert(0, str(ROOT / "backend"))
from app.database import async_session, run_schema_maintenance, engine
from app.main import app
from app.models import Product, ProductBlacklist
from testing.r1_sqlite import require_isolated_sqlite


async def main():
    require_isolated_sqlite()
    await run_schema_maintenance()
    await run_schema_maintenance()  # repeatable schema setup
    async with async_session() as db:
        hidden = Product(gigab2b_url="https://fixture.invalid/hidden", upc="fixture-hidden", status="pending_review",
                         workflow_node="confirm_images_aplus", workflow_status="pending")
        visible = Product(gigab2b_url="https://fixture.invalid/visible", status="pending_review",
                          workflow_node="confirm_images_aplus", workflow_status="pending")
        db.add_all([hidden, visible])
        await db.commit()
        hidden_id, visible_id = hidden.id, visible.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        initial = await client.get("/api/products")
        assert initial.status_code == 200, initial.text
        assert initial.json()["total"] == 2
        response = await client.post(f"/api/products/{hidden_id}/blacklist")
        assert response.status_code == 200, response.text
        again = await client.post(f"/api/products/{hidden_id}/blacklist")
        assert again.status_code == 200 and again.json() == response.json()
        for params in ({}, {"work_status": "confirm_images_aplus"}, {"upc": "fixture-hidden"}):
            rows = (await client.get("/api/products", params=params)).json()
            assert all(row["id"] != hidden_id for row in rows["items"])
            assert rows["total"] == (0 if "upc" in params else 1)
        detail = await client.get(f"/api/products/{hidden_id}", params={"compact": True})
        assert detail.status_code == 200 and detail.json()["blacklisted_at"]
        overview = (await client.get("/api/products/overview")).json()
        assert overview["total_products"] == 1 and overview["confirm_images_aplus"] == 1
        deletion = await client.delete(f"/api/products/{hidden_id}")
        assert deletion.status_code == 409
        assert (await client.post("/api/products/999999/blacklist")).status_code == 404
    async with async_session() as db:
        assert await db.get(Product, hidden_id) is not None
        for statement in (
            delete(Product).where(Product.id == hidden_id),
            delete(ProductBlacklist).where(ProductBlacklist.product_id == hidden_id),
            text("UPDATE product_blacklist SET product_id=:visible WHERE product_id=:hidden").bindparams(visible=visible_id, hidden=hidden_id),
        ):
            try:
                await db.execute(statement)
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError("permanent blacklist SQL protection did not reject mutation")
        assert len((await db.execute(select(ProductBlacklist))).scalars().all()) == 1
    await engine.dispose()
    print("PASS: permanent addition, idempotency, list/count/overview exclusions, detail state, API and DB deletion protection")


if __name__ == "__main__":
    asyncio.run(main())
