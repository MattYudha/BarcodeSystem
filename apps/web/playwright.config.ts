import { defineConfig, devices } from "@playwright/test";

/**
 * E2E web: build produksi Next (`pnpm build`) + API asli (stack Docker, lihat README).
 * Variabel:
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD  admin yang dibuat via `bhv create-admin`
 *   API_ORIGIN                            default http://localhost:8000
 *   PLAYWRIGHT_BASE_URL                   pakai server yang sudah jalan (lewati webServer)
 * Port 3000 dipakai karena API menerima Origin http://localhost:3000 (cek CSRF).
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // data bersama satu DB; tes tetap memakai nama unik
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL,
    locale: "id-ID",
    timezoneId: "Asia/Jakarta",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile.spec.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "pnpm start --port 3000",
        url: `${baseURL}/login`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: { API_ORIGIN: process.env.API_ORIGIN ?? "http://localhost:8000" },
      },
});
