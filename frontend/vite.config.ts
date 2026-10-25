import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './tests/setup.ts',
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**'],
    clearMocks: true,
    restoreMocks: true
  },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/session': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/cases': 'http://127.0.0.1:8000',
      '/reviewer': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/ready': 'http://127.0.0.1:8000',
    },
  }
});
