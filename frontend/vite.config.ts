import fs from 'node:fs'
import { defineConfig } from 'vite'
import { devtools } from '@tanstack/devtools-vite'

import { tanstackStart } from '@tanstack/react-start/plugin/vite'

import viteReact, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'

/**
 * Микрофон работает только в защищённом контексте: https или localhost.
 * Чтобы открыть Рудика с телефона или соседней машины, положите сертификат
 * в frontend/certs/ — он подхватится сам. Пути можно переопределить
 * переменными RUDIK_TLS_CERT и RUDIK_TLS_KEY, а чтобы вернуться на http,
 * достаточно убрать папку certs.
 */
function httpsOptions() {
  const cert = process.env.RUDIK_TLS_CERT ?? 'certs/dev.pem'
  const key = process.env.RUDIK_TLS_KEY ?? 'certs/dev-key.pem'
  if (!fs.existsSync(cert) || !fs.existsSync(key)) return undefined
  return { cert: fs.readFileSync(cert), key: fs.readFileSync(key) }
}

const config = defineConfig({
  resolve: { tsconfigPaths: true },
  server: {
    // Слушаем все интерфейсы, чтобы страница открывалась по адресу машины.
    host: true,
    https: httpsOptions(),
    // Бэкенд Рудика (FastAPI) вызывается сервером Vite, поэтому CORS не нужен
    // и сам бэкенд наружу выставлять не обязательно.
    proxy: {
      '/api': {
        target: process.env.RUDIK_API ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  plugins: [
    devtools(),
    tailwindcss(),
    tanstackStart(),
    viteReact(),
    babel({ presets: [reactCompilerPreset()] }),
  ],
})

export default config
