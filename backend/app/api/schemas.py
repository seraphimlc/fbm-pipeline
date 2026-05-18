from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


# ─── Products ───

class ProductCreate(BaseModel):
    gigab2b_url: str
    competitor_asin: str | None = None
    upc: str | None = None
    brand: str = "Vindhvisk"


class ProductUpdate(BaseModel):
    gigab2b_url: str | None = None
    competitor_asin: str | None = None
    upc: str | None = None
    brand: str | None = None
    status: str | None = None
    current_step: int | None = None
    error_message: str | None = None
    categories: Any | None = None
    leaf_category: str | None = None
    listing_title: str | None = None
    listing_bullets: Any | None = None
    listing_search_terms: str | None = None
    listing_title_zh: str | None = None
    listing_bullets_zh: Any | None = None
    listing_search_terms_zh: str | None = None
    listing_primary_keyword: str | None = None


class AplusRegenerateRequest(BaseModel):
    module_position: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=2000)


class ProductResponse(BaseModel):
    id: int
    source_url: str | None = None
    source_item_id: str | None = None
    gigab2b_url: str
    gigab2b_product_id: str | None = None
    competitor_asin: str | None = None
    amazon_asin: str | None = None
    asin_sync_status: str | None = None
    asin_synced_at: datetime | None = None
    asin_sync_error: str | None = None
    aplus_upload_status: str | None = None
    aplus_uploaded_at: datetime | None = None
    aplus_upload_error: str | None = None
    upc: str | None = None
    brand: str = "Vindhvisk"
    status: str
    current_step: int = 0
    current_task_status: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProductListItem(ProductResponse):
    item_code: str | None = None
    title: str | None = None
    leaf_category: str | None = None


class ProductFileEntry(BaseModel):
    name: str
    path: str
    size: int
    modified_at: datetime | None = None
    extracted_dir: str | None = None
    extracted_exists: bool = False
    extracted_files: list[str] = Field(default_factory=list)


class ProductFolderEntry(BaseModel):
    path: str
    exists: bool = False
    file_count: int = 0
    files: list[str] = Field(default_factory=list)


class ProductGeneratedFileResponse(BaseModel):
    id: int
    product_id: int
    file_type: str
    label: str
    path: str
    directory: str | None = None
    metadata_json: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProductDetail(ProductResponse):
    """完整商品详情（含子表数据）"""
    data: "ProductDataResponse | None" = None
    images: "ProductImageResponse | None" = None
    aplus: "ProductAplusResponse | None" = None
    zip_files: list[ProductFileEntry] = Field(default_factory=list)
    generated_files: list[ProductGeneratedFileResponse] = Field(default_factory=list)
    video_folder: ProductFolderEntry | None = None
    aplus_folder: ProductFolderEntry | None = None


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
    shipping_cost: float | None = None
    shipping_cost_min: float | None = None
    shipping_cost_max: float | None = None
    features: str | None = None
    description: str | None = None
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
    pricing_detail: str | None = None
    keywords_top: str | None = None
    keyword_excel_path: str | None = None
    categories: str | None = None
    leaf_category: str | None = None
    listing_title: str | None = None
    listing_bullets: str | None = None
    listing_search_terms: str | None = None
    listing_title_zh: str | None = None
    listing_bullets_zh: str | None = None
    listing_search_terms_zh: str | None = None
    listing_check: str | None = None
    listing_primary_keyword: str | None = None
    listing_removed_keywords: str | None = None
    amazon_template_path: str | None = None
    amazon_template_warnings: str | None = None
    amazon_template_fill_summary: str | None = None
    amazon_template_generated_at: datetime | None = None
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
    items: list[ProductListItem]
    total: int
    page: int
    page_size: int


class CatalogProductResponse(BaseModel):
    id: int
    source_product_id: int
    source_url: str | None = None
    source_item_id: str | None = None
    gigab2b_url: str
    gigab2b_product_id: str | None = None
    competitor_asin: str | None = None
    amazon_asin: str | None = None
    asin_sync_status: str | None = None
    asin_synced_at: datetime | None = None
    asin_sync_error: str | None = None
    aplus_upload_status: str | None = None
    aplus_uploaded_at: datetime | None = None
    aplus_upload_error: str | None = None
    upc: str | None = None
    brand: str = "Vindhvisk"
    item_code: str | None = None
    title: str | None = None
    leaf_category: str | None = None
    status: str
    confirmed_at: datetime | None = None
    imported_at: datetime | None = None
    updated_at: datetime | None = None
    template_risk_level: str | None = None
    template_warnings_count: int | None = None

    model_config = {"from_attributes": True}


class CatalogAsinUpdateRequest(BaseModel):
    amazon_asin: str = Field(..., min_length=10, max_length=10)


class PaginatedCatalogProducts(BaseModel):
    items: list[CatalogProductResponse]
    total: int
    page: int
    page_size: int


class AsinSyncCreateRequest(BaseModel):
    catalog_product_ids: list[int] = Field(..., min_length=1, max_length=1000)
    store: str = Field(default="Andy店-US", max_length=100)


class AsinSyncBatchResponse(BaseModel):
    id: int
    store: str = "Andy店-US"
    status: str
    total_count: int = 0
    success_count: int = 0
    not_found_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class AsinSyncItemResponse(BaseModel):
    id: int
    batch_id: int
    catalog_product_id: int
    product_id: int
    lookup_code: str | None = None
    lookup_type: str | None = None
    matched_code: str | None = None
    amazon_asin: str | None = None
    status: str
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class AsinSyncBatchDetail(AsinSyncBatchResponse):
    items: list[AsinSyncItemResponse] = Field(default_factory=list)


class PaginatedAsinSyncBatches(BaseModel):
    items: list[AsinSyncBatchResponse]
    total: int
    page: int
    page_size: int


class AplusUploadCreateRequest(BaseModel):
    catalog_product_ids: list[int] = Field(..., min_length=1, max_length=1000)
    store: str = Field(default="Andy店-US", max_length=100)
    submit_for_approval: bool = True


class AplusUploadBatchResponse(BaseModel):
    id: int
    store: str = "Andy店-US"
    submit_for_approval: int = 1
    status: str
    total_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class AplusUploadItemResponse(BaseModel):
    id: int
    batch_id: int
    catalog_product_id: int
    product_id: int
    amazon_asin: str | None = None
    item_code: str | None = None
    document_name: str | None = None
    status: str
    uploaded_images: str | None = None
    lingxing_response: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class AplusUploadBatchDetail(AplusUploadBatchResponse):
    items: list[AplusUploadItemResponse] = Field(default_factory=list)


class PaginatedAplusUploadBatches(BaseModel):
    items: list[AplusUploadBatchResponse]
    total: int
    page: int
    page_size: int


class BulkStartRequest(BaseModel):
    product_ids: list[int] = Field(..., min_length=1)


class BulkStartResponse(BaseModel):
    requested: int
    started: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
    started_ids: list[int] = Field(default_factory=list)


class BulkImportResponse(BaseModel):
    created: int
    skipped: int
    skipped_details: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    product_ids: list[int] = Field(default_factory=list)


class WorkbenchOverview(BaseModel):
    running_tasks: int = 0
    manual_review_tasks: int = 0
    failed_tasks: int = 0
    confirmable_tasks: int = 0
    asin_not_synced: int = 0
    asin_attention: int = 0
    aplus_failed: int = 0
    listing_high_risk: int = 0


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
