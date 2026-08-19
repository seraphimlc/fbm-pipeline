#!/usr/bin/env python3
"""Focused contracts for the image-analysis -> customer-mindset boundary."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.products import _hydrate_product_detail_customer_mindset, _require_generation_prerequisites  # noqa: E402
from app.pipeline.customer_mindset import (  # noqa: E402
    ALLOWED_CONTENT_USES,
    DYNAMIC_QUESTION_MAX,
    DYNAMIC_QUESTION_MIN,
    DYNAMIC_QUESTION_FOCUSES,
    FIXED_QUESTIONS,
    SCHEMA_VERSION,
    _answer_prompt,
    _dynamic_question_prompt,
    build_evidence_catalog,
    build_mindset_input_fingerprint,
    customer_mindset_context,
    customer_mindset_matches_product,
    image_analysis_ready,
    keyword_research_ready,
    load_customer_mindset,
    normalize_dynamic_questions,
    normalize_mindset_answers,
    _write_customer_mindset_artifact,
)


def _assert_raises(message: str, callback) -> None:
    try:
        callback()
    except RuntimeError:
        return
    raise AssertionError(message)


def _product_fixture() -> SimpleNamespace:
    data = SimpleNamespace(
        title="Modular linen sofa",
        product_type="modular sofa",
        color="Green",
        material="Linen",
        filler="Foam",
        dimension_length=85.0,
        dimension_width=34.0,
        dimension_height=30.0,
        weight=120.0,
        packages=json.dumps([{"count": 3}]),
        features=json.dumps(["modular layout", "removable cushions"]),
        description="Three-piece modular sofa for living-room seating.",
        variants=json.dumps([{"color": "Green"}]),
        origin="China",
        categories=json.dumps(["Furniture", "Living Room Furniture", "Sofas"]),
        leaf_category="Sofas",
        suggested_price=699.99,
        pricing_detail=json.dumps({"margin_rate": 0.08}),
        gigab2b_raw_snapshot=json.dumps({
            "product": {"name": "Modular linen sofa"},
            "specification": {"property_infos": [{"name": "Pieces", "value": "3"}]},
        }),
        keywords_top=json.dumps(
            [
                {"keyword": "modular sofa", "search_volume": 12000},
                {"keyword": "green sectional couch", "search_volume": 3500},
            ]
        ),
        customer_mindset=None,
    )
    images = SimpleNamespace(
        main_image_path="https://images.example.test/sofa-main.jpg",
        image_analysis=json.dumps(
            {
                "images": [
                    {
                        "filename": "sofa-main.jpg",
                        "conversion_role": "product_identity",
                        "visible_selling_point": "three modular seat sections",
                        "material_texture": "woven fabric",
                        "scene_type": "white background",
                        "size_scale_cues": "three visible seat modules",
                        "visible_parts": "three bases and cushions",
                        "confidence": "high",
                        "uncertainty": ["package contents are not shown"],
                        "risk_flags": [],
                    }
                ],
                "selection_diagnostics": {
                    "missing_roles": ["dimensions", "package contents"],
                    "image_health": {"label": "needs_more_proof"},
                    "listing_image_alignment": {"missing_evidence": ["exact dimensions"]},
                },
            }
        ),
        image_selling_points=json.dumps(["modular configuration", "woven upholstery"]),
    )
    return SimpleNamespace(
        id=91001,
        brand="Vindhvisk",
        competitor_asin="B0TESTCOMP1",
        data=data,
        images=images,
    )


def _competitor_fixture() -> SimpleNamespace:
    return SimpleNamespace(
        asin="B0TESTCOMP1",
        title="Competitor modular sofa",
        price=749.99,
        rating=4.3,
        review_count=128,
        brand="CompetitorBrand",
        leaf_category="Sofas",
        description="Competitor reference content.",
        product_details_json=json.dumps({"pieces": 3}),
        final_reason="Closest visually matched modular configuration.",
        final_risks_json=json.dumps(["Competitor claims are not our product proof."]),
        bullets_json=json.dumps(["Competitor-only comfort claim"]),
    )


def _dynamic_payload(count: int) -> dict:
    questions = [
        {
            "focus": "actual_use_behavior",
            "topic": "module_connection",
            "question": "用户重新布置这款三模块沙发时，模块之间采用什么连接方式，需要哪些操作？",
            "why_asked": "商品明确为模块化布局，但当前图片没有展示连接细节，实际重排行为仍不清楚。",
            "closest_fixed_question_id": "core_04_job_to_be_done",
            "incremental_decision_gap": "补充模块重新组合时的具体操作和连接限制，而不重复首要使用任务。",
            "trigger_evidence_refs": ["product.features", "image.diagnostics"],
            "downstream_impact": ["bullet_2", "bullet_4", "listing_image", "aplus"],
        },
        {
            "focus": "material_or_performance_parameter",
            "topic": "seat_support_parameter",
            "question": "这款亚麻面料泡棉沙发有哪些可验证的支撑或回弹参数，用户能据此判断坐感吗？",
            "why_asked": "商品材料字段能确认亚麻和泡棉，但缺少可验证的支撑性能参数，不能凭材料名称承诺坐感。",
            "closest_fixed_question_id": "core_09_feature_benefit_proof",
            "incremental_decision_gap": "补充坐感相关参数是否存在，避免把材料名称直接推导为性能收益。",
            "trigger_evidence_refs": ["product.material", "product.filler"],
            "downstream_impact": ["bullet_2", "bullet_5", "aplus"],
        },
        {
            "focus": "placement_or_environment_fit",
            "topic": "delivery_fit",
            "question": "这款三件包装的模块沙发分别多大，用户搬入常见门厅或楼梯时会遇到什么空间限制？",
            "why_asked": "商品证据能确认三件包装，但缺少单箱尺寸，具体搬入环境是否合适仍未知。",
            "closest_fixed_question_id": "core_06_success_conditions",
            "incremental_decision_gap": "从成品空间适配进一步钻取单箱搬入尺寸和路径限制。",
            "trigger_evidence_refs": ["product.packages", "image.diagnostics"],
            "downstream_impact": ["bullet_4", "bullet_5", "listing_image"],
        },
        {
            "focus": "long_term_use_or_maintenance",
            "topic": "fabric_maintenance",
            "question": "用户长期使用这款绿色亚麻沙发时，可以采用哪些有证据支持的日常清洁方式？",
            "why_asked": "图片能确认织物纹理，商品字段能确认亚麻材料，但没有这款产品的清洁说明。",
            "closest_fixed_question_id": "core_11_objections_evidence_and_return_risks",
            "incremental_decision_gap": "把泛化维护疑虑细化为该面料可验证的日常清洁方法。",
            "trigger_evidence_refs": ["product.material", "image.01"],
            "downstream_impact": ["bullet_5", "listing_image", "aplus"],
        },
        {
            "focus": "misbuy_risk_or_evidence_gap",
            "topic": "layout_boundary",
            "question": "用户购买这款三模块沙发前，哪些明确布局已有证据，哪些布局仍不能承诺以避免买错？",
            "why_asked": "用户会按空间选择模块布局，但当前资料没有完整展示这款三模块商品的组合边界。",
            "closest_fixed_question_id": "core_12_fit_boundaries",
            "incremental_decision_gap": "将适用边界落实为这款三模块商品可承诺与不可承诺的具体布局。",
            "trigger_evidence_refs": ["product.features", "image.01"],
            "downstream_impact": ["title", "bullet_3", "listing_image", "aplus"],
        },
    ]
    return {"dynamic_questions": questions[:count]}


def _answer_payload(dynamic_questions: list[dict], evidence_catalog: list[dict]) -> dict:
    questions = [dict(item, question_type="fixed") for item in FIXED_QUESTIONS] + [
        dict(item, question_type="dynamic") for item in dynamic_questions
    ]
    evidence_ref = "product.title"
    assert any(item["id"] == evidence_ref for item in evidence_catalog)
    answers = []
    for index, question in enumerate(questions):
        answers.append(
            {
                "id": question["id"],
                "status": "supported",
                "conclusion": f"Evidence-grounded answer for {question['id']}",
                "supporting_rationale": "Uses the supplied evidence catalog.",
                "evidence_refs": [evidence_ref],
                "confidence": "high",
                "assumptions": [],
                "unknowns": [],
                "content_uses": list(question.get("content_uses") or question.get("downstream_impact") or ["aplus"]),
            }
        )
    # Prove unsupported conclusions are normalized to unknown/low instead of
    # inheriting the model's optimistic status and confidence.
    answers[-1]["evidence_refs"] = ["not.a.real.evidence.id"]
    answers[-1]["status"] = "supported"
    answers[-1]["confidence"] = "high"
    return {
        "answers": answers,
        "strategy": {
            "primary_buyer": "A shopper comparing modular living-room seating.",
            "actual_user": "The household member using the seating.",
            "current_pain": "The current seating does not adapt to the available room layout.",
            "purchase_trigger": "A need for configurable seating.",
            "primary_job": "Create a configurable supported seating area.",
            "core_value_proposition": "Three visible modules support flexible room planning.",
            "top_scenarios": [{"rank": 1, "scenario": "living room", "evidence_refs": [evidence_ref]}],
            "decision_criteria": [
                {"rank": index, "criterion": criterion, "evidence_refs": [evidence_ref]}
                for index, criterion in enumerate(
                    ("room fit", "offer contents", "layout options", "material", "delivery fit"),
                    start=1,
                )
            ],
            "benefit_ladder": [{"feature": "modules", "buyer_benefit": "layout choice", "proof_refs": [evidence_ref]}],
            "differentiators": [],
            "objections": [
                {
                    "objection": "The modules may not fit the intended room.",
                    "response": "Compare the supplied dimensions with the room before purchase.",
                    "proof_refs": [evidence_ref],
                    "remaining_gap": "Individual package dimensions are not supplied.",
                }
            ],
            "fit_boundaries": ["Do not claim unsupported layouts or cleanability."],
            "keyword_intent_map": {"identity": ["modular sofa"], "attribute": [], "problem": [], "scenario": [], "excluded": []},
            "content_direction": {
                "title_job": "Identify the exact product and configuration.",
                "title_required_proof_refs": [evidence_ref],
                "bullet_jobs": [
                    {
                        "position": index,
                        "buyer_question": f"Buyer question {index}",
                        "message_job": f"Message job {index}",
                        "required_proof_refs": [evidence_ref],
                    }
                    for index in range(1, 6)
                ],
                "future_visual_jobs": [{"buyer_question": "How does it fit?", "visual_job": "Show scale", "required_proof_refs": [evidence_ref]}],
                "aplus_jobs": [{"buyer_question": "Why choose it?", "story_job": "Explain supported value", "required_proof_refs": [evidence_ref]}],
                "claims_to_avoid": ["Unsupported stain resistance"],
            },
        },
        "quality": {"critical_unknowns": [], "conflicts": []},
    }


def _valid_customer_mindset_brief(product=None) -> dict:
    product = product or _product_fixture()
    evidence = build_evidence_catalog(product, _competitor_fixture())
    dynamic = normalize_dynamic_questions(_dynamic_payload(5), evidence_catalog=evidence)
    questions, strategy, quality = normalize_mindset_answers(
        _answer_payload(dynamic, evidence),
        dynamic_questions=dynamic,
        evidence_catalog=evidence,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source_fingerprint": "test-customer-mindset-fixture",
        "input_fingerprint": build_mindset_input_fingerprint(product),
        "evidence_catalog": evidence,
        "questions": questions,
        "strategy": strategy,
        "quality": quality,
    }


def test_fixed_and_dynamic_question_contract() -> None:
    assert SCHEMA_VERSION == "customer_mindset_v1"
    assert len(FIXED_QUESTIONS) == 13
    assert DYNAMIC_QUESTION_MIN == 2
    assert DYNAMIC_QUESTION_MAX == 5
    fixed_ids = [item["id"] for item in FIXED_QUESTIONS]
    assert len(fixed_ids) == len(set(fixed_ids))
    assert fixed_ids == [
        "core_01_offer_identity",
        "core_02_buyer_and_user",
        "core_03_purchase_trigger_and_pain",
        "core_04_job_to_be_done",
        "core_05_scenario_priority",
        "core_06_success_conditions",
        "core_07_decision_criteria",
        "core_08_core_value",
        "core_09_feature_benefit_proof",
        "core_10_differentiation",
        "core_11_objections_evidence_and_return_risks",
        "core_12_fit_boundaries",
        "core_13_search_intent_language",
    ]
    for question in FIXED_QUESTIONS:
        assert question["question"].strip()
        assert question["answer_goal"].strip()
        assert question["content_uses"]
        assert set(question["content_uses"]) <= ALLOWED_CONTENT_USES

    evidence = build_evidence_catalog(_product_fixture(), _competitor_fixture())
    dynamic = normalize_dynamic_questions(_dynamic_payload(5), evidence_catalog=evidence)
    assert len(dynamic) == 5
    assert [item["id"] for item in dynamic] == [f"dynamic_{index:02d}" for index in range(1, 6)]
    assert {item["focus"] for item in dynamic} == set(DYNAMIC_QUESTION_FOCUSES)
    assert all(item["question"] and item["why_asked"] and item["trigger_evidence_refs"] for item in dynamic)
    assert all(item["closest_fixed_question_id"] and item["incremental_decision_gap"] for item in dynamic)

    assert len(normalize_dynamic_questions(_dynamic_payload(2), evidence_catalog=evidence)) == 2
    _assert_raises("one dynamic question must be rejected", lambda: normalize_dynamic_questions(_dynamic_payload(1), evidence_catalog=evidence))
    six = _dynamic_payload(5)
    six["dynamic_questions"].append(dict(six["dynamic_questions"][0], topic="extra", question="用户还需要确认这款商品的哪个额外事实？"))
    _assert_raises("six dynamic questions must be rejected", lambda: normalize_dynamic_questions(six, evidence_catalog=evidence))

    duplicate = _dynamic_payload(5)
    duplicate["dynamic_questions"][1]["question"] = duplicate["dynamic_questions"][0]["question"]
    _assert_raises("duplicate dynamic questions must be rejected", lambda: normalize_dynamic_questions(duplicate, evidence_catalog=evidence))

    duplicate_focus = _dynamic_payload(5)
    duplicate_focus["dynamic_questions"][1]["focus"] = duplicate_focus["dynamic_questions"][0]["focus"]
    _assert_raises("all five user-view focuses must be unique", lambda: normalize_dynamic_questions(duplicate_focus, evidence_catalog=evidence))

    invalid_trigger = _dynamic_payload(5)
    invalid_trigger["dynamic_questions"][0]["trigger_evidence_refs"] = ["not.a.real.evidence.id"]
    _assert_raises("dynamic questions must be product-evidence-triggered", lambda: normalize_dynamic_questions(invalid_trigger, evidence_catalog=evidence))

    no_incremental_gap = _dynamic_payload(2)
    no_incremental_gap["dynamic_questions"][0]["incremental_decision_gap"] = ""
    _assert_raises(
        "dynamic questions must state their incremental decision gap",
        lambda: normalize_dynamic_questions(no_incremental_gap, evidence_catalog=evidence),
    )


def test_evidence_answer_and_prompt_contract() -> None:
    evidence = build_evidence_catalog(_product_fixture(), _competitor_fixture())
    evidence_ids = {item["id"] for item in evidence}
    for expected in (
        "product.material",
        "business.selected_competitor_asin",
        "business.category",
        "keyword.01",
        "image.01",
        "image.diagnostics",
        "image.health",
        "image.listing_alignment",
        "competitor.asin",
        "competitor.bullet.01",
    ):
        assert expected in evidence_ids, (expected, sorted(evidence_ids))

    dynamic = normalize_dynamic_questions(_dynamic_payload(5), evidence_catalog=evidence)
    answers, strategy, quality = normalize_mindset_answers(
        _answer_payload(dynamic, evidence),
        dynamic_questions=dynamic,
        evidence_catalog=evidence,
    )
    assert len(answers) == 18
    assert sum(item["question_type"] == "fixed" for item in answers) == 13
    assert sum(item["question_type"] == "dynamic" for item in answers) == 5
    assert answers[-1]["answer"]["status"] == "unknown"
    assert answers[-1]["answer"]["confidence"] == "low"
    assert answers[-1]["id"] in quality["unknown_question_ids"]
    assert quality == {
        **quality,
        "fixed_question_count": 13,
        "dynamic_question_count": 5,
        "total_question_count": 18,
        "requires_review": True,
        "ready_for_listing": True,
    }
    assert len(strategy["content_direction"]["bullet_jobs"]) == 5
    assert strategy["content_direction"]["title_required_proof_refs"] == ["product.title"]
    assert strategy["content_direction"]["title_claim_proof_usable"] is True
    assert strategy["strategy_field_evidence"]["primary_buyer"]["status"] == "inferred"
    assert strategy["strategy_field_evidence"]["primary_buyer"]["copy_claim_usable"] is False
    assert answers[1]["answer"]["status"] == "inferred"
    assert answers[1]["answer"]["copy_claim_usable"] is False
    assert answers[0]["answer"]["status"] == "supported"
    assert answers[0]["answer"]["copy_claim_usable"] is True
    assert strategy["content_direction"]["future_visual_jobs"]
    assert strategy["content_direction"]["aplus_jobs"]
    assert strategy["content_direction"]["claims_to_avoid"]

    missing = _answer_payload(dynamic, evidence)
    missing["answers"].pop()
    _assert_raises(
        "missing fixed or dynamic answers must fail closed",
        lambda: normalize_mindset_answers(missing, dynamic_questions=dynamic, evidence_catalog=evidence),
    )

    dynamic_prompt = _dynamic_question_prompt(evidence)
    answer_prompt = _answer_prompt(evidence, dynamic)
    assert "The 13 mandatory questions" in dynamic_prompt
    assert "Do not repeat or paraphrase them" in dynamic_prompt
    assert "Create 2 to 5 additional questions" in dynamic_prompt
    assert "Do not add filler" in dynamic_prompt
    assert "incremental decision gap" in dynamic_prompt
    assert "closest_fixed_question_id" in dynamic_prompt
    assert "Use Simplified Chinese for question" in dynamic_prompt
    assert "Answer all 18 questions" in answer_prompt
    assert "Use Simplified Chinese for every shopper-facing answer" in answer_prompt
    assert "Keywords only indicate search intent" in answer_prompt
    assert "Competitor facts only indicate market concerns" in answer_prompt
    assert "status=unknown and confidence=low" in answer_prompt
    assert "title_required_proof_refs" in answer_prompt
    assert "Visual facts may support only high-confidence visible appearance" in answer_prompt
    assert "research hypotheses" in answer_prompt

    visual_only_title = _answer_payload(dynamic, evidence)
    visual_only_title["strategy"]["content_direction"]["title_required_proof_refs"] = ["image.01"]
    _, visual_only_strategy, visual_only_quality = normalize_mindset_answers(
        visual_only_title,
        dynamic_questions=dynamic,
        evidence_catalog=evidence,
    )
    assert visual_only_strategy["content_direction"]["title_claim_proof_usable"] is False
    assert visual_only_strategy["content_direction"]["title_visual_anchor_usable"] is True
    assert any("title_job" in item for item in visual_only_quality["evidence_boundary_issues"])

    brief = _valid_customer_mindset_brief()
    listing_context = customer_mindset_context(brief, surface="listing")
    listing_answer_ids = [item["id"] for item in listing_context["relevant_question_answers"]]
    assert listing_answer_ids[:13] == [item["id"] for item in FIXED_QUESTIONS]
    assert len(listing_answer_ids) == 18
    assert set(listing_answer_ids[-5:]) == {f"dynamic_{index:02d}" for index in range(1, 6)}
    assert "future_visual_jobs" not in listing_context["strategy"]["content_direction"]
    assert "aplus_jobs" not in listing_context["strategy"]["content_direction"]

    # content_uses is a placement hint, not permission to discard a buyer
    # question from Listing context.  This regression covers a model that
    # incorrectly marks every answer as an A+ use only.
    for item in brief["questions"]:
        item["answer"]["content_uses"] = ["aplus"]
    forced_listing_context = customer_mindset_context(brief, surface="listing")
    assert len(forced_listing_context["relevant_question_answers"]) == 18
    assert not customer_mindset_context(brief, surface="aplus")["relevant_question_answers"] == []


def test_upstream_readiness_and_fingerprint_contract() -> None:
    product = _product_fixture()
    assert keyword_research_ready(product.data.keywords_top)
    assert not keyword_research_ready("[]")
    assert not keyword_research_ready("{not-json")
    assert image_analysis_ready(product.images.image_analysis)
    assert not image_analysis_ready("{}")
    assert not image_analysis_ready(json.dumps({"images": []}))
    assert not image_analysis_ready(json.dumps({"images": [{"foo": "bar"}]}))

    brief = _valid_customer_mindset_brief(product)
    product.data.customer_mindset = json.dumps(brief)
    assert customer_mindset_matches_product(product.data.customer_mindset, product)
    missing_fingerprint = dict(brief)
    missing_fingerprint.pop("input_fingerprint", None)
    assert not customer_mindset_matches_product(json.dumps(missing_fingerprint), product)

    # Step5 updates only downstream image-vs-copy diagnostics after final Listing
    # persistence. Those updates must not invalidate the upstream mindset brief.
    original_image_analysis = product.images.image_analysis
    image_analysis = json.loads(original_image_analysis)
    diagnostics = image_analysis.setdefault("selection_diagnostics", {})
    diagnostics["listing_image_alignment"] = {
        "status": "complete",
        "missing_evidence": ["final listing copy gap"],
    }
    diagnostics["image_health"] = {
        "label": "needs_review_after_listing",
        "issue_count": 1,
    }
    product.images.image_analysis = json.dumps(image_analysis)
    assert customer_mindset_matches_product(product.data.customer_mindset, product)

    image_analysis["images"][0]["visible_selling_point"] = "changed upstream visual evidence"
    product.images.image_analysis = json.dumps(image_analysis)
    assert not customer_mindset_matches_product(product.data.customer_mindset, product)

    product.images.image_analysis = original_image_analysis
    product.data.material = "Velvet"
    assert not customer_mindset_matches_product(product.data.customer_mindset, product)


def test_large_mindset_uses_a_verified_local_file_reference() -> None:
    product = _product_fixture()
    brief = _valid_customer_mindset_brief(product)
    serialized = json.dumps(brief, ensure_ascii=False)
    with tempfile.TemporaryDirectory() as temporary_dir:
        product.data.material_dir = temporary_dir
        reference = _write_customer_mindset_artifact(product, serialized)
        assert len(reference) < 400
        restored = load_customer_mindset(reference)
        assert restored == brief
        assert customer_mindset_matches_product(reference, product)
        detail = SimpleNamespace(data=SimpleNamespace(customer_mindset=reference))
        _hydrate_product_detail_customer_mindset(detail)
        assert json.loads(detail.data.customer_mindset) == brief
        artifact = Path(temporary_dir) / "image analysis" / "customer_mindset.json"
        artifact.write_text("{}", encoding="utf-8")
        _assert_raises("tampered artifact must fail closed", lambda: load_customer_mindset(reference))


async def test_listing_prerequisite_cannot_bypass_customer_mindset() -> None:
    product = _product_fixture()
    try:
        await _require_generation_prerequisites(SimpleNamespace(), product, 6)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "用户心智" in str(exc.detail)
    else:
        raise AssertionError("Listing prerequisites must reject a product without customer_mindset")

    product.data.customer_mindset = "{not-valid-json"
    try:
        await _require_generation_prerequisites(SimpleNamespace(), product, 6)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "用户心智" in str(exc.detail)
    else:
        raise AssertionError("corrupted customer_mindset JSON must not bypass Listing prerequisites")

    product.data.customer_mindset = json.dumps(_valid_customer_mindset_brief(product))
    await _require_generation_prerequisites(SimpleNamespace(), product, 6)


def test_downstream_consumers_use_the_same_brief() -> None:
    listing_text = (BACKEND / "app" / "pipeline" / "step5_listing.py").read_text(encoding="utf-8")
    aplus_text = (BACKEND / "app" / "pipeline" / "step7_aplus_plan.py").read_text(encoding="utf-8")
    actions_text = (BACKEND / "app" / "product_tasks" / "actions.py").read_text(encoding="utf-8")
    assert "customer_mindset_context(" in listing_text
    assert 'getattr(pd, "customer_mindset", None)' in listing_text
    assert 'surface="listing"' in listing_text
    assert "required=True" in listing_text
    assert "customer_mindset_context(" in aplus_text
    assert 'getattr(pd, "customer_mindset", None)' in aplus_text
    assert 'surface="aplus"' in aplus_text
    assert "class ProductCustomerMindsetAction" in actions_text
    image_section = actions_text.split("class ProductImageAnalysisAction", 1)[1].split("class ProductCustomerMindsetAction", 1)[0]
    mindset_section = actions_text.split("class ProductCustomerMindsetAction", 1)[1].split("class ProductListingGenerationAction", 1)[0]
    assert 'return "product_customer_mindset"' in image_section
    assert '"product_listing_generation"' not in image_section
    assert "run_customer_mindset(product_id)" in mindset_section
    assert '"product_listing_generation"' in mindset_section


def main() -> None:
    test_fixed_and_dynamic_question_contract()
    test_evidence_answer_and_prompt_contract()
    test_upstream_readiness_and_fingerprint_contract()
    test_large_mindset_uses_a_verified_local_file_reference()
    asyncio.run(test_listing_prerequisite_cannot_bypass_customer_mindset())
    test_downstream_consumers_use_the_same_brief()
    print("customer mindset fixed/dynamic/evidence/downstream contract checks passed")


if __name__ == "__main__":
    main()
