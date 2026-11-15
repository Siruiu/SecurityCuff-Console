import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: process.env.DEMO_URL || "http://127.0.0.1:18081",
    headless: true,
    screenshot: "only-on-failure",
  },
  reporter: "list",
});
