import { defineConfig, devices } from '@playwright/test';
// Requires the backend on :8000 and Vite on :5173 (see README). Live Kartverket/NVE/MET access needed.
export default defineConfig({
  testDir: 'e2e', timeout: 120_000, retries: 0, reporter: 'list', workers: 1, // projects share one backend
  use: { baseURL: 'http://localhost:5173', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 900 } } },
    { name: 'iphone', use: { ...devices['iPhone 14'], browserName: 'chromium', defaultBrowserType: 'chromium' } }, // WebKit build rejects Page.overrideSetting on this macOS
  ],
});
