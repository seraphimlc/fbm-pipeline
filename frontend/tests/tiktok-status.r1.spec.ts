import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';


type ChannelStatus = 'failed' | 'draft' | 'missing_required_info' | 'unsupported';

type TikTokFrontendState = {
  frontend_base_url: string;
  tiktok_data_source_id: number;
  product_ids: Record<string, number>;
  pagination_tie_product_ids: number[];
  pagination_tie_timestamp: string;
};

type ProductListItem = {
  id: number;
  sales_channel: string | null;
  channel_status: ChannelStatus | null;
  channel_status_label: string | null;
  channel_status_reason: string | null;
  channel_capabilities: { export_supported: boolean; publish_supported: boolean } | null;
};

type ProductListPayload = {
  items: ProductListItem[];
  total: number;
};

const statePath = process.env.R1_TIKTOK_FRONTEND_STATE;
if (!statePath) throw new Error('R1_TIKTOK_FRONTEND_STATE is required');
const state = JSON.parse(readFileSync(statePath, 'utf-8')) as TikTokFrontendState;

const ALLOWED_CONSOLE_MESSAGES = new Set([
  'Warning: [antd: compatible] antd v5 support React is 16 ~ 18. see https://u.ant.design/v5-for-19 for compatible.',
]);

const normalizeConsoleText = (value: string) => value
  .replaceAll('\r\n', '\n')
  .replaceAll('\r', '\n')
  .split('\n')
  .map((line) => line.trim())
  .filter(Boolean)
  .join(' ');

const observeBrowserFailures = (page: Page) => {
  const failures: string[] = [];
  page.on('pageerror', (error) => failures.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (!['error', 'warning'].includes(message.type())) return;
    const normalized = normalizeConsoleText(message.text());
    if (!ALLOWED_CONSOLE_MESSAGES.has(normalized)) failures.push(`console ${message.type()}: ${normalized}`);
  });
  page.on('requestfailed', (request) => failures.push(`requestfailed: ${request.url()} ${request.failure()?.errorText || ''}`));
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (['http:', 'https:'].includes(url.protocol) && !['127.0.0.1', 'localhost'].includes(url.hostname)) {
      failures.push(`external-request: ${request.url()}`);
    }
  });
  return failures;
};

const isGetPath = (response: { url: () => string; request: () => { method: () => string } }, path: string) => {
  const url = new URL(response.url());
  return response.request().method() === 'GET' && url.pathname === path;
};

test('TikTok product list uses projected channel status, filters and counts', async ({ page }) => {
  const failures = observeBrowserFailures(page);
  const productListQueries: URL[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (request.method() === 'GET' && url.pathname === '/api/products') productListQueries.push(url);
  });
  await page.addInitScript(({ dataSourceId }) => {
    window.localStorage.setItem('fbm.productList.dataSourceId', String(dataSourceId));
  }, { dataSourceId: state.tiktok_data_source_id });

  const listResponsePromise = page.waitForResponse((response) => {
    if (!isGetPath(response, '/api/products')) return false;
    const url = new URL(response.url());
    return url.searchParams.get('data_source_id') === String(state.tiktok_data_source_id)
      && !url.searchParams.has('channel_status');
  });
  const overviewResponsePromise = page.waitForResponse((response) => {
    if (!isGetPath(response, '/api/products/overview')) return false;
    return new URL(response.url()).searchParams.get('data_source_id') === String(state.tiktok_data_source_id);
  });
  await page.goto('/products?status=completed&work_status=export_ready');
  const listResponse = await listResponsePromise;
  const overviewResponse = await overviewResponsePromise;
  expect(listResponse.status()).toBe(200);
  expect(overviewResponse.status()).toBe(200);
  expect(productListQueries.every((url) => !url.searchParams.has('status') && !url.searchParams.has('work_status'))).toBe(true);

  const payload = await listResponse.json() as ProductListPayload;
  expect(payload.total).toBeGreaterThan(payload.items.length);
  expect(payload.items.length).toBeLessThanOrEqual(20);
  for (const item of payload.items) {
    expect(item).toMatchObject({
      sales_channel: 'tiktok',
      channel_capabilities: { export_supported: false, publish_supported: false },
    });
  }

  const workbench = page.locator('.product-workbench');
  await expect(page.getByTestId('tiktok-channel-filter')).toBeVisible();
  for (const status of ['failed', 'draft', 'missing_required_info', 'unsupported'] satisfies ChannelStatus[]) {
    await expect(page.getByTestId(`tiktok-channel-metric-${status}`)).toBeVisible();
  }
  await expect(workbench).not.toContainText('待 TikTok 导出');

  const rows = workbench.locator('.ant-table-tbody .ant-table-row');
  for (let index = 0; index < await rows.count(); index += 1) {
    const buttonText = await rows.nth(index).locator('button').allTextContents();
    expect(buttonText.join(' ')).not.toMatch(/Amazon Export Center|^导出$|^发布$/);
  }

  const statusLabels: Array<[ChannelStatus, string]> = [
    ['failed', '失败'],
    ['draft', '草稿'],
    ['missing_required_info', '资料不完整'],
    ['unsupported', '资料已齐 · 导出暂未接入'],
  ];
  for (const [status, label] of statusLabels) {
    const filteredResponsePromise = page.waitForResponse((response) => {
      if (!isGetPath(response, '/api/products')) return false;
      const url = new URL(response.url());
      return url.searchParams.get('data_source_id') === String(state.tiktok_data_source_id)
        && url.searchParams.get('channel_status') === status;
    });
    await page.getByTestId(`tiktok-channel-metric-${status}`).click();
    const filteredResponse = await filteredResponsePromise;
    expect(filteredResponse.status()).toBe(200);
    const filteredPayload = await filteredResponse.json() as ProductListPayload;
    expect(filteredPayload.total).toBeGreaterThan(0);
    expect(filteredPayload.items.every((item) => item.channel_status === status)).toBe(true);
    await expect(page).toHaveURL(new RegExp(`channel_status=${status}`));
    await expect(workbench.locator('.ant-table-tbody .ant-table-row')).toHaveCount(filteredPayload.items.length);
    await expect(workbench.getByText(label, { exact: true }).first()).toBeVisible();
    await expect(workbench).not.toContainText('待 TikTok 导出');
  }

  const expectedPaginationIds = [...state.pagination_tie_product_ids].sort((left, right) => right - left);
  const observedPaginationIds: number[] = [];
  for (let pageNumber = 1; observedPaginationIds.length < expectedPaginationIds.length; pageNumber += 1) {
    const response = await page.request.get('/api/products', {
      params: {
        data_source_id: state.tiktok_data_source_id,
        created_from: state.pagination_tie_timestamp,
        created_to: state.pagination_tie_timestamp,
        page: pageNumber,
        page_size: 7,
      },
    });
    expect(response.status()).toBe(200);
    const pagePayload = await response.json() as ProductListPayload;
    expect(pagePayload.total).toBe(expectedPaginationIds.length);
    const pageIds = pagePayload.items.map((item) => item.id);
    expect(new Set(pageIds).size).toBe(pageIds.length);
    observedPaginationIds.push(...pageIds);
  }
  expect(observedPaginationIds).toEqual(expectedPaginationIds);
  expect(new Set(observedPaginationIds).size).toBe(expectedPaginationIds.length);

  expect(failures).toEqual([]);
});

test('TikTok detail uses the same four statuses and exposes refresh only', async ({ page }) => {
  const failures = observeBrowserFailures(page);
  const expectedLabels: Array<[string, ChannelStatus, string]> = [
    ['failed', 'failed', '失败'],
    ['draft', 'draft', '草稿'],
    ['missing_required_info', 'missing_required_info', '资料不完整'],
    ['unsupported', 'unsupported', '资料已齐 · 导出暂未接入'],
  ];

  for (const [key, expectedStatus, label] of expectedLabels) {
    const productId = state.product_ids[key];
    const responsePromise = page.waitForResponse((response) => isGetPath(response, `/api/tiktok/products/${productId}`));
    await page.goto(`/tiktok/products/${productId}`);
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    expect((await response.json()).status).toBe(expectedStatus);

    const detail = page.locator('.tiktok-product-detail');
    await expect(detail.getByText(label, { exact: true }).first()).toBeVisible();
    await expect(detail.getByText(
      '当前版本暂不支持 TikTok 导出或发布；不会生成文件，也不会提交到平台',
      { exact: true },
    )).toBeVisible();
    await expect(detail).not.toContainText('待 TikTok 导出');
    const buttons = detail.getByRole('button');
    await expect(buttons).toHaveCount(1);
    await expect(buttons.first()).toHaveText('刷新');
  }

  const detailSource = readFileSync('./src/pages/TikTokProductDetail.tsx', 'utf-8');
  const listSource = readFileSync('./src/pages/ProductList.tsx', 'utf-8');
  expect(detailSource).not.toContain('export_ready');
  expect(detailSource).not.toContain('待 TikTok 导出');
  expect(listSource).not.toContain('待 TikTok 导出');
  expect(failures).toEqual([]);
});
