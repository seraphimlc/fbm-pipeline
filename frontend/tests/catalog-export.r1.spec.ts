import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';


type CatalogFrontendState = {
  frontend_base_url: string;
  partial_run_id: number;
  failed_run_id: number;
  historical_missing_rows_run_id: number;
  malformed_run_id: number;
  malformed_offline_task_id: number;
  unsafe_run_id: number;
  unsafe_offline_task_id: number;
  unsafe_category: string;
  legacy_done_run_id: number;
  malformed_row_count: number;
  partial_skipped_row_ordinal: number;
  failed_row_ordinal: number;
  partial_reason: string;
  failed_reason: string;
  artifact_filename: string;
  artifact_sha256: string;
  artifact_size: number;
};

type CatalogExportRowApi = {
  row_ordinal: number;
  catalog_id?: number | null;
  product_id?: number | null;
  item_code?: string | null;
  seller_sku?: string | null;
  category?: string | null;
  status?: string | null;
  reason?: string | null;
  template_file?: string | null;
  output_file?: string | null;
};

type CatalogTaskRunApi = {
  id: number;
  status: string;
  display_status?: string | null;
  display_status_label?: string | null;
  catalog_export_result?: {
    status?: string | null;
    requested_count?: number | null;
    success_count?: number | null;
    skipped_count?: number | null;
    failed_count?: number | null;
    report_count?: number | null;
    rows?: CatalogExportRowApi[] | null;
  } | null;
};

type CatalogTaskRunListApi = {
  items: CatalogTaskRunApi[];
  total: number;
  base_total?: number | null;
  filtered_total?: number | null;
  page: number;
  page_size: number;
};

type CatalogExportFileApi = {
  task_id: number;
  task_source: string;
  task_status: string;
  can_download: boolean;
  success_count: number;
  skipped_count: number;
  failed_count: number;
  rows: CatalogExportRowApi[];
};

type CatalogExportFileListApi = {
  items: CatalogExportFileApi[];
};

type CatalogOfflineTaskApi = {
  id: number;
  status: string;
  result_json: string | null;
  can_download: boolean;
  catalog_export_result?: CatalogTaskRunApi['catalog_export_result'];
  steps?: Array<{ result_json: string | null }>;
};

type CatalogOfflineTaskListApi = {
  items: CatalogOfflineTaskApi[];
};

const statePath = process.env.R1_CATALOG_FRONTEND_STATE;
if (!statePath) {
  throw new Error('R1_CATALOG_FRONTEND_STATE is required');
}
const state = JSON.parse(readFileSync(statePath, 'utf-8')) as CatalogFrontendState;
const ALLOWED_CONSOLE_MESSAGES = new Set<string>([
  'Warning: [antd: compatible] antd v5 support React is 16 ~ 18. see https://u.ant.design/v5-for-19 for compatible.',
]);

const normalizeConsoleText = (value: string) => value
  .replaceAll('\r\n', '\n')
  .replaceAll('\r', '\n')
  .split('\n')
  .map((line) => line.trim())
  .filter(Boolean)
  .join(' ');

const isGetResponseForPath = (response: { url: () => string; request: () => { method: () => string } }, path: string) => {
  const url = new URL(response.url());
  return response.request().method() === 'GET' && url.pathname === path;
};

const catalogResultEvidence = (run: CatalogTaskRunApi) => {
  const result = run.catalog_export_result;
  if (!result) throw new Error(`TaskRun #${run.id} missing catalog_export_result`);
  return {
    status: result.status ?? null,
    requested_count: result.requested_count ?? null,
    success_count: result.success_count ?? null,
    skipped_count: result.skipped_count ?? null,
    failed_count: result.failed_count ?? null,
    report_count: result.report_count ?? null,
    rows: (result.rows ?? []).map((row) => ({
      row_ordinal: row.row_ordinal,
      catalog_id: row.catalog_id ?? null,
      product_id: row.product_id ?? null,
      item_code: row.item_code ?? null,
      seller_sku: row.seller_sku ?? null,
      category: row.category ?? null,
      status: row.status ?? null,
      reason: row.reason ?? null,
      template_file: row.template_file ?? null,
      output_file: row.output_file ?? null,
    })),
  };
};

const visibleReasonTestIds = async (container: Locator, prefix: string) => (
  container.locator(`[data-testid^="${prefix}"]`).evaluateAll((nodes) => (
    nodes.map((node) => node.getAttribute('data-testid'))
  ))
);

const reasonTestIds = (prefix: string, ordinals: number[]) => (
  ordinals.map((ordinal) => `${prefix}${ordinal}`)
);

const observeBrowserFailures = (page: Page) => {
  const failures: string[] = [];
  const knownCompatibilityWarnings: string[] = [];
  page.on('pageerror', (error) => failures.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() !== 'error' && message.type() !== 'warning') return;
    const normalizedText = normalizeConsoleText(message.text());
    if (ALLOWED_CONSOLE_MESSAGES.has(normalizedText)) {
      knownCompatibilityWarnings.push(normalizedText);
      return;
    }
    failures.push(`console ${message.type()}: ${normalizedText}`);
  });
  page.on('requestfailed', (request) => {
    failures.push(`requestfailed: ${request.url()} ${request.failure()?.errorText || ''}`);
  });
  page.on('request', (request) => {
    const url = new URL(request.url());
    const isHttp = url.protocol === 'http:' || url.protocol === 'https:';
    const isLocal = url.hostname === '127.0.0.1' || url.hostname === 'localhost';
    if (isHttp && !isLocal) {
      failures.push(`external-request: ${request.url()}`);
    }
  });
  return { failures, knownCompatibilityWarnings };
};

test('catalog export structured results use real TaskRun and Export APIs', async ({ page }) => {
  const { failures, knownCompatibilityWarnings } = observeBrowserFailures(page);

  const listResponsePromise = page.waitForResponse((response) => {
    if (!isGetResponseForPath(response, '/api/task-runs')) return false;
    const url = new URL(response.url());
    return url.searchParams.get('q') === 'R1 Catalog Frontend'
      && url.searchParams.get('task_type') === 'catalog_export';
  });
  await page.goto(`/task-runs?view=all&task_type=catalog_export&q=${encodeURIComponent('R1 Catalog Frontend')}`);
  const listResponse = await listResponsePromise;
  expect(listResponse.status()).toBe(200);
  const listPayload = await listResponse.json() as CatalogTaskRunListApi;
  const partialListRun = listPayload.items.find((run) => run.id === state.partial_run_id);
  const historicalListRun = listPayload.items.find((run) => run.id === state.historical_missing_rows_run_id);
  const malformedListRun = listPayload.items.find((run) => run.id === state.malformed_run_id);
  const unsafeListRun = listPayload.items.find((run) => run.id === state.unsafe_run_id);
  const legacyDoneListRun = listPayload.items.find((run) => run.id === state.legacy_done_run_id);
  expect(partialListRun).toBeDefined();
  expect(historicalListRun).toBeDefined();
  expect(malformedListRun).toBeDefined();
  expect(unsafeListRun).toBeDefined();
  expect(legacyDoneListRun).toBeDefined();
  if (!partialListRun || !historicalListRun || !malformedListRun || !unsafeListRun || !legacyDoneListRun) {
    throw new Error('catalog list fixtures missing');
  }
  const partialListEvidence = catalogResultEvidence(partialListRun);
  const malformedListEvidence = catalogResultEvidence(malformedListRun);
  expect(historicalListRun.catalog_export_result?.rows ?? []).toEqual([]);
  expect(malformedListEvidence).toMatchObject({
    status: 'failed',
    requested_count: 15,
    success_count: 1,
    skipped_count: 1,
    failed_count: 13,
    report_count: 15,
  });
  expect(malformedListEvidence.rows.map((row) => row.row_ordinal)).toEqual(
    Array.from({ length: state.malformed_row_count }, (_, index) => index + 1),
  );
  expect(catalogResultEvidence(unsafeListRun)).toMatchObject({
    status: 'failed',
    requested_count: 1,
    success_count: 0,
    skipped_count: 0,
    failed_count: 1,
    report_count: 1,
    rows: [{ row_ordinal: 1, catalog_id: null, status: 'failed' }],
  });
  expect(unsafeListRun).toMatchObject({
    status: 'failed',
    display_status: 'failed',
    display_status_label: '失败',
  });
  expect(catalogResultEvidence(legacyDoneListRun)).toMatchObject({
    status: 'done',
    requested_count: 1,
    success_count: 1,
    skipped_count: 0,
    failed_count: 0,
  });

  const partialSummary = page.getByTestId(`task-run-catalog-summary-${state.partial_run_id}`);
  await expect(partialSummary).toBeVisible();
  await expect(page.getByTestId(`task-run-catalog-result-status-${state.partial_run_id}`)).toContainText('部分完成');
  await expect(page.getByTestId(`task-run-catalog-count-requested-${state.partial_run_id}`)).toContainText('请求 3');
  await expect(page.getByTestId(`task-run-catalog-count-success-${state.partial_run_id}`)).toContainText('成功 1');
  await expect(page.getByTestId(`task-run-catalog-count-skipped-${state.partial_run_id}`)).toContainText('跳过 1');
  await expect(page.getByTestId(`task-run-catalog-count-failed-${state.partial_run_id}`)).toContainText('失败 1');
  await expect(page.getByTestId(`task-run-catalog-count-report-${state.partial_run_id}`)).toContainText('报告 3');
  await expect(page.getByTestId(`task-run-download-${state.partial_run_id}`)).toBeVisible();
  await expect(page.getByTestId(`task-run-download-${state.failed_run_id}`)).toHaveCount(0);
  await expect(page.getByTestId(`task-run-catalog-result-status-${state.unsafe_run_id}`)).toContainText('失败');
  await expect(page.getByTestId(`task-run-catalog-count-success-${state.unsafe_run_id}`)).toContainText('成功 0');
  await expect(page.getByTestId(`task-run-catalog-count-failed-${state.unsafe_run_id}`)).toContainText('失败 1');
  await expect(page.getByTestId(`task-run-download-${state.unsafe_run_id}`)).toHaveCount(0);
  await expect(
    page.getByTestId(`task-run-expand-${state.unsafe_run_id}`).locator('xpath=ancestor::tr[1]').getByText('失败', { exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId(`task-run-catalog-result-status-${state.legacy_done_run_id}`)).toContainText('已完成');
  await expect(page.getByTestId(`task-run-download-${state.legacy_done_run_id}`)).toBeVisible();

  const failedCurrentResponse = await page.request.get('/api/task-runs', {
    params: {
      page: 1,
      page_size: 1,
      view: 'current',
      display_status: 'failed',
      task_type: 'catalog_export',
      q: 'R1 Catalog Frontend',
    },
  });
  expect(failedCurrentResponse.status()).toBe(200);
  const failedCurrentPayload = await failedCurrentResponse.json() as CatalogTaskRunListApi;
  expect(failedCurrentPayload).toMatchObject({
    total: 4,
    base_total: 5,
    filtered_total: 4,
    page: 1,
    page_size: 1,
  });
  expect(failedCurrentPayload.items.map((run) => run.id)).toEqual([state.unsafe_run_id]);
  expect(failedCurrentPayload.items[0]).toMatchObject({ status: 'failed', display_status: 'failed' });

  const succeededHistoryResponse = await page.request.get('/api/task-runs', {
    params: {
      page: 1,
      page_size: 1,
      view: 'history',
      display_status: 'succeeded',
      task_type: 'catalog_export',
      q: 'R1 Catalog Frontend',
    },
  });
  expect(succeededHistoryResponse.status()).toBe(200);
  const succeededHistoryPayload = await succeededHistoryResponse.json() as CatalogTaskRunListApi;
  expect(succeededHistoryPayload).toMatchObject({
    total: 1,
    base_total: 1,
    filtered_total: 1,
    page: 1,
    page_size: 1,
  });
  expect(succeededHistoryPayload.items.map((run) => run.id)).toEqual([state.legacy_done_run_id]);
  expect(succeededHistoryPayload.items[0]).toMatchObject({ status: 'succeeded', display_status: 'succeeded' });

  const partialDetailResponsePromise = page.waitForResponse(
    (response) => isGetResponseForPath(response, `/api/task-runs/${state.partial_run_id}`),
  );
  await page.getByTestId(`task-run-expand-${state.partial_run_id}`).click();
  const partialDetailResponse = await partialDetailResponsePromise;
  expect(partialDetailResponse.status()).toBe(200);
  const partialDetailPayload = await partialDetailResponse.json() as CatalogTaskRunApi;
  const partialDetailEvidence = catalogResultEvidence(partialDetailPayload);
  expect(partialDetailEvidence).toEqual(partialListEvidence);

  // Re-assert after the detail response has replaced the list record in component state.
  await expect(page.getByTestId(`task-run-catalog-result-status-${state.partial_run_id}`)).toContainText('部分完成');
  await expect(page.getByTestId(`task-run-catalog-count-requested-${state.partial_run_id}`)).toContainText('请求 3');
  await expect(page.getByTestId(`task-run-catalog-count-success-${state.partial_run_id}`)).toContainText('成功 1');
  await expect(page.getByTestId(`task-run-catalog-count-skipped-${state.partial_run_id}`)).toContainText('跳过 1');
  await expect(page.getByTestId(`task-run-catalog-count-failed-${state.partial_run_id}`)).toContainText('失败 1');
  await expect(page.getByTestId(`task-run-catalog-count-report-${state.partial_run_id}`)).toContainText('报告 3');
  await expect(page.getByTestId(`task-run-catalog-rows-${state.partial_run_id}`)).toBeVisible();
  await expect(
    page.getByTestId(`task-run-catalog-row-reason-${state.partial_run_id}-${state.partial_skipped_row_ordinal}`),
  ).toHaveText(state.partial_reason);

  const malformedDetailResponsePromise = page.waitForResponse(
    (response) => isGetResponseForPath(response, `/api/task-runs/${state.malformed_run_id}`),
  );
  await page.getByTestId(`task-run-expand-${state.malformed_run_id}`).click();
  const malformedDetailResponse = await malformedDetailResponsePromise;
  expect(malformedDetailResponse.status()).toBe(200);
  const malformedDetailPayload = await malformedDetailResponse.json() as CatalogTaskRunApi;
  expect(malformedDetailPayload.catalog_export_result).toEqual(malformedListRun.catalog_export_result);

  const malformedRunRows = page.getByTestId(`task-run-catalog-rows-${state.malformed_run_id}`);
  const malformedRunReasonPrefix = `task-run-catalog-row-reason-${state.malformed_run_id}-`;
  await expect.poll(() => visibleReasonTestIds(malformedRunRows, malformedRunReasonPrefix)).toEqual(
    reasonTestIds(malformedRunReasonPrefix, [1, 2, 3, 4, 5, 6, 7, 8]),
  );
  await expect(malformedRunRows.getByText('资料 #72002', { exact: true })).toHaveCount(2);
  await expect(page.getByTestId(`${malformedRunReasonPrefix}4`)).toHaveText('duplicate first');
  await expect(page.getByTestId(`${malformedRunReasonPrefix}5`)).toHaveText('duplicate second');
  await expect(page.getByTestId(`${malformedRunReasonPrefix}6`)).toHaveText('导出结果行格式异常');
  await expect(page.getByTestId(`${malformedRunReasonPrefix}7`)).toHaveText('导出结果行格式异常');
  await expect(page.getByTestId(`${malformedRunReasonPrefix}8`)).toHaveText('slash code');
  await expect(malformedRunRows.getByText('A/B', { exact: true })).toBeVisible();
  await malformedRunRows.locator('.ant-pagination-next button').click();
  await expect.poll(() => visibleReasonTestIds(malformedRunRows, malformedRunReasonPrefix)).toEqual(
    reasonTestIds(malformedRunReasonPrefix, [9, 10, 11, 12, 13, 14, 15]),
  );
  await expect(page.getByTestId(`${malformedRunReasonPrefix}9`)).toHaveText('space code');
  await expect(page.getByTestId(`${malformedRunReasonPrefix}10`)).toHaveText('Unicode 行');
  await expect(malformedRunRows.getByText('A B', { exact: true })).toBeVisible();
  await expect(malformedRunRows.getByText('商品-甲', { exact: true })).toBeVisible();
  for (const ordinal of [11, 12, 13, 14, 15]) {
    await expect(page.getByTestId(`${malformedRunReasonPrefix}${ordinal}`)).toHaveText('导出结果行格式异常');
  }
  await expect(malformedRunRows.getByText('BAD-STATUS', { exact: true })).toBeVisible();

  const historicalDetailResponsePromise = page.waitForResponse(
    (response) => isGetResponseForPath(response, `/api/task-runs/${state.historical_missing_rows_run_id}`),
  );
  await page.getByTestId(`task-run-expand-${state.historical_missing_rows_run_id}`).click();
  const historicalDetailResponse = await historicalDetailResponsePromise;
  expect(historicalDetailResponse.status()).toBe(200);
  const historicalDetailPayload = await historicalDetailResponse.json() as CatalogTaskRunApi;
  expect(historicalDetailPayload.catalog_export_result?.rows ?? []).toEqual([]);
  await expect(page.getByTestId(`task-run-catalog-rows-${state.historical_missing_rows_run_id}`)).toContainText(
    '暂无逐商品结果',
  );

  const offlineListResponsePromise = page.waitForResponse(
    (response) => isGetResponseForPath(response, '/api/offline-tasks'),
  );
  await page.goto('/offline-tasks');
  const offlineListResponse = await offlineListResponsePromise;
  expect(offlineListResponse.status()).toBe(200);
  const offlineListPayload = await offlineListResponse.json() as CatalogOfflineTaskListApi;
  const malformedOfflineListTask = offlineListPayload.items.find((item) => item.id === state.malformed_offline_task_id);
  const unsafeOfflineListTask = offlineListPayload.items.find((item) => item.id === state.unsafe_offline_task_id);
  expect(malformedOfflineListTask).toBeDefined();
  expect(unsafeOfflineListTask).toBeDefined();
  expect(malformedOfflineListTask?.catalog_export_result).toEqual(malformedListRun.catalog_export_result);
  expect(JSON.parse(malformedOfflineListTask?.result_json || '{}')).toEqual(malformedListRun.catalog_export_result);
  expect(malformedOfflineListTask?.can_download).toBe(false);
  expect(unsafeOfflineListTask?.catalog_export_result).toEqual(unsafeListRun.catalog_export_result);
  expect(JSON.parse(unsafeOfflineListTask?.result_json || '{}')).toEqual(unsafeListRun.catalog_export_result);
  expect(unsafeOfflineListTask?.status).toBe('failed');
  expect(unsafeOfflineListTask?.can_download).toBe(false);
  await expect(page.getByTestId(`offline-task-${state.malformed_offline_task_id}`)).toBeVisible();
  await expect(page.getByTestId(`offline-task-catalog-summary-${state.malformed_offline_task_id}`)).toContainText(
    '成功 1',
  );
  await expect(page.getByTestId(`offline-task-catalog-summary-${state.malformed_offline_task_id}`)).toContainText(
    '失败 13',
  );
  await expect(page.getByTestId(`offline-task-download-${state.malformed_offline_task_id}`)).toHaveCount(0);
  await expect(page.getByTestId(`offline-task-${state.unsafe_offline_task_id}`)).toBeVisible();
  await expect(
    page.getByTestId(`offline-task-${state.unsafe_offline_task_id}`).getByText('失败', { exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId(`offline-task-catalog-result-status-${state.unsafe_offline_task_id}`)).toContainText(
    '失败',
  );
  await expect(page.getByTestId(`offline-task-catalog-summary-${state.unsafe_offline_task_id}`)).toContainText(
    '成功 0',
  );
  await expect(page.getByTestId(`offline-task-catalog-summary-${state.unsafe_offline_task_id}`)).toContainText(
    '失败 1',
  );
  await expect(page.getByTestId(`offline-task-download-${state.unsafe_offline_task_id}`)).toHaveCount(0);

  const offlineDetailResponsePromise = page.waitForResponse(
    (response) => isGetResponseForPath(response, `/api/offline-tasks/${state.malformed_offline_task_id}`),
  );
  await page.getByTestId(`offline-task-expand-${state.malformed_offline_task_id}`).click();
  const offlineDetailResponse = await offlineDetailResponsePromise;
  expect(offlineDetailResponse.status()).toBe(200);
  const offlineDetailPayload = await offlineDetailResponse.json() as CatalogOfflineTaskApi;
  expect(offlineDetailPayload.catalog_export_result).toEqual(malformedListRun.catalog_export_result);
  expect(JSON.parse(offlineDetailPayload.result_json || '{}')).toEqual(malformedListRun.catalog_export_result);
  expect(offlineDetailPayload.steps?.every((step) => step.result_json === null)).toBe(true);

  const malformedOfflineRows = page.getByTestId(`offline-task-catalog-rows-${state.malformed_offline_task_id}`);
  const malformedOfflineReasonPrefix = `offline-task-catalog-row-reason-${state.malformed_offline_task_id}-`;
  await expect.poll(() => visibleReasonTestIds(malformedOfflineRows, malformedOfflineReasonPrefix)).toEqual(
    reasonTestIds(malformedOfflineReasonPrefix, [1, 2, 3, 4, 5, 6, 7, 8]),
  );
  await expect(page.getByTestId(`${malformedOfflineReasonPrefix}4`)).toHaveText('duplicate first');
  await expect(page.getByTestId(`${malformedOfflineReasonPrefix}5`)).toHaveText('duplicate second');
  await expect(page.getByTestId(`${malformedOfflineReasonPrefix}6`)).toHaveText('导出结果行格式异常');
  await expect(page.getByTestId(`${malformedOfflineReasonPrefix}7`)).toHaveText('导出结果行格式异常');
  await malformedOfflineRows.locator('.ant-pagination-next button').click();
  await expect.poll(() => visibleReasonTestIds(malformedOfflineRows, malformedOfflineReasonPrefix)).toEqual(
    reasonTestIds(malformedOfflineReasonPrefix, [9, 10, 11, 12, 13, 14, 15]),
  );
  for (const ordinal of [11, 12, 13, 14, 15]) {
    await expect(page.getByTestId(`${malformedOfflineReasonPrefix}${ordinal}`)).toHaveText('导出结果行格式异常');
  }
  await expect(malformedOfflineRows.getByText('A B', { exact: true })).toBeVisible();
  await expect(malformedOfflineRows.getByText('商品-甲', { exact: true })).toBeVisible();
  await expect(malformedOfflineRows.getByText('BAD-STATUS', { exact: true })).toBeVisible();

  await page.goto('/export-center');
  const exportFilesResponsePromise = page.waitForResponse(
    (response) => isGetResponseForPath(response, '/api/products/catalog/export-files'),
  );
  const exportCategoriesResponsePromise = page.waitForResponse(
    (response) => isGetResponseForPath(response, '/api/products/catalog/export-categories'),
  );
  await page.getByRole('tab', { name: '已导出列表', exact: true }).click();
  const [exportFilesResponse, exportCategoriesResponse] = await Promise.all([
    exportFilesResponsePromise,
    exportCategoriesResponsePromise,
  ]);
  expect(exportFilesResponse.status()).toBe(200);
  expect(exportCategoriesResponse.status()).toBe(200);
  const exportFilesPayload = await exportFilesResponse.json() as CatalogExportFileListApi;
  const malformedExportFile = exportFilesPayload.items.find((item) => (
    item.task_source === 'task_run' && item.task_id === state.malformed_run_id
  ));
  const malformedOfflineExportFile = exportFilesPayload.items.find((item) => (
    item.task_source === 'offline_task' && item.task_id === state.malformed_offline_task_id
  ));
  const unsafeExportFile = exportFilesPayload.items.find((item) => (
    item.task_source === 'task_run' && item.task_id === state.unsafe_run_id
  ));
  const unsafeOfflineExportFile = exportFilesPayload.items.find((item) => (
    item.task_source === 'offline_task' && item.task_id === state.unsafe_offline_task_id
  ));
  const legacyDoneExportFile = exportFilesPayload.items.find((item) => (
    item.task_source === 'task_run' && item.task_id === state.legacy_done_run_id
  ));
  expect(malformedExportFile).toBeDefined();
  expect(malformedOfflineExportFile).toBeDefined();
  expect(unsafeExportFile).toBeDefined();
  expect(unsafeOfflineExportFile).toBeDefined();
  expect(legacyDoneExportFile).toBeDefined();
  expect(malformedExportFile?.can_download).toBe(false);
  expect(malformedOfflineExportFile?.can_download).toBe(false);
  expect(malformedExportFile?.rows).toEqual(malformedListRun.catalog_export_result?.rows);
  expect(malformedOfflineExportFile?.rows).toEqual(malformedListRun.catalog_export_result?.rows);
  for (const item of [unsafeExportFile, unsafeOfflineExportFile]) {
    expect(item).toMatchObject({
      task_status: 'failed',
      success_count: 0,
      skipped_count: 0,
      failed_count: 1,
      can_download: false,
    });
  }
  expect(legacyDoneExportFile).toMatchObject({ task_status: 'succeeded', success_count: 1, can_download: true });
  const exportedCategories = (await exportCategoriesResponse.json() as { exported: Array<{ category: string }> }).exported;
  expect(exportedCategories.some((item) => item.category === state.unsafe_category)).toBe(false);

  const partialKey = `task_run-${state.partial_run_id}`;
  const failedKey = `task_run-${state.failed_run_id}`;
  const malformedKey = `task_run-${state.malformed_run_id}`;
  const malformedOfflineKey = `offline_task-${state.malformed_offline_task_id}`;
  const unsafeKey = `task_run-${state.unsafe_run_id}`;
  const unsafeOfflineKey = `offline_task-${state.unsafe_offline_task_id}`;
  const legacyDoneKey = `task_run-${state.legacy_done_run_id}`;
  await expect(page.getByTestId(`catalog-export-file-${partialKey}`)).toBeVisible();
  await expect(page.getByTestId(`catalog-export-file-${failedKey}`)).toBeVisible();
  await expect(page.getByTestId(`catalog-export-file-${malformedKey}`)).toBeVisible();
  await expect(page.getByTestId(`catalog-export-file-${malformedOfflineKey}`)).toBeVisible();
  await expect(page.getByTestId(`catalog-export-file-${unsafeKey}`)).toBeVisible();
  await expect(page.getByTestId(`catalog-export-file-${unsafeOfflineKey}`)).toBeVisible();
  await expect(page.getByTestId(`catalog-export-file-${legacyDoneKey}`)).toBeVisible();
  await expect(page.getByTestId(`catalog-export-file-status-${partialKey}`)).toContainText('部分完成');
  await expect(page.getByTestId(`catalog-export-file-status-${failedKey}`)).toContainText('失败');
  await expect(page.getByTestId(`catalog-export-file-status-${malformedKey}`)).toContainText('失败');
  await expect(page.getByTestId(`catalog-export-file-status-${unsafeKey}`)).toContainText('失败');
  await expect(page.getByTestId(`catalog-export-file-status-${unsafeOfflineKey}`)).toContainText('失败');
  await expect(page.getByTestId(`catalog-export-file-status-${legacyDoneKey}`)).toContainText('已完成');
  await expect(page.getByTestId(`catalog-export-file-counts-${partialKey}`)).toContainText('成功 1 · 跳过 1 · 失败 1 · 报告 3');

  const partialDownload = page.getByTestId(`catalog-export-file-download-${partialKey}`);
  const failedDownload = page.getByTestId(`catalog-export-file-download-${failedKey}`);
  const malformedDownload = page.getByTestId(`catalog-export-file-download-${malformedKey}`);
  const malformedOfflineDownload = page.getByTestId(`catalog-export-file-download-${malformedOfflineKey}`);
  const unsafeDownload = page.getByTestId(`catalog-export-file-download-${unsafeKey}`);
  const unsafeOfflineDownload = page.getByTestId(`catalog-export-file-download-${unsafeOfflineKey}`);
  const legacyDoneDownload = page.getByTestId(`catalog-export-file-download-${legacyDoneKey}`);
  await expect(partialDownload).toBeEnabled();
  await expect(failedDownload).toBeDisabled();
  await expect(malformedDownload).toBeDisabled();
  await expect(malformedOfflineDownload).toBeDisabled();
  await expect(unsafeDownload).toBeDisabled();
  await expect(unsafeOfflineDownload).toBeDisabled();
  await expect(legacyDoneDownload).toBeEnabled();

  await page.getByTestId(`catalog-export-file-expand-${partialKey}`).click();
  await expect(
    page.getByTestId(`catalog-export-file-row-reason-${partialKey}-${state.partial_skipped_row_ordinal}`),
  ).toHaveText(state.partial_reason);
  await page.getByTestId(`catalog-export-file-expand-${failedKey}`).click();
  await expect(
    page.getByTestId(`catalog-export-file-row-reason-${failedKey}-${state.failed_row_ordinal}`),
  ).toHaveText(state.failed_reason);
  await page.getByTestId(`catalog-export-file-expand-${malformedKey}`).click();
  const malformedFileRows = page.getByTestId(`catalog-export-file-rows-${malformedKey}`);
  const malformedFileReasonPrefix = `catalog-export-file-row-reason-${malformedKey}-`;
  await expect.poll(() => visibleReasonTestIds(malformedFileRows, malformedFileReasonPrefix)).toEqual(
    reasonTestIds(malformedFileReasonPrefix, [1, 2, 3, 4, 5, 6, 7, 8]),
  );
  await expect(malformedFileRows.getByText('资料 #72002', { exact: true })).toHaveCount(2);
  await expect(page.getByTestId(`${malformedFileReasonPrefix}4`)).toHaveText('duplicate first');
  await expect(page.getByTestId(`${malformedFileReasonPrefix}5`)).toHaveText('duplicate second');
  await expect(page.getByTestId(`${malformedFileReasonPrefix}6`)).toHaveText('导出结果行格式异常');
  await expect(page.getByTestId(`${malformedFileReasonPrefix}7`)).toHaveText('导出结果行格式异常');
  await expect(page.getByTestId(`${malformedFileReasonPrefix}8`)).toHaveText('slash code');
  await malformedFileRows.locator('.ant-pagination-next button').click();
  await expect.poll(() => visibleReasonTestIds(malformedFileRows, malformedFileReasonPrefix)).toEqual(
    reasonTestIds(malformedFileReasonPrefix, [9, 10, 11, 12, 13, 14, 15]),
  );
  await expect(page.getByTestId(`${malformedFileReasonPrefix}9`)).toHaveText('space code');
  await expect(page.getByTestId(`${malformedFileReasonPrefix}10`)).toHaveText('Unicode 行');
  await expect(malformedFileRows.getByText('A B', { exact: true })).toBeVisible();
  await expect(malformedFileRows.getByText('商品-甲', { exact: true })).toBeVisible();
  for (const ordinal of [11, 12, 13, 14, 15]) {
    await expect(page.getByTestId(`${malformedFileReasonPrefix}${ordinal}`)).toHaveText('导出结果行格式异常');
  }

  const unsafeTaskDownloadResponse = await page.request.get(
    `/api/task-runs/${state.unsafe_run_id}/download`,
    { maxRedirects: 0 },
  );
  expect(unsafeTaskDownloadResponse.status()).toBe(400);
  const unsafeOfflineTaskDownloadResponse = await page.request.get(
    `/api/offline-tasks/${state.unsafe_offline_task_id}/download`,
    { maxRedirects: 0 },
  );
  expect(unsafeOfflineTaskDownloadResponse.status()).toBe(400);

  const downloadResponsePromise = page.waitForResponse(
    (response) => isGetResponseForPath(response, `/api/task-runs/${state.partial_run_id}/download`),
  );
  const [download, downloadResponse] = await Promise.all([
    page.waitForEvent('download'),
    downloadResponsePromise,
    partialDownload.click(),
  ]);
  expect(downloadResponse.status()).toBe(200);
  const responseHeaders = downloadResponse.headers();
  const responseContentType = (responseHeaders['content-type'] || '').split(';', 1)[0].trim().toLowerCase();
  const allowedZipContentTypes = new Set(['application/zip', 'application/octet-stream', 'application/x-zip-compressed']);
  expect(allowedZipContentTypes.has(responseContentType)).toBe(true);
  expect(responseHeaders['content-disposition'] || '').toContain(state.artifact_filename);
  expect(download.suggestedFilename()).toBe(state.artifact_filename);
  const downloadedPath = await download.path();
  expect(downloadedPath).not.toBeNull();
  const downloadedBytes = readFileSync(downloadedPath!);
  expect(downloadedBytes.length).toBe(state.artifact_size);
  expect(createHash('sha256').update(downloadedBytes).digest('hex')).toBe(state.artifact_sha256);
  expect(downloadedBytes.subarray(0, 2).toString('ascii')).toBe('PK');

  await expect.poll(() => failures, { timeout: 1_000 }).toEqual([]);
  if (knownCompatibilityWarnings.length) {
    console.log(`Known Ant Design/React compatibility warning observed: ${knownCompatibilityWarnings[0]}`);
  }
});
