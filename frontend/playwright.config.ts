import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: "rm -f .e2e.sqlite3 .e2e.sqlite3-shm .e2e.sqlite3-wal && SCAMFLOW_ENVIRONMENT=test SCAMFLOW_DATABASE_PATH=frontend/.e2e.sqlite3 SCAMFLOW_TRUSTED_ORIGIN=http://127.0.0.1:5173 .venv/bin/uvicorn backend.scamflow.app:app --host 127.0.0.1 --port 8000",
      cwd: '..',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: false,
    },
    { command: 'npm run dev', cwd: '.', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
  ],
})
