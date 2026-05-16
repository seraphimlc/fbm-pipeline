"""
模块5：Listing文案 — 使用 LLM 生成标题、五点描述、Search Terms

输入：模块1采集的商品属性 + 模块3的关键词 + 模块4的类目
输出：listing_title, listing_bullets, listing_search_terms, 中文翻译, listing_check
"""

import json
import logging
import re
from datetime import datetime

from app.config import settings
from app.database import async_session
from app.models import Product, ProductData
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert Amazon listing copywriter specializing in the US marketplace.
Your goal is to write buyer-centered listing copy that attracts the right customers and reduces mismatched clicks.

Core principles:
- Searchable but natural language
- Product truth over keyword stuffing
- Scenario-driven benefits that help shoppers imagine daily use
- Clear answers to buyer doubts about fit, use, durability, etc.
- No exaggeration or unsupported claims

You must output valid JSON only, no markdown fences."""

DEFAULT_LISTING_STRATEGY = """General marketplace strategy:
- Title should be rational and searchable, not poetic. It helps shoppers and Amazon quickly identify the product.
- Five bullets should sell the outcome of owning the product. Turn each important fact into a buyer-relevant result: feature -> usage situation -> practical benefit.
- Use life scenes in bullets when they make the product easier to picture, but keep claims concrete and supported.
- Cover these buyer questions across the five bullets: what is it, why it fits my need, how it feels/works, where I use it, what might cause returns if misunderstood."""

LISTING_STRATEGIES = [
    (
        ("sofas & couches", "sofa", "couch", "sectional", "loveseat"),
        """Sofas & couches strategy:
- Title formula: Brand + primary sofa keyword + configuration/seat count + comfort or construction + fabric/material + room fit + size + color suffix.
- Strong title signals include: sectional sofa, couch, modular, deep seat, oversized, all-foam, fabric type, apartment/living room fit, exact width.
- Five bullets should prioritize: room fit and layout, sitting/lounging comfort, fabric/touch, modular/move-in practicality, assembly and ordering boundaries.
- Good sofa bullets help the buyer picture movie night, apartment lounging, open living rooms, reading/gaming, and whether the sofa can fit through doors or into smaller rooms.
- Reduce returns by clearly stating dimensions, number of pieces, stationary vs sleeper/recliner, assembly expectations, and any limitation visible in the facts.""",
    ),
    (
        ("flashlight", "torch", "lantern", "headlamp", "work light"),
        """Lighting and flashlight strategy:
- Title formula: Brand + core light type + brightness/beam or power source + rechargeable/battery details + durability/use case + pack count.
- Five bullets should translate specs into situations: lighting the walk from car to door, power outage, camping, roadside repair, garage work, dog walking, emergency kit.
- Mention lumens, battery, modes, waterproofing, drop resistance, or runtime only when supported by facts. Avoid survival/safety guarantees.""",
    ),
    (
        ("storage", "organizer", "shelf", "cabinet", "bin", "rack"),
        """Storage and organizer strategy:
- Title formula: Brand + core organizer keyword + capacity/size + material + placement/use case + quantity/color.
- Five bullets should sell order and space recovery: less clutter, faster access, drawer/cabinet/garage fit, easy setup, and what items it realistically holds.
- Include dimensions early so shoppers can judge fit before buying.""",
    ),
    (
        ("pet", "dog", "cat", "pet bed", "litter", "crate"),
        """Pet product strategy:
- Title formula: Brand + pet type/product type + size + material/function + intended pet/use case + color.
- Five bullets should speak to both pet comfort and owner maintenance: cleaning, odor, durability, sizing, home placement.
- Avoid unsupported health, calming, safety, chew-proof, or vet claims.""",
    ),
    (
        ("kid", "kids", "toddler", "baby", "nursery", "children"),
        """Child and nursery product strategy:
- Title formula: Brand + product type + age/size if supported + material/function + room/use case + color.
- Five bullets should help parents evaluate fit, setup, cleaning, and everyday use.
- Be conservative: do not invent safety certifications, age ranges, non-toxic claims, or developmental benefits.""",
    ),
]

LISTING_PROMPT_TEMPLATE = """Generate an Amazon product listing based on the following information.

## Product Attributes
- Title (supplier): {title}
- Brand: {brand}
- Color: {color}
- Material: {material}
- Filler: {filler}
- Product Type: {product_type}
- Dimensions: {length}" L x {width}" W x {height}" H
- Weight: {weight} lbs
- Features: {features}
- Supplier Description: {description}
- Origin: {origin}

## Top Keywords (from competitor analysis)
{keywords_json}

## Category
{category_path}

## Category-Specific Selling Strategy
{category_strategy}

## Strategic Requirements
Before writing copy, build a keyword and positioning strategy. Keywords serve Amazon search relevance; the copy serves buyer click-through and conversion.

Keyword rules:
- Choose one primary keyword that truthfully names the product. Put it in the first 80 characters of the title when possible.
- Put product-identity and high-intent keywords in the title. Do not turn the title into a keyword warehouse.
- Put scenario/use keywords in bullets when they help shoppers understand fit and use.
- Put synonym, long-tail, and secondary terms in Search Terms only when they are not already covered by title/bullets.
- Exclude any keyword that conflicts with product facts. Never use traffic words such as leather, sleeper, recliner, waterproof, certified, non-toxic, etc. unless the facts support them.

Copy rules:
1. **Title** (max 200 chars): Optimize for click-through and algorithm clarity. Use this shape where possible: brand + primary keyword + key type/configuration + strongest factual differentiators + suitable use/room + size/count + color suffix. Put the color at the very end in parentheses, for example "(Brown)"; do not put the color elsewhere if it can be avoided. Avoid more than two commas.
2. **Five Bullets** (each max 500 chars): Each bullet must have one clear selling job and should not repeat the same claim in different words. Turn facts into buyer-relevant outcomes without exaggeration.
3. **Search Terms** (max 250 bytes total, space-separated): Algorithm-only field. Do not repeat words already used in title/bullets. Do not include punctuation or claims not supported by facts.
4. **Compliance Check**: Flag risky claims, unsupported keywords, prohibited words, length/clarity issues, and any conversion risk.
5. **Chinese Translation**: Provide faithful Chinese translations for the title, five bullets, and search terms. Keep meaning accurate; do not add claims.

Bullet structure guidance:
- Bullet 1: strongest purchase reason and product identity.
- Bullet 2: main experience or performance benefit.
- Bullet 3: lifestyle/use scene that makes the product easy to imagine.
- Bullet 4: fit, dimensions, compatibility, setup, maintenance, or included parts.
- Bullet 5: buyer boundary/objection handling to reduce returns.

Output JSON:
{{
  "keyword_plan": {{
    "primary_keyword": "...",
    "title_keywords": ["..."],
    "bullet_keywords": ["..."],
    "search_terms_only": ["..."],
    "excluded_keywords": ["keyword - reason"]
  }},
  "positioning": {{
    "target_buyer": "...",
    "main_click_reason": "...",
    "conversion_risks": ["..."]
  }},
  "title": "...",
  "bullets": ["...", "...", "...", "...", "..."],
  "search_terms": "...",
  "title_zh": "...",
  "bullets_zh": ["...", "...", "...", "...", "..."],
  "search_terms_zh": "...",
  "primary_keyword": "...",
  "compliance_check": {{
    "status": "pass|warning",
    "issues": ["..."]
  }},
  "removed_keywords": ["keywords intentionally excluded and why"]
}}"""


def _build_prompt(product: Product, pd: ProductData) -> str:
    """构建LLM Prompt"""
    # 解析关键词
    keywords = []
    if pd.keywords_top:
        try:
            keywords = json.loads(pd.keywords_top)
        except:
            pass

    # 解析features
    features = "N/A"
    if pd.features:
        try:
            fl = json.loads(pd.features)
            features = "; ".join(fl) if isinstance(fl, list) else str(fl)
        except:
            features = str(pd.features)

    # 类目路径
    category_path = "N/A"
    if pd.categories:
        try:
            cats = json.loads(pd.categories)
            category_path = " > ".join(cats) if isinstance(cats, list) else str(cats)
        except:
            category_path = str(pd.categories)

    keywords_json = json.dumps(keywords, ensure_ascii=False, indent=2) if keywords else "[]"
    category_strategy = _listing_strategy(pd, category_path)

    return LISTING_PROMPT_TEMPLATE.format(
        title=pd.title or "N/A",
        brand=product.brand or settings.DEFAULT_BRAND,
        color=pd.color or "N/A",
        material=pd.material or "N/A",
        filler=pd.filler or "N/A",
        product_type=pd.product_type or "N/A",
        length=pd.dimension_length or "?",
        width=pd.dimension_width or "?",
        height=pd.dimension_height or "?",
        weight=pd.weight or "?",
        features=features,
        description=pd.description or "N/A",
        origin=pd.origin or "N/A",
        keywords_json=keywords_json,
        category_path=category_path,
        category_strategy=category_strategy,
    )


def _listing_strategy(pd: ProductData, category_path: str) -> str:
    haystack = " ".join([
        category_path or "",
        pd.leaf_category or "",
        pd.product_type or "",
        pd.title or "",
        pd.description or "",
    ]).lower()
    for keywords, strategy in LISTING_STRATEGIES:
        if any(keyword in haystack for keyword in keywords):
            return strategy
    return DEFAULT_LISTING_STRATEGY


def _title_with_color_suffix(title: str | None, color: str | None) -> str | None:
    if not title:
        return title
    cleaned = " ".join(str(title).split()).strip()
    color_clean = " ".join(str(color or "").split()).strip()
    if not color_clean or color_clean.upper() == "N/A":
        return cleaned

    suffix = f"({color_clean})"
    if cleaned.lower().endswith(suffix.lower()):
        return cleaned

    # Remove common trailing color forms before adding the house style suffix.
    escaped = re.escape(color_clean)
    cleaned = re.sub(rf"\s*[\-–—,]\s*{escaped}\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"\s*\(\s*{escaped}\s*\)\s*$", "", cleaned, flags=re.IGNORECASE)

    max_base_len = max(1, 200 - len(suffix) - 1)
    if len(cleaned) > max_base_len:
        cleaned = cleaned[:max_base_len].rstrip(" ,;-")
    return f"{cleaned} {suffix}"


def _trim_chars(value: str | None, limit: int) -> tuple[str, bool]:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip(" ,;-"), True


def _trim_utf8_bytes(value: str | None, limit: int) -> tuple[str, bool]:
    words = str(value or "").split()
    selected: list[str] = []
    changed = False
    for word in words:
        candidate = " ".join([*selected, word]) if selected else word
        if len(candidate.encode("utf-8")) <= limit:
            selected.append(word)
        else:
            changed = True
    text = " ".join(selected)
    return text, changed or text != str(value or "").strip()


def _visible_words(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 1
    }


def _dedupe_search_terms(search_terms: str | None, visible_copy: str) -> tuple[str, bool]:
    """去掉标题/五点中已经出现的单词，避免 Search Terms 重复浪费权重。"""
    visible = _visible_words(visible_copy)
    kept: list[str] = []
    seen: set[str] = set()
    changed = False
    for raw in str(search_terms or "").split():
        cleaned = re.sub(r"[^A-Za-z0-9-]", "", raw).strip("-").lower()
        if not cleaned:
            changed = True
            continue
        key = cleaned.replace("-", "")
        if key in seen or key in visible:
            changed = True
            continue
        kept.append(cleaned)
        seen.add(key)
    text = " ".join(kept)
    return text, changed or text != str(search_terms or "").strip()


def _as_text_list(value) -> list[str]:
    if isinstance(value, list):
        return [" ".join(str(item).split()).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [" ".join(line.split()).strip() for line in value.splitlines() if line.strip()]
    return []


def _normalize_listing(listing: dict, color: str | None) -> dict:
    """统一裁剪 Listing 输出，避免超过 Amazon 字段限制。"""
    adjustments: list[str] = []

    title = _title_with_color_suffix(listing.get("title"), color)
    title, changed = _trim_chars(title, settings.STEP5_TITLE_MAX_CHARS)
    if changed:
        adjustments.append(f"title_trimmed_to_{settings.STEP5_TITLE_MAX_CHARS}_chars")
    listing["title"] = title

    bullets = _as_text_list(listing.get("bullets"))[:5]
    normalized_bullets = []
    for bullet in bullets:
        trimmed, changed = _trim_chars(bullet, settings.STEP5_BULLET_MAX_CHARS)
        if changed:
            adjustments.append(f"bullet_trimmed_to_{settings.STEP5_BULLET_MAX_CHARS}_chars")
        normalized_bullets.append(trimmed)
    listing["bullets"] = normalized_bullets

    bullets_zh = _as_text_list(listing.get("bullets_zh"))[:5]
    listing["bullets_zh"] = bullets_zh

    visible_copy = " ".join([title or "", *normalized_bullets])
    search_terms, changed = _dedupe_search_terms(listing.get("search_terms"), visible_copy)
    if changed:
        adjustments.append("search_terms_deduped_against_visible_copy")
    search_terms, changed = _trim_utf8_bytes(
        search_terms,
        settings.STEP5_SEARCH_TERMS_MAX_BYTES,
    )
    if changed:
        adjustments.append(f"search_terms_trimmed_to_{settings.STEP5_SEARCH_TERMS_MAX_BYTES}_bytes")
    listing["search_terms"] = search_terms

    check = listing.get("compliance_check")
    if not isinstance(check, dict):
        check = {"status": "warning", "issues": ["LLM compliance_check missing or invalid"]}
    if len(normalized_bullets) != 5:
        check.setdefault("issues", []).append(f"Expected 5 bullets, got {len(normalized_bullets)}")
        check["status"] = "warning"
    keyword_plan = listing.get("keyword_plan") if isinstance(listing.get("keyword_plan"), dict) else {}
    positioning = listing.get("positioning") if isinstance(listing.get("positioning"), dict) else {}
    primary_keyword = (
        listing.get("primary_keyword")
        or keyword_plan.get("primary_keyword")
        or ""
    )
    listing["primary_keyword"] = primary_keyword
    if primary_keyword and primary_keyword.lower() not in (title or "")[:80].lower():
        check.setdefault("issues", []).append("Primary keyword is not present in the first 80 title characters")
        check["status"] = "warning"
    if (title or "").count(",") > 2:
        check.setdefault("issues", []).append("Title has more than two commas and may read like keyword stuffing")
        check["status"] = "warning"
    check["keyword_plan"] = keyword_plan
    check["positioning"] = positioning
    if adjustments:
        check.setdefault("system_adjustments", []).extend(sorted(set(adjustments)))
        if check.get("status") != "warning":
            check["status"] = "warning"
    listing["compliance_check"] = check
    if not listing.get("removed_keywords") and keyword_plan.get("excluded_keywords"):
        listing["removed_keywords"] = keyword_plan.get("excluded_keywords")

    return listing


async def run_listing(product_id: int) -> dict:
    """
    执行 Listing 文案生成
    
    读取 Step1-4 的数据，调用 LLM 生成 Listing
    """
    async with async_session() as db:
        result = await db.execute(
            select(Product)
            .options(selectinload(Product.data))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if not product or not product.data:
            raise ValueError(f"Product {product_id} not found or no data")

        pd = product.data
        if not pd.title and not pd.product_type:
            raise ValueError("缺少商品基本信息，无法生成Listing")

        # 构建Prompt
        prompt = _build_prompt(product, pd)

        # 调用 LLM
        client = settings.get_llm_client()

        logger.info(f"[Step5] 调用LLM生成Listing: {pd.title}")
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=settings.STEP5_LLM_TEMPERATURE,
            max_tokens=settings.STEP5_LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM 返回空结果")

        try:
            listing = json.loads(content)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"LLM 返回JSON解析失败: {e}")

        listing = _normalize_listing(listing, pd.color)

        # 保存到数据库
        pd.listing_title = listing.get("title")
        pd.listing_bullets = json.dumps(listing.get("bullets", []), ensure_ascii=False)
        pd.listing_search_terms = listing.get("search_terms")
        pd.listing_title_zh = listing.get("title_zh")
        pd.listing_bullets_zh = json.dumps(listing.get("bullets_zh", []), ensure_ascii=False)
        pd.listing_search_terms_zh = listing.get("search_terms_zh")
        pd.listing_check = json.dumps(listing.get("compliance_check", {}), ensure_ascii=False)
        pd.listing_primary_keyword = listing.get("primary_keyword")
        pd.listing_removed_keywords = json.dumps(listing.get("removed_keywords", []), ensure_ascii=False)
        await db.commit()

        logger.info(
            f"[Step5] Listing生成完成: 标题='{listing.get('title', '')[:50]}...', "
            f"主关键词='{listing.get('primary_keyword')}'"
        )
        return listing
