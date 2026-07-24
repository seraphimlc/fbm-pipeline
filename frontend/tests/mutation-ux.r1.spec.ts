import { expect, test, type Locator, type Page } from '@playwright/test';

import { mutationInventory, type MutationCallsiteId } from '../src/api/mutationInventory.generated';


const REMOTE_READ_ONLY_MESSAGE = '当前是远程只读访问';
const UNHANDLED_REJECTION_PREFIX = '__R1_UNHANDLED_REJECTION__:';
const observedRuntimeIds = new Set<MutationCallsiteId>();

type MutationCollector = {
  ids: string[];
  interceptorId: number;
};

type FixtureOptions = {
  catalogProduct?: Record<string, unknown>;
  config?: Record<string, unknown>;
  imageReviewDetail?: Record<string, unknown>;
  imageReviewQueue?: Record<string, unknown>[];
  offlineTask?: Record<string, unknown>;
  product?: Record<string, unknown>;
  productDataSource?: Record<string, unknown>;
  taskRun?: Record<string, unknown>;
  taskRunDetail?: Record<string, unknown>;
  templateCategories?: Record<string, unknown>[];
  templateFiles?: Record<string, unknown>[];
  mutationDelayMs?: number;
};

const productDataSourceFixture = {
  id: 1,
  name: 'R1 Amazon Test Source',
  platform: 'giga',
  sales_channel: 'amazon',
  site: 'US',
  country: 'US',
  fulfillment_mode: 'dropship',
  api_base: 'https://openapi.gigab2b.com',
  client_id: 'r1-client',
  client_secret_masked: '***',
  shipping_cost_mode: 'api',
  packing_fee: null,
  inventory_mode: 'api',
  enabled: true,
  remark: 'R1 mutation fixture',
  created_at: '2026-07-22T00:00:00',
  updated_at: '2026-07-22T00:00:00',
};

const catalogProductFixture = {
  id: 201,
  source_product_id: 42,
  source_url: 'https://example.invalid/product/42',
  source_item_id: 'R1-ITEM-42',
  gigab2b_url: 'https://example.invalid/product/42',
  gigab2b_product_id: 'R1-ITEM-42',
  competitor_asin: 'B000R1TEST',
  amazon_asin: null,
  amazon_seller_sku: null,
  asin_sync_status: 'not_synced',
  asin_synced_at: null,
  asin_sync_error: null,
  amazon_product_status: null,
  amazon_product_status_synced_at: null,
  amazon_product_status_error: null,
  aplus_upload_status: 'not_uploaded',
  aplus_uploaded_at: null,
  aplus_upload_error: null,
  aplus_status: null,
  aplus_image_count: 0,
  upc: '714532191586',
  brand: 'R1',
  item_code: 'R1-ITEM-42',
  title: 'R1 Catalog Product',
  leaf_category: 'R1 Category',
  stock: 3,
  stock_sync_status: 'synced',
  stock_synced_at: '2026-07-22T00:00:00',
  stock_sync_error: null,
  status: 'ready',
  confirmed_at: '2026-07-22T00:00:00',
  exported_at: null,
  export_task_id: null,
  export_file_path: null,
  imported_at: '2026-07-22T00:00:00',
  updated_at: '2026-07-22T00:00:00',
  template_risk_level: 'pass',
  template_warnings_count: 0,
};

const taskStepFixture = {
  id: 1001,
  task_run_id: 101,
  task_group_id: 501,
  step_key: 'r1-step',
  step_type: 'r1_step',
  step_label: 'R1 Step',
  status: 'failed',
  display_status: 'failed',
  sort_order: 1,
  payload_json: null,
  result_json: null,
  error_message: 'R1 failure',
  error_summary: 'R1 failure',
  display_reason: 'R1 failure',
  progress_current: 0,
  progress_total: 1,
  attempt_count: 1,
  max_attempts: 3,
  locked_by: null,
  locked_until: null,
  heartbeat_at: null,
  started_at: '2026-07-22T00:00:00',
  finished_at: '2026-07-22T00:01:00',
  created_at: '2026-07-22T00:00:00',
  updated_at: '2026-07-22T00:01:00',
  events: [],
  available_actions: ['retry_step'],
};

const taskRunFixture = {
  id: 101,
  task_type: 'r1_mutation',
  task_type_label: 'R1 Mutation',
  title: 'R1 Runtime Mutation Fixture',
  status: 'failed',
  display_status: 'failed',
  display_status_label: '失败',
  display_reason: 'R1 failure',
  current_step_label: 'R1 Step',
  progress_current: 0,
  progress_total: 1,
  progress_percent: 0,
  error_summary: 'R1 failure',
  latest_event_message: 'R1 failure',
  available_actions: ['cancel', 'wake_runtime', 'retry_failed_steps', 'mark_interrupted'],
  payload_json: null,
  summary_json: null,
  created_by: 'r1',
  started_at: '2026-07-22T00:00:00',
  finished_at: '2026-07-22T00:01:00',
  created_at: '2026-07-22T00:00:00',
  updated_at: '2026-07-22T00:01:00',
};

const taskRunDetailFixture = {
  ...taskRunFixture,
  groups: [{
    id: 501,
    task_run_id: 101,
    group_key: 'r1-group',
    title: 'R1 Group',
    status: 'failed',
    display_status: 'failed',
    display_reason: 'R1 failure',
    sort_order: 1,
    depends_on_group_keys_json: null,
    failure_policy: 'stop',
    retry_policy: 'manual',
    progress_current: 0,
    progress_total: 1,
    summary_json: null,
    started_at: '2026-07-22T00:00:00',
    finished_at: '2026-07-22T00:01:00',
    created_at: '2026-07-22T00:00:00',
    updated_at: '2026-07-22T00:01:00',
    steps: [taskStepFixture],
  }],
};

const offlineTaskFixture = {
  id: 301,
  task_type: 'giga_pull',
  title: 'R1 Offline Task',
  status: 'failed',
  total_steps: 1,
  success_steps: 0,
  failed_steps: 1,
  running_steps: 0,
  created_by: 'r1',
  payload_json: null,
  result_json: null,
  error_message: 'R1 failure',
  can_download: false,
  created_at: '2026-07-22T00:00:00',
  started_at: '2026-07-22T00:00:00',
  finished_at: '2026-07-22T00:01:00',
  updated_at: '2026-07-22T00:01:00',
};

const configFixture = {
  project_name: 'FBM Pipeline', version: 'r1', backend_port: 8000, frontend_port: 5173,
  default_brand: 'R1', llm_model: 'r1-llm', vlm_model: 'r1-vlm', vlm_use_llm_api: true,
  gpt_image_model: 'r1-image', gpt_image_use_llm_api: true, gpt_image_api_provider: 'openai',
  aplus_image_width: 1464, aplus_image_height: 600, aplus_image_jpeg_quality: 90,
  aplus_image_api_retries: 2, aplus_image_overwrite_policy: 'skip_success',
  product_base_dir: '/tmp/r1-products', pipeline_max_concurrency: 2, browser_workflow_concurrency: 1,
  bulk_start_max_tasks: 100, aplus_concurrency: 1, poll_interval: 5, step3_4_parallel: true,
  step1_extract_retry_attempts: 2, step1_extract_retry_delay_seconds: 1, step1_download_timeout_seconds: 60,
  step1_material_package_priority: 'Information', step1_price_missing_policy: 'manual_review',
  step1_material_missing_policy: 'manual_review', step1_allow_existing_materials: true,
  pricing_net_revenue_rate: 0.85, pricing_target_margin_rate: 0.15, pricing_min_profit: 5,
  pricing_fixed_cost: 1, pricing_return_credit_rate: 0.05, step3_manual_login_on_auth_failure: false,
  step4_missing_asin_policy: 'manual_review', step4_category_missing_policy: 'manual_review',
  step4_allow_existing_category: true, step5_llm_temperature: 0.2, step5_llm_max_tokens: 2048,
  step5_title_max_chars: 200, step5_bullet_max_chars: 500, step5_search_terms_max_bytes: 250,
  llm_api_configured: true, vlm_api_configured: true, gpt_image_api_configured: true,
  sellersprite_configured: true, env_file: '/tmp/r1.env',
};

const productFixture = {
  id: 42,
  source_url: 'https://example.invalid/product/42',
  source_item_id: 'R1-ITEM-42',
  gigab2b_url: 'https://example.invalid/product/42',
  gigab2b_product_id: 'R1-ITEM-42',
  competitor_asin: 'B000R1TEST',
  amazon_asin: null,
  amazon_seller_sku: null,
  asin_sync_status: 'not_synced',
  asin_synced_at: null,
  asin_sync_error: null,
  amazon_product_status: null,
  amazon_product_status_synced_at: null,
  amazon_product_status_error: null,
  aplus_upload_status: 'not_uploaded',
  aplus_uploaded_at: null,
  aplus_upload_error: null,
  aplus_status: null,
  aplus_image_count: 0,
  upc: '714532191586',
  item_code: 'R1-ITEM-42',
  title: 'R1 Runtime Product',
  brand: 'R1',
  source_data_source_id: 1,
  source_site: 'US',
  source_batch_id: null,
  sales_channel: 'amazon',
  status: 'completed',
  current_step: 6,
  current_task_status: '待导出',
  workflow: null,
  error_message: null,
  leaf_category: 'Sofas',
  created_at: '2026-07-22T00:00:00',
  updated_at: '2026-07-22T00:00:00',
};

const productDetailFixture = {
  ...productFixture,
  data: {
    id: 1,
    product_id: 42,
    item_code: 'R1-ITEM-42',
    title: 'R1 Runtime Product',
    material_dir: '/tmp/r1-product-42',
    categories: JSON.stringify(['Furniture', 'Sofas']),
    leaf_category: 'Sofas',
    listing_title: 'R1 retained listing title',
    listing_bullets: JSON.stringify(['R1 bullet']),
    listing_description: 'R1 listing description',
    listing_search_terms: 'r1 search terms',
    listing_title_zh: 'R1 中文标题',
    listing_bullets_zh: JSON.stringify(['R1 中文五点']),
    listing_description_zh: 'R1 中文描述',
    listing_search_terms_zh: 'R1 中文关键词',
    listing_primary_keyword: 'r1 keyword',
    keywords_top: JSON.stringify(['r1 keyword']),
    variants: JSON.stringify([]),
    packages: JSON.stringify([]),
    features: JSON.stringify([]),
  },
  images: {
    id: 1,
    product_id: 42,
    main_image_path: 'r1/main.jpg',
    main_image_source: 'main',
    gallery_images: JSON.stringify(['r1/gallery.jpg']),
    gallery_order: JSON.stringify([
      { path: 'r1/main.jpg', image_type: 'main' },
      { path: 'r1/gallery.jpg', image_type: 'gallery' },
      { path: 'r1/unused.jpg', image_type: 'file' },
    ]),
    image_analysis: JSON.stringify({ images: [{ image_id: 'R1-1', path: 'r1/main.jpg' }] }),
  },
  aplus: null,
  zip_files: [{
    name: 'r1-materials.zip',
    path: '/tmp/r1-materials.zip',
    size: 128,
    modified_at: '2026-07-22T00:00:00',
    extracted_dir: '/tmp/r1-materials',
    extracted_exists: true,
    extracted_files: ['r1.txt'],
  }],
  generated_files: [{
    id: 1,
    product_id: 42,
    file_type: 'listing',
    label: 'R1 Listing File',
    path: '/tmp/r1-listing.xlsx',
    directory: '/tmp',
    metadata_json: null,
    created_at: '2026-07-22T00:00:00',
    updated_at: '2026-07-22T00:00:00',
  }],
  video_folder: null,
  aplus_folder: null,
  amazon_export_preview: null,
};

const workflowFixture = (action: string, label: string) => ({
  stage: 'capture_competitor_candidates',
  stage_status: 'failed',
  label: 'R1 workflow failed',
  work_status: 'failed',
  node_key: 'capture_competitor_candidates',
  node_label: 'R1 workflow node',
  node_type: 'async',
  node_status: 'failed',
  primary_action: action,
  primary_action_label: label,
  allowed_actions: [action, 'open_detail'],
  action_reason: 'R1 workflow retry fixture',
  color: 'error',
  related_task_run_id: null,
  related_correlation_key: null,
});

const installMutationCollector = async (page: Page) => page.evaluate(async () => {
  const apiModule = await import('/src/api/index.ts');
  const ids: string[] = [];
  const interceptorId = apiModule.default.interceptors.request.use((config) => {
    if (config.fbmMutationCallsiteId) ids.push(config.fbmMutationCallsiteId);
    return config;
  });
  (window as typeof window & { __r1MutationCollector?: MutationCollector }).__r1MutationCollector = {
    ids,
    interceptorId,
  };
  return interceptorId;
});

const collectedMutationIds = async (page: Page) => page.evaluate(() => (
  (window as typeof window & { __r1MutationCollector?: MutationCollector }).__r1MutationCollector?.ids || []
));

const installPageFailureGuard = async (page: Page) => {
  let rejected = false;
  let rejectFailure: (error: Error) => void = () => undefined;
  const failure = new Promise<never>((_, reject) => {
    rejectFailure = reject;
  });
  const fail = (error: Error) => {
    if (rejected) return;
    rejected = true;
    rejectFailure(error);
  };
  const onPageError = (error: Error) => fail(new Error(`pageerror: ${error.message}`));
  const onConsole = (consoleMessage: { type: () => string; text: () => string }) => {
    const text = consoleMessage.text();
    if (consoleMessage.type() === 'error' && text.startsWith(UNHANDLED_REJECTION_PREFIX)) {
      fail(new Error(`unhandledrejection: ${text.slice(UNHANDLED_REJECTION_PREFIX.length)}`));
    }
  };
  page.on('pageerror', onPageError);
  page.on('console', onConsole);
  await page.addInitScript((prefix) => {
    window.addEventListener('unhandledrejection', (event) => {
      const reason = event.reason instanceof Error
        ? `${event.reason.name}: ${event.reason.message}`
        : String(event.reason);
      console.error(`${prefix}${reason}`);
    });
  }, UNHANDLED_REJECTION_PREFIX);
  return {
    failure,
    dispose: () => {
      page.off('pageerror', onPageError);
      page.off('console', onConsole);
    },
  };
};

const jsonResponse = (body: unknown) => ({
  contentType: 'application/json',
  body: JSON.stringify(body),
});

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const antButtonName = (name: string | RegExp): RegExp => {
  if (name instanceof RegExp) return name;
  const pattern = name
    .trim()
    .split(/\s+/)
    .map((token) => [...token].map(escapeRegExp).join('\\s*'))
    .join('\\s+');
  return new RegExp(`${pattern}$`);
};

const installGetFixtures = async (page: Page, options: FixtureOptions = {}) => {
  const source = { ...productDataSourceFixture, ...options.productDataSource };
  const catalogProduct = { ...catalogProductFixture, ...options.catalogProduct };
  const run = { ...taskRunFixture, ...options.taskRun };
  const runDetail = { ...taskRunDetailFixture, ...run, ...options.taskRunDetail };
  const offlineTask = { ...offlineTaskFixture, ...options.offlineTask };
  const imageReviewQueue = options.imageReviewQueue || [{
    id: 42,
    gigab2b_product_id: 'R1-ITEM-42',
    status: 'created',
    current_step: 0,
    current_task_status: '待确认图片',
    item_code: 'R1-ITEM-42',
    title: 'R1 Image Review Product',
    created_at: '2026-07-22T00:00:00',
    updated_at: '2026-07-22T00:00:00',
  }];
  const imageReviewDetail = options.imageReviewDetail || {
    id: 42,
    source_item_id: 'R1-ITEM-42',
    gigab2b_product_id: 'R1-ITEM-42',
    status: 'created',
    current_step: 0,
    current_task_status: '待确认图片',
    data: { item_code: 'R1-ITEM-42', title: 'R1 Image Review Product' },
    images: {
      id: 1,
      product_id: 42,
      main_image_path: 'r1/main.jpg',
      main_image_source: 'main',
      gallery_images: JSON.stringify(['r1/gallery.jpg']),
      gallery_order: JSON.stringify([
        { path: 'r1/main.jpg', image_type: 'main' },
        { path: 'r1/gallery.jpg', image_type: 'gallery' },
      ]),
      gallery_order_total: 2,
      gallery_order_limit: 200,
    },
  };

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      if (options.mutationDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.mutationDelayMs));
      }
      await route.continue();
      return;
    }
    const pathname = new URL(request.url()).pathname;
    if (!pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }
    if (pathname === '/api/product-data-sources') {
      await route.fulfill(jsonResponse({ items: [source], total: 1, page: 1, page_size: 100 }));
      return;
    }
    if (pathname === '/api/products/catalog') {
      await route.fulfill(jsonResponse({ items: [catalogProduct], total: 1, page: 1, page_size: 20 }));
      return;
    }
    if (pathname === '/api/products/catalog/export-files') {
      await route.fulfill(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));
      return;
    }
    if (pathname === '/api/products/catalog/export-categories') {
      await route.fulfill(jsonResponse({ pending: [], exported: [] }));
      return;
    }
    if (pathname === '/api/products/catalog/template-categories') {
      await route.fulfill(jsonResponse(options.templateCategories || []));
      return;
    }
    if (pathname === '/api/products/catalog/template-files') {
      await route.fulfill(jsonResponse(options.templateFiles || []));
      return;
    }
    if (pathname === '/api/products/overview') {
      await route.fulfill(jsonResponse({ total_products: 1 }));
      return;
    }
    if (pathname === '/api/products/image-review-queue') {
      await route.fulfill(jsonResponse({ items: imageReviewQueue, total: imageReviewQueue.length, limit: 30 }));
      return;
    }
    if (/^\/api\/products\/image-review-detail\/\d+$/.test(pathname)) {
      await route.fulfill(jsonResponse(imageReviewDetail));
      return;
    }
    if (pathname === '/api/products/upc-pool') {
      await route.fulfill(jsonResponse({
        items: [], total: 0, page: 1, page_size: 50,
        summary: { total: 0, available: 0, bound: 0 },
      }));
      return;
    }
    if (pathname === '/api/products/category-options') {
      await route.fulfill(jsonResponse({
        items: [{ key: 'Furniture > Sofas', label: 'Furniture > Sofas', categories: ['Furniture', 'Sofas'], leaf_category: 'Sofas', source: 'r1' }],
      }));
      return;
    }
    if (pathname === '/api/products/42') {
      await route.fulfill(jsonResponse(options.product || {}));
      return;
    }
    if (pathname === '/api/products') {
      await route.fulfill(jsonResponse({ items: options.product ? [options.product] : [], total: options.product ? 1 : 0, page: 1, page_size: 20 }));
      return;
    }
    if (pathname === '/api/giga/batches') {
      await route.fulfill(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));
      return;
    }
    if (pathname === '/api/giga/inventory') {
      await route.fulfill(jsonResponse({ items: [], total: 0, page: 1, page_size: 50, pulled_at: null }));
      return;
    }
    if (pathname === `/api/task-runs/${run.id}`) {
      await route.fulfill(jsonResponse(runDetail));
      return;
    }
    if (pathname === '/api/task-runs') {
      await route.fulfill(jsonResponse({ items: [run], total: 1, page: 1, page_size: 50 }));
      return;
    }
    if (pathname === `/api/offline-tasks/${offlineTask.id}`) {
      await route.fulfill(jsonResponse({ ...offlineTask, steps: [] }));
      return;
    }
    if (pathname === '/api/offline-tasks') {
      await route.fulfill(jsonResponse({ items: [offlineTask], total: 1, page: 1, page_size: 50 }));
      return;
    }
    if (pathname === '/api/config') {
      await route.fulfill(jsonResponse({ ...configFixture, ...options.config }));
      return;
    }
    await route.fulfill(jsonResponse({}));
  });
};

const confirmPopconfirm = async (page: Page, trigger: Locator, confirmName: string | RegExp) => {
  await trigger.click();
  await page.locator('.ant-popconfirm-buttons').getByRole('button', { name: antButtonName(confirmName) }).click();
};

const expectRemoteMutation = async (
  page: Page,
  callsiteId: MutationCallsiteId,
  trigger: () => Promise<void>,
  preserve?: () => Promise<void>,
  duringLoading?: () => Promise<void>,
) => {
  const responsePromise = page.waitForResponse((response) => (
    !['GET', 'HEAD', 'OPTIONS'].includes(response.request().method())
      && new URL(response.url()).pathname.startsWith('/api/')
  ));
  await trigger();
  if (duringLoading) await duringLoading();
  await expect.poll(() => collectedMutationIds(page)).toEqual([callsiteId]);
  const response = await responsePromise;
  expect(response.status()).toBe(403);
  expect(await response.json()).toMatchObject({ code: 'REMOTE_DEV_READ_ONLY' });
  const notices = page.locator('.ant-message-notice-content').filter({ hasText: REMOTE_READ_ONLY_MESSAGE });
  await expect(notices).toHaveCount(1);
  await expect(page.locator('.ant-message-notice-content')).toHaveCount(1);
  await expect(page.locator('.ant-btn-loading')).toHaveCount(0);
  await expect(page.locator('.ant-spin-spinning')).toHaveCount(0);
  if (preserve) await preserve();
};

const mutationTest = (
  title: string,
  callsiteId: MutationCallsiteId,
  path: string,
  options: FixtureOptions,
  trigger: (page: Page) => Promise<void>,
  preserve?: (page: Page) => Promise<void>,
  duringLoading?: (page: Page) => Promise<void>,
) => {
  test(title, async ({ page }) => {
    const pageFailureGuard = await installPageFailureGuard(page);
    try {
      await Promise.race([
        (async () => {
          await installGetFixtures(page, options);
          await page.goto(path);
          const interceptorId = await installMutationCollector(page);
          expect(interceptorId).toBeGreaterThanOrEqual(0);
          await expectRemoteMutation(
            page,
            callsiteId,
            () => trigger(page),
            preserve ? () => preserve(page) : undefined,
            duringLoading ? () => duringLoading(page) : undefined,
          );
          observedRuntimeIds.add(callsiteId);
        })(),
        pageFailureGuard.failure,
      ]);
    } finally {
      pageFailureGuard.dispose();
    }
  });
};

test.afterAll(() => {
  if (process.env.R1_MUTATION_PARTIAL !== '1') {
    expect([...observedRuntimeIds].sort()).toEqual(mutationInventory.map((item) => item.id).sort());
  }
});

mutationTest(
  'CreateProduct preserves form state through the real remote guard',
  'createProduct|frontend/src/pages/CreateProduct.tsx|handleSubmit',
  '/products/new',
  {},
  async (page) => {
    await page.getByLabel('原始数据链接').fill('https://example.invalid/r1-shared-axios');
    await page.getByRole('button', { name: '创建任务' }).click();
  },
  async (page) => {
    await expect(page.getByLabel('原始数据链接')).toHaveValue('https://example.invalid/r1-shared-axios');
  },
);

for (const taskRunCase of [
  {
    title: 'TaskRunCenter wakes a run',
    id: 'wakeTaskRun|frontend/src/pages/TaskRunCenter.tsx|wakeRun' as const,
    trigger: async (page: Page) => page.getByRole('button', { name: '唤醒' }).click(),
  },
  {
    title: 'TaskRunCenter retries failed steps',
    id: 'retryFailedTaskRunSteps|frontend/src/pages/TaskRunCenter.tsx|retryRun' as const,
    trigger: async (page: Page) => page.getByRole('button', { name: '重试失败步骤' }).click(),
  },
  {
    title: 'TaskRunCenter marks a run interrupted',
    id: 'markTaskRunInterrupted|frontend/src/pages/TaskRunCenter.tsx|markInterrupted' as const,
    trigger: async (page: Page) => page.getByRole('button', { name: '标记中断' }).click(),
  },
]) {
  mutationTest(taskRunCase.title, taskRunCase.id, '/task-runs', {}, taskRunCase.trigger);
}

mutationTest(
  'TaskRunCenter cancels a run from the real owner menu',
  'cancelTaskRun|frontend/src/pages/TaskRunCenter.tsx|cancelRun',
  '/task-runs',
  {},
  async (page) => {
    const row = page.getByText('#101', { exact: true }).locator('xpath=ancestor::tr');
    await row.locator('button:has(.anticon-more)').click();
    await page.getByText('取消', { exact: true }).click();
    await page.getByRole('button', { name: '取消任务' }).click();
  },
);

mutationTest(
  'TaskRunCenter retries one expanded step',
  'retryTaskStep|frontend/src/pages/TaskRunCenter.tsx|retryOneStep',
  '/task-runs',
  {},
  async (page) => {
    await page.getByTestId('task-run-expand-101').click();
    await page.locator('.ant-table-expanded-row .ant-table-row-expand-icon-collapsed').first().click();
    await page.getByRole('button', { name: '重试此步骤' }).click();
  },
);

mutationTest(
  'AplusManagement preserves the selected row',
  'createAplusGenerateBatch|frontend/src/pages/AplusManagement.tsx|submitGenerate',
  '/aplus',
  {},
  async (page) => {
    await page.getByRole('checkbox').nth(1).check();
    await page.getByRole('button', { name: /批量生成/ }).click();
  },
  async (page) => expect(page.getByRole('checkbox').nth(1)).toBeChecked(),
);

for (const inventoryCase of [
  {
    title: 'InventorySyncList submits inventory sync',
    id: 'createGigaInventorySyncTaskRuns|frontend/src/pages/InventorySyncList.tsx|handleSync' as const,
    button: '同步库存',
    confirm: '开始同步',
  },
  {
    title: 'InventorySyncList submits price sync',
    id: 'createGigaPriceSyncTaskRuns|frontend/src/pages/InventorySyncList.tsx|handlePriceSync' as const,
    button: '同步价格',
    confirm: '开始同步',
  },
]) {
  mutationTest(inventoryCase.title, inventoryCase.id, '/inventory-sync', {}, async (page) => {
    await confirmPopconfirm(page, page.getByRole('button', { name: inventoryCase.button }).first(), inventoryCase.confirm);
  });
}

mutationTest(
  'ProductDataSourceList preserves a create modal form',
  'createProductDataSource|frontend/src/pages/ProductDataSourceList.tsx|save',
  '/data-sources',
  {},
  async (page) => {
    await page.getByRole('button', { name: '新增店铺' }).click();
    await page.getByLabel('名称').fill('R1 retained source');
    await page.getByLabel('SK / Client Secret').fill('r1-secret');
    await page.locator('.ant-modal:visible .ant-modal-footer .ant-btn-primary').click();
  },
  async (page) => {
    await expect(page.getByRole('dialog', { name: '新增店铺' })).toBeVisible();
    await expect(page.getByLabel('名称')).toHaveValue('R1 retained source');
  },
);

const productDataSourceRow = (page: Page) => (
  page.getByText('R1 Amazon Test Source', { exact: true }).locator('xpath=ancestor::tr')
);

mutationTest(
  'ProductDataSourceList preserves an edit modal',
  'updateProductDataSource|frontend/src/pages/ProductDataSourceList.tsx|save',
  '/data-sources',
  {},
  async (page) => {
    await productDataSourceRow(page).getByRole('button', { name: antButtonName('编辑') }).click();
    await page.getByLabel('名称').fill('R1 retained edit');
    await page.locator('.ant-modal:visible .ant-modal-footer .ant-btn-primary').click();
  },
  async (page) => {
    await expect(page.getByRole('dialog', { name: '编辑店铺' })).toBeVisible();
    await expect(page.getByLabel('名称')).toHaveValue('R1 retained edit');
  },
);

mutationTest(
  'ProductDataSourceList keeps the row after delete denial',
  'deleteProductDataSource|frontend/src/pages/ProductDataSourceList.tsx|remove',
  '/data-sources',
  {},
  async (page) => {
    await confirmPopconfirm(
      page,
      productDataSourceRow(page).getByRole('button', { name: antButtonName('停用') }),
      '确认',
    );
  },
  async (page) => expect(page.getByText('R1 Amazon Test Source')).toBeVisible(),
);

mutationTest(
  'UpcPoolPage preserves the UPC form text',
  'importUpcPool|frontend/src/pages/UpcPoolPage.tsx|handleAdd',
  '/upc-pool',
  {},
  async (page) => {
    await page.getByLabel('批量加入UPC').fill('714532191586');
    await page.getByRole('button', { name: '加入池子' }).click();
  },
  async (page) => expect(page.getByLabel('批量加入UPC')).toHaveValue('714532191586'),
);

for (const offlineCase of [
  {
    title: 'OfflineTaskCenter pauses a running task',
    id: 'pauseOfflineTask|frontend/src/pages/OfflineTaskCenter.tsx|pauseTask' as const,
    status: 'running',
    button: '挂起',
  },
  {
    title: 'OfflineTaskCenter resumes a paused task',
    id: 'resumeOfflineTask|frontend/src/pages/OfflineTaskCenter.tsx|resumeTask' as const,
    status: 'paused',
    button: '恢复',
  },
  {
    title: 'OfflineTaskCenter reruns a failed task',
    id: 'rerunOfflineTask|frontend/src/pages/OfflineTaskCenter.tsx|rerunTask' as const,
    status: 'failed',
    button: '重跑',
  },
]) {
  mutationTest(
    offlineCase.title,
    offlineCase.id,
    '/offline-tasks',
    { offlineTask: { status: offlineCase.status } },
    async (page) => page.getByRole('button', { name: offlineCase.button }).click(),
  );
}

mutationTest(
  'ConfigPage preserves its configuration form',
  'updateConfig|frontend/src/pages/ConfigPage.tsx|saveConfig',
  '/config',
  {},
  async (page) => {
    await page.getByLabel('Pipeline 最大并发').fill('3');
    await page.getByRole('button', { name: '保存配置' }).click();
  },
  async (page) => expect(page.getByLabel('Pipeline 最大并发')).toHaveValue('3'),
);

mutationTest(
  'ProductImageReview preserves the loaded detail cache and draft',
  'updateProductListingImages|frontend/src/pages/ProductImageReview.tsx|saveAndNext',
  '/products/image-review?data_source_id=1&product_id=42',
  {},
  async (page) => page.getByRole('button', { name: '保存并下一条' }).click(),
  async (page) => {
    await expect(page.getByText('R1 Image Review Product')).toBeVisible();
    await expect(page.getByText('主图', { exact: true })).toBeVisible();
  },
);

const templateFileFixture = {
  file_id: 'r1-template-file',
  file_no: 'R1-TEMPLATE',
  file_name: 'r1-template.xlsm',
  file_status: 'enabled',
  enabled: true,
  source: 'upload',
  template_path: '/tmp/r1-template.xlsm',
  oss_object_key: null,
  oss_url: null,
  support_categories: ['R1 Category'],
  template_errors: [],
  can_download: true,
  can_delete: true,
};

mutationTest(
  'CatalogList preserves selected products on export denial',
  'createCatalogExportTaskRuns|frontend/src/pages/CatalogList.tsx|createExportTasksByIds',
  '/export-center',
  {},
  async (page) => {
    await page.getByRole('checkbox').nth(1).check();
    await page.getByRole('button', { name: /导出选中/ }).click();
  },
  async (page) => expect(page.getByRole('checkbox').nth(1)).toBeChecked(),
);

for (const templateCase of [
  {
    title: 'CatalogList toggles a template file',
    id: 'updateCatalogTemplateFileStatus|frontend/src/pages/CatalogList.tsx|toggleTemplateFile' as const,
    trigger: async (page: Page) => page.getByRole('button', { name: '停用' }).click(),
  },
  {
    title: 'CatalogList deletes a template file',
    id: 'deleteCatalogTemplateFile|frontend/src/pages/CatalogList.tsx|deleteTemplateFile' as const,
    trigger: async (page: Page) => confirmPopconfirm(
      page,
      page.getByRole('button', { name: antButtonName('删除') }),
      '删除',
    ),
  },
]) {
  mutationTest(
    templateCase.title,
    templateCase.id,
    '/export-center',
    { templateFiles: [templateFileFixture] },
    async (page) => {
      await page.getByRole('tab', { name: '类目模板管理' }).click();
      await templateCase.trigger(page);
    },
    async (page) => expect(page.getByText('R1-TEMPLATE', { exact: true })).toBeVisible(),
  );
}

mutationTest(
  'CatalogList preserves the uncovered category while upload is denied',
  'uploadCatalogCategoryTemplate|frontend/src/pages/CatalogList.tsx|uploadTemplateForCategory',
  '/export-center',
  {
    mutationDelayMs: 500,
    templateCategories: [{
      category: 'R1 Missing Category', count: 1, exportable_count: 1, blocked_count: 0,
      template_available: false, template_name: null, template_path: null, template_error: null,
      uploaded_template_name: null, uploaded_template_cache_path: null, uploaded_template_oss_url: null,
      uploaded_template_object_key: null, uploaded_template_uploaded_at: null, sample_item_codes: ['R1-ITEM-42'],
    }, {
      category: 'R1 Other Category', count: 1, exportable_count: 1, blocked_count: 0,
      template_available: false, template_name: null, template_path: null, template_error: null,
      uploaded_template_name: null, uploaded_template_cache_path: null, uploaded_template_oss_url: null,
      uploaded_template_object_key: null, uploaded_template_uploaded_at: null, sample_item_codes: ['R1-ITEM-43'],
    }],
  },
  async (page) => {
    await page.getByRole('tab', { name: '类目模板管理' }).click();
    const targetRow = page.getByText('R1 Missing Category', { exact: true }).locator('xpath=ancestor::tr');
    await targetRow.locator('input[type="file"]').setInputFiles({
      name: 'r1-category-template.xlsm',
      mimeType: 'application/vnd.ms-excel.sheet.macroEnabled.12',
      buffer: Buffer.from('r1-template'),
    });
  },
  async (page) => {
    await expect(page.getByText('R1 Missing Category')).toBeVisible();
    await expect(page.getByTestId('catalog-template-pending-file-R1 Missing Category'))
      .toHaveText('r1-category-template.xlsm（上传失败，文件名已保留，请重新选择上传）');
    const targetRow = page.getByText('R1 Missing Category', { exact: true }).locator('xpath=ancestor::tr');
    await expect(targetRow.getByRole('button', { name: antButtonName('上传模板') })).not.toHaveClass(/ant-btn-loading/);
    await expect(targetRow.getByRole('button', { name: antButtonName('上传模板') })).toBeEnabled();
  },
  async (page) => {
    const targetRow = page.getByText('R1 Missing Category', { exact: true }).locator('xpath=ancestor::tr');
    const otherRow = page.getByText('R1 Other Category', { exact: true }).locator('xpath=ancestor::tr');
    const targetButton = targetRow.getByRole('button', { name: antButtonName('上传模板') });
    const otherButton = otherRow.getByRole('button', { name: antButtonName('上传模板') });
    await expect(page.locator('.ant-btn-loading')).toHaveCount(1);
    await expect(targetButton).toHaveClass(/ant-btn-loading/);
    await expect(targetButton).toBeDisabled();
    await expect(otherButton).not.toHaveClass(/ant-btn-loading/);
    await expect(otherButton).toBeEnabled();
  },
);

const productListRow = (page: Page) => (
  page.getByText('R1-ITEM-42', { exact: true }).first().locator('xpath=ancestor::tr')
);

mutationTest(
  'ProductList preserves the pull modal selection',
  'createGigaPullTaskRuns|frontend/src/pages/ProductList.tsx|pullMissingGigaProducts',
  '/products',
  { product: productFixture },
  async (page) => {
    await page.getByRole('button', { name: '同步店铺商品' }).click();
    await page.locator('.ant-modal:visible').getByRole('button', { name: '提交任务中心' }).click();
  },
  async (page) => {
    await expect(page.getByRole('dialog', { name: '同步店铺商品' })).toBeVisible();
    await expect(page.locator('.ant-modal:visible .ant-select-selection-item')).toContainText('R1 Amazon Test Source');
  },
);

mutationTest(
  'ProductList preserves the active filter on bulk advance denial',
  'createProductBulkAdvanceTaskByFilter|frontend/src/pages/ProductList.tsx|onOk',
  '/products',
  { product: productFixture },
  async (page) => {
    await page.getByPlaceholder('SKU / Item Code / 标题').fill('retained-filter');
    await page.getByRole('button', { name: '批量推进当前筛选' }).click();
    await page.locator('.ant-modal-confirm').getByRole('button', { name: '创建任务' }).click();
  },
  async (page) => expect(page.getByPlaceholder('SKU / Item Code / 标题')).toHaveValue('retained-filter'),
);

mutationTest(
  'ProductList preserves its row and filter on delete denial',
  'deleteProduct|frontend/src/pages/ProductList.tsx|handleDeleteProduct',
  '/products',
  { product: productFixture },
  async (page) => {
    await page.getByPlaceholder('SKU / Item Code / 标题').fill('retained-delete-filter');
    await confirmPopconfirm(page, productListRow(page).locator('button:has(.anticon-delete)'), '删除');
  },
  async (page) => {
    await expect(productListRow(page)).toBeVisible();
    await expect(page.getByPlaceholder('SKU / Item Code / 标题')).toHaveValue('retained-delete-filter');
  },
);

mutationTest(
  'ProductList preserves a legacy failed row on pause denial',
  'pausePipeline|frontend/src/pages/ProductList.tsx|suspendProductTask',
  '/products',
  { product: { ...productFixture, status: 'failed', current_step: 3, current_task_status: 'R1 failed', error_message: 'R1 generic failure', workflow: null } },
  async (page) => confirmPopconfirm(
    page,
    productListRow(page).getByRole('button', { name: antButtonName('挂起') }),
    '挂起',
  ),
  async (page) => expect(productListRow(page)).toContainText('R1-ITEM-42'),
);

mutationTest(
  'ProductList preserves a legacy completed row on restart denial',
  'restartPipeline|frontend/src/pages/ProductList.tsx|render',
  '/products',
  { product: { ...productFixture, workflow: null } },
  async (page) => confirmPopconfirm(page, productListRow(page).locator('button:has(.anticon-redo)'), '重新开始'),
  async (page) => expect(productListRow(page)).toContainText('R1-ITEM-42'),
);

mutationTest(
  'ProductList preserves a paused legacy row on resume denial',
  'resumePipeline|frontend/src/pages/ProductList.tsx|resumeProductTask',
  '/products',
  { product: { ...productFixture, status: 'paused', current_step: 4, current_task_status: '已挂起', workflow: null } },
  async (page) => productListRow(page).getByRole('button', { name: antButtonName('继续') }).click(),
  async (page) => expect(productListRow(page)).toContainText('已挂起'),
);

for (const workflowCase of [
  {
    title: 'ProductList dispatches workflow resume',
    id: 'resumePipeline|frontend/src/pages/ProductList.tsx|runProductWorkflowAction' as const,
    action: 'resume',
    label: '继续',
  },
  {
    title: 'ProductList dispatches workflow auto-image retry',
    id: 'retryProductAutoImageSelection|frontend/src/pages/ProductList.tsx|runProductWorkflowAction' as const,
    action: 'retry_auto_image_selection',
    label: '重试自动选图',
  },
  {
    title: 'ProductList dispatches workflow competitor-search retry',
    id: 'retryProductCompetitorSearch|frontend/src/pages/ProductList.tsx|runProductWorkflowAction' as const,
    action: 'retry_competitor_search',
    label: '重试 Amazon 搜索',
  },
  {
    title: 'ProductList dispatches workflow visual-match retry',
    id: 'retryProductCompetitorVisualMatch|frontend/src/pages/ProductList.tsx|runProductWorkflowAction' as const,
    action: 'retry_competitor_visual_match',
    label: '重试视觉初筛',
  },
  {
    title: 'ProductList dispatches workflow generic retry',
    id: 'retryStep|frontend/src/pages/ProductList.tsx|runProductWorkflowAction' as const,
    action: 'retry',
    label: '重试',
  },
]) {
  mutationTest(
    workflowCase.title,
    workflowCase.id,
    '/products',
    { product: { ...productFixture, status: 'failed', current_step: 3, workflow: workflowFixture(workflowCase.action, workflowCase.label) } },
    async (page) => productListRow(page).getByRole('button', { name: antButtonName(workflowCase.label) }).click(),
    async (page) => expect(productListRow(page)).toContainText('R1-ITEM-42'),
  );
}

mutationTest(
  'ProductList distinguishes interrupted legacy retry owner',
  'retryStep|frontend/src/pages/ProductList.tsx|renderPrimaryRowAction|1',
  '/products',
  {
    product: {
      ...productFixture,
      status: 'step5_listing',
      current_step: 5,
      current_task_status: '运行状态已中断，请重试',
      workflow: null,
    },
  },
  async (page) => productListRow(page).getByRole('button', { name: antButtonName('重试') }).click(),
  async (page) => expect(productListRow(page)).toContainText('已中断'),
);

mutationTest(
  'ProductList distinguishes failed legacy retry owner',
  'retryStep|frontend/src/pages/ProductList.tsx|renderPrimaryRowAction|2',
  '/products',
  {
    product: {
      ...productFixture,
      status: 'failed',
      current_step: 3,
      current_task_status: 'R1 generic failure',
      error_message: 'R1 generic failure',
      workflow: null,
    },
  },
  async (page) => productListRow(page).getByRole('button', { name: antButtonName('重试') }).click(),
  async (page) => expect(productListRow(page)).toContainText('R1 generic failure'),
);

const clickDetailTab = async (page: Page, name: string | RegExp) => {
  await page.getByRole('tab', { name }).click();
};

mutationTest(
  'ProductDetail preserves loaded detail on delete denial',
  'deleteProduct|frontend/src/pages/ProductDetail.tsx|handleDelete',
  '/products/42',
  { product: productDetailFixture },
  async (page) => confirmPopconfirm(
    page,
    page.getByRole('button', { name: antButtonName('删除') }),
    '删除',
  ),
  async (page) => expect(page.getByRole('heading', { name: '商品 #42' })).toBeVisible(),
);

mutationTest(
  'ProductDetail clears observable file-open loading',
  'openProductFile|frontend/src/pages/ProductDetail.tsx|openPath',
  '/products/42',
  { product: productDetailFixture, mutationDelayMs: 500 },
  async (page) => {
    await clickDetailTab(page, /文件信息/);
    await page.getByRole('button', { name: /r1-materials\.zip/ }).click();
  },
  async (page) => {
    const targetButton = page.getByRole('button', { name: /r1-materials\.zip/ });
    await expect(targetButton).not.toHaveClass(/ant-btn-loading/);
    await expect(targetButton).toBeEnabled();
  },
  async (page) => {
    const zipRow = page.getByText('r1-materials.zip', { exact: true }).locator('xpath=ancestor::tr');
    const targetButton = zipRow.getByRole('button', { name: /r1-materials\.zip/ });
    const otherButton = zipRow.getByRole('button', { name: antButtonName('文件夹') });
    await expect(page.locator('.ant-btn-loading')).toHaveCount(1);
    await expect(targetButton).toHaveClass(/ant-btn-loading/);
    await expect(targetButton).toBeDisabled();
    await expect(otherButton).not.toHaveClass(/ant-btn-loading/);
    await expect(otherButton).toBeEnabled();
  },
);

mutationTest(
  'ProductDetail clears observable zip-extract loading',
  'extractProductZip|frontend/src/pages/ProductDetail.tsx|extractZip',
  '/products/42',
  { product: productDetailFixture },
  async (page) => {
    await clickDetailTab(page, /文件信息/);
    await page.getByRole('button', { name: antButtonName('解压') }).click();
  },
  async (page) => expect(page.getByRole('button', { name: antButtonName('解压') })).not.toHaveClass(/ant-btn-loading/),
);

mutationTest(
  'ProductDetail preserves A+ tab state on generation denial',
  'generateProductAplus|frontend/src/pages/ProductDetail.tsx|generateAplus',
  '/products/42',
  { product: { ...productDetailFixture, aplus: null } },
  async (page) => {
    await clickDetailTab(page, /A\+内容/);
    await page.getByRole('button', { name: antButtonName('生成A+') }).click();
  },
  async (page) => expect(page.getByRole('tab', { name: /A\+内容/ })).toHaveAttribute('aria-selected', 'true'),
);

mutationTest(
  'ProductDetail distinguishes direct running pause owner',
  'pausePipeline|frontend/src/pages/ProductDetail.tsx|ProductDetail|1',
  '/products/42',
  {
    product: {
      ...productDetailFixture,
      status: 'step5_listing',
      current_step: 5,
      current_task_status: 'R1 pipeline running',
      workflow: null,
    },
  },
  async (page) => page.getByRole('button', { name: antButtonName('挂起') }).click(),
  async (page) => expect(page.getByRole('heading', { name: '商品 #42' })).toBeVisible(),
);

mutationTest(
  'ProductDetail distinguishes confirm-triggered pause owner',
  'pausePipeline|frontend/src/pages/ProductDetail.tsx|ProductDetail|2',
  '/products/42',
  {
    product: {
      ...productDetailFixture,
      status: 'created',
      current_step: 0,
      current_task_status: '待确认图片',
      workflow: null,
    },
  },
  async (page) => confirmPopconfirm(
    page,
    page.getByRole('button', { name: antButtonName('挂起') }),
    '挂起',
  ),
  async (page) => expect(page.getByRole('heading', { name: '商品 #42' })).toBeVisible(),
);

const aplusDoneFixture = {
  id: 1,
  product_id: 42,
  aplus_status: 'done',
  aplus_image_count: 1,
  aplus_plan: JSON.stringify({ modules: [{ position: 1, conversion_goal: 'R1 goal' }] }),
  aplus_scripts: JSON.stringify({ scripts: [{ module_position: 1, width: 1464, height: 600, style: 'image', prompt: 'R1 prompt' }] }),
  aplus_images: JSON.stringify([{ position: 1, path: 'r1/aplus-1.jpg', status: 'done' }]),
};

mutationTest(
  'ProductDetail preserves A+ regeneration reason and modal',
  'regenerateAplusModule|frontend/src/pages/ProductDetail.tsx|regenerateAplus',
  '/products/42',
  { product: { ...productDetailFixture, aplus: aplusDoneFixture } },
  async (page) => {
    await clickDetailTab(page, /A\+内容/);
    const moduleCard = page.locator('.ant-card').filter({ hasText: '模块 1' }).last();
    await moduleCard.getByRole('button', { name: '重新生成' }).first().click();
    const dialog = page.getByRole('dialog', { name: /A\+模块 1/ });
    await dialog.getByRole('textbox').fill('R1 retained regeneration reason');
    await dialog.locator('.ant-modal-footer .ant-btn-primary').click();
  },
  async (page) => {
    const dialog = page.getByRole('dialog', { name: /A\+模块 1/ });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('textbox')).toHaveValue('R1 retained regeneration reason');
  },
);

mutationTest(
  'ProductDetail preserves detail state on restart denial',
  'restartPipeline|frontend/src/pages/ProductDetail.tsx|doRestart',
  '/products/42',
  { product: { ...productDetailFixture, workflow: null } },
  async (page) => confirmPopconfirm(page, page.getByRole('button', { name: '重新开始流程' }), '重新开始'),
  async (page) => expect(page.getByText('R1 retained listing title')).toBeVisible(),
);

for (const resumeCase of [
  {
    title: 'ProductDetail distinguishes paused legacy resume owner',
    id: 'resumePipeline|frontend/src/pages/ProductDetail.tsx|ProductDetail|1' as const,
    status: 'paused',
    currentStep: 4,
    taskStatus: '已挂起',
  },
  {
    title: 'ProductDetail distinguishes review legacy resume owner',
    id: 'resumePipeline|frontend/src/pages/ProductDetail.tsx|ProductDetail|2' as const,
    status: 'pending_review',
    currentStep: 4,
    taskStatus: '待人工处理',
  },
]) {
  mutationTest(
    resumeCase.title,
    resumeCase.id,
    '/products/42',
    {
      product: {
        ...productDetailFixture,
        status: resumeCase.status,
        current_step: resumeCase.currentStep,
        current_task_status: resumeCase.taskStatus,
        workflow: null,
      },
    },
    async (page) => page.getByRole('button', { name: antButtonName('继续') }).click(),
    async (page) => expect(page.getByRole('heading', { name: '商品 #42' })).toBeVisible(),
  );
}

for (const workflowCase of [
  {
    title: 'ProductDetail dispatches workflow resume',
    id: 'resumePipeline|frontend/src/pages/ProductDetail.tsx|runWorkflowAction' as const,
    action: 'resume',
    label: '继续',
  },
  {
    title: 'ProductDetail dispatches workflow auto-image retry',
    id: 'retryProductAutoImageSelection|frontend/src/pages/ProductDetail.tsx|runWorkflowAction' as const,
    action: 'retry_auto_image_selection',
    label: '重试自动选图',
  },
  {
    title: 'ProductDetail dispatches workflow competitor-search retry',
    id: 'retryProductCompetitorSearch|frontend/src/pages/ProductDetail.tsx|runWorkflowAction' as const,
    action: 'retry_competitor_search',
    label: '重试 Amazon 搜索',
  },
  {
    title: 'ProductDetail dispatches workflow visual-match retry',
    id: 'retryProductCompetitorVisualMatch|frontend/src/pages/ProductDetail.tsx|runWorkflowAction' as const,
    action: 'retry_competitor_visual_match',
    label: '重试视觉初筛',
  },
  {
    title: 'ProductDetail dispatches workflow generic retry',
    id: 'retryStep|frontend/src/pages/ProductDetail.tsx|runWorkflowAction' as const,
    action: 'retry',
    label: '重试',
  },
]) {
  mutationTest(
    workflowCase.title,
    workflowCase.id,
    '/products/42',
    {
      product: {
        ...productDetailFixture,
        status: 'failed',
        current_step: 3,
        workflow: workflowFixture(workflowCase.action, workflowCase.label),
      },
    },
    async (page) => page.getByRole('button', { name: antButtonName(workflowCase.label) }).click(),
    async (page) => expect(page.getByRole('heading', { name: '商品 #42' })).toBeVisible(),
  );
}

mutationTest(
  'ProductDetail preserves A+ output on retry-regeneration denial',
  'retryAplusRegeneration|frontend/src/pages/ProductDetail.tsx|retryInterruptedAplus',
  '/products/42',
  { product: { ...productDetailFixture, aplus: { ...aplusDoneFixture, aplus_status: 'regen_interrupted' } } },
  async (page) => page.getByRole('button', { name: '重试A+重新生图' }).click(),
  async (page) => {
    await expect(page.getByText('重新生图被中断').first()).toBeVisible();
    await expect(page.getByText('模块 1').first()).toBeVisible();
  },
);

mutationTest(
  'ProductDetail distinguishes direct failed retry owner',
  'retryStep|frontend/src/pages/ProductDetail.tsx|ProductDetail',
  '/products/42',
  {
    product: {
      ...productDetailFixture,
      status: 'failed',
      current_step: 3,
      current_task_status: 'R1 generic failure',
      error_message: 'R1 generic failure',
      workflow: null,
    },
  },
  async (page) => page.getByRole('button', { name: antButtonName('重试') }).click(),
  async (page) => expect(page.getByText('R1 generic failure').first()).toBeVisible(),
);

mutationTest(
  'ProductDetail preserves Listing tab on regenerate denial',
  'runProductFromStep|frontend/src/pages/ProductDetail.tsx|regenerateListing',
  '/products/42',
  { product: productDetailFixture },
  async (page) => {
    await clickDetailTab(page, /Listing文案/);
    const titleCard = page.locator('.ant-card').filter({ has: page.getByText('标题', { exact: true }) }).first();
    await confirmPopconfirm(page, titleCard.getByRole('button', { name: '重新生成' }), '重新生成');
  },
  async (page) => expect(page.getByRole('tab', { name: /Listing文案/ })).toHaveAttribute('aria-selected', 'true'),
);

mutationTest(
  'ProductDetail preserves interrupted-node detail on run-from-step denial',
  'runProductFromStep|frontend/src/pages/ProductDetail.tsx|retryInterruptedPipeline',
  '/products/42',
  {
    product: {
      ...productDetailFixture,
      status: 'step5_listing',
      current_step: 5,
      current_task_status: '运行状态已中断，请重试',
      workflow: null,
    },
  },
  async (page) => page.getByRole('button', { name: '重试当前节点' }).click(),
  async (page) => expect(page.getByRole('heading', { name: '商品 #42' })).toBeVisible(),
);

mutationTest(
  'ProductDetail preserves category editor selection',
  'updateProduct|frontend/src/pages/ProductDetail.tsx|saveCategory',
  '/products/42',
  { product: productDetailFixture },
  async (page) => {
    await clickDetailTab(page, /基本信息/);
    await page.getByRole('button', { name: '编辑类目' }).click();
    const dialog = page.getByRole('dialog', { name: '编辑 Amazon 类目' });
    await expect(dialog.locator('.ant-select-selection-item')).toContainText('Furniture > Sofas');
    await dialog.locator('.ant-modal-footer .ant-btn-primary').click();
  },
  async (page) => {
    const dialog = page.getByRole('dialog', { name: '编辑 Amazon 类目' });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.ant-select-selection-item')).toContainText('Furniture > Sofas');
  },
);

mutationTest(
  'ProductDetail preserves Listing editor draft',
  'updateProduct|frontend/src/pages/ProductDetail.tsx|saveListing',
  '/products/42',
  { product: productDetailFixture },
  async (page) => {
    await clickDetailTab(page, /Listing文案/);
    const titleCard = page.locator('.ant-card').filter({ has: page.getByText('标题', { exact: true }) }).first();
    await titleCard.getByRole('button', { name: '编辑 Listing' }).click();
    const dialog = page.getByRole('dialog', { name: '编辑 Listing 文案' });
    await dialog.locator('textarea').first().fill('R1 retained edited title');
    await dialog.locator('.ant-modal-footer .ant-btn-primary').click();
  },
  async (page) => {
    const dialog = page.getByRole('dialog', { name: '编辑 Listing 文案' });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('textarea').first()).toHaveValue('R1 retained edited title');
  },
);

mutationTest(
  'ProductDetail preserves listing-image draft',
  'updateProductListingImages|frontend/src/pages/ProductDetail.tsx|saveListingImagePaths',
  '/products/42',
  { product: productDetailFixture },
  async (page) => {
    await clickDetailTab(page, /图片素材/);
    await page.getByAltText('unused.jpg').dblclick();
    const imageCard = page.locator('.ant-card').filter({ has: page.getByText('商品图片确认', { exact: true }) });
    await imageCard.getByRole('button', { name: antButtonName('保存') }).click();
  },
  async (page) => {
    await expect(page.getByText('未保存', { exact: true })).toBeVisible();
    const retainedDraftImage = page.getByAltText('副图2');
    await expect(retainedDraftImage).toBeVisible();
    await expect(retainedDraftImage).toHaveAttribute('src', /\/api\/images\/r1\/unused\.jpg$/);
  },
);
