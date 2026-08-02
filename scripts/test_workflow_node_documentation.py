"""Static regression checks for the workflow-node documentation contract."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIONS_PATH = ROOT / "backend" / "app" / "product_tasks" / "actions.py"

ACTION_EXPECTATIONS = {
    "ProductAutoImageSelectionAction": ("最多保存 8 张", "search_competitor/pending", "fail-closed"),
    "ProductCompetitorSearchAction": ("最多取 12 条", "最多 20 条", "Sponsored"),
    "ProductCompetitorVisualMatchAction": ("Top 4-6", "Contact Sheet", "fail closed"),
    "ProductCompetitorCandidateCaptureAction": ("1-6", "单一数据库事务", "adapter"),
    "ProductAutoCompetitorSelectionAction": ("rule_based_auto_competitor_v1", "可复现的规则评分", "competitor_asin"),
    "ProductKeywordResearchAction": ("run_keywords", "0.685", "leaf_category"),
    "ProductImageAnalysisAction": ("商品自己的", "fingerprint", "product_customer_mindset"),
    "ProductCustomerMindsetAction": ("固定 13", "2 至 5", "15 至 18"),
    "ProductListingGenerationAction": ("最大 75", "最大 500", "最多 20", "最大 250", "最大输出 2000"),
}


def _class_docstrings(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name: ast.get_docstring(node, clean=False) or ""
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }


def main() -> None:
    docstrings = _class_docstrings(ACTIONS_PATH)
    for class_name, required_fragments in ACTION_EXPECTATIONS.items():
        docstring = docstrings.get(class_name, "")
        assert docstring, f"{class_name} must have a node-level docstring"
        normalized_docstring = re.sub(r"\s+", " ", docstring)
        for fragment in required_fragments:
            assert fragment in normalized_docstring, f"{class_name} docstring is missing: {fragment}"

    step7 = (ROOT / "backend" / "app" / "pipeline" / "step7_aplus_plan.py").read_text(encoding="utf-8")
    step8 = (ROOT / "backend" / "app" / "pipeline" / "step8_aplus_script.py").read_text(encoding="utf-8")
    step9 = (ROOT / "backend" / "app" / "pipeline" / "step9_aplus_image.py").read_text(encoding="utf-8")
    assert "恰好 5 个宽横幅脚本" in step8 and "reference_images" in step8
    assert "1940x1200" in step8 and "100-300" in step8 and "1-3" in step8
    assert "商品叙事诊断" in step7 and "standard_header_image_text_v1" in step7
    assert "reference_images" in step9 and "2,000,000 bytes" in step9
    assert "APLUS_CONCURRENCY" in step9 and "当前默认 1" in step9
    assert "5个并发" not in step9 and "15-30秒" not in step9

    print("workflow node documentation checks passed")


if __name__ == "__main__":
    main()
