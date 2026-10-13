// Fila de acções feitas sem rede.
//
// A app já abria offline com os últimos dados, mas não deixava escrever nada —
// e é precisamente na rua, sem ligação ao Mac, que apetece apontar um gasto ou
// riscar um bloco do plano. O que se faz sem rede fica aqui guardado e sai
// assim que a ligação volta.
//
// Só entram acções seguras de repetir: criar coisas novas e marcar estados.
// Nada de importações nem de pedidos que gastam dinheiro em IA.

const CHAVE = 'cristopherOutbox';

export type AccaoPendente = {
  id: string;
  path: string;
  method: string;
  body?: string;
  descricao: string;
  criada_em: number;
};

// caminhos que vale a pena guardar quando falham por falta de rede
const GUARDAVEIS: { padrao: RegExp; metodo: string; descricao: (corpo: any) => string }[] = [
  { padrao: /^\/expenses\/$/, metodo: 'POST', descricao: b => `gasto: ${b?.description || ''} ${b?.amount ? `${b.amount}€` : ''}`.trim() },
  { padrao: /^\/quick\/capture$/, metodo: 'POST', descricao: b => `apontamento: ${(b?.text || '').slice(0, 40)}` },
  { padrao: /^\/mood\/journal$/, metodo: 'POST', descricao: () => 'entrada do diário' },
  { padrao: /^\/mood\/$/, metodo: 'POST', descricao: b => `humor ${b?.mood ?? ''}/10` },
  { padrao: /^\/day-planner\/plans\/[\d-]+\/blocks\/\d+\/toggle$/, metodo: 'POST', descricao: () => 'bloco do plano marcado' },
  { padrao: /^\/lists\/items\/\d+$/, metodo: 'PUT', descricao: () => 'reminder actualizado' },
  { padrao: /^\/lists\/items$/, metodo: 'POST', descricao: b => `reminder: ${(b?.text || '').slice(0, 40)}` },
];

function ler(): AccaoPendente[] {
  try {
    return JSON.parse(localStorage.getItem(CHAVE) || '[]');
  } catch {
    return [];
  }
}

function escrever(fila: AccaoPendente[]): void {
  try {
    localStorage.setItem(CHAVE, JSON.stringify(fila.slice(0, 200)));
  } catch { /* armazenamento cheio: não vale a pena rebentar por isto */ }
  window.dispatchEvent(new CustomEvent('cristopher:outbox', { detail: fila.length }));
}

export function pendentes(): AccaoPendente[] {
  return ler();
}

export function guardavel(path: string, method: string): boolean {
  const limpo = path.split('?')[0];
  return GUARDAVEIS.some(g => g.metodo === method.toUpperCase() && g.padrao.test(limpo));
}

export function guardar(path: string, options: RequestInit): AccaoPendente | null {
  const method = (options.method || 'GET').toUpperCase();
  if (!guardavel(path, method)) return null;
  const limpo = path.split('?')[0];
  let corpo: any = null;
  try { corpo = options.body ? JSON.parse(options.body as string) : null; } catch { /* corpo não-JSON */ }
  const regra = GUARDAVEIS.find(g => g.metodo === method && g.padrao.test(limpo));
  const accao: AccaoPendente = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    path,
    method,
    body: typeof options.body === 'string' ? options.body : undefined,
    descricao: regra ? regra.descricao(corpo) : `${method} ${limpo}`,
    criada_em: Date.now(),
  };
  escrever([...ler(), accao]);
  return accao;
}

let aEnviar = false;

export async function enviarPendentes(): Promise<{ enviadas: number; falhadas: number }> {
  if (aEnviar) return { enviadas: 0, falhadas: 0 };
  aEnviar = true;
  let enviadas = 0;
  let falhadas = 0;
  try {
    for (const accao of ler()) {
      try {
        const res = await fetch(`/api${accao.path}`, {
          method: accao.method,
          headers: { 'Content-Type': 'application/json' },
          body: accao.body,
        });
        if (res.ok || (res.status >= 400 && res.status < 500)) {
          // 4xx = o servidor recebeu e recusou; repetir não adianta
          escrever(ler().filter(a => a.id !== accao.id));
          enviadas += res.ok ? 1 : 0;
          falhadas += res.ok ? 0 : 1;
        } else {
          falhadas += 1;
        }
      } catch {
        falhadas += 1;
        break;        // sem rede: volta a tentar mais tarde
      }
    }
  } finally {
    aEnviar = false;
  }
  return { enviadas, falhadas };
}

export function iniciarOutbox(): void {
  window.addEventListener('online', () => { enviarPendentes(); });
  // e de vez em quando, porque o evento "online" nem sempre chega no iOS
  setInterval(() => {
    if (navigator.onLine && ler().length) enviarPendentes();
  }, 60000);
  if (navigator.onLine && ler().length) enviarPendentes();
}
