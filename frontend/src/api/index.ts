import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

// ─── Types ───

export interface Product {
  id: number;
  gigab2b_url: string;
  gigab2b_product_id: string | null;
  competitor_asin: string | null;
  brand: string;
  status: string;
  current_step: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
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
  value_total: number | null;
  estimated_total: number | null;
  image_count: number | null;
  material_dir: string | null;
  suggested_price: number | null;
  cost_total: number | null;
  profit: number | null;
  profit_rate: number | null;
  keywords_top: string | null;
  categories: string | null;
  leaf_category: string | null;
  listing_title: string | null;
  listing_bullets: string | null;
  listing_search_terms: string | null;
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
}

export interface PaginatedProducts {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
}

export interface SystemConfig {
  project_name: string;
  version: string;
  backend_port: number;
  frontend_port: number;
  default_brand: string;
  llm_model: string;
  vlm_model: string;
  gpt_image_model: string;
  product_base_dir: string;
  aplus_concurrency: number;
  poll_interval: number;
  step3_4_parallel: boolean;
  llm_api_configured: boolean;
  vlm_api_configured: boolean;
  gpt_image_api_configured: boolean;
  sellersprite_configured: boolean;
}

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
  completed: 'success',
  failed: 'error',
  paused: 'warning',
};

// ─── API calls ───

export const createProduct = (data: { gigab2b_url: string; competitor_asin?: string; brand?: string }) =>
  api.post<Product>('/products', data);

export const listProducts = (params?: { page?: number; page_size?: number; status?: string }) =>
  api.get<PaginatedProducts>('/products', { params });

export const getProduct = (id: number) =>
  api.get<ProductDetail>(`/products/${id}`);

export const updateProduct = (id: number, data: Partial<Product>) =>
  api.patch<Product>(`/products/${id}`, data);

export const deleteProduct = (id: number) =>
  api.delete(`/products/${id}`);

export const startPipeline = (id: number) =>
  api.post<Product>(`/products/${id}/start`);

export const retryStep = (id: number) =>
  api.post<Product>(`/products/${id}/retry`);

export const pausePipeline = (id: number) =>
  api.post<Product>(`/products/${id}/pause`);

export const getConfig = () =>
  api.get<SystemConfig>('/config');

export const getHealth = () =>
  api.get<{ status: string; version: string }>('/health');

export default api;
