import { expect, test } from '@playwright/test';


const nonReadyMindsetStates = [
  { state: 'processing', message: '正在加载内容' },
  { state: 'absent', message: '暂无内容' },
  { state: 'failed', message: '内容加载失败' },
  { state: 'unresolved', message: '历史内容无法解析' },
] as const;


test('mindset tab is GET-only and polling keeps the loaded questions', async ({ page }) => {
  const browserErrors: string[] = [];
  const productRequests: Array<{ method: string; path: string }> = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('requestfailed', (request) => browserErrors.push(`request failed: ${request.method()} ${request.url()}`));
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/products/1')) {
      productRequests.push({ method: request.method(), path: `${url.pathname}${url.search}` });
    }
  });

  await page.goto('/products/1');
  await expect(page.getByRole('tab', { name: '用户心智' })).toBeVisible();
  await page.getByRole('tab', { name: /基本信息/ }).click();
  productRequests.length = 0;

  const mindsetResponse = page.waitForResponse((response) => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === '/api/products/1/sections/mindset'
  ));
  await page.getByRole('tab', { name: '用户心智' }).click();
  const response = await mindsetResponse;
  expect(response.status()).toBe(200);
  const mindset = await response.json();
  const expectedStatus = mindset.data?.quality?.requires_review
    ? '已生成，存在需要人工关注的未知项'
    : '用户心智梳理已完成';
  await expect(page.getByText(expectedStatus)).toBeVisible();
  await expect(page.getByText('核心策略')).toBeVisible();

  await page.waitForTimeout(3_500);
  await expect(page.getByText('核心策略')).toBeVisible();
  expect(productRequests.filter((request) => request.method !== 'GET')).toEqual([]);
  expect(productRequests.some((request) => request.path === '/api/products/1/sections/mindset')).toBe(true);
  expect(productRequests.some((request) => request.path.includes('/step/6'))).toBe(false);
  expect(browserErrors).toEqual([]);
});

for (const fixture of nonReadyMindsetStates) {
  test(`mindset renders ${fixture.state} section state`, async ({ page }) => {
    await page.route('**/api/products/1/sections/mindset', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          loaded: true,
          state: fixture.state,
          has_content: false,
          revision: 1,
          updated_at: null,
          data: null,
          error_code: fixture.state === 'failed' || fixture.state === 'unresolved'
            ? `fixture_${fixture.state}`
            : undefined,
        }),
      });
    });

    await page.goto('/products/1');
    await page.getByRole('tab', { name: '用户心智' }).click();
    await expect(page.getByText(fixture.message)).toBeVisible();
  });
}

test('A+ plan, script, and assets load independently', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/api/products/1/sections/aplus') requests.push(url.searchParams.get('part') || '');
  });

  await page.goto('/products/1');
  await page.getByRole('tab', { name: /基本信息/ }).click();
  requests.length = 0;
  await page.getByRole('tab', { name: /A\+内容/ }).click();
  await expect.poll(() => [...new Set(requests)].sort()).toEqual(['assets', 'plan', 'script']);
});

test('summary polling refreshes a loaded section when its revision changes', async ({ page }) => {
  let summaryRequests = 0;
  let mindsetRequests = 0;
  const browserErrors: string[] = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));

  await page.route('**/api/products/1**', async (route) => {
    const requestUrl = new URL(route.request().url());
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    if (requestUrl.pathname === '/api/products/1') {
      const response = await route.fetch();
      const body = await response.json();
      summaryRequests += 1;
      body.workflow = { ...body.workflow, stage_status: 'processing', work_status: 'running' };
      body.sections.mindset.revision = summaryRequests >= 2 ? 2 : 1;
      await route.fulfill({ response, json: body });
      return;
    }
    if (requestUrl.pathname === '/api/products/1/sections/mindset') {
      const response = await route.fetch();
      const body = await response.json();
      mindsetRequests += 1;
      body.revision = mindsetRequests >= 2 ? 2 : 1;
      await route.fulfill({ response, json: body });
      return;
    }
    await route.continue();
  });

  await page.goto('/products/1');
  await page.getByRole('tab', { name: '用户心智' }).click();
  await expect(page.getByText('核心策略')).toBeVisible();
  await expect.poll(() => mindsetRequests, { timeout: 8_000 }).toBeGreaterThanOrEqual(2);
  await expect(page.getByText('核心策略')).toBeVisible();
  expect(summaryRequests).toBeGreaterThanOrEqual(2);
  expect(browserErrors).toEqual([]);
});
