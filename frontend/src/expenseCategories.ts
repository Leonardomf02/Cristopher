import { useEffect, useState } from 'react';
import { expensesApi, CategoriaDeGasto } from './api';
import { EXPENSE_CATEGORIES } from './types';

// As categorias de origem mais as que ele cria. Lidas uma vez e partilhadas por
// todas as páginas: quem cria uma avisa as outras.
type Categoria = { value: string; label: string; emoji: string; custom?: boolean };

let extras: CategoriaDeGasto[] = [];
let pedido: Promise<void> | null = null;
const ouvintes = new Set<() => void>();

function avisa() { ouvintes.forEach(f => f()); }

export function carregaCategorias(forcar = false) {
  if (!pedido || forcar) {
    pedido = expensesApi.categories()
      .then(l => { extras = l; avisa(); })
      .catch(() => { pedido = null; });
  }
  return pedido;
}

export function todasCategorias(): Categoria[] {
  // "Outro" fica sempre no fim, depois das dele.
  const origem = EXPENSE_CATEGORIES.filter(c => c.value !== 'other');
  const outro = EXPENSE_CATEGORIES.filter(c => c.value === 'other');
  return [...origem, ...extras.map(c => ({ ...c, custom: true })), ...outro];
}

export function infoCategoria(v: string): Categoria {
  return todasCategorias().find(c => c.value === v) || { value: v, label: v, emoji: '📦' };
}

export async function criaCategoria(label: string, emoji: string) {
  const c = await expensesApi.createCategory(label, emoji);
  if (!extras.some(x => x.value === c.value)) extras = [...extras, c];
  avisa();
  return c;
}

export async function apagaCategoria(value: string) {
  await expensesApi.deleteCategory(value);
  extras = extras.filter(c => c.value !== value);
  avisa();
}

export function useCategorias() {
  const [, setVersao] = useState(0);
  useEffect(() => {
    const f = () => setVersao(v => v + 1);
    ouvintes.add(f);
    carregaCategorias();
    return () => { ouvintes.delete(f); };
  }, []);
  return todasCategorias();
}
