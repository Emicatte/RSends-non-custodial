/**
 * vitest.config.ts — Test runner configuration
 */

import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/__tests__/**/*.test.{ts,tsx}'],
    testTimeout: 10_000,
    css: false,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
      '@src': path.resolve(__dirname, './src'),
    },
  },
});
