// Categorias do Screen Time partilhadas entre a página do Screen Time e o calendário.

// Ordem de empilhamento (de baixo para cima / da esquerda para a direita).
export const CATEGORY_STACK_ORDER = [
  'Social',
  'Productivity & Finance',
  'Creativity',
  'Travel',
  'Games',
  'Utilities',
  'Entertainment',
  'Information & Reading',
  'Other',
];

export const CATEGORY_FILL: Record<string, string> = {
  'Social': '#60a5fa',
  'Productivity & Finance': '#a78bfa',
  'Creativity': '#fb923c',
  'Travel': '#38bdf8',
  'Games': '#f472b6',
  'Utilities': '#a1a1aa',
  'Entertainment': '#f87171',
  'Information & Reading': '#34d399',
  'Other': '#52525b',
};

export function categoryFill(category: string): string {
  return CATEGORY_FILL[category] || '#52525b';
}

// 3720 → "1h02"; 900 → "15m"
export function fmtHm(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h${String(rem).padStart(2, '0')}` : `${h}h`;
}
