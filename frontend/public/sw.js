// Service worker do Cristopher.
//
// Objectivo: a app abrir no telemóvel mesmo quando o Mac (ou o Tailscale) não
// responde. O shell e os ficheiros do build ficam em cache; os dados vão sempre
// à rede primeiro e só caem na última resposta guardada quando não há ligação.
const VERSAO = 'cristopher-v6';
// Em desenvolvimento os ficheiros mudam a cada gravação: aí o service worker só
// trata da navegação e dos dados, nunca guarda código (senão servia versões
// velhas e dava a ideia de que a app tinha partido).
const DEV = new URL(self.location.href).searchParams.get('dev') === '1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];

// Os ficheiros do build têm nomes com hash, por isso são descobertos a partir do
// index.html em vez de estarem escritos aqui à mão.
async function ficheirosDoBuild() {
  try {
    const html = await fetch('/index.html', { cache: 'no-cache' }).then(r => r.text());
    return [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map(m => m[1]);
  } catch {
    return [];
  }
}

self.addEventListener('install', evento => {
  evento.waitUntil((async () => {
    const cache = await caches.open(VERSAO);
    await Promise.all(SHELL.map(u => cache.add(u).catch(() => {})));
    if (!DEV) {
      const assets = await ficheirosDoBuild();
      await Promise.all(assets.map(a => cache.add(a).catch(() => {})));
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', evento => {
  evento.waitUntil(
    caches.keys()
      .then(chaves => Promise.all(chaves.filter(k => k !== VERSAO).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', evento => {
  const pedido = evento.request;
  if (pedido.method !== 'GET') return;
  const url = new URL(pedido.url);
  if (url.origin !== self.location.origin) return;

  // Dados: rede primeiro, cache como rede de segurança.
  if (url.pathname.startsWith('/api/')) {
    evento.respondWith(
      fetch(pedido)
        .then(resposta => {
          const copia = resposta.clone();
          caches.open(VERSAO).then(c => c.put(pedido, copia));
          return resposta;
        })
        .catch(() => caches.match(pedido).then(r => r || new Response(
          JSON.stringify({ offline: true, detail: 'Sem ligação ao Cristopher' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        )))
    );
    return;
  }

  // Navegação: se não houver rede, abre o shell guardado.
  if (pedido.mode === 'navigate') {
    evento.respondWith(
      fetch(pedido)
        .then(r => {
          const copia = r.clone();
          caches.open(VERSAO).then(c => c.put('/index.html', copia));
          return r;
        })
        .catch(() => caches.match('/index.html').then(r => r || Response.error()))
    );
    return;
  }

  // Ficheiros. Em produção têm hash no nome, por isso vale a cache primeiro. Em
  // dev vai-se sempre ao servidor e a cache só serve para o caso de não haver
  // rede — assim nunca se vê código velho enquanto se está a mexer na app.
  evento.respondWith((async () => {
    const cache = await caches.open(VERSAO);
    const daCache = async () =>
      (await cache.match(pedido, { ignoreVary: true }))
      || (await cache.match(url.pathname + url.search, { ignoreVary: true }))
      || (await cache.match(url.pathname, { ignoreVary: true }));

    if (!DEV) {
      const guardado = await daCache();
      if (guardado) return guardado;
    }
    try {
      const resposta = await fetch(pedido);
      if (resposta.ok) cache.put(pedido, resposta.clone());
      return resposta;
    } catch (e) {
      return (await daCache()) || new Response('', { status: 504, statusText: 'sem ligação' });
    }
  })());
});


// ── Avisos ────────────────────────────────────────────────────────
// Chegam do backend mesmo com a app fechada, desde que esteja instalada no
// ecrã principal e servida por HTTPS.
self.addEventListener('push', evento => {
  let dados = { title: 'Cristopher', body: '', url: '/' };
  try { dados = { ...dados, ...evento.data.json() }; } catch { dados.body = evento.data?.text() || ''; }
  evento.waitUntil(self.registration.showNotification(dados.title, {
    body: dados.body,
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { url: dados.url || '/' },
    tag: dados.tag || 'cristopher',
  }));
});

self.addEventListener('notificationclick', evento => {
  evento.notification.close();
  const destino = evento.notification.data?.url || '/';
  evento.waitUntil((async () => {
    const janelas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const j of janelas) {
      if (j.url.includes(self.location.origin)) {
        await j.focus();
        return j.navigate(destino).catch(() => {});
      }
    }
    return self.clients.openWindow(destino);
  })());
});
