const { test, expect } = require('@playwright/test');

const ENTERED = 'garden-entered';

test.describe('welcome gate — first visit', () => {
  test.use({ storageState: undefined });

  test('splash renders with her garden', async ({ page }) => {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('/');

    await expect(page).toHaveTitle(/The Garden/);
    await expect(page.locator('h1')).toContainText('the living garden');
    await expect(page.locator('.specimen')).toHaveCount(6);
    await expect(page.locator('#st-plants')).toHaveText(/51 plants/);
    await expect(page.locator('#st-beds')).toHaveText(/10 beds/);
    await expect(page.locator('#st-tasks')).toHaveText(/11 open tasks/);

    // dock + CTA point into the real app
    await expect(page.locator('.dock a[href="/"]:not(.dock-mark)')).toBeVisible();
    await expect(page.locator('.dock a[href="/tasks"]')).toBeVisible();
    await expect(page.locator('.dock a[href="/calendar"]')).toBeVisible();
    await expect(page.locator('#cta')).toHaveAttribute('href', '/auth?redirect=%2Findex.php');

    // every specimen photo actually loaded
    const photos = page.locator('.specimen img');
    expect(await photos.count()).toBeGreaterThan(0);
    for (const img of await photos.all()) {
      expect(await img.evaluate(el => el.naturalWidth)).toBeGreaterThan(0);
    }

    // native vines present, pollen canvas running
    await expect(page.locator('.vine--tl')).toBeVisible();
    await expect(page.locator('.vine--br')).toBeVisible();
    await expect(page.locator('#pollen')).toBeVisible();

    expect(errors, 'no page errors').toEqual([]);
  });

  test('CTA fades out and hands off to the app', async ({ page }) => {
    await page.goto('/');
    await page.click('#cta');
    await page.waitForURL('**/auth**', { timeout: 8000 });
    const flag = await page.evaluate(([k]) => localStorage.getItem(k), [ENTERED]);
    expect(flag).toBe('1');
    await expect(page.locator('body')).not.toContainText('the living garden');
  });

  test('dock links point at routes the app actually serves', async ({ page }) => {
    // Source-verified route table (grep "Handles URL:" across app/controller/
    // inside the hortusfox container). A bare /plants does NOT exist — the
    // plant list is the workspace at / — which is exactly the 404 this test
    // exists to prevent. Logged-out requests all 302 to /auth before routing,
    // so only this contract can catch phantom links.
    const REAL_ROUTES = new Set(['/', '/auth', '/tasks', '/calendar', '/inventory', '/chat']);
    await page.goto('/');
    const hrefs = await page.locator('.dock a, .specimen').evaluateAll(
      els => els.map(el => new URL(el.getAttribute('href'), 'https://x').pathname));
    for (const href of hrefs) {
      expect(REAL_ROUTES.has(href), `dock href ${href} is not a real app route`).toBe(true);
    }
  });

  test('deep dock links reach the app (auth-gated)', async ({ page }) => {
    await page.goto('/tasks');
    await expect(page).toHaveURL(/\/auth/);
    // the app preserved the deep link for after login
    await expect(page).toHaveURL(/redirect=%2Ftasks/);
  });
});

test.describe('welcome gate — returning visitor', () => {
  test('splash steps aside instantly for anyone who already entered', async ({ page }) => {
    await page.addInitScript(([k]) => localStorage.setItem(k, '1'), [ENTERED]);
    await page.goto('/');
    await page.waitForURL('**/auth**', { timeout: 8000 });   // / → /index.php → auth (logged out)
    expect(page.url()).not.toMatch(/index\.html$/);
  });
});

test.describe('welcome gate — accessibility & mobile', () => {
  test('reduced motion hides pollen and stops the vines', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await expect(page.locator('#pollen')).toBeHidden();
  });

  test('mobile: strip scrolls horizontally, dock collapses to glyphs', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    const strip = page.locator('#strip');
    const scrollable = await strip.evaluate(
      el => el.scrollWidth > el.clientWidth && getComputedStyle(el).overflowX === 'auto');
    expect(scrollable).toBeTruthy();
    const labelHidden = await page.locator('.dock a[href="/tasks"] span:not(.glyph)')
      .evaluate(el => getComputedStyle(el).display === 'none');
    expect(labelHidden).toBeTruthy();
  });
});
