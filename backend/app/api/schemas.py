from pydantic import BaseModel, Field
from datetime import datetime


# ─── Products ───

class ProductCreate(BaseModel):
    gigab2b_url: str
    competitor_asin: str | None = None
    brand: str = "Vindhvisk"


class ProductUpdate(BaseModel):
    gigab2b_url: str | None = None
    competitor_asin: str | None = None
    brand: str | None = None
    status: str | None = None
    current_step: int | None = None
    error_message: str | None = None


class ProductResponse(BaseModel):
    id: int
    gigab2b_url: str
    gigab2b_product_id: str | None = None
    competitor_asin: str | None = None
    brand: str = "Vindhvisk"
    status: str
    current_step: int = 0
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProductDetail(ProductResponse):
    """完整商品详情（含子表数据）"""
    data: "ProductDataResponse | None" = None
    images: "ProductImageResponse | None" = None
    aplus: "ProductAplusResponse | None" = None


# ─── ProductData ───

class ProductDataResponse(BaseModel):
    id: int
    product_id: int
    item_code: str | None = None
    title: str | None = None
    color: str | None = None
    material: str | None = None
    filler: str | None = None
    product_type: str | None = None
    dimension_length: float | None = None
    dimension_width: float | None = None
    dimension_height: float | None = None
    weight: float | None = None
    packages: str | None = None
    value_total: float | None = None
    estimated_total: float | None = None
    features: str | None = None
    variants: str | None = None
    stock: int | None = None
    seller: str | None = None
    origin: str | None = None
    image_count: int | None = None
    material_dir: str | None = None
    suggested_price: float | None = None
    cost_total: float | None = None
    profit: float | None = None
    profit_rate: float | None = None
    keywords_top: str | None = None
    keyword_excel_path: str | None = None
    categories: str | None = None
    leaf_category: str | None = None
    listing_title: str | None = None
    listing_bullets: str | None = None
    listing_search_terms: str | None = None
    listing_check: str | None = None
    listing_primary_keyword: str | None = None
    listing_removed_keywords: str | None = None
    collected_at: datetime | None = None

    model_config = {"from_attributes": True}


# ─── ProductImage ───

class ProductImageResponse(BaseModel):
    id: int
    product_id: int
    contact_sheet_path: str | None = None
    image_analysis: str | None = None
    image_selling_points: str | None = None
    category_style: str | None = None
    main_image_path: str | None = None
    main_image_source: str | None = None
    gallery_images: str | None = None
    gallery_order: str | None = None
    main_image_summary: str | None = None
    analyzed_at: datetime | None = None
    vlm_model: str | None = None

    model_config = {"from_attributes": True}


# ─── ProductAplus ───

class ProductAplusResponse(BaseModel):
    id: int
    product_id: int
    aplus_plan: str | None = None
    aplus_plan_summary: str | None = None
    aplus_scripts: str | None = None
    aplus_scripts_summary: str | None = None
    aplus_images: str | None = None
    aplus_image_count: int | None = None
    aplus_status: str | None = None
    planned_at: datetime | None = None
    scripted_at: datetime | None = None
    generated_at: datetime | None = None
    llm_model: str | None = None

    model_config = {"from_attributes": True}


# ─── Common ───

class PaginatedResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    page_size: int


class StepLogResponse(BaseModel):
    id: int
    product_id: int
    step: int
    status: str
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


# Update forward refs
ProductDetail.model_rebuild()
