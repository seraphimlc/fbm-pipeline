import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

// ─── Types ───

export interface Product {
  id: number;
  source_url?: string | null;
  source_item_id?: string | null;
  gigab2b_url: string;
  gigab2b_product_id: string | null;
  competitor_asin: string | null;
  amazon_asin: string | null;
  asin_sync_status: string | null;
  asin_synced_at: string | null;
  asin_sync_error: string | null;
  amazon_product_status: string | null;
  amazon_product_status_synced_at: string | null;
  amazon_product_status_error: string | null;
  aplus_upload_status: string | null;
  aplus_uploaded_at: string | null;
  aplus_upload_error: string | null;
  aplus_status?: string | null;
  aplus_image_count?: number | null;
  upc: string | null;
  item_code?: string | null;
  title?: string | null;
  brand: string;
  source_data_source_id?: number | null;
  source_site?: string | null;
  source_batch_id?: string | null;
  catalog_exported_at?: string | null;
  catalog_export_task_id?: number | null;
  status: string;
  current_step: number;
  current_task_status?: string | null;
  error_message: string | null;
  leaf_category?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CatalogProduct {
  id: number;
  source_product_id: number;
  source_url?: string | null;
  source_item_id?: string | null;
  gigab2b_url: string;
  gigab2b_product_id: string | null;
  competitor_asin: string | null;
  amazon_asin: string | null;
  asin_sync_status: string | null;
  asin_synced_at: string | null;
  asin_sync_error: string | null;
  amazon_product_status: string | null;
  amazon_product_status_synced_at: string | null;
  amazon_product_status_error: string | null;
  aplus_upload_status: string | null;
  aplus_uploaded_at: string | null;
  aplus_upload_error: string | null;
  aplus_status?: string | null;
  aplus_image_count?: number | null;
  upc: string | null;
  brand: string;
  item_code: string | null;
  title: string | null;
  leaf_category: string | null;
  stock: number | null;
  stock_sync_status: string | null;
  stock_synced_at: string | null;
  stock_sync_error: string | null;
  status: string;
  confirmed_at: string | null;
  exported_at: string | null;
  export_task_id: number | null;
  export_file_path: string | null;
  imported_at: string;
  updated_at: string;
  template_risk_level: string | null;
  template_warnings_count: number | null;
}

export interface ProductData {
  id: number;
  product_id: number;
  item_code: string | null;
  title: string | null;
  color: string | null;
  material: string | null;
  filler: string | null;
  product_type: string | null;
  dimension_length: number | null;
  dimension_width: number | null;
  dimension_height: number | null;
  weight: number | null;
  packages: string | null;
  value_total: number | null;
  estimated_total: number | null;
  shipping_cost: number | null;
  shipping_cost_min: number | null;
  shipping_cost_max: number | null;
  features: string | null;
  description: string | null;
  variants: string | null;
  stock: number | null;
  seller: string | null;
  origin: string | null;
  image_count: number | null;
  material_dir: string | null;
  suggested_price: number | null;
  cost_total: number | null;
  profit: number | null;
  profit_rate: number | null;
  pricing_detail: string | null;
  keywords_top: string | null;
  categories: string | null;
  leaf_category: string | null;
  listing_title: string | null;
  listing_bullets: string | null;
  listing_description: string | null;
  listing_search_terms: string | null;
  listing_title_zh: string | null;
  listing_bullets_zh: string | null;
  listing_description_zh: string | null;
  listing_search_terms_zh: string | null;
  listing_check: string | null;
  listing_primary_keyword: string | null;
  listing_removed_keywords: string | null;
  amazon_template_path: string | null;
  amazon_template_warnings: string | null;
  amazon_template_fill_summary: string | null;
  amazon_template_generated_at: string | null;
  gigab2b_raw_snapshot: string | null;
  [key: string]: unknown;
}

export interface ProductImage {
  id: number;
  product_id: number;
  main_image_path: string | null;
  gallery_images: string | null;
  gallery_order: string | null;
  image_analysis: string | null;
  [key: string]: unknown;
}

export interface ProductAplus {
  id: number;
  product_id: number;
  aplus_plan: string | null;
  aplus_scripts: string | null;
  aplus_images: string | null;
  aplus_status: string | null;
  aplus_image_count: number | null;
  [key: string]: unknown;
}

export interface ProductDetail extends Product {
  data: ProductData | null;
  images: ProductImage | null;
  aplus: ProductAplus | null;
  zip_files: ProductFileEntry[];
  generated_files: ProductGeneratedFile[];
  video_folder: ProductFolderEntry | null;
  aplus_folder: ProductFolderEntry | null;
  amazon_export_preview: Record<string, any> | null;
}

export interface ProductImageReviewQueueItem {
  id: number;
  gigab2b_product_id: string | null;
  status: string;
  current_step: number;
  current_task_status: string | null;
  item_code: string | null;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProductImageReviewQueue {
  items: ProductImageReviewQueueItem[];
  total: number;
  limit: number;
}

export interface ProductImageReviewDetail {
  id: number;
  source_item_id: string | null;
  gigab2b_product_id: string | null;
  status: string;
  current_step: number;
  current_task_status: string | null;
  data: {
    item_code: string | null;
    title: string | null;
  } | null;
  images: {
    id: number | null;
    product_id: number;
    main_image_path: string | null;
    main_image_source: string | null;
    gallery_images: string | null;
    gallery_order: string | null;
    gallery_order_total?: number | null;
    gallery_order_limit?: number | null;
  } | null;
}

export interface ProductCompetitorReviewQueueItem {
  id: number;
  source_item_id: string | null;
  gigab2b_product_id: string | null;
  competitor_asin: string | null;
  status: string;
  current_step: number;
  current_task_status: string | null;
  error_message: string | null;
  item_code: string | null;
  title: string | null;
  leaf_category: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProductCompetitorReviewQueue {
  items: ProductCompetitorReviewQueueItem[];
  total: number;
  limit: number;
}

export interface ProductCompetitorReviewDetail {
  id: number;
  source_item_id: string | null;
  gigab2b_product_id: string | null;
  competitor_asin: string | null;
  status: string;
  current_step: number;
  current_task_status: string | null;
  error_message: string | null;
  leaf_category: string | null;
  data: {
    item_code: string | null;
    title: string | null;
    gigab2b_raw_snapshot: string | null;
  } | null;
  images: {
    id: number | null;
    product_id: number;
    main_image_path: string | null;
    main_image_source: string | null;
  } | null;
}

export interface CategoryOption {
  key: string;
  label: string;
  categories: string[];
  leaf_category: string;
  source: string;
}

export interface ProductFolderEntry {
  path: string;
  exists: boolean;
  file_count: number;
  files: string[];
}

export interface ProductGeneratedFile {
  id: number;
  product_id: number;
  file_type: string;
  label: string;
  path: string;
  directory: string | null;
  metadata_json: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProductFileEntry {
  name: string;
  path: string;
  size: number;
  modified_at: string | null;
  extracted_dir: string | null;
  extracted_exists: boolean;
  extracted_files: string[];
}

export interface PaginatedProducts {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
}

export interface PaginatedCatalogProducts {
  items: CatalogProduct[];
  total: number;
  page: number;
  page_size: number;
}

export interface CatalogExportFile {
  task_id: number;
  task_status: string;
  title: string | null;
  filename: string | null;
  file_path: string | null;
  oss_url: string | null;
  file_size: number | null;
  exported_at: string | null;
  category: string | null;
  categories: string[];
  category_count: number;
  template_name: string | null;
  catalog_product_ids: number[];
  task_product_count: number;
  file_product_count: number;
  success_count: number;
  exported_count: number;
  skipped_count: number;
  failed_count: number;
  report_count: number;
  can_download: boolean;
  created_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
}

export interface PaginatedCatalogExportFiles {
  items: CatalogExportFile[];
  total: number;
  page: number;
  page_size: number;
}

export interface CatalogExportCategorySummary {
  category: string;
  count: number;
  exportable_count: number;
  blocked_count: number;
  template_available: boolean;
  template_name: string | null;
  template_path: string | null;
  template_error: string | null;
  uploaded_template_name: string | null;
  uploaded_template_cache_path: string | null;
  uploaded_template_oss_url: string | null;
  uploaded_template_object_key: string | null;
  uploaded_template_uploaded_at: string | null;
  sample_item_codes: string[];
}

export interface CatalogExportCategories {
  pending: CatalogExportCategorySummary[];
  exported: CatalogExportCategorySummary[];
}

export interface CatalogTemplateUploadResult {
  category: string;
  filename: string;
  cache_path: string;
  object_key: string | null;
  oss_url: string | null;
  uploaded_at: string;
}

export interface CatalogTemplateFileSummary {
  file_id: string;
  file_no: string;
  file_name: string;
  file_status: 'enabled' | 'disabled' | 'unmapped' | string;
  enabled: boolean;
  source: string;
  template_path: string | null;
  oss_object_key: string | null;
  oss_url: string | null;
  support_categories: string[];
  template_errors: string[];
  can_download: boolean;
  can_delete: boolean;
}

export interface InventorySyncBatch {
  id: number;
  status: string;
  total_count: number;
  success_count: number;
  unavailable_count: number;
  failed_count: number;
  skipped_count: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface InventorySyncItem {
  id: number;
  batch_id: number;
  catalog_product_id: number;
  product_id: number;
  gigab2b_product_id: string | null;
  item_code: string | null;
  old_stock: number | null;
  new_stock: number | null;
  availability_status: string | null;
  status: string;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface InventorySyncBatchDetail extends InventorySyncBatch {
  items: InventorySyncItem[];
}

export interface PaginatedInventorySyncBatches {
  items: InventorySyncBatch[];
  total: number;
  page: number;
  page_size: number;
}

export interface GigaSyncBatch {
  id: number;
  task_id: string | null;
  batch_id: string;
  site: string;
  data_source_id?: number | null;
  data_source_name?: string | null;
  fulfillment_mode?: string | null;
  current_category: string | null;
  status: string;
  raw_sku_count: number;
  sku_count: number;
  item_count: number;
  price_count: number;
  inventory_count: number;
  group_count: number;
  deleted_single_sku_group_count: number;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface GigaItem {
  id: number;
  batch_id: string;
  site: string;
  data_source_id?: number | null;
  data_source_name?: string | null;
  fulfillment_mode?: string | null;
  item_code: string;
  parent_sku_code: string | null;
  item_name: string | null;
  category: string | null;
  sku_count: number;
  sku_codes_json: string | null;
  missing_related_skus_json: string | null;
  raw_group_json: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface GigaSku {
  id: number;
  batch_id: string;
  site: string;
  data_source_id?: number | null;
  data_source_name?: string | null;
  fulfillment_mode?: string | null;
  sku_code: string;
  item_code: string | null;
  parent_sku_code: string | null;
  parentage: string | null;
  child_sequence: number | null;
  is_primary_child: number | null;
  product_name: string | null;
  main_image_url: string | null;
  attributes_json: string | null;
  variation_attributes_json: string | null;
  currency: string | null;
  price: number | null;
  effective_price: number | null;
  exclusive_price: number | null;
  discounted_price: number | null;
  shipping_fee: number | null;
  estimated_shipping_fee: number | null;
  seller_available_inventory: number | null;
  total_buyer_available_inventory: number | null;
  availability_status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface GigaInventorySyncResult {
  batch_id: string;
  site: string;
  data_source_id: number | null;
  data_source_name: string | null;
  task_id: string | null;
  total_skus: number;
  success_count: number;
  failed_count: number;
  alert_count: number;
  out_of_stock_count: number;
  restocked_count: number;
  previous_batch_id: string | null;
  pulled_at: string;
  failed_skus: Array<{ sku_code: string; error: string }>;
}

export interface GigaPriceSyncResult {
  batch_id: string;
  site: string;
  data_source_id: number | null;
  data_source_name: string | null;
  task_id: string | null;
  total_skus: number;
  success_count: number;
  failed_count: number;
  alert_count: number;
  price_changed_count: number;
  previous_batch_id: string | null;
  pulled_at: string;
  failed_skus: Array<{ sku_code: string; error: string }>;
}

export interface GigaProductSyncResult {
  batch_id: string;
  site: string;
  data_source_id?: number | null;
  data_source_name?: string | null;
  raw_sku_count: number;
  sku_count: number;
  item_count: number;
  price_count: number;
  inventory_count: number;
  group_count: number;
  deleted_single_sku_group_count: number;
  skipped_existing_count: number;
}

export interface GigaSyncQueuedResult {
  batch_id: string;
  site: string;
  data_source_id: number | null;
  data_source_name: string | null;
  status: string;
  started: boolean;
}

export interface ProductDataSource {
  id: number;
  name: string;
  platform: string;
  site: string;
  country?: string | null;
  fulfillment_mode: string;
  api_base: string | null;
  client_id: string | null;
  client_secret_masked: string | null;
  shipping_cost_mode: string;
  packing_fee: number | null;
  inventory_mode: string;
  enabled: boolean;
  remark: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PaginatedProductDataSources {
  items: ProductDataSource[];
  total: number;
  page: number;
  page_size: number;
}

export interface OfflineTaskStep {
  id: number;
  task_id: number;
  step_type: string;
  title: string;
  status: string;
  data_source_id: number | null;
  data_source_name: string | null;
  site: string | null;
  batch_id: string | null;
  progress_current: number;
  progress_total: number;
  payload_json: string | null;
  result_json: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
}

export interface OfflineTask {
  id: number;
  task_type: string;
  title: string;
  status: string;
  total_steps: number;
  success_steps: number;
  failed_steps: number;
  running_steps: number;
  created_by: string | null;
  payload_json: string | null;
  result_json: string | null;
  error_message: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
}

export interface OfflineTaskDetail extends OfflineTask {
  steps: OfflineTaskStep[];
}

export interface PaginatedOfflineTasks {
  items: OfflineTask[];
  total: number;
  page: number;
  page_size: number;
}

export interface OfflineTaskQueuedResult {
  task: OfflineTask;
  steps: OfflineTaskStep[];
}

export interface OfflineTaskBatchQueuedResult {
  tasks: OfflineTask[];
  errors: string[];
}

export interface AmazonStyleSnapCandidate {
  id: number;
  batch_id: string;
  site: string;
  item_code: string;
  sku_code: string;
  product_name: string | null;
  source_image_url: string | null;
  source_image_path: string | null;
  rank: number;
  asin: string;
  title: string | null;
  url: string | null;
  brand: string | null;
  seller: string | null;
  delivery: string | null;
  price: string | null;
  rating: string | null;
  review_count: string | null;
  leaf_category: string | null;
  category_rank: string | null;
  color: string | null;
  size: string | null;
  style: string | null;
  amazon_image_url: string | null;
  raw_snippet: string | null;
  is_selected: number;
  selected_at: string | null;
  listing_capture_id: number | null;
  listing_capture_status: string | null;
  listing_capture_error: string | null;
  listing_capture_has_main_image: boolean;
  listing_summary: string | null;
  listing_captured_at: string | null;
  captured_at: string | null;
  imported_at: string | null;
  updated_at: string | null;
}

export interface AmazonStyleSnapCandidateGroup {
  batch_id: string;
  site: string;
  item_code: string;
  sku_code: string;
  product_name: string | null;
  source_image_url: string | null;
  source_image_path: string | null;
  selected_candidate_id: number | null;
  product_task_id: number | null;
  product_task_status: string | null;
  task_ready: boolean;
  task_ready_reason: string | null;
  candidates: AmazonStyleSnapCandidate[];
}

export interface GigaInventoryAlert {
  id: number;
  batch_id: string;
  site: string;
  data_source_id: number | null;
  sku_code: string;
  item_code: string | null;
  product_name: string | null;
  previous_batch_id: string | null;
  previous_stock_qty: number | null;
  current_stock_qty: number | null;
  previous_status: string | null;
  current_status: string | null;
  change_type: string;
  message: string;
  created_at: string | null;
}

export interface GigaPriceAlert {
  id: number;
  batch_id: string;
  site: string;
  data_source_id: number | null;
  sku_code: string;
  item_code: string | null;
  product_name: string | null;
  previous_batch_id: string | null;
  previous_effective_price: number | null;
  current_effective_price: number | null;
  previous_price: number | null;
  current_price: number | null;
  previous_exclusive_price: number | null;
  current_exclusive_price: number | null;
  previous_discounted_price: number | null;
  current_discounted_price: number | null;
  previous_shipping_fee: number | null;
  current_shipping_fee: number | null;
  change_type: string;
  message: string;
  created_at: string | null;
}

export interface GigaInventory {
  id: number;
  site: string;
  data_source_id: number | null;
  fulfillment_mode: string | null;
  inventory_mode: string | null;
  sku_code: string;
  item_code: string | null;
  product_name: string | null;
  stock_qty: number | null;
  seller_available_inventory: number | null;
  total_buyer_available_inventory: number | null;
  seller_inventory_distribution: string | null;
  buyer_inventory_distribution: string | null;
  next_arrival_inventory: string | null;
  availability_status: string | null;
  pulled_at: string | null;
  updated_at: string | null;
}

export interface PaginatedGigaSyncBatches {
  items: GigaSyncBatch[];
  total: number;
  page: number;
  page_size: number;
}

export interface PaginatedGigaItems {
  items: GigaItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface PaginatedGigaSkus {
  items: GigaSku[];
  total: number;
  page: number;
  page_size: number;
}

export interface PaginatedGigaInventoryAlerts {
  items: GigaInventoryAlert[];
  total: number;
  page: number;
  page_size: number;
}

export interface PaginatedGigaPriceAlerts {
  items: GigaPriceAlert[];
  total: number;
  page: number;
  page_size: number;
}

export interface PaginatedGigaInventory {
  items: GigaInventory[];
  total: number;
  page: number;
  page_size: number;
  latest_batch_id: string | null;
  pulled_at: string | null;
}

export interface WorkbenchOverview {
  total_products: number;
  select_images: number;
  competitor_searching: number;
  select_competitor: number;
  capture_detail: number;
  ready_to_generate: number;
  running: number;
  suspended: number;
  manual_review: number;
  export_ready: number;
  export_ready_unexported?: number;
  export_ready_exported?: number;
  failed: number;
  running_tasks: number;
  manual_review_tasks: number;
  failed_tasks: number;
  confirmable_tasks: number;
  asin_not_synced: number;
  asin_attention: number;
  aplus_failed: number;
  listing_high_risk: number;
}

export interface UpcPoolSummary {
  total: number;
  available: number;
  bound: number;
}

export interface UpcPoolItem {
  id: number;
  upc: string;
  status: string;
  source: string | null;
  product_id: number | null;
  bound_item_code: string | null;
  bound_source_product_id: string | null;
  bound_source_url: string | null;
  bound_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PaginatedUpcPoolItems {
  items: UpcPoolItem[];
  total: number;
  page: number;
  page_size: number;
  summary: UpcPoolSummary;
}

export interface AsinSyncBatch {
  id: number;
  store: string;
  status: string;
  total_count: number;
  success_count: number;
  not_found_count: number;
  failed_count: number;
  skipped_count: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface AsinSyncItem {
  id: number;
  batch_id: number;
  catalog_product_id: number;
  product_id: number;
  lookup_code: string | null;
  lookup_type: string | null;
  matched_code: string | null;
  amazon_asin: string | null;
  amazon_product_status: string | null;
  status: string;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AsinSyncBatchDetail extends AsinSyncBatch {
  items: AsinSyncItem[];
}

export interface PaginatedAsinSyncBatches {
  items: AsinSyncBatch[];
  total: number;
  page: number;
  page_size: number;
}

export interface AplusUploadBatch {
  id: number;
  store: string;
  submit_for_approval: number;
  status: string;
  total_count: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface AplusUploadItem {
  id: number;
  batch_id: number;
  catalog_product_id: number;
  product_id: number;
  amazon_asin: string | null;
  item_code: string | null;
  document_name: string | null;
  status: string;
  uploaded_images: string | null;
  lingxing_response: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AplusUploadBatchDetail extends AplusUploadBatch {
  items: AplusUploadItem[];
}

export interface PaginatedAplusUploadBatches {
  items: AplusUploadBatch[];
  total: number;
  page: number;
  page_size: number;
}

export interface BulkStartResult {
  requested: number;
  started: number;
  skipped: number;
  errors: string[];
  started_ids: number[];
}

export interface SystemConfig {
  project_name: string;
  version: string;
  backend_port: number;
  frontend_port: number;
  default_brand: string;
  llm_model: string;
  vlm_model: string;
  vlm_use_llm_api: boolean;
  gpt_image_model: string;
  gpt_image_use_llm_api: boolean;
  gpt_image_api_provider: string;
  aplus_image_width: number;
  aplus_image_height: number;
  aplus_image_jpeg_quality: number;
  aplus_image_api_retries: number;
  aplus_image_overwrite_policy: 'skip_success' | 'overwrite_all';
  product_base_dir: string;
  pipeline_max_concurrency: number;
  browser_workflow_concurrency: number;
  bulk_start_max_tasks: number;
  aplus_concurrency: number;
  poll_interval: number;
  step3_4_parallel: boolean;
  step1_extract_retry_attempts: number;
  step1_extract_retry_delay_seconds: number;
  step1_download_timeout_seconds: number;
  step1_material_package_priority: string;
  step1_price_missing_policy: 'fail' | 'manual_review' | 'continue';
  step1_material_missing_policy: 'fail' | 'manual_review' | 'continue';
  step1_allow_existing_materials: boolean;
  pricing_net_revenue_rate: number;
  pricing_target_margin_rate: number;
  pricing_min_profit: number;
  pricing_fixed_cost: number;
  pricing_return_credit_rate: number;
  step3_manual_login_on_auth_failure: boolean;
  step4_missing_asin_policy: 'fail' | 'manual_review' | 'continue';
  step4_category_missing_policy: 'fail' | 'manual_review' | 'continue';
  step4_allow_existing_category: boolean;
  step5_llm_temperature: number;
  step5_llm_max_tokens: number;
  step5_title_max_chars: number;
  step5_bullet_max_chars: number;
  step5_search_terms_max_bytes: number;
  llm_api_configured: boolean;
  vlm_api_configured: boolean;
  gpt_image_api_configured: boolean;
  sellersprite_configured: boolean;
  env_file: string;
}

export type SystemConfigUpdate = Partial<Pick<
  SystemConfig,
  | 'default_brand'
  | 'product_base_dir'
  | 'pipeline_max_concurrency'
  | 'browser_workflow_concurrency'
  | 'bulk_start_max_tasks'
  | 'aplus_concurrency'
  | 'poll_interval'
  | 'step3_4_parallel'
  | 'step1_extract_retry_attempts'
  | 'step1_extract_retry_delay_seconds'
  | 'step1_download_timeout_seconds'
  | 'step1_material_package_priority'
  | 'step1_price_missing_policy'
  | 'step1_material_missing_policy'
  | 'step1_allow_existing_materials'
  | 'pricing_net_revenue_rate'
  | 'pricing_target_margin_rate'
  | 'pricing_min_profit'
  | 'pricing_fixed_cost'
  | 'pricing_return_credit_rate'
  | 'step3_manual_login_on_auth_failure'
  | 'step4_missing_asin_policy'
  | 'step4_category_missing_policy'
  | 'step4_allow_existing_category'
  | 'step5_llm_temperature'
  | 'step5_llm_max_tokens'
  | 'step5_title_max_chars'
  | 'step5_bullet_max_chars'
  | 'step5_search_terms_max_bytes'
  | 'llm_model'
  | 'vlm_model'
  | 'vlm_use_llm_api'
  | 'gpt_image_model'
  | 'gpt_image_use_llm_api'
> & {
	  aplus_image_width: number;
	  aplus_image_height: number;
	  aplus_image_jpeg_quality: number;
	  aplus_image_api_retries: number;
	  aplus_image_overwrite_policy: 'skip_success' | 'overwrite_all';
	}>;

// ─── Step labels ───

export const STEP_LABELS: Record<number, string> = {
  0: '待处理',
  1: '商品采集',
  2: '利润计算',
  3: '关键词获取',
  4: '类目获取',
  5: '图片分析',
  6: 'Listing构建',
  7: 'A+规划',
  8: 'A+脚本',
  9: 'A+出图',
  10: '导入表格',
};

export const STATUS_COLORS: Record<string, string> = {
  created: 'default',
  step1_collecting: 'processing',
  step1_done: 'success',
  step2_pricing: 'processing',
  step2_done: 'success',
  step3_keywords: 'processing',
  step4_category: 'processing',
  step3_4_done: 'success',
  step5_listing: 'processing',
  step5_done: 'success',
  step6_curating: 'processing',
  step6_done: 'success',
  step7_aplus_plan: 'processing',
  step7_done: 'success',
  step8_aplus_script: 'processing',
  step8_done: 'success',
  step9_aplus_image: 'processing',
  step9_done: 'success',
  step10_amazon_template: 'processing',
  step10_done: 'success',
  pending_review: 'warning',
  completed: 'success',
  unavailable: 'default',
  source_unavailable: 'default',
  failed: 'error',
  paused: 'warning',
};

// ─── API calls ───

export const createProduct = (data: { gigab2b_url: string; competitor_asin?: string; upc?: string; brand?: string }) =>
  api.post<Product>('/products', data);

export const listProducts = (params?: { page?: number; page_size?: number; status?: string; item_id?: string; data_source_id?: number; competitor_asin?: string; upc?: string; created_from?: string; created_to?: string }) =>
  api.get<PaginatedProducts>('/products', { params });

export const listProductImageReviewQueue = (params?: { data_source_id?: number; limit?: number }) =>
  api.get<ProductImageReviewQueue>('/products/image-review-queue', { params });

export const getProductImageReviewDetail = (productId: number, params?: { image_limit?: number }) =>
  api.get<ProductImageReviewDetail>(`/products/image-review-detail/${productId}`, { params });

export const listProductCompetitorReviewQueue = (params?: { data_source_id?: number; limit?: number }) =>
  api.get<ProductCompetitorReviewQueue>('/products/competitor-review-queue', { params });

export const getProductCompetitorReviewDetail = (productId: number) =>
  api.get<ProductCompetitorReviewDetail>(`/products/competitor-review-detail/${productId}`);

export const downloadImportTemplate = () =>
  api.get<Blob>('/products/import/template', { responseType: 'blob' });

export const importProducts = (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post<{ created: number; skipped: number; skipped_details: string[]; errors: string[]; product_ids: number[] }>('/products/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
};

export const bulkStartPipelines = (productIds: number[]) =>
  api.post<BulkStartResult>('/products/bulk-start', { product_ids: productIds }, { timeout: 120000 });

export const autoStartReadyGeneration = (params?: { data_source_id?: number; limit?: number }) =>
  api.post<BulkStartResult>('/products/auto-start-ready-generation', null, { params, timeout: 120000 });

export const createProductBulkAdvanceTask = (productIds: number[]) =>
  api.post<OfflineTask>('/products/bulk-advance-task', { product_ids: productIds }, { timeout: 120000 });

export const createProductBulkAdvanceTaskByFilter = (params: {
  status?: string;
  item_id?: string;
  data_source_id?: number;
  competitor_asin?: string;
  upc?: string;
  created_from?: string;
  created_to?: string;
  sku_keyword?: string;
  limit?: number;
}) => api.post<OfflineTask>('/products/bulk-advance-task/by-filter', params, { timeout: 120000 });

export const getWorkbenchOverview = (params?: { data_source_id?: number }) =>
  api.get<WorkbenchOverview>('/products/overview', { params });

export const listUpcPool = (params?: { page?: number; page_size?: number; status?: string; q?: string }) =>
  api.get<PaginatedUpcPoolItems>('/products/upc-pool', { params });

export const importUpcPool = (text: string) =>
  api.post<{ added: number; duplicated: number; invalid: string[]; summary: UpcPoolSummary }>('/products/upc-pool/import', { text });

export const listCategoryOptions = () =>
  api.get<{ items: CategoryOption[] }>('/products/category-options');

export const listCatalogProducts = (params?: {
  page?: number;
  page_size?: number;
  item_id?: string;
  competitor_asin?: string;
  amazon_asin?: string;
  asin_sync_status?: string;
  amazon_product_status?: string;
  aplus_upload_status?: string;
  stock_sync_status?: string;
  template_risk_level?: string;
  upc?: string;
  category?: string;
  export_status?: 'pending' | 'exported';
  imported_from?: string;
  imported_to?: string;
  stock_synced_from?: string;
  stock_synced_to?: string;
}) => api.get<PaginatedCatalogProducts>('/products/catalog', { params });

export const listCatalogExportFiles = (params?: {
  page?: number;
  page_size?: number;
  category?: string;
}) => api.get<PaginatedCatalogExportFiles>('/products/catalog/export-files', { params });

export const listCatalogExportCategories = () =>
  api.get<CatalogExportCategories>('/products/catalog/export-categories');

export const listCatalogTemplateCategories = () =>
  api.get<CatalogExportCategorySummary[]>('/products/catalog/template-categories');

export const listCatalogTemplateFiles = () =>
  api.get<CatalogTemplateFileSummary[]>('/products/catalog/template-files');

export const downloadCatalogTemplateFile = (fileId: string) =>
  api.get<Blob>(`/products/catalog/template-files/${fileId}/download`, { responseType: 'blob', timeout: 300000 });

export const updateCatalogTemplateFileStatus = (fileId: string, enabled: boolean) =>
  api.patch<CatalogTemplateFileSummary>(`/products/catalog/template-files/${fileId}/status`, { enabled });

export const deleteCatalogTemplateFile = (fileId: string) =>
  api.delete<CatalogTemplateFileSummary[]>(`/products/catalog/template-files/${fileId}`);

export const downloadCatalogCategoryTemplate = (category: string) =>
  api.get<Blob>('/products/catalog/category-template-download', { params: { category }, responseType: 'blob', timeout: 300000 });

export const createCatalogExportOfflineTasks = (ids: number[]) =>
  api.post<OfflineTaskBatchQueuedResult>('/offline-tasks/catalog-export', { catalog_product_ids: ids }, { timeout: 30000 });

export const exportCatalogProducts = (ids: number[]) =>
  api.post<Blob>('/products/catalog/export', ids, { responseType: 'blob', timeout: 300000 });

export const exportCatalogProductsByCategory = (category: string) =>
  api.post<Blob>('/products/catalog/export-by-category', { category }, { responseType: 'blob', timeout: 300000 });

export const uploadCatalogCategoryTemplate = (category: string, file: File) => {
  const formData = new FormData();
  formData.append('category', category);
  formData.append('file', file);
  return api.post<CatalogTemplateUploadResult>('/products/catalog/category-template-upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
};

export const exportInventoryUpdateTemplate = (ids: number[]) =>
  api.post<Blob>('/products/catalog/inventory-template/export', ids, { responseType: 'blob', timeout: 300000 });

export const updateCatalogAsin = (catalogId: number, amazonAsin: string) =>
  api.post<CatalogProduct>(`/products/catalog/${catalogId}/asin`, { amazon_asin: amazonAsin });

export const clearCatalogAsin = (catalogId: number) =>
  api.delete<CatalogProduct>(`/products/catalog/${catalogId}/asin`);

export const createInventorySyncBatch = (catalogProductIds?: number[]) =>
  api.post<InventorySyncBatch>('/products/catalog/inventory-sync', { catalog_product_ids: catalogProductIds || null }, { timeout: 120000 });

export const listInventorySyncBatches = (params?: { page?: number; page_size?: number }) =>
  api.get<PaginatedInventorySyncBatches>('/products/inventory-sync-batches', { params });

export const listGigaBatches = (params?: { page?: number; page_size?: number; site?: string; data_source_id?: number; status?: string }) =>
  api.get<PaginatedGigaSyncBatches>('/giga/batches', { params });

export const syncMissingGigaProducts = (body: { site?: string; data_source_id: number; task_id?: string | null; current_category?: string | null; page_size?: number | null; max_pages?: number | null }) =>
  api.post<GigaProductSyncResult>('/giga/sync-missing', body, { timeout: 600000 });

export const syncMissingGigaProductsBackground = (body: { site?: string; data_source_id: number; task_id?: string | null; current_category?: string | null; page_size?: number | null; max_pages?: number | null }) =>
  api.post<GigaSyncQueuedResult>('/giga/sync-missing/background', body, { timeout: 30000 });

export const createGigaPullOfflineTask = (body: { data_source_ids: number[]; current_category?: string | null; page_size?: number | null; max_pages?: number | null }) =>
  api.post<OfflineTaskQueuedResult>('/offline-tasks/giga-pull', body, { timeout: 30000 });

export const createGigaInventorySyncOfflineTask = (body: { data_source_ids: number[]; sku_codes?: string[] | null }) =>
  api.post<OfflineTaskQueuedResult>('/offline-tasks/giga-inventory-sync', body, { timeout: 30000 });

export const createGigaPriceSyncOfflineTask = (body: { data_source_ids: number[]; sku_codes?: string[] | null }) =>
  api.post<OfflineTaskQueuedResult>('/offline-tasks/giga-price-sync', body, { timeout: 30000 });

export const listOfflineTasks = (params?: { page?: number; page_size?: number; task_type?: string; status?: string; include_progress?: boolean }) =>
  api.get<PaginatedOfflineTasks>('/offline-tasks', { params });

export const getOfflineTask = (id: number) =>
  api.get<OfflineTaskDetail>(`/offline-tasks/${id}`);

export const rerunOfflineTask = (id: number) =>
  api.post<OfflineTaskDetail>(`/offline-tasks/${id}/rerun`);

export const pauseOfflineTask = (id: number) =>
  api.post<OfflineTaskDetail>(`/offline-tasks/${id}/pause`);

export const resumeOfflineTask = (id: number) =>
  api.post<OfflineTaskDetail>(`/offline-tasks/${id}/resume`);

export const downloadOfflineTaskResult = (id: number) =>
  api.get<Blob>(`/offline-tasks/${id}/download`, { responseType: 'blob', timeout: 300000 });

export const listGigaItems = (params: { batch_id?: string; site?: string; data_source_id?: number; page?: number; page_size?: number; sku_code?: string }) =>
  api.get<PaginatedGigaItems>('/giga/items', { params });

export const listGigaSkus = (params: { batch_id: string; site?: string; data_source_id?: number; item_code?: string; page?: number; page_size?: number }) =>
  api.get<PaginatedGigaSkus>('/giga/skus', { params });

export const listProductDataSources = (params?: { page?: number; page_size?: number; platform?: string; site?: string; enabled?: boolean }) =>
  api.get<PaginatedProductDataSources>('/product-data-sources', { params });

export const createProductDataSource = (body: Partial<ProductDataSource> & { name: string; site: string; client_secret?: string | null }) =>
  api.post<ProductDataSource>('/product-data-sources', body);

export const updateProductDataSource = (id: number, body: Partial<ProductDataSource> & { client_secret?: string | null }) =>
  api.patch<ProductDataSource>(`/product-data-sources/${id}`, body);

export const deleteProductDataSource = (id: number) =>
  api.delete<ProductDataSource>(`/product-data-sources/${id}`);

export const listGigaInventory = (params: { site: string; data_source_id?: number; page?: number; page_size?: number; sku_code?: string; availability_status?: string }) =>
  api.get<PaginatedGigaInventory>('/giga/inventory', { params });

export const syncGigaInventory = (body: { batch_id: string; site: string; data_source_id: number; task_id?: string | null; sku_codes?: string[] | null }) =>
  api.post<GigaInventorySyncResult>('/giga/inventory/sync', body, { timeout: 300000 });

export const syncGigaPrice = (body: { batch_id: string; site: string; data_source_id: number; task_id?: string | null; sku_codes?: string[] | null }) =>
  api.post<GigaPriceSyncResult>('/giga/price/sync', body, { timeout: 300000 });

export const listGigaInventoryAlerts = (params: { site: string; data_source_id?: number; batch_id?: string; change_type?: string; page?: number; page_size?: number }) =>
  api.get<PaginatedGigaInventoryAlerts>('/giga/inventory/alerts', { params });

export const listGigaPriceAlerts = (params: { site: string; data_source_id?: number; batch_id?: string; change_type?: string; page?: number; page_size?: number }) =>
  api.get<PaginatedGigaPriceAlerts>('/giga/price/alerts', { params });

export const listProductCompetitorCandidates = (productId: number, params?: { enrich_images?: boolean }) =>
  api.get<AmazonStyleSnapCandidateGroup>(`/amazon-stylesnap/products/${productId}/competitor-candidates`, { params });

export const searchProductCompetitorCandidates = (productId: number, force = false) =>
  api.post<Product>(
    `/amazon-stylesnap/products/${productId}/competitor-candidates/search`,
    null,
    { params: { force }, timeout: 60000 },
  );

export const selectProductCompetitorCandidate = (productId: number, candidateId: number, forceCapture = false) =>
  api.post<AmazonStyleSnapCandidateGroup>(
    `/amazon-stylesnap/products/${productId}/competitor-candidates/${candidateId}/select`,
    null,
    { params: { force_capture: forceCapture }, timeout: 180000 },
  );

export const retryProductCompetitorCandidateCapture = (productId: number, candidateId: number, force = true) =>
  api.post<AmazonStyleSnapCandidateGroup>(
    `/amazon-stylesnap/products/${productId}/competitor-candidates/${candidateId}/capture`,
    null,
    { params: { force }, timeout: 60000 },
  );

export const getInventorySyncBatch = (id: number) =>
  api.get<InventorySyncBatchDetail>(`/products/inventory-sync-batches/${id}`);

export const createAsinSyncBatch = (catalogProductIds: number[], store = 'Andy店-US') =>
  api.post<AsinSyncBatch>('/products/catalog/asin-sync', { catalog_product_ids: catalogProductIds, store }, { timeout: 120000 });

export const listAsinSyncBatches = (params?: { page?: number; page_size?: number }) =>
  api.get<PaginatedAsinSyncBatches>('/products/asin-sync-batches', { params });

export const getAsinSyncBatch = (id: number) =>
  api.get<AsinSyncBatchDetail>(`/products/asin-sync-batches/${id}`);

export const createAplusUploadBatch = (catalogProductIds: number[], store = 'Andy店-US', submitForApproval = true) =>
  api.post<AplusUploadBatch>('/products/catalog/aplus-upload', { catalog_product_ids: catalogProductIds, store, submit_for_approval: submitForApproval }, { timeout: 120000 });

export const createAplusGenerateBatch = (catalogProductIds: number[], force = false) =>
  api.post<BulkStartResult>('/products/catalog/aplus-generate', { catalog_product_ids: catalogProductIds, force }, { timeout: 120000 });

export const listAplusUploadBatches = (params?: { page?: number; page_size?: number }) =>
  api.get<PaginatedAplusUploadBatches>('/products/aplus-upload-batches', { params });

export const getAplusUploadBatch = (id: number) =>
  api.get<AplusUploadBatchDetail>(`/products/aplus-upload-batches/${id}`);

export const getProduct = (id: number, params?: { compact?: boolean }) =>
  api.get<ProductDetail>(`/products/${id}`, { params });

export const updateProduct = (id: number, data: Partial<Product> & {
  categories?: string | string[];
  leaf_category?: string;
  listing_title?: string;
  listing_bullets?: string | string[];
  listing_description?: string;
  listing_search_terms?: string;
  listing_title_zh?: string;
  listing_bullets_zh?: string | string[];
  listing_description_zh?: string;
  listing_search_terms_zh?: string;
  listing_primary_keyword?: string;
  main_image_path?: string | null;
  gallery_images?: string[];
}) =>
  api.patch<Product>(`/products/${id}`, data);

export const updateProductListingImages = (id: number, data: {
  main_image_path: string;
  gallery_images: string[];
}) =>
  api.put<ProductImage>(`/products/${id}/listing-images`, data);

export const confirmProduct = (id: number) =>
  api.post<Product>(`/products/${id}/confirm`);

export const deleteProduct = (id: number) =>
  api.delete(`/products/${id}`);

export const refreshProductFromGiga = (id: number, data?: { data_source_id?: number | null; item_code?: string | null; sku_codes?: string[] }) =>
  api.post<Product>(`/products/${id}/refresh-giga`, data || {});

export const restartPipeline = (id: number) =>
  api.post<Product>(`/products/${id}/restart`);

export const retryStep = (id: number) =>
  api.post<Product>(`/products/${id}/retry`);

export const runProductFromStep = (id: number, startStep = 5) =>
  api.post<Product>(`/products/${id}/run-from-step`, null, { params: { start_step: startStep } });

export const resumePipeline = (id: number) =>
  api.post<Product>(`/products/${id}/resume`);

export const runPipelineStep = (id: number, step: number) =>
  api.post<{ status: string; step: number; data: unknown }>(`/products/${id}/step/${step}`, null, { timeout: 240000 });

export const pausePipeline = (id: number) =>
  api.post<Product>(`/products/${id}/pause`);

export const openProductFile = (id: number, path?: string, directory?: boolean) =>
  api.post<{ status: string; path: string }>(`/products/${id}/files/open`, null, { params: { path, directory } });

export const extractProductZip = (id: number, path: string) =>
  api.post<{ status: string; extracted_dir: string; files: string[] }>(`/products/${id}/files/extract`, null, { params: { path } });

export const regenerateAplusModule = (id: number, data: { module_position: number; reason: string }) =>
  api.post<{ status: string; message: string; module_position: number; task_id: number }>(`/products/${id}/aplus/regenerate`, data);

export const retryAplusRegeneration = (id: number) =>
  api.post<{ status: string; message: string; task_ids: number[]; module_positions: number[] }>(`/products/${id}/aplus/regenerate/retry`);

export const generateProductAplus = (id: number, force = false) =>
  api.post<{ status: string; product_id: number; task_id?: number | null }>(`/products/${id}/aplus/generate`, null, { params: { force }, timeout: 120000 });

export const getConfig = () =>
  api.get<SystemConfig>('/config');

export const updateConfig = (data: SystemConfigUpdate) =>
  api.patch<{ status: string; restart_required: boolean; env_file: string; updated_fields: string[] }>('/config', data);

export const getHealth = () =>
  api.get<{ status: string; version: string }>('/health');

export default api;
