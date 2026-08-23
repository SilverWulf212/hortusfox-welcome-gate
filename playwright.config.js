const { defineConfig, devices } = require('@playwright/test');

// E2E for the welcome gate. Runs against the live hostname; when launched
// via deploy/e2e.sh on the Docker host, /etc/hosts pins the name to the
// local Traefik edge so tests exercise router + gate + app without Cloudflare.
module.exports = defineConfig({
  testDir: './tests',
  timeout: 30000,
  retries: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE || 'https://plants.silverwulf.org',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile',  use: { ...devices['Pixel 7'] } },
  ],
});
