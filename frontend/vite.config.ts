import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { createDevApiWriteGuard } from './dev-api-write-guard';

export default defineConfig(({ mode }) => {
  const viteEnv = loadEnv(mode, process.cwd(), 'VITE_');
  const backendPort = process.env.BACKEND_PORT || '8190';
  const frontendPort = Number(
    process.env.VITE_FRONTEND_PORT
    || process.env.FRONTEND_PORT
    || viteEnv.VITE_FRONTEND_PORT
    || 3190,
  );
  const backendUrl = process.env.VITE_BACKEND_URL
    || viteEnv.VITE_BACKEND_URL
    || `http://localhost:${backendPort}`;
  const devApiWriteToken = process.env.DEV_API_WRITE_TOKEN;

  return {
    plugins: [
      {
        name: 'fbm-dev-api-write-guard',
        enforce: 'pre',
        configureServer(server) {
          server.middlewares.use('/api', createDevApiWriteGuard(devApiWriteToken));
        },
      },
      react(),
    ],
    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
      port: frontendPort,
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
  };
});
