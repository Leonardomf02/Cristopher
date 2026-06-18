// Auth single-user + ligação ao backend.
//
// Em produção (Cloudflare Pages) o backend vive noutra origem (VITE_API_URL).
// Em vez de tocar nas ~28 chamadas do api.ts, intercetamos o fetch global:
//  - reescreve pedidos /api/* para o backend absoluto
//  - injeta o Bearer token
//  - em 401, limpa o token e avisa a app para mostrar o login

const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '');
const TOKEN_KEY = 'cristopher_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

let installed = false;

export function installFetchInterceptor() {
  if (installed) return;
  installed = true;

  const orig = window.fetch.bind(window);

  window.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    // Só mexemos em chamadas à nossa API (paths relativos a /api).
    if (typeof input !== 'string' || !input.startsWith('/api')) {
      return orig(input as any, init);
    }

    const url = API_BASE ? API_BASE + input : input;
    const headers = new Headers(init.headers || {});
    const token = getToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);

    const res = await orig(url, { ...init, headers });
    if (res.status === 401) {
      clearToken();
      window.dispatchEvent(new Event('cristopher:unauthorized'));
    }
    return res;
  }) as typeof window.fetch;
}
