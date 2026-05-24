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
  aplus_upload_status: string | null;
  aplus_uploaded_at: string | null;
  aplus_upload_error: string | null;
  upc: string | null;
  item_code?: string | null;
  title?: string | null;
  brand: string;
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
  aplus_upload_status: string | null;
  aplus_uploaded_at: string | null;
  aplus_upload_error: string | null;
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
  listing_search_terms: string | null;
  listing_title_zh: string | null;
  listing_bullets_zh: string | null;
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

export interface WorkbenchOverview {
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
  5: 'Listing构建',
  6: '主图分析',
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

export const listProducts = (params?: { page?: number; page_size?: number; status?: string; item_id?: string; competitor_asin?: string; upc?: string; created_from?: string; created_to?: string }) =>
  api.get<PaginatedProducts>('/products', { params });

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

export const getWorkbenchOverview = () =>
  api.get<WorkbenchOverview>('/products/overview');

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
  aplus_upload_status?: string;
  stock_sync_status?: string;
  template_risk_level?: string;
  upc?: string;
  category?: string;
  imported_from?: string;
  imported_to?: string;
  stock_synced_from?: string;
  stock_synced_to?: string;
}) => api.get<PaginatedCatalogProducts>('/products/catalog', { params });

export const exportCatalogProducts = (ids: number[]) =>
  api.post<Blob>('/products/catalog/export', ids, { responseType: 'blob', timeout: 300000 });

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

export const listAplusUploadBatches = (params?: { page?: number; page_size?: number }) =>
  api.get<PaginatedAplusUploadBatches>('/products/aplus-upload-batches', { params });

export const getAplusUploadBatch = (id: number) =>
  api.get<AplusUploadBatchDetail>(`/products/aplus-upload-batches/${id}`);

export const getProduct = (id: number) =>
  api.get<ProductDetail>(`/products/${id}`);

export const updateProduct = (id: number, data: Partial<Product> & {
  categories?: string | string[];
  leaf_category?: string;
  listing_title?: string;
  listing_bullets?: string | string[];
  listing_search_terms?: string;
  listing_title_zh?: string;
  listing_bullets_zh?: string | string[];
  listing_search_terms_zh?: string;
  listing_primary_keyword?: string;
}) =>
  api.patch<Product>(`/products/${id}`, data);

export const confirmProduct = (id: number) =>
  api.post<Product>(`/products/${id}/confirm`);

export const deleteProduct = (id: number) =>
  api.delete(`/products/${id}`);

export const startPipeline = (id: number) =>
  api.post<Product>(`/products/${id}/start`);

export const restartPipeline = (id: number) =>
  api.post<Product>(`/products/${id}/restart`);

export const retryStep = (id: number) =>
  api.post<Product>(`/products/${id}/retry`);

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

export const getConfig = () =>
  api.get<SystemConfig>('/config');

export const updateConfig = (data: SystemConfigUpdate) =>
  api.patch<{ status: string; restart_required: boolean; env_file: string; updated_fields: string[] }>('/config', data);

export const getHealth = () =>
  api.get<{ status: string; version: string }>('/health');

export default api;
