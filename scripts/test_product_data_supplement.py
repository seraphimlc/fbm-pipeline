"""Evidence validation, cache invalidation and search-term fallback regressions."""
import json
import sys
import unittest
import asyncio
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.product_data_supplement import validate_ai_fields, reusable_attributes
from app.pipeline.search_terms import supplement_search_terms
from app.pipeline.amazon_export.attribute_rules import supplement_supplier_fingerprint, stored_supplement_attributes


class SupplementTests(unittest.TestCase):
    def test_only_explicit_values_in_verbatim_source_are_accepted(self):
        options = {"style": ["Modern", "Rustic"], "mounting_type": ["Wall Mount"]}
        payload = {"fields": {
            "style": {"values": ["Modern", "Rustic", "Invalid"], "quote": "Modern cabinet with drawers."},
            "mounting_type": {"values": ["Wall Mount"], "quote": "Modern cabinet with drawers."}}}
        result = validate_ai_fields(payload, options, "Modern cabinet with drawers.")
        self.assertEqual(result["style"]["values"], ["Modern"])
        self.assertNotIn("mounting_type", result)

    def test_fabricated_negative_and_uncertain_quotes_are_rejected(self):
        for quote in ["No Wall Mount hardware is included.", "Possibly Wall Mount style.", "Wall Mount cabinet with hardware."]:
            payload = {"fields": {"mounting_type": {"values": ["Wall Mount"], "quote": quote}}}
            self.assertEqual(validate_ai_fields(payload, {"mounting_type": ["Wall Mount"]}, "No Wall Mount hardware is included. Possibly Wall Mount style."), {})

    def test_product_changes_invalidate_stored_attributes(self):
        pd = SimpleNamespace(title="Modern cabinet", listing_check="{}")
        report = {"supplier_fingerprint": supplement_supplier_fingerprint(pd), "attributes": {"style": {"values": ["Modern"]}}}
        pd.listing_check = json.dumps({"data_supplement": report})
        self.assertIn("style", stored_supplement_attributes(pd))
        pd.title = "Different cabinet"
        self.assertEqual(stored_supplement_attributes(pd), {})

    def test_contracted_negations_are_not_positive_evidence(self):
        for quote in ["This isn't a Wall Mount cabinet.", "It can't support Wall Mount installation.", "It might support Wall Mount installation."]:
            payload = {"fields": {"mounting_type": {"values": ["Wall Mount"], "quote": quote}}}
            self.assertEqual(validate_ai_fields(payload, {"mounting_type": ["Wall Mount"]}, quote), {})

    def test_refresh_preserves_and_repairs_explicit_ai_cache(self):
        previous = {"supplier_fingerprint": "same", "attributes": {}, "rows": [{
            "key": "specific_uses_for_product", "source": "ai_evidence", "value": ["Road"],
            "evidence": [{"quote": "Applicable Terrain: Road"}]}]}
        result = reusable_attributes(previous, "same", {"specific_uses_for_product": ["Road"]}, "Applicable Terrain: Road")
        self.assertEqual(result["specific_uses_for_product"]["values"], ["Road"])
        previous["attributes"] = result
        self.assertEqual(reusable_attributes(previous, "same", {"specific_uses_for_product": ["Road"]}, "Applicable Terrain: Road"), result)
        self.assertEqual(reusable_attributes(previous, "changed", {"specific_uses_for_product": ["Road"]}, "Applicable Terrain: Road"), {})

    def test_keyword_fallback_uses_safe_noun_synonyms(self):
        result, source = supplement_search_terms("", candidates=[{"keyword": "waterproof cabinet"}], supplier_title="Storage Cabinet", visible_copy="Storage Cabinet")
        self.assertEqual(result, "cupboard")
        self.assertEqual(source, "keyword_rule")
        self.assertNotIn("waterproof", result)

    def test_keywords_can_remain_empty_without_new_supported_candidates(self):
        self.assertEqual(supplement_search_terms("", supplier_title="Storage Cabinet", visible_copy="Storage Cabinet cupboard")[0], "")

    def test_existing_valid_terms_are_kept(self):
        self.assertEqual(supplement_search_terms("cupboard", supplier_title="Cabinet", visible_copy="Cabinet")[0], "cupboard")

    def test_previously_rejected_keyword_is_not_reintroduced(self):
        result, _ = supplement_search_terms("", candidates=[{"keyword": "2 tier bookshelf kids"}],
            supplier_title="2 tier bookshelf kids", visible_copy="bookshelf", removed_terms=["2 tier bookshelf kids - conflicting tier evidence"])
        self.assertNotIn("2 tier", result)

    def test_export_never_invokes_model_for_missing_semantic_fields(self):
        from app.pipeline.step10_amazon_template import ensure_amazon_template_semantic_fields
        pd = SimpleNamespace(listing_check='{}', product_type='CABINET')
        with patch('app.pipeline.step10_amazon_template._template_product_type_for_semantic_fields', return_value='CABINET'), \
             patch('app.pipeline.step10_amazon_template._semantic_dropdown_options', return_value={'style': ['Modern']}), \
             patch('app.config.Settings.get_llm_client', side_effect=AssertionError('export model call')):
            asyncio.run(ensure_amazon_template_semantic_fields(SimpleNamespace(id=1), pd, {}, Path('unused')))
        self.assertEqual(json.loads(pd.listing_check)['amazon_template_fields']['style']['values'], [])

    def test_ride_on_keyword_fallback_does_not_invent_motor_or_battery(self):
        text, _ = supplement_search_terms('', supplier_title='Kids ride on car', visible_copy='Kids ride on car')
        self.assertTrue(text)
        self.assertNotIn('motor', text)
        self.assertNotIn('battery', text)


if __name__ == "__main__":
    unittest.main()
