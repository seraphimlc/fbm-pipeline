#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PIPELINE_DIR = ROOT / "backend" / "app" / "pipeline"
DEFAULT_MAPPING_DIR = DEFAULT_PIPELINE_DIR / "template_mappings"


@dataclass
class Finding:
    level: str
    file: str
    message: str


def split_category_path(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"\s*>\s*|\s*›\s*", str(value)) if part.strip()]


def category_option_key(categories: list[str], leaf_category: str | None) -> str:
    return " > ".join(categories) or (leaf_category or "")


def resolve_template_path(template_path: str | Path, pipeline_dir: Path) -> Path:
    path = Path(template_path).expanduser()
    if path.is_absolute():
        return path
    return (pipeline_dir / path).resolve()


def option_to_category_record(item: dict[str, Any], source: str) -> dict[str, Any] | None:
    path = str(item.get("path") or "").strip()
    node = str(item.get("node") or "").strip()
    categories = split_category_path(path)
    if not categories:
        return None
    leaf = f"{categories[-1]} ({node})" if node else categories[-1]
    option_categories = [*categories[:-1], leaf]
    key = category_option_key(option_categories, leaf)
    return {
        "key": key,
        "label": " > ".join(option_categories),
        "categories": option_categories,
        "leaf_category": leaf,
        "source": source,
        "raw": item,
    }


def merge_category_options(mapping_sources: list[tuple[str, dict[str, Any]]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    merged: dict[str, dict[str, Any]] = {}
    overrides: list[dict[str, str]] = []

    for source, mapping in mapping_sources:
        for item in mapping.get("browse_category_options") or []:
            if not isinstance(item, dict):
                continue
            record = option_to_category_record(item, source)
            if not record:
                continue
            previous = merged.get(record["key"])
            if previous:
                overrides.append({
                    "key": record["key"],
                    "from": previous["source"],
                    "to": source,
                })
            merged[record["key"]] = record

    return merged, overrides


def load_mapping(path: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except Exception as exc:
        return None, [Finding("ERROR", str(path), f"JSON 读取失败: {type(exc).__name__}: {exc}")]


def validate_mapping(path: Path, mapping: dict[str, Any], pipeline_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)

    required_types = {
        "template_path": str,
        "output_filename": str,
        "data_row": int,
        "fixed_values": dict,
        "dynamic_fields": dict,
    }
    for key, expected_type in required_types.items():
        if key not in mapping:
            findings.append(Finding("ERROR", rel, f"缺少必填字段 `{key}`"))
            continue
        if not isinstance(mapping[key], expected_type):
            findings.append(Finding("ERROR", rel, f"`{key}` 类型应为 {expected_type.__name__}"))

    template_path = mapping.get("template_path")
    if isinstance(template_path, str):
        resolved = resolve_template_path(template_path, pipeline_dir)
        if not resolved.is_file():
            findings.append(Finding("ERROR", rel, f"`template_path` 指向的模板不存在: {resolved}"))
        elif resolved.suffix.lower() != ".xlsm":
            findings.append(Finding("WARN", rel, f"`template_path` 不是 .xlsm 文件: {resolved.name}"))

    if isinstance(mapping.get("data_row"), int) and mapping["data_row"] <= 0:
        findings.append(Finding("ERROR", rel, "`data_row` 必须是正整数"))

    for optional_dict in ("image_fields", "package_fields", "shipping_template_by_brand"):
        if optional_dict in mapping and not isinstance(mapping[optional_dict], dict):
            findings.append(Finding("ERROR", rel, f"`{optional_dict}` 类型应为 dict"))

    if "bullet_fields" in mapping and not isinstance(mapping["bullet_fields"], list):
        findings.append(Finding("ERROR", rel, "`bullet_fields` 类型应为 list"))

    if "required_fields" in mapping and not isinstance(mapping["required_fields"], list):
        findings.append(Finding("ERROR", rel, "`required_fields` 类型应为 list"))

    options = mapping.get("browse_category_options")
    if options is not None and not isinstance(options, list):
        findings.append(Finding("ERROR", rel, "`browse_category_options` 类型应为 list"))
    elif isinstance(options, list):
        seen_in_file: dict[str, int] = {}
        for index, item in enumerate(options, start=1):
            if not isinstance(item, dict):
                findings.append(Finding("ERROR", rel, f"`browse_category_options[{index}]` 类型应为 dict"))
                continue
            record = option_to_category_record(item, path.stem)
            if not record:
                findings.append(Finding("ERROR", rel, f"`browse_category_options[{index}]` 缺少有效 path"))
                continue
            previous_index = seen_in_file.get(record["key"])
            if previous_index:
                findings.append(Finding("WARN", rel, f"文件内重复类目 key，第 {previous_index} 项会被第 {index} 项覆盖: {record['key']}"))
            seen_in_file[record["key"]] = index

    fixed_values = mapping.get("fixed_values")
    if isinstance(fixed_values, dict):
        if "::record_action" not in fixed_values:
            findings.append(Finding("WARN", rel, "`fixed_values` 未设置 `::record_action`"))
        if not any(str(key).startswith("product_type") for key in fixed_values):
            findings.append(Finding("WARN", rel, "`fixed_values` 未设置 product_type"))

    dynamic_fields = mapping.get("dynamic_fields")
    if isinstance(dynamic_fields, dict):
        for key in ("sku", "title", "brand", "price", "shipping_template"):
            if key not in dynamic_fields:
                findings.append(Finding("WARN", rel, f"`dynamic_fields` 未设置常用字段 `{key}`"))

    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Amazon template mapping JSON files.")
    parser.add_argument("--mapping-dir", type=Path, default=DEFAULT_MAPPING_DIR)
    parser.add_argument("--pipeline-dir", type=Path, default=DEFAULT_PIPELINE_DIR)
    parser.add_argument("--quiet", action="store_true", help="Only print errors and warnings.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapping_dir = args.mapping_dir.resolve()
    pipeline_dir = args.pipeline_dir.resolve()

    if not mapping_dir.is_dir():
        print(f"ERROR: mapping directory does not exist: {mapping_dir}", file=sys.stderr)
        return 2

    mapping_paths = sorted(mapping_dir.glob("*.json"))
    if not mapping_paths:
        print(f"ERROR: no mapping JSON files found in {mapping_dir}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    mapping_sources: list[tuple[str, dict[str, Any]]] = []

    for path in mapping_paths:
        mapping, load_findings = load_mapping(path)
        findings.extend(load_findings)
        if mapping is None:
            continue
        mapping_sources.append((path.stem, mapping))
        findings.extend(validate_mapping(path, mapping, pipeline_dir))

    merged_options, overrides = merge_category_options(mapping_sources)
    error_count = sum(1 for finding in findings if finding.level == "ERROR")
    warn_count = sum(1 for finding in findings if finding.level == "WARN")

    if not args.quiet:
        print("FBM template mapping validation")
        print(f"- mapping files: {len(mapping_paths)}")
        print(f"- category options: {len(merged_options)}")
        print(f"- override events: {len(overrides)}")
        for event in overrides:
            print(f"  override: {event['key']} | {event['from']} -> {event['to']}")

    for finding in findings:
        print(f"{finding.level}: {finding.file}: {finding.message}")

    if error_count:
        print(f"FAILED: {error_count} error(s), {warn_count} warning(s)")
        return 1

    print(f"OK: {len(mapping_paths)} mapping file(s), {warn_count} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
