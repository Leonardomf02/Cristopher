// Tema da app: escuro (default) ou claro. O tema fica no <html data-theme="...">
// e a folha theme-light.css remapeia as cores quando está "light".

export type Theme = 'dark' | 'light';

const THEME_KEY = 'cristopherTheme';

export function getTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* ignora */ }
}

// Corre antes do render para não haver flash do tema errado.
export function initTheme() {
  applyTheme(getTheme());
}

// Cores escolhidas pelo utilizador (tipos de dia, eventos, listas) foram pensadas
// para fundo escuro. Em tema claro escurecem-se para o texto continuar legível.
export function inkColor(hex: string, factor = 0.62): string {
  if (getTheme() !== 'light') return hex;
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(c => Math.round(c * factor));
  return `#${ch.map(c => c.toString(16).padStart(2, '0')).join('')}`;
}
