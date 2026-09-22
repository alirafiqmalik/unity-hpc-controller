import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

/**
 * The dashboard build.
 *
 * `outDir` is `dist/`, which `controller/http.py::_static` serves. The dev
 * server proxies `/api` to the running controller, so `npm run dev` drives the
 * real API instead of a mock.
 */
export default defineConfig({
  plugins: [
    react({
      jsxImportSource: '@emotion/react',
      babel: { plugins: ['@emotion/babel-plugin'] },
    }),
  ],
  server: {
    port: 8301,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8300',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        // Recharts and React change far less often than the dashboard does.
        // Three chunks keep a reload after a UI edit small.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom', 'recoil'],
          charts: ['recharts'],
        },
      },
    },
  },
});
