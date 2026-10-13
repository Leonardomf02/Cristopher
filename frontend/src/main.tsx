import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import './theme-light.css'
import { installFetchInterceptor } from './auth'
import { initTheme } from './theme'
import { iniciarOutbox } from './outbox'

installFetchInterceptor()
initTheme()
iniciarOutbox()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)

// Instalável e a abrir sem ligação: o service worker guarda a app e a última
// resposta de cada pedido, para o telemóvel não ficar num ecrã em branco quando
// o Mac está desligado.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // Em dev o service worker não guarda código (só o shell e os dados), para não
    // servir versões velhas enquanto se está a mexer na app.
    const url = import.meta.env.PROD ? '/sw.js' : '/sw.js?dev=1';
    navigator.serviceWorker.register(url).catch(() => { /* sem service worker, a app funciona na mesma */ });
  });
}
