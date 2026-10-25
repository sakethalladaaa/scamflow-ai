import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { tmpdir } from 'node:os'

const e2eDatabasePath = path.join(tmpdir(), `scamflow-ai-e2e-${process.pid}.sqlite3`)

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `SCAMFLOW_ENVIRONMENT=test SCAMFLOW_DATABASE_PATH=${JSON.stringify(e2eDatabasePath)} SCAMFLOW_TRUSTED_ORIGIN=http://127.0.0.1:5173 .venv/bin/uvicorn backend.scamflow.app:app --host 127.0.0.1 --port 8000`,
      cwd: '..',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: false,
    },
    { command: 'npm run dev', cwd: '.', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
  ],
})
