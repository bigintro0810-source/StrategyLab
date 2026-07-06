import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8736',
    },
  },
  test: {
    // Pure-logic unit tests only (conditionTreeUtils, rangeUtils) - no DOM
    // needed, so the default 'node' environment is fine and avoids an extra
    // jsdom dependency.
    include: ['src/**/*.test.ts'],
  },
})
