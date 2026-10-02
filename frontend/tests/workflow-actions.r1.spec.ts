import React from 'react';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

import { ProductWorkflowUnknownAction } from '../src/workflow/ProductWorkflowUnknownAction';

for (const outcome of ['success', 'failed', 'already-blacklisted'] as const) {
  test(`blacklist detail permanent confirmation and error retention: ${outcome}`, async ({ page }) => {
    page.on('pageerror', (error) => { throw error; });
    let mutations = 0;
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (!path.startsWith('/api/')) return route.continue();
      const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      if (path === '/api/products/42/blacklist') {
        mutations++;
        return outcome === 'failed' ? reply({ detail: '黑名单提交失败测试' }, 400)
          : reply({ status: 'blacklisted', product_id: 42, blacklisted_at: '2026-10-02T13:00:00' });
      }
      if (path === '/api/products/42') return reply({ ...productFixture('confirm_product'), id: 42,
        blacklisted_at: outcome === 'already-blacklisted' ? '2026-10-02T13:00:00' : null,
        data: null, images: null, aplus: null, generated_files: [],
        video_folder: null, aplus_folder: null, amazon_export_preview: null });
      if (path === '/api/products') return reply({ items: [], total: 0 });
      return reply({ items: [], data: null, loaded: true, state: 'absent', has_content: false });
    });
    await page.goto('/products/42');
    await expect(page.getByRole('heading', { name: '商品 #42' })).toBeVisible();
    if (outcome === 'already-blacklisted') {
      await expect(page.getByText('永久黑名单 · 禁止删除')).toBeVisible();
      await expect(page.getByRole('button', { name: /删除$/ })).toBeDisabled();
      await expect(page.getByRole('button', { name: '加入黑名单', exact: true })).toHaveCount(0);
      expect(mutations).toBe(0);
      return;
    }
    const button = page.getByRole('button', { name: /加入黑名单$/ });
    await button.click();
    await expect(page.getByText('加入后无法移出、无法删除商品，商品列表不再显示。')).toBeVisible();
    expect(mutations).toBe(0);
    await page.getByRole('button', { name: '永久加入', exact: true }).click();
    if (outcome === 'failed') {
      await expect(page.getByText('黑名单提交失败测试')).toBeVisible();
      await expect(button).toBeEnabled();
      await expect(page).toHaveURL(/\/products\/42$/);
    } else await expect(page).toHaveURL(/\/products$/);
    expect(mutations).toBe(1);
  });
}


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

for (const scenario of ['next', 'busy-next', 'disabled', 'empty', 'query-failed', 'confirm-failed', 'manual-next', 'manual-empty', 'manual-query-failed'] as const) {
  test(`detail auto next confirmation: ${scenario}`, async ({ page }) => {
    const manual = scenario.startsWith('manual-');
    const mutations: string[] = [];
    let queueReads = 0;
    let confirmed = false;
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (!url.pathname.startsWith('/api/')) return route.continue();
      const reply = (body: unknown, status = 200) => route.fulfill({
        status, contentType: 'application/json', body: JSON.stringify(body),
      });
      if (request.method() === 'POST') {
        mutations.push(url.pathname);
        if (scenario === 'confirm-failed') return reply({ detail: '确认失败测试' }, 400);
        confirmed = true;
        return reply(productFixture('confirm_product'));
      }
      if (url.pathname === '/api/products') {
        queueReads++;
        expect(confirmed).toBe(!manual);
        expect(url.searchParams.get('work_status')).toBe('confirm_images_aplus');
        if (scenario.endsWith('query-failed')) return reply({ detail: 'test unavailable' }, 500);
        if (scenario === 'busy-next') {
          return reply({ items: url.searchParams.get('page') === '1'
            ? [{ id: 42 }, { id: 44, aplus_status: 'regen_image_running' }]
            : [{ id: 43, aplus_status: 'done' }], total: 3 });
        }
        return reply({ items: scenario.endsWith('empty') ? [] : [{ id: 42 }, { id: 43 }], total: 2 });
      }
      if (/^\/api\/products\/\d+$/.test(url.pathname)) {
        const id = Number(url.pathname.split('/').pop());
        const product = productFixture('confirm_product');
        return reply({ ...product, id, data: null, images: null, aplus: null,
          generated_files: [], video_folder: null, aplus_folder: null, amazon_export_preview: null,
          workflow: { ...product.workflow, stage: 'confirm_images_aplus', stage_status: 'pending',
            work_status: 'confirm_images_aplus', primary_action_label: '确认图片与 A+' } });
      }
      return reply({ items: [], data: null, loaded: true, state: 'absent', has_content: false });
    });
    await page.goto('/products/42');
    const toggle = page.getByRole('switch', { name: '确认后自动打开下一个待确认商品' });
    await expect(toggle).not.toBeChecked();
    if (!manual && scenario !== 'disabled') await toggle.click();
    await page.getByRole('button', manual
      ? { name: '下一个待确认', exact: true }
      : { name: /确认图片与 A\+$/ }).click();
    if (scenario === 'next' || scenario === 'busy-next' || scenario === 'manual-next') {
      await expect(page).toHaveURL(/\/products\/43$/);
      await expect(page.getByRole('heading', { name: '商品 #43' })).toBeVisible();
      if (manual) await expect(toggle).not.toBeChecked();
      else await expect(toggle).toBeChecked();
    } else {
      await expect(page.getByRole('button', { name: /确认图片与 A\+$/ })).toBeEnabled();
      await expect(page).toHaveURL(/\/products\/42$/);
      if (scenario.endsWith('empty') || scenario.endsWith('query-failed')) {
        await expect(page.getByRole('status')).toHaveText(scenario.endsWith('empty')
          ? '没有下一个待确认图片与 A+ 的商品了'
          : manual ? '获取下一个待确认商品失败，请稍后重试'
          : '当前商品已确认，获取下一个待确认商品失败，请稍后重试');
      }
    }
    await expect.poll(() => mutations.length).toBe(manual ? 0 : 1);
    await expect.poll(() => queueReads).toBe(['disabled', 'confirm-failed'].includes(scenario) ? 0 : scenario === 'busy-next' ? 2 : 1);
    expect(mutations).toEqual(manual ? [] : ['/api/products/42/confirm']);
  });
}
