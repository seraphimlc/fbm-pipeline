#!/usr/bin/env python3
"""Supplier rule regressions, with real templates and no provider/DB writes."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.pipeline.amazon_export.attribute_rules import resolve_attributes
from app.pipeline.step10_amazon_template import _load_template_mapping, ensure_amazon_template_semantic_fields


def mapping(name):
    m = json.loads((ROOT / "backend/app/pipeline/template_mappings" / name).read_text())
    m["template_path"] = str(ROOT / "backend/app/pipeline" / m["template_path"])
    return m


def product_data(**values):
    defaults = dict(title="", product_type="", material="", description="", features="[]",
                    variants="[]", gigab2b_raw_snapshot=None, leaf_category="", categories="[]",
                    dimension_length=80, dimension_width=60, listing_check="{}",
                    listing_title="", listing_description="", listing_bullets="[]")
    return SimpleNamespace(**(defaults | values))


class AttributeRuleTests(unittest.TestCase):
    def test_ride_on_components_use_current_supplier_identity(self):
        for title, expected in [
            ("12V electric Kids Pedal Go Kart", ["Go Kart"]),
            ("24V Kids Ride on Car UTV W/Parents Remote Control", ["Ride-On Car", "Remote Control"]),
            ("Kids Electric Go Kart", ["Go Kart"]),
        ]:
            pd = product_data(title=title)
            d = self.resolve(pd, "ride_on_toy.json", "RIDE_ON_TOY")
            self.assertEqual(d["included_components"]["values"], expected)

    def test_ride_on_does_not_guess_accessories_or_copy_other_variant(self):
        pd = product_data(title="Kids Go Kart", description="Battery and charger not included. With remote control not included.",
                          variants='[{"title": "Ride on car with remote control"}]')
        d = self.resolve(pd, "ride_on_toy.json", "RIDE_ON_TOY")
        self.assertEqual(d["included_components"]["values"], ["Go Kart"])
        self.assertEqual(self.resolve(product_data(title="Unknown Toy"), "ride_on_toy.json", "RIDE_ON_TOY")["included_components"]["values"], [])

    def test_ride_on_components_are_required(self):
        from app.pipeline.step10_amazon_template import _missing_required_fields
        m = mapping("ride_on_toy.json")
        attr = m["dynamic_fields"]["included_components"][0]
        fill = {"product_type#1.value": "RIDE_ON_TOY"}
        self.assertIn(attr, _missing_required_fields(m, fill, {attr: "BV"}))
        fill[attr] = "Go Kart"
        self.assertNotIn(attr, _missing_required_fields(m, fill, {attr: "BV"}))

    def resolve(self, pd, name, typ):
        m = mapping(name)
        return resolve_attributes(pd, m, Path(m["template_path"]), typ)

    def test_supplier_bike_specs(self):
        pd = product_data(title="26 Inch Mountain Bike 21-Speed", material="Steel", description=
            "Frame Material Type\nHigh-Carbon Steel Frame\nRim Material\nAluminum Alloy\n"
            "Tire Type\nClincher\nAge Range Description\nAdult\nSuspension Type\nFull Suspension\n"
            "Included Components\nToolkits,Reflector,Assembly Instructions")
        d = self.resolve(pd, "vindhvisk_bicycle.json", "BICYCLE")
        for key, expected in {"material": ["Steel"], "frame_material": ["High Carbon Steel"],
                              "tire_type": ["Clincher"], "suspension_type": ["Dual"],
                              "age_range_description": ["Adult"]}.items():
            self.assertEqual(d[key]["values"], expected)
        self.assertIn("Tool Kit", d["included_components"]["values"])

    def test_single_speed_and_negative_components(self):
        pd = product_data(title="Single speed 1-Speed bike without basket", material="Steel")
        d = self.resolve(pd, "vindhvisk_bicycle.json", "BICYCLE")
        self.assertNotIn("Multi-Speed", d["special_features"]["values"])
        self.assertNotIn("Basket", d["included_components"]["values"])
        self.assertEqual(d["tire_type"]["values"], [])

    def test_geometry_not_round_knob_and_zero_drawers(self):
        pd = product_data(title="Bathroom Cabinet", material="MDF", description="Round knobs. No drawers. Adjustable shelf.")
        d = self.resolve(pd, "andy_storage_furniture.json", "CABINET")
        self.assertEqual(d["item_shape"]["values"], ["Rectangular"])
        self.assertEqual(d["number_of_drawers"]["values"], [0])
        self.assertIn("Adjustable Shelf", d["special_features"]["values"])

    def test_box_closure_and_unsupported_finish(self):
        d = self.resolve(product_data(title="Open Toy Storage Box", material="Wood"), "andy_storage_furniture.json", "STORAGE_BOX")
        self.assertEqual(d["closure_type"]["values"], ["None"])
        self.assertEqual(d["finish_type"]["values"], [])

    def test_supplier_identity_over_stale_category(self):
        pd = product_data(title="24 Inch Ladies Bicycle", product_type="Outdoor Bikes", leaf_category="Over-the-Toilet Storage")
        m = _load_template_mapping(SimpleNamespace(brand="Vindhvisk"), pd)
        self.assertEqual(m["category_type"], "bicycle")
        self.assertEqual(pd.leaf_category, "Over-the-Toilet Storage")

    def test_no_model_and_no_generated_copy_evidence(self):
        pd = product_data(title="Bed Frame", material="Wood", listing_title="Painted glass bed")
        m = mapping("vindhvisk_bed_frame.json")
        with patch("app.pipeline.step10_amazon_template.settings", SimpleNamespace()):
            asyncio.run(ensure_amazon_template_semantic_fields(SimpleNamespace(id=1), pd, m, Path(m["template_path"])))
        fields = json.loads(pd.listing_check)["amazon_template_fields"]
        self.assertEqual(fields["finish_type"]["values"], [])
        self.assertEqual(fields["is_fragile"]["values"], ["No"])
        self.assertEqual(fields["item_shape"]["source"], "supplier_rule")

    def test_catalog_merge_uses_rules_over_stale_llm(self):
        from app.api.products import _apply_catalog_export_row_overrides, _template_attribute_columns
        m = mapping("vindhvisk_bicycle.json")
        pd = product_data(title="Adult 26 Inch Bike", material="High Carbon Steel", description=
                          "Rim Material\nAluminum Alloy\nTire Type\nClincher\nSuspension Type\nFull Suspension",
                          listing_check=json.dumps({"amazon_template_fields": {"age_range_description": {"values": ["Infant"]}}}))
        w = load_workbook(m["template_path"], keep_vba=True)
        ws = w["Template"]
        columns = _template_attribute_columns(ws)
        ws.cell(8, columns["product_type#1.value"]).value = "BICYCLE"
        _apply_catalog_export_row_overrides(ws, 8, SimpleNamespace(upc="123456789012"), pd, m)
        for key, expected in {"tire_type": "Clincher", "age_range_description": "Adult", "suspension_type": "Dual", "frame_material": "High Carbon Steel"}.items():
            self.assertEqual(ws.cell(8, columns[m["dynamic_fields"][key]]).value, expected)
        w.close()

    def test_import_and_canonical_source_excludes_warranty(self):
        pd = product_data(title="Teenagers Mountain Bike", origin="China", gigab2b_raw_snapshot=json.dumps({
            "material_facts": {"sources": [
                {"asset_kind": "html", "extraction_status": "extracted", "text_preview": "Includes clear instructions.\n售后规则\nGlass basket returns policy"},
                {"asset_kind": "html", "extraction_status": "extracted", "text_preview": "售后规则\nTubeless"}]}}))
        d = self.resolve(pd, "vindhvisk_bicycle.json", "BICYCLE")
        self.assertEqual(d["import_designation"]["values"], ["Imported"])
        self.assertEqual(d["age_range_description"]["values"], ["Youth"])
        self.assertEqual(d["included_components"]["values"], ["User Manual"])
        self.assertEqual(d["tire_type"]["values"], [])

    def test_user_origin_policy_is_not_supplier_evidence(self):
        d = self.resolve(product_data(title="Kids Tricycle"), "vindhvisk_bicycle.json", "BICYCLE")
        self.assertEqual(d["import_designation"]["values"], ["Imported"])
        self.assertEqual(d["import_designation"]["source"], "user_policy")
        self.assertEqual(d["tire_type"]["values"], [])

    def test_toy_polymer_audience_and_theme(self):
        d = self.resolve(product_data(title="Kids racing go kart", material="Polypropylene"), "ride_on_toy.json", "RIDE_ON_TOY")
        for key, expected in {"material": ["Polypropylene"], "target_audience": ["Unisex Children"],
                              "target_gender": ["Unisex"], "theme": ["Sport"]}.items():
            self.assertEqual(d[key]["values"], expected)

    def test_acrylic_comparison_is_not_glass_material(self):
        d = self.resolve(product_data(title="Kids Vanity", material="MDF", color="White", description="Acrylic mirror is safer than glass."), "andy_storage_furniture.json", "MAKEUP_VANITY")
        self.assertEqual(d["is_fragile"]["values"], ["No"])
        self.assertEqual(d["construction_type"]["values"], ["Engineered Wood Panel Construction"])

    def test_compliance_has_no_blanket_default(self):
        d = self.resolve(product_data(title="Kids Step Stool", material="MDF", dimension_height=36.02), "andy_storage_furniture.json", "STEP_STOOL")
        self.assertNotIn("required_product_compliance_certificate", d)
        self.assertEqual(d["maximum_height"]["values"], [36.02])

    def test_reviewed_evidence_identity_and_bytes(self):
        from app.pipeline.amazon_export.attribute_rules import reviewed_attributes, supplier_identity
        pd = product_data(item_code="TEST", material="MDF")
        with tempfile.TemporaryDirectory(dir=ROOT / "data/products") as temp:
            source = Path(temp) / "label.txt"; source.write_text("CARB")
            import hashlib
            registry = {"TEST": {"identity": supplier_identity(pd), "fields": {"required_product_compliance_certificate": {
                "values": ["California Air Review Board (CARB)"], "reason": "Supplier label", "sources": [{
                    "path": str(source.relative_to(ROOT)), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}}}}
            real_read = Path.read_text
            def read(path, *args, **kwargs):
                return json.dumps(registry) if path.name == "reviewed_supplier_attributes.json" else real_read(path, *args, **kwargs)
            with patch.object(Path, "read_text", read):
                self.assertIn("required_product_compliance_certificate", reviewed_attributes(pd))
                pd.title = "Different product"
                self.assertEqual(reviewed_attributes(pd), {})
                pd.title = ""; source.write_text("Different label")
                self.assertEqual(reviewed_attributes(pd), {})

    def test_user_tire_confirmation_is_scoped_and_keeps_provenance(self):
        from app.pipeline.amazon_export.attribute_rules import supplier_identity
        pd = product_data(item_code="MANUAL_TIRE", title="Mountain Bike", material="Steel")
        with tempfile.TemporaryDirectory(dir=ROOT / "data/products") as temp:
            source = Path(temp) / "confirmation.json"
            source.write_text('User selected Clincher')
            import hashlib
            registry = {pd.item_code: {"identity": supplier_identity(pd), "fields": {"tire_type": {
                "values": ["Clincher"], "source": "user_confirmation", "reason": "Explicit user selection",
                "sources": [{"path": str(source.relative_to(ROOT)), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}}}}
            real_read = Path.read_text
            def read(path, *args, **kwargs):
                return json.dumps(registry) if path.name == "reviewed_supplier_attributes.json" else real_read(path, *args, **kwargs)
            with patch.object(Path, "read_text", read):
                decision = self.resolve(pd, "vindhvisk_bicycle.json", "BICYCLE")["tire_type"]
                self.assertEqual(decision["values"], ["Clincher"])
                self.assertEqual(decision["source"], "user_confirmation")
                pd.item_code = "OTHER_SKU"
                self.assertEqual(self.resolve(pd, "vindhvisk_bicycle.json", "BICYCLE")["tire_type"]["values"], [])
                pd.item_code = "MANUAL_TIRE"
                source.write_text('Changed confirmation')
                self.assertEqual(self.resolve(pd, "vindhvisk_bicycle.json", "BICYCLE")["tire_type"]["values"], [])

    def test_required_slots_are_any_not_all(self):
        from app.pipeline.step10_amazon_template import _missing_required_fields
        m = {"dynamic_fields": {"components": ["slot1", "slot2"]}, "required_by_product_type": {"BICYCLE": ["components"]}}
        columns = {"slot1": "A", "slot2": "B"}
        self.assertEqual(_missing_required_fields(m, {"product_type#1.value": "BICYCLE", "slot1": "Basket"}, columns), [])
        self.assertEqual(_missing_required_fields(m, {"product_type#1.value": "BICYCLE"}, columns), ["slot1"])


if __name__ == "__main__":
    unittest.main()
