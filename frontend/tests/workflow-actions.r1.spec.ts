import React from 'react';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

import { ProductWorkflowUnknownAction } from '../src/workflow/ProductWorkflowUnknownAction';


type WorkflowManifestDefinition = {
  action: string;
  kind: 'api' | 'navigate';
  default_label: string;
  method?: string;
  route?: string;
  target?: string;
};


const workflowManifest = JSON.parse(
  readFileSync(new URL('../../contracts/product_workflow_actions.json', import.meta.url), 'utf8'),
) as WorkflowManifestDefinition[];


const manifestAction = (action: string) => {
  const definition = workflowManifest.find((item) => item.action === action);
  if (!definition) throw new Error(`missing workflow manifest action: ${action}`);
  return definition;
};


const replaceManifestParameters = (
  template: string,
  { productId = 42, relatedCorrelationKey = null }: { productId?: number; relatedCorrelationKey?: string | null } = {},
) => template
  .replace('{product_id}', encodeURIComponent(String(productId)))
  .replace('{related_correlation_key}', encodeURIComponent(String(relatedCorrelationKey)));


const actionWorkflow = (action: string, relatedCorrelationKey: string | null = null) => ({
  stage: 'capture_competitor_candidates',
  stage_status: 'failed',
  label: '候选竞品详情抓取失败',
  work_status: 'capture_detail',
  node_key: 'capture_competitor_candidates',
  node_label: '抓取候选竞品',
  node_type: 'async',
  node_status: 'failed',
  primary_action: action,
  primary_action_label: workflowManifest.find((item) => item.action === action)?.default_label || '未知动作',
  allowed_actions: [action, 'open_detail'],
  action_reason: '注入未知工作流动作',
  color: 'error',
  related_task_run_id: null,
  related_correlation_key: relatedCorrelationKey,
});


const productFixture = (action: string, relatedCorrelationKey: string | null = null) => ({
  id: 42,
  source_url: 'https://example.invalid/product/42',
  source_item_id: 'R1-UNKNOWN-42',
  gigab2b_url: 'https://example.invalid/product/42',
  gigab2b_product_id: 'R1-UNKNOWN-42',
  competitor_asin: null,
  amazon_asin: null,
  asin_sync_status: 'not_synced',
  asin_synced_at: null,
  asin_sync_error: null,
  amazon_product_status: null,
  amazon_product_status_synced_at: null,
  amazon_product_status_error: null,
  aplus_upload_status: 'not_uploaded',
  aplus_uploaded_at: null,
  aplus_upload_error: null,
  upc: null,
  item_code: 'R1-UNKNOWN-42',
  title: 'R1 Unknown Workflow Action Fixture',
  brand: 'R1',
  source_data_source_id: 1,
  source_site: 'US',
  source_batch_id: null,
  status: 'failed',
  current_step: 2,
  current_task_status: '注入未知工作流动作',
  workflow: actionWorkflow(action, relatedCorrelationKey),
  error_message: null,
  leaf_category: null,
  created_at: '2026-07-22T00:00:00',
  updated_at: '2026-07-22T00:00:00',
});


const installPageApiFixtures = async (
  page: Page,
  action: string,
  mutationRequests: string[],
  options: {
    expectedApiAction?: WorkflowManifestDefinition;
    relatedCorrelationKey?: string | null;
  } = {},
) => {
  const product = productFixture(action, options.relatedCorrelationKey);
  const expectedApiPath = options.expectedApiAction?.route
    ? replaceManifestParameters(options.expectedApiAction.route)
    : null;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (!pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      mutationRequests.push(`${request.method()} ${pathname}`);
      if (
        options.expectedApiAction
        && request.method() === options.expectedApiAction.method
        && pathname === expectedApiPath
      ) {
        await route.fulfill({ contentType: 'application/json', body: JSON.stringify(product) });
        return;
      }
      await route.abort();
      return;
    }
    if (pathname === '/api/product-data-sources') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{
            id: 1,
            name: 'R1 Amazon Test Source',
            platform: 'giga',
            sales_channel: 'amazon',
            site: 'US',
            country: 'US',
            fulfillment_mode: 'dropship',
            enabled: 1,
          }],
          total: 1,
          page: 1,
          page_size: 100,
        }),
      });
      return;
    }
    if (pathname === '/api/products/overview') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          total_products: 1,
          needs_initialization: 0,
          auto_select_images: 0,
          select_images: 0,
          competitor_searching: 0,
          select_competitor: 0,
          capture_detail: 1,
          ready_to_generate: 0,
          running: 0,
          export_ready: 0,
          failed: 1,
          running_tasks: 0,
          manual_review_tasks: 0,
          failed_tasks: 1,
          confirmable_tasks: 0,
          asin_not_synced: 1,
          asin_attention: 0,
          aplus_failed: 0,
          listing_high_risk: 0,
        }),
      });
      return;
    }
    if (pathname === '/api/products/42') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          ...product,
          data: null,
          images: null,
          aplus: null,
          zip_files: [],
          generated_files: [],
          video_folder: null,
          aplus_folder: null,
          amazon_export_preview: null,
        }),
      });
      return;
    }
    if (pathname === '/api/products') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ items: [product], total: 1, page: 1, page_size: 20 }),
      });
      return;
    }
    if (pathname === '/api/giga/batches' || pathname === '/api/task-runs') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0, page: 1, page_size: 20 }),
      });
      return;
    }
    await route.fulfill({ contentType: 'application/json', body: '{}' });
  });
  return product;
};


for (const surface of ['product-list', 'product-detail'] as const) {
  test(`${surface} renders an explicit unknown-action fallback without network`, async ({ page }) => {
    const requests: string[] = [];
    page.on('request', (request) => requests.push(request.url()));
    const action = `unknown_${surface.replace('-', '_')}_action`;
    const markup = renderToStaticMarkup(
      React.createElement(ProductWorkflowUnknownAction, {
        action,
        surface,
        size: surface === 'product-list' ? 'small' : 'middle',
      }),
    );

    await page.setContent(`<main>${markup}</main>`);

    const fallback = page.locator(`[data-workflow-action-fallback="${surface}"]`);
    await expect(fallback).toHaveAttribute('data-workflow-action', action);
    await expect(fallback).toHaveAttribute('title', `未知工作流动作：${action}`);
    await expect(fallback.getByRole('button', { name: '当前版本无法执行' })).toBeDisabled();
    expect(requests).toEqual([]);
  });
}


for (const testCase of [
  { surface: 'product-list' as const, action: 'retry_auto_image_selection', path: '/products' },
  { surface: 'product-detail' as const, action: 'retry_competitor_visual_match', path: '/products/42' },
]) {
  test(`actual ${testCase.surface} dispatches its known API action to the manifest endpoint once`, async ({ page }) => {
    const mutationRequests: string[] = [];
    const definition = manifestAction(testCase.action);
    expect(definition.kind).toBe('api');
    expect(definition.method).toBeTruthy();
    expect(definition.route).toBeTruthy();
    if (testCase.surface === 'product-list') {
      await page.addInitScript(() => window.localStorage.setItem('fbm.productList.dataSourceId', '1'));
    }
    await installPageApiFixtures(page, testCase.action, mutationRequests, { expectedApiAction: definition });

    await page.goto(testCase.path);
    await page.getByRole('button', { name: definition.default_label }).click();

    await expect.poll(() => mutationRequests).toEqual([
      `${definition.method} ${replaceManifestParameters(definition.route!)}`,
    ]);
  });
}


for (const testCase of [
  { surface: 'product-list' as const, action: 'open_export_center', path: '/products', relatedCorrelationKey: null },
  {
    surface: 'product-detail' as const,
    action: 'open_task_center',
    path: '/products/42',
    relatedCorrelationKey: 'product:42:competitor_candidate_capture',
  },
]) {
  test(`actual ${testCase.surface} navigates its known action to the manifest target`, async ({ page }) => {
    const mutationRequests: string[] = [];
    const definition = manifestAction(testCase.action);
    expect(definition.kind).toBe('navigate');
    expect(definition.target).toBeTruthy();
    if (testCase.surface === 'product-list') {
      await page.addInitScript(() => window.localStorage.setItem('fbm.productList.dataSourceId', '1'));
    }
    await installPageApiFixtures(page, testCase.action, mutationRequests, {
      relatedCorrelationKey: testCase.relatedCorrelationKey,
    });
    const target = replaceManifestParameters(definition.target!, {
      relatedCorrelationKey: testCase.relatedCorrelationKey,
    });

    await page.goto(testCase.path);
    const actionButton = testCase.surface === 'product-list'
      ? page.getByRole('table').getByRole('button', { name: definition.default_label })
      : page.getByRole('button', { name: definition.default_label });
    await actionButton.click();
    await page.waitForURL((url) => `${url.pathname}${url.search}` === target);

    expect(mutationRequests).toEqual([]);
  });
}


test('actual ProductList surface disables an injected unknown action with zero mutations', async ({ page }) => {
  const mutationRequests: string[] = [];
  const pageErrors: string[] = [];
  const browserErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') browserErrors.push(message.text()); });
  page.on('requestfailed', (request) => browserErrors.push(`${request.url()}: ${request.failure()?.errorText}`));
  const action = 'unknown_product_list_page_action';
  await page.addInitScript(() => window.localStorage.setItem('fbm.productList.dataSourceId', '1'));
  await installPageApiFixtures(page, action, mutationRequests);

  await page.goto('/products');

  const fallback = page.locator('[data-workflow-action-fallback="product-list"]');
  if (await fallback.count() === 0) {
    await page.waitForTimeout(500);
  }
  if (await fallback.count() === 0) {
    throw new Error(`ProductList fallback missing; url=${page.url()} pageErrors=${JSON.stringify(pageErrors)} browserErrors=${JSON.stringify(browserErrors)} html=${await page.content()}`);
  }
  await expect(fallback).toHaveAttribute('data-workflow-action', action);
  await expect(fallback).toHaveAttribute('title', `未知工作流动作：${action}`);
  const button = fallback.getByRole('button', { name: '当前版本无法执行' });
  await expect(button).toBeDisabled();
  await button.evaluate((element: HTMLButtonElement) => element.click());
  await page.waitForTimeout(100);
  expect(mutationRequests).toEqual([]);
});


test('actual ProductDetail surface disables an injected unknown action with zero mutations', async ({ page }) => {
  const mutationRequests: string[] = [];
  const pageErrors: string[] = [];
  const browserErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') browserErrors.push(message.text()); });
  page.on('requestfailed', (request) => browserErrors.push(`${request.url()}: ${request.failure()?.errorText}`));
  const action = 'unknown_product_detail_page_action';
  await installPageApiFixtures(page, action, mutationRequests);

  await page.goto('/products/42');

  const fallback = page.locator('[data-workflow-action-fallback="product-detail"]');
  if (await fallback.count() === 0) {
    await page.waitForTimeout(500);
  }
  if (await fallback.count() === 0) {
    throw new Error(`ProductDetail fallback missing; url=${page.url()} pageErrors=${JSON.stringify(pageErrors)} browserErrors=${JSON.stringify(browserErrors)} html=${await page.content()}`);
  }
  await expect(fallback).toHaveAttribute('data-workflow-action', action);
  await expect(fallback).toHaveAttribute('title', `未知工作流动作：${action}`);
  const button = fallback.getByRole('button', { name: '当前版本无法执行' });
  await expect(button).toBeDisabled();
  await button.evaluate((element: HTMLButtonElement) => element.click());
  await page.waitForTimeout(100);
  expect(mutationRequests).toEqual([]);
});
