import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite dev server fica exposto em 0.0.0.0 para o Tailscale alcançar.
// O proxy /api e /uploads continua a apontar para o backend local (localhost:8000)
// no próprio Mac, portanto o iPhone só fala com o frontend e este encaminha.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // Aceita qualquer hostname *.ts.net (Tailscale) e .local (Bonjour)
    allowedHosts: ['.ts.net', '.local', 'localhost'],
    proxy: {
      '/api': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
    },
  },
})
