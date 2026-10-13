// Acções da paleta ⌘K. Ficam separadas do componente para o ficheiro da paleta
// não crescer e para se poderem acrescentar acções sem lhe mexer.
import { healthApi, quickApi } from './api';
import { applyTheme, getTheme } from './theme';

export type Command = {
  id: string;
  label: string;
  icon: string;
  hint?: string;
  keywords?: string;
  // Devolve uma mensagem para mostrar na paleta, ou nada (fecha logo).
  run: (ctx: CommandCtx) => void | string | Promise<void | string>;
};

export type CommandCtx = {
  navigate: (url: string) => void;
  fechar: () => void;
};

const paginas: [string, string, string, string][] = [
  // url, rótulo, ícone, palavras extra
  ['/', 'Hoje', '🏠', 'dashboard inicio principal'],
  ['/planner', 'Plano do dia', '🗓️', 'planner blocos'],
  ['/calendar', 'Calendário', '📅', 'eventos mês semana'],
  ['/expenses', 'Dinheiro', '💸', 'gastos despesas orçamento envelopes'],
  ['/lists', 'Reminders', '✅', 'listas tarefas todos'],
  ['/notes', 'Notas', '📝', 'apontamentos'],
  ['/code', 'Atividade', '💻', 'vscode código projectos wakatime'],
  ['/habits', 'Hábitos', '🔁', 'rotina streak'],
  ['/sleep', 'Sono', '🌙', 'dormir noites'],
  ['/screen-time', 'Tempo de ecrã', '📱', 'screen time apps'],
  ['/calendar/apps', 'Uso de apps', '🖥️', 'tracker aplicações'],
  ['/lol', 'LoL', '🎮', 'league of legends games'],
  ['/investments', 'Investimentos', '📈', 'bolsa carteira acções'],
  ['/trips', 'Viagens', '✈️', 'trips destinos'],
  ['/deals', 'Deals', '🏷️', 'anúncios vinted olx facebook'],
  ['/spotify', 'Spotify', '🎧', 'música playlists'],
  ['/stories', 'Stories', '📰', 'pesquisas ia'],
  ['/ideas', 'Ideias', '💡', 'brainstorm'],
  ['/ask', 'Perguntar', '✨', 'ia sql dados pergunta'],
];

const navegacao: Command[] = paginas.map(([url, label, icon, keywords]) => ({
  id: `ir:${url}`,
  label: `Ir para ${label}`,
  icon,
  hint: url,
  keywords,
  run: ({ navigate, fechar }) => { fechar(); navigate(url); },
}));

const criar: Command[] = [
  {
    id: 'novo:gasto', label: 'Novo gasto', icon: '💸', keywords: 'despesa adicionar criar recibo',
    run: ({ navigate, fechar }) => { fechar(); navigate('/expenses?new=1'); },
  },
  {
    id: 'novo:nota', label: 'Nova nota', icon: '📝', keywords: 'apontar escrever criar',
    run: ({ navigate, fechar }) => { fechar(); navigate('/notes?new=1'); },
  },
  {
    id: 'novo:evento', label: 'Novo evento', icon: '📅', keywords: 'calendário marcar criar',
    run: ({ navigate, fechar }) => { fechar(); navigate('/calendar?new=1'); },
  },
];

const jobs: Command[] = [
  {
    id: 'job:sync_wakatime', label: 'Sincronizar código (WakaTime)', icon: '🔄',
    keywords: 'wakatime actualizar horas',
    run: async () => {
      const r = await healthApi.runJob('sync_wakatime');
      return r.ok ? `feito: ${r.detail || 'sincronizado'}` : `falhou: ${r.detail}`;
    },
  },
  {
    id: 'job:sinais', label: 'Correr sinais de investimento', icon: '📈',
    keywords: 'bolsa ia analisar carteira',
    run: async () => {
      const r = await healthApi.runJob('sinais_investimento');
      return r.ok ? 'sinais gerados' : `falhou: ${r.detail}`;
    },
  },
  {
    id: 'job:snapshot', label: 'Actualizar sono e tempo de ecrã', icon: '🌙',
    keywords: 'snapshot importar apple',
    run: async () => {
      const r = await healthApi.runJob('snapshot_local');
      return r.ok ? `feito: ${r.detail || 'actualizado'}` : `falhou: ${r.detail}`;
    },
  },
];

const app: Command[] = [
  {
    id: 'app:tema', label: 'Trocar tema claro/escuro', icon: '🎨', keywords: 'light dark cor',
    run: () => {
      applyTheme(getTheme() === 'dark' ? 'light' : 'dark');
      return `tema ${getTheme() === 'dark' ? 'escuro' : 'claro'}`;
    },
  },
  {
    id: 'app:avisos', label: 'Abrir avisos', icon: '🔔', keywords: 'notificações painel',
    run: ({ fechar }) => {
      fechar();
      window.dispatchEvent(new CustomEvent('cristopher:avisos'));
    },
  },
];

export const COMANDOS: Command[] = [...criar, ...navegacao, ...jobs, ...app];

// Escrever "gastei 12 no lidl" na paleta cria a despesa (mesma interpretação da
// captura rápida do telemóvel). Só aparece quando a frase parece uma anotação.
const VERBOS = /(gastei|paguei|comprei|custou|lembra|lembrar|tenho de|preciso de|hoje foi|dia \d)/i;

export function comandoDeCaptura(texto: string): Command | null {
  const t = texto.trim();
  if (t.length < 6 || !VERBOS.test(t)) return null;
  return {
    id: 'captura',
    label: `Apontar: “${t}”`,
    icon: '⚡',
    hint: 'cria despesa, reminder ou humor',
    run: async () => {
      const r = await quickApi.capture(t);
      return r.summary ? `✓ ${r.summary}` : '✓ apontado';
    },
  };
}

export function filtra(comandos: Command[], termo: string): Command[] {
  const t = termo.trim().toLowerCase();
  if (!t) return comandos.slice(0, 6);
  const palavras = t.split(/\s+/);
  const pontos = (c: Command) => {
    const alvo = `${c.label} ${c.keywords || ''} ${c.hint || ''}`.toLowerCase();
    if (!palavras.every(p => alvo.includes(p))) return -1;
    return alvo.startsWith(t) ? 2 : c.label.toLowerCase().includes(t) ? 1 : 0;
  };
  return comandos
    .map(c => ({ c, p: pontos(c) }))
    .filter(x => x.p >= 0)
    .sort((a, b) => b.p - a.p)
    .map(x => x.c)
    .slice(0, 6);
}
