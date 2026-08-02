#!/usr/bin/env python3
"""GIGA 素材到自动选图链路的聚焦行为回归，不访问外部网络。"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import zipfile
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
import sys
import json

from PIL import Image
from openpyxl import Workbook

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.pipeline import step1_collect  # noqa: E402
from app.pipeline import chrome_ctrl  # noqa: E402
from app.config import _load_gpt_image_external_config  # noqa: E402
from app.pipeline.customer_mindset import build_evidence_catalog  # noqa: E402
from app.models import Product, ProductData, ProductMaterialAsset  # noqa: E402
from app.pipeline.step9_aplus_image import (  # noqa: E402
    _ensure_provider_image_large_enough,
    _save_exact_size_image,
    _validate_standard_scripts,
    _write_image_metadata_sidecar,
)
from app.product_tasks.auto_image_selection import _merge_batch_results  # noqa: E402
from app.services import product_material_prepare  # noqa: E402
from app.services.product_material_prepare import write_information_material_facts  # noqa: E402
from app.services.product_pipeline_artifacts import (  # noqa: E402
    write_aplus_plan_artifacts,
    write_aplus_script_artifacts,
    write_image_selection_artifacts,
)
from app.services.product_image_vlm import build_contact_sheets, build_image_url_batches  # noqa: E402


def test_zip_type_binding_copies_without_moving_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "Downloads" / "opaque-name.zip"
        source.parent.mkdir(parents=True)
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("facts/readme.txt", "information package")

        destination = root / "product" / "原始素材"
        results = step1_collect._store_and_extract_zips(
            [source],
            destination,
            {source.resolve(): "information"},
        )

        assert source.is_file(), "Downloads 原 ZIP 必须保留"
        assert len(results) == 1
        assert results[0]["type"] == "information"
        assert results[0]["extracted_count"] == 1
        assert Path(results[0]["path"]).is_file()
        assert Path(results[0]["extracted_dir"]).joinpath("facts/readme.txt").is_file()


def test_twelve_images_make_two_contact_sheets() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        records = []
        for index in range(1, 13):
            path = root / f"source_{index:02d}.jpg"
            Image.new("RGB", (640, 480), (index * 13 % 255, index * 19 % 255, index * 29 % 255)).save(path)
            records.append({
                "image_id": f"#{index:02d}",
                "filename": path.name,
                "path": str(path),
            })

        sheets = build_contact_sheets(records, root / "contact_sheets", "SKU")
        assert len(sheets) == 2
        assert [len(sheet["image_ids"]) for sheet in sheets] == [6, 6]
        assert all(Path(sheet["sheet_path"]).is_file() for sheet in sheets)
        assert records[0]["contact_sheet_evidence"]["sheet_page"] == 1
        assert records[6]["contact_sheet_evidence"]["sheet_page"] == 2


def test_step6_direct_image_batches_are_bounded() -> None:
    records = [
        {
            "image_id": f"#{index:02d}",
            "filename": f"source_{index:02d}.jpg",
            "path": f"https://example.test/source_{index:02d}.jpg",
        }
        for index in range(1, 10)
    ]
    batches = build_image_url_batches(records, batch_size=2)
    assert [len(batch["image_ids"]) for batch in batches] == [2, 2, 2, 2, 1]
    assert [batch["sheet_page"] for batch in batches] == [1, 2, 3, 4, 5]
    assert records[8]["contact_sheet_evidence"] == {
        "sheet_path": "url_batch:05",
        "sheet_page": 5,
        "sheet_label": "#09",
        "source": "direct_image_url",
    }


def test_external_gpt_image_config_normalizes_v1_base() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.json"
        config_path.write_text(
            json.dumps({"base_url": "https://image.example.test", "api_key": "fixture-key", "model": "gpt-image-2"}),
            encoding="utf-8",
        )
        config = _load_gpt_image_external_config(config_path)
        assert config == {
            "base_url": "https://image.example.test/v1",
            "api_key": "fixture-key",
            "model": "gpt-image-2",
        }


def _selection(image_id: str, score: float) -> dict:
    return {
        "image_id": image_id,
        "path": f"/tmp/{image_id[1:]}.jpg",
        "image_url": None,
        "score": score,
        "reason": "fixture",
        "risk_flags": [],
        "main_image_valid": True,
        "material_asset_id": int(image_id[1:]),
        "content_hash": f"hash-{image_id}",
    }


def test_multi_sheet_merge_has_one_decision_per_image() -> None:
    first = [_selection(f"#{index:02d}", 1 - index / 100) for index in range(1, 7)]
    second = [_selection(f"#{index:02d}", 0.9 - index / 100) for index in range(7, 13)]
    reviews = [
        {
            "image_id": f"#{index:02d}",
            "material_asset_id": index,
            "contact_sheet_evidence": {
                "sheet_path": f"/tmp/sheet_{1 if index <= 6 else 2}.jpg",
                "sheet_page": 1 if index <= 6 else 2,
                "sheet_label": f"#{index:02d}",
            },
        }
        for index in range(1, 13)
    ]
    result = _merge_batch_results(
        [
            {
                "selected_main": first[0],
                "selected_gallery": first[1:],
                "rejected": [],
                "confidence": "high",
                "warnings": [],
                "image_reviews": reviews[:6],
            },
            {
                "selected_main": second[0],
                "selected_gallery": second[1:],
                "rejected": [],
                "confidence": "high",
                "warnings": [],
                "image_reviews": reviews[6:],
            },
        ],
        [
            {"sheet_page": 1, "sheet_path": "/tmp/sheet_1.jpg", "image_ids": [f"#{index:02d}" for index in range(1, 7)]},
            {"sheet_page": 2, "sheet_path": "/tmp/sheet_2.jpg", "image_ids": [f"#{index:02d}" for index in range(7, 13)]},
        ],
        [],
        "fixture-vlm",
    )

    coverage = result["decision_coverage"]
    assert coverage == {
        "expected_count": 12,
        "reviewed_count": 12,
        "selected_main_count": 1,
        "selected_gallery_count": 8,
        "rejected_count": 3,
        "complete": True,
    }
    decisions = [result["selected_main"]["image_id"]]
    decisions.extend(item["image_id"] for item in result["selected_gallery"])
    decisions.extend(item["image_id"] for item in result["rejected"])
    assert len(decisions) == len(set(decisions)) == 12


class _FakeScalarResult:
    def scalar_one_or_none(self):
        return None


class _FakeArtifactDb:
    def __init__(self) -> None:
        self.added = []

    async def execute(self, _query):
        return _FakeScalarResult()

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


async def test_pipeline_artifacts_use_persisted_dimensions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        product = Product(id=701, source_site="US")
        product.data = ProductData(
            product_id=701,
            item_code="W5819P522963",
            title="Fixture product",
            material_dir=str(root),
            dimension_length=77.5,
            dimension_width=31.0,
            dimension_height=29.25,
            features='["fixture feature"]',
            gigab2b_raw_snapshot=json.dumps({
                "material_facts": {
                    "schema": "fbm-supplier-material-facts.v1",
                    "sources": [{
                        "asset_id": 801,
                        "filename": "Information.xlsx",
                        "asset_kind": "spreadsheet",
                        "extraction_status": "extracted",
                        "table_preview": {"rows": [["Material", "Fabric"]]},
                    }],
                }
            }),
        )
        db = _FakeArtifactDb()
        selection = {
            "image_reviews": [],
            "decision_coverage": {
                "expected_count": 1,
                "reviewed_count": 1,
                "selected_main_count": 1,
                "selected_gallery_count": 0,
                "rejected_count": 0,
                "complete": True,
            },
        }
        files = await write_image_selection_artifacts(
            db,
            product=product,
            selection=selection,
            main_path="/tmp/main.jpg",
            gallery_paths=[],
        )
        planner_input = json.loads(Path(files["aplus_planner_input_json"]).read_text(encoding="utf-8"))
        assert planner_input["product_facts"]["dimensions"] == {
            "length": 77.5,
            "width": 31.0,
            "height": 29.25,
        }
        assert planner_input["supplier_material_facts"]["sources"][0]["filename"] == "Information.xlsx"
        evidence_catalog = build_evidence_catalog(product, None)
        material_evidence = next(item for item in evidence_catalog if item["id"] == "supplier_material.information_package")
        assert "Information.xlsx" in material_evidence["excerpt"]

        plan_files = await write_aplus_plan_artifacts(
            db,
            product=product,
            plan={"publish_profile": "fixture", "modules": [{"module_position": index} for index in range(1, 6)]},
        )
        script_files = await write_aplus_script_artifacts(
            db,
            product=product,
            scripts_data={
                "publish_profile": "fixture",
                "scripts": [
                    {
                        "module_position": index,
                        "prompt": f"fixture prompt {index}",
                        "reference_images": [{"path": f"/tmp/ref-{index}.jpg"}],
                    }
                    for index in range(1, 6)
                ],
            },
        )
        assert Path(plan_files["json"]).is_file()
        assert Path(plan_files["markdown"]).is_file()
        assert Path(script_files["json"]).is_file()
        assert Path(script_files["markdown"]).is_file()
        assert len(db.added) == 9


def _image_bytes(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def test_aplus_image_count_size_and_sidecar_contract() -> None:
    valid_scripts = [
        {"module_position": index, "reference_images": [{"path": f"/tmp/ref-{index}.jpg"}]}
        for index in range(1, 6)
    ]
    assert _validate_standard_scripts(valid_scripts) == valid_scripts
    try:
        _validate_standard_scripts(valid_scripts[:4])
    except ValueError as exc:
        assert "5 个" in str(exc)
    else:
        raise AssertionError("普通 A+ 少于五个脚本必须失败")

    small_payload = {"bytes": _image_bytes((1200, 900), (32, 64, 96))}
    try:
        _ensure_provider_image_large_enough(small_payload, 1940, 1200, "fixture")
    except RuntimeError as exc:
        assert "禁止放大" in str(exc)
    else:
        raise AssertionError("低于目标尺寸的 provider 图片必须失败")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw_path = root / "aplus_01_raw.jpg"
        final_path = root / "aplus_01.jpg"
        size_info = _save_exact_size_image(
            _image_bytes((2000, 1300), (96, 64, 32)),
            raw_path,
            final_path,
            1940,
            1200,
        )
        sidecar = _write_image_metadata_sidecar(
            final_path,
            raw_path=raw_path,
            evidence={
                "status": "done",
                "model": "fixture-image-model",
                "provider": "fixture",
                "generation_prompt": "fixture prompt",
                "reference_images": ["/tmp/reference.jpg"],
                "result": size_info,
            },
        )
        payload = json.loads(Path(sidecar["metadata_path"]).read_text(encoding="utf-8"))
        assert payload["schema"] == "fbm-aplus-image-evidence.v1"
        assert payload["raw_image"]["sha256"] == sidecar["raw_sha256"]
        assert payload["final_image"]["sha256"] == sidecar["final_sha256"]
        assert payload["final_image"]["width"] == 1940
        assert payload["final_image"]["height"] == 1200


def test_information_package_facts_have_explicit_usage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workbook_path = root / "Information.xlsx"
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Specifications"
        worksheet.append(["Material", "Fabric"])
        worksheet.append(["Overall Width", "78 in"])
        workbook.save(workbook_path)

        video_path = root / "assembly.mp4"
        video_path.write_bytes(b"fixture-video")
        spreadsheet_asset = ProductMaterialAsset(
            id=801,
            product_id=701,
            package_type="information",
            asset_kind="spreadsheet",
            original_filename=workbook_path.name,
            path=str(workbook_path),
            relative_path=workbook_path.name,
            content_hash="spreadsheet-hash",
            processing_status="ready",
        )
        video_asset = ProductMaterialAsset(
            id=802,
            product_id=701,
            package_type="information",
            asset_kind="video",
            original_filename=video_path.name,
            path=str(video_path),
            relative_path=video_path.name,
            content_hash="video-hash",
            processing_status="ready",
        )
        output_path = root / "image analysis" / "material_facts.json"
        payload = write_information_material_facts([spreadsheet_asset, video_asset], output_path)
        assert payload["source_count"] == 2
        assert payload["sources"][0]["table_preview"]["rows"][:2] == [
            ["Material", "Fabric", "", "", "", "", "", "", "", "", "", ""],
            ["Overall Width", "78 in", "", "", "", "", "", "", "", "", "", ""],
        ]
        assert "product_fact_source" in json.loads(spreadsheet_asset.downstream_usage_json)
        assert "preview_only" in json.loads(video_asset.downstream_usage_json)
        assert output_path.is_file()


async def test_exact_search_mapping_and_detail_confirmation() -> None:
    original_workflow = product_material_prepare.chrome_workflow
    original_navigate = product_material_prepare.chrome_navigate
    original_execute = product_material_prepare.chrome_execute_js
    navigated: list[str] = []
    execute_calls = 0

    @asynccontextmanager
    async def fake_workflow(_label: str):
        yield

    async def fake_navigate(url: str, wait: float = 0) -> bool:
        navigated.append(url)
        return True

    async def fake_execute(_script: str, timeout: int = 0) -> str:
        nonlocal execute_calls
        execute_calls += 1
        if execute_calls == 1:
            return "[]"
        if execute_calls == 2:
            return '[{"product_id":"1508722","text":"Item Code: W5819P522963"}]'
        return "Product title\nItem Code: W5819P522963"

    try:
        product_material_prepare.chrome_workflow = fake_workflow
        product_material_prepare.chrome_navigate = fake_navigate
        product_material_prepare.chrome_execute_js = fake_execute
        result = await product_material_prepare.resolve_gigab2b_product_page("W5819P522963")
    finally:
        product_material_prepare.chrome_workflow = original_workflow
        product_material_prepare.chrome_navigate = original_navigate
        product_material_prepare.chrome_execute_js = original_execute

    assert result["product_id"] == "1508722"
    assert result["detail_url"].endswith("product_id=1508722")
    assert "search=W5819P522963" in navigated[0]
    assert navigated[1].endswith("product_id=1508722")
    assert execute_calls == 3


async def test_chrome_navigation_recovers_stale_worker_tab() -> None:
    original_run = chrome_ctrl._run_osascript
    original_tab_file = chrome_ctrl.FBM_TAB_ID_FILE
    calls: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tab_file = Path(tmp) / "worker-tab-id"
        tab_file.write_text("stale-tab", encoding="utf-8")

        def fake_run(script: str, timeout: int = 30) -> tuple[str, str]:
            calls.append(script)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(["osascript"], timeout)
            return "fresh-tab", ""

        try:
            chrome_ctrl._run_osascript = fake_run
            chrome_ctrl.FBM_TAB_ID_FILE = tab_file
            result = await chrome_ctrl.chrome_navigate("https://example.test/", wait=0)
        finally:
            chrome_ctrl._run_osascript = original_run
            chrome_ctrl.FBM_TAB_ID_FILE = original_tab_file

        persisted_tab_id = tab_file.read_text(encoding="utf-8")

    assert result is True
    assert len(calls) == 2
    assert 'set workerTabId to "stale-tab"' in calls[0]
    assert 'set workerTabId to ""' in calls[1]
    assert "URL of t contains" not in calls[0]
    assert "URL of t contains" not in calls[1]
    assert persisted_tab_id == "fresh-tab"


async def test_chrome_js_uses_worker_tab_id_without_url_scan() -> None:
    original_run = chrome_ctrl._run_osascript
    original_tab_file = chrome_ctrl.FBM_TAB_ID_FILE
    calls: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tab_file = Path(tmp) / "worker-tab-id"
        tab_file.write_text("worker-tab", encoding="utf-8")

        def fake_run(script: str, timeout: int = 30) -> tuple[str, str]:
            calls.append(script)
            return "ok", ""

        try:
            chrome_ctrl._run_osascript = fake_run
            chrome_ctrl.FBM_TAB_ID_FILE = tab_file
            result = await chrome_ctrl.chrome_execute_js("'ok'", timeout=1)
        finally:
            chrome_ctrl._run_osascript = original_run
            chrome_ctrl.FBM_TAB_ID_FILE = original_tab_file

    assert result == "ok"
    assert len(calls) == 1
    assert 'set workerTabId to "worker-tab"' in calls[0]
    assert "URL of t contains" not in calls[0]


async def main() -> None:
    test_zip_type_binding_copies_without_moving_source()
    test_twelve_images_make_two_contact_sheets()
    test_step6_direct_image_batches_are_bounded()
    test_external_gpt_image_config_normalizes_v1_base()
    test_multi_sheet_merge_has_one_decision_per_image()
    await test_pipeline_artifacts_use_persisted_dimensions()
    test_aplus_image_count_size_and_sidecar_contract()
    test_information_package_facts_have_explicit_usage()
    await test_exact_search_mapping_and_detail_confirmation()
    await test_chrome_navigation_recovers_stale_worker_tab()
    await test_chrome_js_uses_worker_tab_id_without_url_scan()
    print("GIGA material and Contact Sheet chain checks passed")


if __name__ == "__main__":
    asyncio.run(main())
