#!/usr/bin/env python3
"""素材包下载方式开关回归检查，不访问浏览器或大建网络。"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.pipeline import step1_collect  # noqa: E402


async def main() -> None:
    original_mode = step1_collect.settings.STEP1_MATERIAL_DOWNLOAD_MODE
    original_browser = step1_collect._download_material_zips_via_chrome
    original_api = step1_collect._download_material_zips_via_api
    calls: list[str] = []

    async def browser_ok(save_dir, item_code, product_url, *, required_options=None, download_all=False):
        calls.append("browser")
        return [{"path": "browser.zip"}]

    async def browser_failed(save_dir, item_code, product_url, *, required_options=None, download_all=False):
        calls.append("browser")
        raise RuntimeError("browser failed")

    async def api_ok(save_dir, data, cookie):
        calls.append("api")
        return [{"path": "api.zip"}]

    try:
        step1_collect._download_material_zips_via_chrome = browser_ok
        step1_collect._download_material_zips_via_api = api_ok
        step1_collect.settings.STEP1_MATERIAL_DOWNLOAD_MODE = "browser"
        result = await step1_collect._download_material_zips(
            Path("/tmp/material-test"),
            {"itemCode": "SKU-1"},
            "cookie",
            "https://www.gigab2b.com/product/1",
        )
        assert calls == ["browser"]
        assert result == [{"path": "browser.zip"}]

        calls.clear()
        step1_collect._download_material_zips_via_chrome = browser_failed
        result = await step1_collect._download_material_zips(
            Path("/tmp/material-test"),
            {"itemCode": "SKU-1"},
            "cookie",
            "https://www.gigab2b.com/product/1",
        )
        assert calls == ["browser", "api"]
        assert result == [{"path": "api.zip"}]

        calls.clear()
        step1_collect._download_material_zips_via_chrome = browser_ok
        step1_collect.settings.STEP1_MATERIAL_DOWNLOAD_MODE = "api"
        result = await step1_collect._download_material_zips(
            Path("/tmp/material-test"),
            {"itemCode": "SKU-1"},
            "cookie",
            "https://www.gigab2b.com/product/1",
        )
        assert calls == ["api"]
        assert result == [{"path": "api.zip"}]
    finally:
        step1_collect.settings.STEP1_MATERIAL_DOWNLOAD_MODE = original_mode
        step1_collect._download_material_zips_via_chrome = original_browser
        step1_collect._download_material_zips_via_api = original_api

    original_navigate = step1_collect.chrome_navigate
    original_existing = step1_collect._existing_download_zips
    original_click = step1_collect._click_download_button
    original_options = step1_collect._get_download_options
    original_wait = step1_collect._wait_for_browser_zips
    original_store = step1_collect._store_and_extract_zips
    waited: list[str | None] = []

    async def navigate_ok(url, wait=0):
        return True

    async def click_ok():
        return True

    async def no_menu_options():
        return []

    async def wait_for_direct_download(existing, item_code, since_ts):
        waited.append(item_code)
        return [Path("/tmp/SKU_image+file.zip"), Path("/tmp/SKU_information.zip")]

    def store_direct_downloads(paths, save_dir, explicit_types=None):
        assert [path.name for path in paths] == ["SKU_image+file.zip", "SKU_information.zip"]
        return [
            {"path": str(paths[0]), "type": "to_b"},
            {"path": str(paths[1]), "type": "information"},
        ]

    try:
        step1_collect.chrome_navigate = navigate_ok
        step1_collect._existing_download_zips = lambda: set()
        step1_collect._click_download_button = click_ok
        step1_collect._get_download_options = no_menu_options
        step1_collect._wait_for_browser_zips = wait_for_direct_download
        step1_collect._store_and_extract_zips = store_direct_downloads
        with tempfile.TemporaryDirectory() as tmp:
            direct_results = await step1_collect._download_material_zips_via_chrome(
                Path(tmp),
                "SKU-1",
                "https://www.gigab2b.com/product/1",
                required_options={"To B素材包", "Information"},
                download_all=True,
            )
        assert waited == ["SKU-1"]
        assert {item["type"] for item in direct_results} == {"to_b", "information"}
    finally:
        step1_collect.chrome_navigate = original_navigate
        step1_collect._existing_download_zips = original_existing
        step1_collect._click_download_button = original_click
        step1_collect._get_download_options = original_options
        step1_collect._wait_for_browser_zips = original_wait
        step1_collect._store_and_extract_zips = original_store

    print("Step 1 material download mode checks passed")


if __name__ == "__main__":
    asyncio.run(main())
