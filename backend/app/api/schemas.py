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
    listing_description: str | None = None
    listing_search_terms_zh: str | None = None
    listing_description_zh: str | None = None
    listing_primary_keyword: str | None = None
    main_image_path: str | None = None
    gallery_images: Any | None = None


class ProductListingImagesUpdate(BaseModel):
    main_image_path: str
    gallery_images: list[str] = Field(default_factory=list)


class ProductGigaRefreshRequest(BaseModel):
    data_source_id: int | None = None
    item_code: str | None = None
    sku_codes: list[str] = Field(default_factory=list)


class UpcPoolImportRequest(BaseModel):
    text: str = Field(..., min_length=1)


class UpcPoolItemResponse(BaseModel):
    id: int
    upc: str
    status: str
    source: str | None = None
    product_id: int | None = None
    bound_item_code: str | None = None
    bound_source_product_id: str | None = None
    bound_source_url: str | None = None
    bound_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class UpcPoolSummary(BaseModel):
    total: int
    available: int
    bound: int


class ProductDataSourceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    platform: str = Field(default="giga", max_length=30)
    site: str = Field(..., min_length=1, max_length=20)
    country: str | None = Field(default=None, min_length=1, max_length=20)
    fulfillment_mode: str = Field(default="dropship", max_length=30)
    api_base: str | None = None
    client_id: str | None = None
    shipping_cost_mode: str = Field(default="giga_shipping_fee", max_length=30)
    packing_fee: float | None = Field(default=None, ge=0)
    inventory_mode: str = Field(default="available_qty", max_length=30)
    enabled: bool = True
    remark: str | None = None


class ProductDataSourceCreate(ProductDataSourceBase):
    client_secret: str | None = None


class ProductDataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    platform: str | None = Field(default=None, max_length=30)
    site: str | None = Field(default=None, min_length=1, max_length=20)
    country: str | None = Field(default=None, min_length=1, max_length=20)
    fulfillment_mode: str | None = Field(default=None, max_length=30)
    api_base: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    shipping_cost_mode: str | None = Field(default=None, max_length=30)
    packing_fee: float | None = Field(default=None, ge=0)
    inventory_mode: str | None = Field(default=None, max_length=30)
    enabled: bool | None = None
    remark: str | None = None


class ProductDataSourceResponse(ProductDataSourceBase):
    id: int
    client_secret_masked: str | None = None
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedProductDataSources(BaseModel):
    items: list[ProductDataSourceResponse]
    total: int
    page: int
    page_size: int


class OfflineTaskStepResponse(BaseModel):
    id: int
    task_id: int
    step_type: str
    title: str
    status: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    site: str | None = None
    batch_id: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    payload_json: str | None = None
    result_json: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class OfflineTaskResponse(BaseModel):
    id: int
    task_type: str
    title: str
    status: str
    total_steps: int = 0
    success_steps: int = 0
    failed_steps: int = 0
    running_steps: int = 0
    created_by: str | None = None
    payload_json: str | None = None
    result_json: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class OfflineTaskDetailResponse(OfflineTaskResponse):
    steps: list[OfflineTaskStepResponse] = Field(default_factory=list)


class PaginatedOfflineTasks(BaseModel):
    items: list[OfflineTaskResponse]
    total: int
    page: int
    page_size: int


class OfflineTaskGigaPullRequest(BaseModel):
    data_source_ids: list[int] = Field(..., min_length=1, max_length=20)
    current_category: str | None = Field(default=None, max_length=200)
    page_size: int | None = Field(default=None, ge=1, le=200)
    max_pages: int | None = Field(default=None, ge=1)


class OfflineTaskGigaDynamicSyncRequest(BaseModel):
    data_source_ids: list[int] = Field(..., min_length=1, max_length=20)
    sku_codes: list[str] | None = Field(default=None, max_length=5000)


class OfflineTaskCatalogExportRequest(BaseModel):
    catalog_product_ids: list[int] = Field(..., min_length=1, max_length=1000)


class OfflineTaskQueuedResponse(BaseModel):
    task: OfflineTaskResponse
    steps: list[OfflineTaskStepResponse] = Field(default_factory=list)


class OfflineTaskBatchQueuedResponse(BaseModel):
    tasks: list[OfflineTaskResponse] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GigaSyncRequest(BaseModel):
    batch_id: str = Field(..., min_length=1, max_length=100)
    site: str = Field(default="US", min_length=1, max_length=20)
    data_source_id: int = Field(..., ge=1)
    task_id: str | None = Field(default=None, max_length=100)
    current_category: str | None = Field(default=None, max_length=200)
    page_size: int | None = Field(default=None, ge=1, le=200)
    max_pages: int | None = Field(default=None, ge=1)
    skip_existing: bool = False


class GigaSyncMissingRequest(BaseModel):
    batch_id: str | None = Field(default=None, min_length=1, max_length=100)
    site: str = Field(default="US", min_length=1, max_length=20)
    data_source_id: int = Field(..., ge=1)
    task_id: str | None = Field(default=None, max_length=100)
    current_category: str | None = Field(default=None, max_length=200)
    page_size: int | None = Field(default=None, ge=1, le=200)
    max_pages: int | None = Field(default=None, ge=1)


class GigaSyncResponse(BaseModel):
    batch_id: str
    site: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    raw_sku_count: int
    sku_count: int
    item_count: int
    price_count: int
    inventory_count: int
    group_count: int
    deleted_single_sku_group_count: int
    skipped_existing_count: int = 0


class GigaSyncQueuedResponse(BaseModel):
    batch_id: str
    site: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    status: str
    started: bool


class GigaInventorySyncRequest(BaseModel):
    batch_id: str = Field(..., min_length=1, max_length=100)
    site: str = Field(..., min_length=1, max_length=20)
    data_source_id: int = Field(..., ge=1)
    task_id: str | None = Field(default=None, max_length=100)
    sku_codes: list[str] | None = Field(default=None, max_length=5000)


class GigaInventorySyncResponse(BaseModel):
    batch_id: str
    site: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    task_id: str | None = None
    total_skus: int
    success_count: int
    failed_count: int
    alert_count: int
    out_of_stock_count: int
    restocked_count: int
    previous_batch_id: str | None = None
    pulled_at: datetime
    failed_skus: list[dict[str, str]] = Field(default_factory=list)


class GigaPriceSyncRequest(BaseModel):
    batch_id: str = Field(..., min_length=1, max_length=100)
    site: str = Field(..., min_length=1, max_length=20)
    data_source_id: int = Field(..., ge=1)
    task_id: str | None = Field(default=None, max_length=100)
    sku_codes: list[str] | None = Field(default=None, max_length=5000)


class GigaPriceSyncResponse(BaseModel):
    batch_id: str
    site: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    task_id: str | None = None
    total_skus: int
    success_count: int
    failed_count: int
    alert_count: int = 0
    price_changed_count: int = 0
    previous_batch_id: str | None = None
    pulled_at: datetime
    failed_skus: list[dict[str, str]] = Field(default_factory=list)


class GigaSyncBatchResponse(BaseModel):
    id: int
    task_id: str | None = None
    batch_id: str
    site: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    fulfillment_mode: str | None = None
    current_category: str | None = None
    status: str
    raw_sku_count: int = 0
    sku_count: int = 0
    item_count: int = 0
    price_count: int = 0
    inventory_count: int = 0
    group_count: int = 0
    deleted_single_sku_group_count: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedGigaSyncBatches(BaseModel):
    items: list[GigaSyncBatchResponse]
    total: int
    page: int
    page_size: int


class GigaGroupResponse(BaseModel):
    id: int
    batch_id: str
    site: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    fulfillment_mode: str | None = None
    group_code: str
    parent_sku_code: str | None = None
    current_category: str | None = None
    item_codes_json: str
    sku_codes_json: str
    variation_keys_json: str | None = None
    group_size: int
    deleted_single_sku_group: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedGigaGroups(BaseModel):
    items: list[GigaGroupResponse]
    total: int
    page: int
    page_size: int


class GigaItemResponse(BaseModel):
    id: int
    batch_id: str
    site: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    fulfillment_mode: str | None = None
    item_code: str
    parent_sku_code: str | None = None
    item_name: str | None = None
    category: str | None = None
    sku_count: int
    sku_codes_json: str | None = None
    missing_related_skus_json: str | None = None
    raw_group_json: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedGigaItems(BaseModel):
    items: list[GigaItemResponse]
    total: int
    page: int
    page_size: int


class GigaSkuResponse(BaseModel):
    id: int
    giga_item_id: int | None = None
    batch_id: str
    site: str
    data_source_id: int | None = None
    data_source_name: str | None = None
    fulfillment_mode: str | None = None
    sku_code: str
    item_code: str | None = None
    parent_sku_code: str | None = None
    parentage: str | None = None
    child_sequence: int | None = None
    is_primary_child: int | None = None
    product_name: str | None = None
    main_image_url: str | None = None
    description: str | None = None
    attributes_json: str | None = None
    variation_attributes_json: str | None = None
    currency: str | None = None
    price: float | None = None
    effective_price: float | None = None
    exclusive_price: float | None = None
    discounted_price: float | None = None
    shipping_fee: float | None = None
    estimated_shipping_fee: float | None = None
    seller_available_inventory: int | None = None
    total_buyer_available_inventory: int | None = None
    availability_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PaginatedGigaSkus(BaseModel):
    items: list[GigaSkuResponse]
    total: int
    page: int
    page_size: int


class GigaProductImageResponse(BaseModel):
    id: int
    batch_id: str
    site: str
    data_source_id: int | None = None
    item_code: str | None = None
    sku_code: str
    image_url: str
    local_path: str | None = None
    image_type: str | None = None
    sort_order: int | None = None
    file_size: int | None = None
    mime_type: str | None = None
    download_status: str
    error_message: str | None = None
    pulled_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedGigaProductImages(BaseModel):
    items: list[GigaProductImageResponse]
    total: int
    page: int
    page_size: int


class GigaInventoryAlertResponse(BaseModel):
    id: int
    batch_id: str
    site: str
    data_source_id: int | None = None
    sku_code: str
    item_code: str | None = None
    product_name: str | None = None
    previous_batch_id: str | None = None
    previous_stock_qty: int | None = None
    current_stock_qty: int | None = None
    previous_status: str | None = None
    current_status: str | None = None
    change_type: str
    message: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedGigaInventoryAlerts(BaseModel):
    items: list[GigaInventoryAlertResponse]
    total: int
    page: int
    page_size: int


class GigaPriceAlertResponse(BaseModel):
    id: int
    batch_id: str
    site: str
    data_source_id: int | None = None
    sku_code: str
    item_code: str | None = None
    product_name: str | None = None
    previous_batch_id: str | None = None
    previous_effective_price: float | None = None
    current_effective_price: float | None = None
    previous_price: float | None = None
    current_price: float | None = None
    previous_exclusive_price: float | None = None
    current_exclusive_price: float | None = None
    previous_discounted_price: float | None = None
    current_discounted_price: float | None = None
    previous_shipping_fee: float | None = None
    current_shipping_fee: float | None = None
    change_type: str
    message: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedGigaPriceAlerts(BaseModel):
    items: list[GigaPriceAlertResponse]
    total: int
    page: int
    page_size: int


class GigaInventoryResponse(BaseModel):
    id: int
    site: str
    data_source_id: int | None = None
    fulfillment_mode: str | None = None
    inventory_mode: str | None = None
    sku_code: str
    item_code: str | None = None
    product_name: str | None = None
    stock_qty: int | None = None
    seller_available_inventory: int | None = None
    total_buyer_available_inventory: int | None = None
    seller_inventory_distribution: str | None = None
    buyer_inventory_distribution: str | None = None
    next_arrival_inventory: str | None = None
    availability_status: str | None = None
    pulled_at: datetime | None = None
    updated_at: datetime | None = None


class PaginatedGigaInventory(BaseModel):
    items: list[GigaInventoryResponse]
    total: int
    page: int
    page_size: int
    latest_batch_id: str | None = None
    pulled_at: datetime | None = None


class AmazonStyleSnapCandidateResponse(BaseModel):
    id: int
    batch_id: str
    site: str
    item_code: str
    sku_code: str
    product_name: str | None = None
    source_image_url: str | None = None
    source_image_path: str | None = None
    rank: int
    asin: str
    url: str | None = None
    brand: str | None = None
    seller: str | None = None
    delivery: str | None = None
    price: str | None = None
    rating: str | None = None
    category_rank: str | None = None
    color: str | None = None
    size: str | None = None
    style: str | None = None
    amazon_image_url: str | None = None
    raw_snippet: str | None = None
    is_selected: int = 0
    selected_at: datetime | None = None
    listing_capture_id: int | None = None
    listing_capture_status: str | None = None
    listing_captured_at: datetime | None = None
    captured_at: datetime | None = None
    imported_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class AmazonStyleSnapCandidateGroupResponse(BaseModel):
    batch_id: str
    site: str
    item_code: str
    sku_code: str
    product_name: str | None = None
    source_image_url: str | None = None
    source_image_path: str | None = None
    selected_candidate_id: int | None = None
    product_task_id: int | None = None
    product_task_status: str | None = None
    task_ready: bool = False
    task_ready_reason: str | None = None
    candidates: list[AmazonStyleSnapCandidateResponse]


class UpcPoolImportResponse(BaseModel):
    added: int
    duplicated: int
    invalid: list[str] = Field(default_factory=list)
    summary: UpcPoolSummary


class PaginatedUpcPoolItems(BaseModel):
    items: list[UpcPoolItemResponse]
    total: int
    page: int
    page_size: int
    summary: UpcPoolSummary


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
    amazon_product_status: str | None = None
    amazon_product_status_synced_at: datetime | None = None
    amazon_product_status_error: str | None = None
    aplus_upload_status: str | None = None
    aplus_uploaded_at: datetime | None = None
    aplus_upload_error: str | None = None
    aplus_status: str | None = None
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
    amazon_export_preview: dict[str, Any] | None = None


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
    gigab2b_raw_snapshot: str | None = None
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
    listing_description: str | None = None
    listing_search_terms_zh: str | None = None
    listing_description_zh: str | None = None
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
    amazon_product_status: str | None = None
    amazon_product_status_synced_at: datetime | None = None
    amazon_product_status_error: str | None = None
    aplus_upload_status: str | None = None
    aplus_uploaded_at: datetime | None = None
    aplus_upload_error: str | None = None
    aplus_status: str | None = None
    aplus_image_count: int | None = None
    upc: str | None = None
    brand: str = "Vindhvisk"
    item_code: str | None = None
    title: str | None = None
    leaf_category: str | None = None
    stock: int | None = None
    stock_sync_status: str | None = None
    stock_synced_at: datetime | None = None
    stock_sync_error: str | None = None
    status: str
    confirmed_at: datetime | None = None
    exported_at: datetime | None = None
    export_task_id: int | None = None
    export_file_path: str | None = None
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


class CatalogExportCategorySummary(BaseModel):
    category: str
    count: int = 0
    exportable_count: int = 0
    blocked_count: int = 0
    template_available: bool = False
    template_name: str | None = None
    template_path: str | None = None
    template_error: str | None = None
    uploaded_template_name: str | None = None
    uploaded_template_cache_path: str | None = None
    uploaded_template_oss_url: str | None = None
    uploaded_template_object_key: str | None = None
    uploaded_template_uploaded_at: datetime | None = None
    sample_item_codes: list[str] = Field(default_factory=list)


class CatalogExportCategoriesResponse(BaseModel):
    pending: list[CatalogExportCategorySummary]
    exported: list[CatalogExportCategorySummary]


class CatalogExportByCategoryRequest(BaseModel):
    category: str = Field(..., min_length=1)


class CatalogTemplateUploadResponse(BaseModel):
    category: str
    filename: str
    cache_path: str
    object_key: str | None = None
    oss_url: str | None = None
    uploaded_at: datetime


class CatalogTemplateFileSummary(BaseModel):
    file_id: str
    file_no: str
    file_name: str
    file_status: str
    enabled: bool = True
    source: str
    template_path: str | None = None
    oss_object_key: str | None = None
    oss_url: str | None = None
    support_categories: list[str] = Field(default_factory=list)
    template_errors: list[str] = Field(default_factory=list)
    can_download: bool = True
    can_delete: bool = False


class InventorySyncCreateRequest(BaseModel):
    catalog_product_ids: list[int] | None = Field(default=None, max_length=5000)


class InventorySyncBatchResponse(BaseModel):
    id: int
    status: str
    total_count: int = 0
    success_count: int = 0
    unavailable_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class InventorySyncItemResponse(BaseModel):
    id: int
    batch_id: int
    catalog_product_id: int
    product_id: int
    gigab2b_product_id: str | None = None
    item_code: str | None = None
    old_stock: int | None = None
    new_stock: int | None = None
    availability_status: str | None = None
    status: str
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class InventorySyncBatchDetail(InventorySyncBatchResponse):
    items: list[InventorySyncItemResponse] = Field(default_factory=list)


class PaginatedInventorySyncBatches(BaseModel):
    items: list[InventorySyncBatchResponse]
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
    amazon_product_status: str | None = None
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


class AplusGenerateRequest(BaseModel):
    catalog_product_ids: list[int] = Field(..., min_length=1, max_length=1000)
    force: bool = False


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
