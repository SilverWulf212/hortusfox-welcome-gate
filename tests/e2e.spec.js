const { test, expect } = require('@playwright/test');

const ENTERED = 'garden_entered';

test.describe('welcome gate — first visit', () => {
  test.use({ storageState: undefined });

  test('splash renders with her garden', async ({ page }) => {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('/');

    await expect(page).toHaveTitle(/The Garden/);
    await expect(page.locator('h1')).toContainText('the living garden');
    // numbers are rebuilt nightly by deploy/bake.py, so assert shape, not values
    expect(await page.locator('.specimen').count()).toBeGreaterThan(0);
    await expect(page.locator('#st-plants')).toHaveText(/^[1-9]\d* plants$/);
    await expect(page.locator('#st-beds')).toHaveText(/^[1-9]\d* beds/);
    await expect(page.locator('#st-tasks')).toHaveText(/^\d+ open tasks$/);

    // dock + CTA point into the real app
    await expect(page.locator('.dock a[href="/"]:not(.dock-mark)')).toBeVisible();
    await expect(page.locator('.dock a[href="/tasks"]')).toBeVisible();
    await expect(page.locator('.dock a[href="/calendar"]')).toBeVisible();
    await expect(page.locator('#cta')).toHaveAttribute('href', '/auth?redirect=%2F');

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

  test('CTA fades out and hands off to the app', async ({ page, context }) => {
    await page.goto('/');
    await page.click('#cta');
    await page.waitForURL('**/auth**', { timeout: 8000 });
    const flag = await page.evaluate(([k]) => localStorage.getItem(k), [ENTERED]);
    expect(flag).toBe('1');
    const cookie = (await context.cookies()).find(c => c.name === ENTERED);
    expect(cookie, 'server-readable cookie set').toBeTruthy();
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

  test('every link on the page resolves — no 404s, ever', async ({ page }) => {
    await page.goto('/');
    const hrefs = await page.locator('a[href]').evaluateAll(
      els => [...new Set(els.map(el => el.getAttribute('href')))]
        .filter(h => !h.startsWith('#') && !h.startsWith('mailto:')));
    expect(hrefs.length).toBeGreaterThanOrEqual(4); // /, /tasks, /calendar, /auth — specimens dedupe to /
    for (const href of hrefs) {
      // assets are gate-served (200); app routes auth-gate logged out (302); neither may 4xx
      const res = await page.request.get(href, { maxRedirects: 0 });
      expect(res.status(), `${href} must not error`).toBeLessThan(400);
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
  test('cookie hands / straight to the app — never a splash, never a dead URL', async ({ page, context }) => {
    await context.addCookies([{ name: 'garden_entered', value: '1', url: process.env.E2E_BASE || 'https://plants.silverwulf.org' }]);
    await page.goto('/');
    // Gate proxies / to the app; logged out, the app bounces to /auth.
    // If we're still on / with splash content, the cookie was ignored.
    await page.waitForURL('**/auth**', { timeout: 8000 });
    // reaching /auth at all proves the gate proxied / to the app — a splash
    // never navigates. (The auth page has its own <h1>, so count it not.)
    expect(new URL(page.url()).pathname, 'must have left the splash').toBe('/auth');
  });

  test('legacy hyphen cookie (pre-rename) still gets the app at /', async ({ page, context }) => {
    await context.addCookies([{ name: 'garden-entered', value: '1', url: process.env.E2E_BASE || 'https://plants.silverwulf.org' }]);
    await page.goto('/');
    await page.waitForURL('**/auth**', { timeout: 8000 });
    expect(new URL(page.url()).pathname, 'must have left the splash').toBe('/auth');
  });

  test('legacy localStorage flag self-heals: sets cookie and enters', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('garden-entered', '1'));
    await page.goto('/');
    await page.waitForURL('**/auth**', { timeout: 8000 });
    expect(new URL(page.url()).pathname, 'must have left the splash').toBe('/auth');
  });

  test('a logged-in visitor (PHPSESSID) gets the workspace at /, not the splash', async ({ page, context }) => {
    // Lance's 404-adjacent complaint: clicking Plants while logged into the
    // app must land in the app. The gate must treat ANY app session cookie
    // as "already inside" — even without our splash flag.
    await context.addCookies([{ name: 'PHPSESSID', value: 'e2e-fake-session', url: process.env.E2E_BASE || 'https://plants.silverwulf.org' }]);
    await page.goto('/');
    await page.waitForURL('**/auth**', { timeout: 8000 }); // fake session → app rejects → /auth
    expect(new URL(page.url()).pathname, 'must have left the splash').toBe('/auth');
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

// garden.silverwulf.org: the same page fronts The Garden dashboard for
// signed-out visitors (Traefik router garden-gate). Absolute URLs, so this
// block runs whatever E2E_BASE is.
const GARDEN = process.env.E2E_GARDEN || 'https://garden.silverwulf.org';

test.describe('garden dashboard front page', () => {
  test('signed out: / is the welcome page, every enter link goes to /login', async ({ page, context }) => {
    await page.goto(GARDEN + '/');
    expect(new URL(page.url()).pathname).toBe('/');
    await expect(page.locator('h1')).toContainText('the living garden');
    await expect(page.locator('#cta')).toHaveAttribute('href', '/login');
    await expect(page.locator('#cta')).toContainText('Sign in');
    const hrefs = await page.locator('[data-enter]').evaluateAll(as => [...new Set(as.map(a => a.getAttribute('href')))]);
    expect(hrefs).toEqual(['/login']);
    await page.locator('#cta').click();
    await page.waitForURL('**/login', { timeout: 8000 });
    // the HortusFox hand-off cookie must never be set on this host
    expect((await context.cookies(GARDEN)).find(c => c.name === ENTERED)).toBeFalsy();
  });

  test('a garden_entered cookie never shows HortusFox here', async ({ page, context }) => {
    await context.addCookies([{ name: ENTERED, value: '1', url: GARDEN }]);
    await page.goto(GARDEN + '/');
    await expect(page.locator('#cta')).toHaveAttribute('href', '/login');
  });

  test('with a session cookie, / goes to the dashboard (fake session -> its /login)', async ({ page, context }) => {
    await context.addCookies([{ name: 'garden_session', value: 'e2e-fake', url: GARDEN }]);
    await page.goto(GARDEN + '/');
    await page.waitForURL('**/login', { timeout: 8000 });
    await expect(page.locator('h1')).not.toContainText('the living garden');
  });
});
