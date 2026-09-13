import { test, expect, type Page } from '@playwright/test';

const errors: string[] = [];
test.beforeEach(({ page }) => { errors.length = 0; page.on('pageerror', e => errors.push(e.message)); page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); }); });

// The mobile sheet handle cycles half -> full -> peek -> half.
const peek = async (page: Page, isMobile: boolean) => { if (isMobile) { await page.getByRole('button', { name: 'Resize panel' }).click(); await page.waitForTimeout(400); await page.getByRole('button', { name: 'Resize panel' }).click(); await page.waitForTimeout(400); } };
const half = async (page: Page, isMobile: boolean) => { if (isMobile) { await page.getByRole('button', { name: 'Resize panel' }).click(); await page.waitForTimeout(400); } };

async function loadArea(page: Page) {
  await page.getByRole('button', { name: 'Explore this area' }).click();
  await expect(page.getByText(/m grid · .*% covered/)).toBeVisible({ timeout: 90_000 });
}

test('explore, filter, inspect, draw and read forecasts', async ({ page, isMobile }, info) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Rando' })).toBeVisible();

  // Summit tours load from data/, then candidate search over the current view.
  await expect(page.locator('.cand').first()).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: 'Find candidates' }).click();
  await page.getByRole('button', { name: 'Search this map view' }).click();
  await expect(page.locator('.cand').first()).toBeVisible({ timeout: 110_000 });
  await page.locator('.cand').first().click();
  await expect(page.locator('.cand.on')).toHaveCount(1);
  await page.screenshot({ path: info.outputPath('candidates.png') });

  await page.getByRole('button', { name: 'Terrain preference' }).click();
  await loadArea(page);
  await expect(page.getByText(/20→40 km changed horizons/)).toBeVisible();
  await page.screenshot({ path: info.outputPath('loaded.png') });

  // Filter changes re-request the overlay quickly once terrain is loaded.
  const overlay = page.waitForResponse(r => r.url().includes('/overlay.png') && r.url().includes('bearing=0'));
  const t0 = Date.now();
  await page.getByRole('button', { name: 'North ±45°' }).click();
  expect((await overlay).ok()).toBe(true);
  expect(Date.now() - t0).toBeLessThan(1500);

  // Inspect the map centre.
  const map = page.locator('.map-canvas');
  const box = (await map.boundingBox())!;
  await peek(page, isMobile);
  await page.mouse.click(box.x + box.width / 2, box.y + (isMobile ? 200 : box.height / 2));
  await half(page, isMobile);
  await page.getByRole('button', { name: 'Inspect a point' }).click();
  await expect(page.getByText(/^Elevation$/)).toBeVisible();
  await expect(page.getByText(/\d+ m$/).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('.timeline').first()).toBeVisible();

  // Draw a three-point ascent.
  await page.getByRole('button', { name: 'Ascent route' }).click();
  await page.getByRole('button', { name: 'Draw' }).click();
  await peek(page, isMobile);
  const y = isMobile ? 200 : box.y + box.height / 2;
  for (const dx of [-120, 0, 120]) await page.mouse.click(box.x + box.width / 2 + dx, y + dx / 3);
  await half(page, isMobile);
  await expect(page.getByText(/^Distance$/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('Moving time', { exact: true })).toBeVisible();
  await expect(page.locator('svg.profile')).toBeVisible();
  await page.screenshot({ path: info.outputPath('route.png') });

  // Forecast section shows either a warning or an explicit unavailable/out-of-range note.
  await page.getByRole('button', { name: 'Avalanche & weather' }).click();
  await expect(page.locator('.forecast, .caution.range, .caution.missing, .caution.unavailable, .caution.stale').first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('columnheader', { name: 'Cloud' }).or(page.getByText(/No MET forecast/))).toBeVisible();
  await page.screenshot({ path: info.outputPath('forecast.png'), fullPage: !isMobile });

  // Save a plan locally and export GPX.
  await page.getByRole('button', { name: 'Plans & travel' }).click();
  await page.getByPlaceholder('Plan name').fill('E2E tour');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.locator('.plan-name', { hasText: 'E2E tour' })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Plans & travel' }).click();
  await expect(page.locator('.plan-name', { hasText: 'E2E tour' })).toBeVisible();
  expect(errors.filter(e => !/favicon|WebGL|net::ERR/.test(e))).toEqual([]);
});
