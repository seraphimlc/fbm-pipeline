"""Deterministic supplier evidence -> template attributes, shared by both exports.

Never use generated Listing copy as evidence or substitute an unrelated allowed
value. A missing decision stays visible as a data gap rather than invoking LLM.
"""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

RULE_VERSION = "supplier-attributes-2026-10-07-v3"
RULE_FAMILIES = {"bed_frame", "bicycle", "home_storage_furniture", "ride_on_toy"}


def uses_attribute_rules(mapping: dict) -> bool:
    return (mapping.get("strategy_family") or mapping.get("category_type")) in RULE_FAMILIES


def supplier_text(pd: Any) -> str:
    # JSON preserves variant attributes and source feature lists without pulling
    # unrelated competitor/customer-mindset or generated Listing content.
    return " ".join([*(str(getattr(pd, key, None) or "") for key in
                    ("title", "product_type", "material", "description", "features", "variants")),
                    *supplier_material_texts(pd)]).lower()


def supplier_material_texts(pd: Any) -> list[str]:
    """Use existing deterministic HTML/spreadsheet extractions, never VLM copy."""
    try:
        snapshot = json.loads(getattr(pd, "gigab2b_raw_snapshot", None) or "{}")
    except (TypeError, ValueError):
        return []
    facts = snapshot.get("material_facts") or {}
    return [re.split(r"售后规则|After[- ]Sales Policy", str(source["text_preview"]), flags=re.I)[0] for source in facts.get("sources", [])
            if source.get("asset_kind") in {"html", "text"}
            and source.get("extraction_status") == "extracted" and source.get("text_preview")]


def supplier_pairs(pd: Any) -> dict[str, str]:
    from .strategies.bed_frame import _property_values, _product_information_values, _clean_text
    pairs = {**_property_values(pd), **_product_information_values(pd)}
    description = "\n".join([str(getattr(pd, "description", None) or ""), *supplier_material_texts(pd)])
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    labels = ("frame material", "frame material type", "tire type", "suspension type",
              "age range description", "age range (description)", "included components",
              "material", "shape", "item shape", "finish type", "number of drawers",
              "country of origin", "origin", "place of origin")
    for i, line in enumerate(lines[:-1]):
        name = _clean_text(line).lower().rstrip(":")
        if name in labels:
            pairs[name] = _clean_text(lines[i + 1])
    try:
        variants = json.loads(getattr(pd, "variants", None) or "[]")
    except (ValueError, TypeError):
        variants = []
    for variant in variants if isinstance(variants, list) else []:
        for key, value in (variant.get("attributes") or {}).items():
            pairs.setdefault(str(key).lower(), str(value))
    return pairs


def _matches(text: str, pattern: str) -> bool:
    # Avoid turning explicit negative features into positive claims.
    return any(not re.search(r"\b(?:no|without|not|does not)(?:\s+\w+){0,2}\s*$",
                             text[max(0, match.start()-35):match.start()])
               and not re.match(r"\s*(?:is |are )?not included", text[match.end():])
               for match in re.finditer(pattern, text))


def _materials(text: str) -> list[str]:
    candidates = []
    for pattern, values in (
        (r"high[- ]carbon steel", ["High Carbon Steel", "Carbon Steel", "Alloy Steel", "Metal"]),
        (r"carbon steel", ["Carbon Steel", "Alloy Steel", "Metal"]),
        (r"stainless steel", ["Stainless Steel", "Metal"]),
        (r"high[- ]tensile steel", ["High Tensile Steel", "Alloy Steel", "Metal"]),
        (r"\bsteel\b", ["Alloy Steel", "Steel", "Metal"]),
        (r"alumin(?:um|ium)(?: alloy)?", ["Aluminum", "Aluminum Alloy"]),
        (r"\biron\b", ["Iron", "Metal"]),
        (r"carbon fiber", ["Carbon Fiber"]),
        (r"\bmdf\b|plywood|particle\s*board|engineered wood", ["Engineered Wood"]),
        (r"\bwood(?:en)?\b", ["Wood"]),
        (r"\bplastic\b", ["Plastic"]),
        (r"\bbamboo\b", ["Bamboo"]),
        (r"\blinen\b", ["Linen", "Fabric"]),
        (r"\bfabric\b", ["Fabric"]),
        (r"\bpolyethylene\b", ["Polyethylene", "Plastic"]),
        (r"\bpolypropylene\b", ["Polypropylene", "Plastic"]),
        (r"\babs\b", ["Acrylonitrile Butadiene Styrene", "Plastic"]),
        (r"\brubber\b", ["Rubber"]),
    ):
        if re.search(pattern, text):
            candidates.extend(values)
    return list(dict.fromkeys(candidates))


def rule_candidates(pd: Any, product_type: str) -> dict[str, list[Any]]:
    pairs = supplier_pairs(pd)
    text = supplier_text(pd) + " " + " ".join(pairs.values()).lower()
    result: dict[str, list[Any]] = {}
    def set_values(key, values):
        result[key] = list(dict.fromkeys(values))
    frame = pairs.get("frame material type") or pairs.get("frame material")
    set_values("material", _materials(str(getattr(pd, "material", None) or "").lower()) + _materials(text))
    if product_type == "BICYCLE":
        raw = str(getattr(pd, "material", None) or "").strip()
        if raw.lower() == "steel": result["material"].insert(0, "Steel")
    set_values("frame_material", _materials((frame or str(getattr(pd, "material", None) or "")).lower()))
    set_values("frame_material_structured", result["frame_material"][:1])
    components = []
    for pattern, label in (
        (r"basket", "Basket"), (r"tool\s*kits?", "Tool Kit"),
        (r"reflectors?", "Reflectors"), (r"\bbell\b", "Bell"),
        (r"assembly instructions|user manual|(?:detailed|clear) instructions", "User Manual"),
        (r"assembly instructions|installation manual|detailed instructions", "Installation Manual"),
        (r"all hardware|hardware (?:bag|included)|hardware and", "Hardware Bag"),
        (r"training wheels?", "Training Wheel"), (r"kickstand", "Kickstand"),
        (r"\bbattery (?:is )?included\b|\b(?:includes?|included)(?:\s+(?:a|the|one|rechargeable)){0,3}\s+battery\b", "Battery"),
        (r"\bcharger (?:is )?included\b|\b(?:includes?|included)(?:\s+(?:a|the|one)){0,3}\s+charger\b", "Charger"),
        (r"anti[- ]tip (?:device|kit)|anti[- ]tipping", "Anti-Tip Device"),
        (r"\bheadboard\b", "Headboard"), (r"\bslats?\b", "Slat"),
        (r"\bdrawers?\b", "Drawers"), (r"\bdoors?\b", "Doors"),
        (r"\bshelves\b|\bshelf\b", "Shelves"), (r"\blid\b", "Lid"),
        (r"hanging rod|clothes rod", "Hanging Rod"),
        (r"\bcanopy\b", "Canopy"), (r"\bguardrail\b", "Guardrail"),
    ):
        if _matches(text, pattern): components.append(label)
    # Free-text component fields use product identity when no detachable
    # accessory is stated; do not pretend a manual/tool kit is included.
    if not components and product_type in {"DRESSER", "STORAGE_BOX", "STEP_STOOL", "MAKEUP_VANITY"}:
        components = [{"DRESSER": "Dresser", "STORAGE_BOX": "Storage Box",
                       "STEP_STOOL": "Step Stool", "MAKEUP_VANITY": "Vanity"}[product_type]]
    if product_type == "BED_FRAME":
        components = [v for v in ("Headboard", "Installation Manual", "Slat") if v in components]
    if product_type == "RIDE_ON_TOY":
        # The supplied vehicle itself is a component. Require its explicit
        # supplier identity; do not default an unknown toy to a vehicle, and
        # do not borrow accessories from other variants or generated copy.
        title = str(getattr(pd, "title", None) or "").lower()
        current_source = " ".join([title, str(getattr(pd, "features", None) or ""),
                                   str(getattr(pd, "description", None) or ""),
                                   *supplier_material_texts(pd)]).lower()
        vehicle = (
            "Go Kart" if _matches(title, r"\bgo[- ]?kart\b") else
            "Ride-On Car" if _matches(title, r"\bride[- ]on (?:car|utv|truck|atv)\b") else None
        )
        if vehicle:
            components.insert(0, vehicle)
        if _matches(current_source, r"(?:\bwith\s+|\bw/\s*)(?:parents?\s+)?(?:wireless\s+)?remote control"):
            components.append("Remote Control")
        components = list(dict.fromkeys(components))
    set_values("included_components", components)
    features = []
    for pattern, label in (
        (r"adjustable (?:seat|saddle)|seat height.*adjustable", "Adjustable Seat"),
        (r"seatpost adjustment[\s\S]{0,40}height[- ]adjustable", "Adjustable Seat"),
        (r"adjustable handlebars?", "Adjustable Handlebars"),
        (r"dual disc brake|front and rear disc", "Dual Disc Brake"),
        (r"full suspension|dual suspension", "Dual Suspension"),
        (r"\bfenders?\b", "Fenders"), (r"foldable|folding", "Foldable"),
        (r"digital display|lcd display", "Digital Display"),
        (r"\bdurable\b|strong and durable", "Durable"),
        (r"\blightweight\b", "Lightweight"),
        (r"adjustable headboard", "Adjustable"),
        (r"\bslats?\b", "Slatted"), (r"upholstered", "Upholstered"),
        (r"adjustable shel(?:f|ves)", "Adjustable Shelf"),
        (r"anti[- ]tip", "Anti-Tipping"), (r"soft[- ]clos", "Soft-Close"),
        (r"removable drawers?", "Removable Drawer"),
        (r"built[- ]in handle|carrying handle|cut[- ]out handles?", "Built-In Handle"),
        (r"adjustable height|height[- ]adjustable", "Adjustable Height"),
        (r"\bcompact\b|small space", "Compact"),
        (r"non[- ]slip (?:feet|pads)|non[- ]skid", "Non-Skid Feet"),
        (r"\bportable\b", "Portable"),
        (r"scratch[- ]resistant", "Scratch Resistant"),
        (r"\bwheels\b|\bcasters\b|wheeled", "Wheeled"),
        (r"open[- ]front", "Open-Front"), (r"safety hinge|safety hinged", "Safety Hinge"),
        (r"sliding doors?", "Sliding Doors"), (r"hanging rod", "Hanging Rod"),
    ):
        if _matches(text, pattern): features.append(label)
    if re.search(r"no box spring|box spring not required|spring box.*no need", text):
        features.append("No Box Spring Needed")
    if any(int(n) > 1 for n in re.findall(r"\b(\d+)[- ]speeds?\b", text)):
        features.append("Multi-Speed")
    if product_type == "BED_FRAME":
        features = [v for v in ("Adjustable", "No Box Spring Needed", "Slatted", "Upholstered") if v in features]
    set_values("special_features", features)
    age = (pairs.get("age range description") or pairs.get("age range (description)") or "") + " " + text
    explicit = next((label for word, label in [("adult", "Adult"), ("youth", "Youth"),
                    ("toddler", "Toddler"), ("infant", "Infant"), ("big kid", "Big Kid"),
                    ("little kid", "Little Kid")] if re.search(r"\b" + word + r"\b", age.lower())), None)
    age_number = re.search(r"(?:age(?:s)?[: ]*|^)(\d{1,2})\s*(?:\+|[-–]|years)", age.lower())
    if not explicit and age_number:
        n = int(age_number.group(1))
        explicit = "Adult" if n >= 16 else "Youth" if n >= 12 else "Big Kid" if n >= 6 else "Little Kid" if n >= 3 else "Toddler"
    if not explicit:
        if re.search(r"\bmen\b|\bwomen\b|\bladies\b", text): explicit = "Adult"
        elif re.search(r"\b(?:teens?|teenagers?)\b", text): explicit = "Youth"
        elif re.search(r"\b700c\b", text) and re.search(r"commut|road bike", text): explicit = "Adult"
    set_values("age_range_description", [explicit] if explicit else [])
    tire = pairs.get("tire type", "") + " " + text
    set_values("tire_type", [v for v in ("Clincher", "Tubeless", "Tubular") if re.search(r"\b" + v.lower() + r"\b", tire)])
    suspension = (pairs.get("suspension type", "") or text).lower()
    set_values("suspension_type", ["Dual" if re.search(r"full suspension|dual suspension", suspension) else
               "Dual" if suspension.strip() == "dual" else
               "Front" if re.search(r"front suspension|suspension fork", suspension) else
               "Rear" if "rear suspension" in suspension else "Rigid"])
    shapes = [(r"\bsquare\b", "Square"), (r"rectang(?:ular|le)", "Rectangular"),
              (r"\bround\b", "Round"), (r"\boval\b", "Oval"), (r"corner cabinet|triangular", "Triangular")]
    # Shape words in component descriptions (e.g. round knobs) are not the
    # product shape. Restrict explicit shape to supplier title/shape property.
    shape_text = str(getattr(pd, "title", None) or "").lower() + " " + pairs.get("shape", pairs.get("item shape", "")).lower()
    shape = next((label for pattern, label in shapes if re.search(pattern, shape_text)), None)
    if not shape and product_type in {"BED_FRAME", "CABINET", "DRESSER", "STORAGE_BOX", "MAKEUP_VANITY"}:
        length, width = getattr(pd, "dimension_length", None), getattr(pd, "dimension_width", None)
        if length and width:
            shape = "Square" if abs(length-width)/max(length,width) < .02 else "Rectangular"
    set_values("item_shape", [shape] if shape else [])
    set_values("container_shape", result["item_shape"])
    set_values("room_type", [label for marker, label in [("bedroom", "Bedroom"), ("bathroom", "Bathroom"),
               ("kitchen", "Kitchen"), ("living room", "Living Room"), ("nursery", "Nursery"), ("playroom", "Playroom")]
               if marker in text])
    closure = "Flip Top" if re.search(r"hinged lid|flip[- ]top|lift[- ](?:up|top)|lid.*hinge", text) else "Sliding" if re.search(r"pull[- ]out|sliding drawer", text) else "None" if re.search(r"open (?:toy |top |storage |shelves)|without lid|no lid", text) else None
    set_values("closure_type", [closure] if closure else [])
    drawer_property = pairs.get("number of drawers", "")
    drawers = re.search(r"\b(\d+)\s*[- ]?drawers?\b", text)
    if drawer_property.isdigit(): set_values("number_of_drawers", [int(drawer_property)])
    elif drawers: set_values("number_of_drawers", [int(drawers.group(1))])
    elif re.search(r"no drawers|without drawers", text): set_values("number_of_drawers", [0])
    elif product_type == "CABINET" and not re.search(r"\bdrawers?\b", text) and re.search(r"\bdoors?\b|hanging rod|\bshelves\b", text):
        set_values("number_of_drawers", [0])
    finish = pairs.get("finish type", "")
    finishes = [label for pattern, label in [(r"powder[- ]coated", "Powder Coated"),
                (r"\blacquer(?:ed)?\b", "Lacquered"), (r"\bvarnish(?:ed)?\b", "Varnished"),
                (r"painted|paint finish", "Painted"), (r"\blaminated\b", "Laminated"),
                (r"matte finish", "Matte Finish"), (r"\bunfinished\b", "Unfinished")]
                if _matches(text, pattern)]
    set_values("finish_type", [finish] if finish else finishes)
    if not result["finish_type"] and product_type == "BED_FRAME" and "upholstered" in text:
        set_values("finish_type", ["Linen Upholstered" if "linen" in text else "Upholstered"])
    elif not result["finish_type"] and re.search(r"\bfinish(?:ed)?\b", text):
        color = str(getattr(pd, "color", None) or "").strip()
        if color: set_values("finish_type", [color + " Finish"])
    # Fragility is a shipping classification, not a strength guarantee. Hard
    # furniture without glass/ceramic/stone constituents is non-fragile.
    if product_type in {"BED_FRAME", "CABINET", "DRESSER", "MAKEUP_VANITY"}:
        fragile_text = re.sub(r"(?:safer|stronger) than glass|unlike glass", "", text)
        fragile = _matches(fragile_text, r"\bglass\b|\bceramic\b|\bmarble\b|\bstone\b")
        set_values("is_fragile", ["Yes" if fragile else "No"])
    if product_type in {"CABINET", "DRESSER", "MAKEUP_VANITY"}:
        materials = _materials(str(getattr(pd, "material", None) or "").lower())
        if materials: set_values("construction_type", [materials[0] + " Panel Construction"])
        color = str(getattr(pd, "color", None) or "").strip()
        if color: set_values("furniture_finish", [color])
        style = next((label for pattern, label in [(r"glass doors?|glass[- ]front", "Glass Front"),
                     (r"shaker", "Shaker"), (r"sliding doors?", "Sliding"),
                     (r"louver", "Louvered"), (r"raised panel", "Raised Panel"),
                     (r"flat panel|slab door", "Flat Panel")] if re.search(pattern, text)), None)
        if not style and not re.search(r"\bdoors?\b", text):
            style = "Open Frame" if "hanging rod" in text else "Drawer Front" if "drawer" in text else None
        set_values("door_style", [style] if style else [])
        mount = "Wall Mount" if re.search(r"wall[- ]mount|mounted on a wall", text) else "Floor Mount" if re.search(r"freestanding|free[- ]standing|floor cabinet|floor mount|clothes rack|sliding doors", text) else None
        set_values("mounting_type", [mount] if mount else [])
    if product_type == "STEP_STOOL" and getattr(pd, "dimension_height", None):
        set_values("maximum_height", [pd.dimension_height])
        set_values("maximum_height_unit", ["Inches"])
    if product_type == "BICYCLE":
        origin = str(getattr(pd, "origin", None) or pairs.get("origin") or pairs.get("country of origin") or pairs.get("place of origin") or "").lower()
        set_values("import_designation", [])
        if origin and origin not in {"united states", "usa", "us"}: set_values("import_designation", ["Imported"])
    if product_type == "RIDE_ON_TOY":
        set_values("target_audience", ["Unisex Children"] if re.search(r"kids|children", text) else [])
        set_values("target_gender", ["Unisex"] if re.search(r"kids|children|boys.*girls|girls.*boys", text) else [])
        set_values("theme", ["Music"] if re.search(r"music|mp3|bluetooth", text) else ["Sport"] if re.search(r"go[- ]?kart|racing", text) else [])
    # Reviewed supplier photos supplement text once; future exports verify the
    # product identity and original bytes, without calling a model again.
    result.update({key: entry["values"] for key, entry in reviewed_attributes(pd).items()})
    return result


def supplier_identity(pd: Any) -> str:
    return hashlib.sha256(json.dumps({key: getattr(pd, key, None) for key in
        ("item_code", "title", "material", "color")}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reviewed_attributes(pd: Any) -> dict:
    path = Path(__file__).with_name("reviewed_supplier_attributes.json")
    if not path.is_file(): return {}
    entry = json.loads(path.read_text()).get(str(getattr(pd, "item_code", "")), {})
    if entry.get("identity") != supplier_identity(pd): return {}
    root = Path(__file__).resolve().parents[4]
    valid = {}
    for key, decision in entry.get("fields", {}).items():
        sources = decision.get("sources") or []
        if not sources: continue
        try:
            for source in sources:
                file = (root / source["path"]).resolve()
                if not file.is_relative_to(root / "data/products") or not file.is_file(): break
                if hashlib.sha256(file.read_bytes()).hexdigest() != source["sha256"]: break
            else:
                valid[key] = decision
        except (OSError, KeyError):
            continue
    return valid


def supplement_supplier_fingerprint(pd: Any) -> str:
    payload = {key: getattr(pd, key, None) for key in (
        "item_code", "title", "material", "color", "description", "features", "variants",
        "gigab2b_raw_snapshot", "dimension_length", "dimension_width", "dimension_height", "weight")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def stored_supplement_attributes(pd: Any) -> dict:
    try:
        report = json.loads(getattr(pd, "listing_check", None) or "{}").get("data_supplement", {})
    except (ValueError, TypeError):
        return {}
    if report.get("supplier_fingerprint") != supplement_supplier_fingerprint(pd):
        return {}
    return report.get("attributes", {})


def resolve_attributes(pd: Any, mapping: dict, template_path: Path, product_type: str) -> dict[str, dict]:
    from app.pipeline import step10_amazon_template as legacy
    resolved = {}
    reviewed = reviewed_attributes(pd)
    supplemental = stored_supplement_attributes(pd)
    for key, candidates in rule_candidates(pd, product_type).items():
        user_origin_default = key == "import_designation" and not candidates and mapping.get("supplier_origin_default") == "China"
        if user_origin_default: candidates = ["Imported"]
        attrs = legacy._flatten_mapping_values(mapping.get("dynamic_fields", {}).get(key))
        if key == "target_audience":
            attrs += [v for k, v in mapping.get("dynamic_fields", {}).items() if k.startswith("target_audience_")]
        if key == "theme": attrs += legacy._flatten_mapping_values(mapping.get("dynamic_fields", {}).get("theme_1"))
        if not attrs: continue
        allowed = legacy._allowed_values_for_template_attr(template_path, product_type, attrs[0])
        open_text = key in mapping.get("supplier_text_fields", [])
        values = [value for value in candidates if open_text or not allowed or str(value) in allowed]
        # Material is a scalar in these mappings; specificity has priority.
        if key not in {"included_components", "special_features", "room_type"}: values = values[:1]
        resolved[key] = {"values": values[:len(attrs)], "source": "supplier_rule",
                         "rule_version": RULE_VERSION, "product_type": product_type,
                         "reason": "Supplier properties/text and category geometry rules" if values else "Supplier evidence has no supported template value",
                         "allowed_values": allowed}
        if key in reviewed:
            source = "user_confirmation" if reviewed[key].get("source") == "user_confirmation" else "supplier_reviewed_evidence"
            resolved[key].update(source=source, reason=reviewed[key]["reason"], evidence=reviewed[key]["sources"])
        elif user_origin_default:
            resolved[key].update(source="user_policy", reason="User explicitly authorized China as the fallback origin for this product family on 2026-10-07")
        extra = supplemental.get(key, {})
        if key not in reviewed and extra.get("values") and (not values or extra.get("source") == "user_confirmation"):
            selected = [v for v in extra["values"] if open_text or not allowed or str(v) in allowed]
            if selected:
                resolved[key].update(values=selected[:len(attrs)], source=extra.get("source", "ai_evidence"),
                                     reason=extra.get("reason", ""), evidence=extra.get("evidence", []))
    for key, extra in supplemental.items():
        if key in resolved or not extra.get("values"):
            continue
        attrs = legacy._flatten_mapping_values(mapping.get("dynamic_fields", {}).get(key))
        if not attrs:
            continue
        allowed = legacy._allowed_values_for_template_attr(template_path, product_type, attrs[0])
        selected = [v for v in extra["values"] if str(v) in allowed]
        if selected:
            resolved[key] = {**extra, "values": selected[:len(attrs)], "allowed_values": allowed, "product_type": product_type}
    return resolved


def apply_attribute_rules(ctx: Any) -> None:
    if not uses_attribute_rules(ctx.mapping): return
    typ = str(ctx.fill.get("product_type#1.value") or "")
    decisions = resolve_attributes(ctx.product_data, ctx.mapping, ctx.template_path, typ)
    from app.pipeline import step10_amazon_template as legacy
    for key, decision in decisions.items():
        attrs = legacy._flatten_mapping_values(ctx.fields.get(key))
        if key == "target_audience": attrs += [v for k,v in ctx.fields.items() if k.startswith("target_audience_")]
        if key == "theme": attrs += legacy._flatten_mapping_values(ctx.fields.get("theme_1"))
        for attr in attrs: ctx.fill.pop(attr, None)
        for attr, value in zip(attrs, decision["values"]): ctx.fill[attr] = value
        if not decision["values"] and key in {"material", "frame_material", "age_range_description", "tire_type", "finish_type", "included_components", "special_features", "closure_type"}:
            ctx.warnings.append(f"属性待补充 {key}: 供应商证据不足或没有匹配的模板允许值。")
