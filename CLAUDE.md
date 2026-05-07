# Cristopher — Personal Life Manager

App pessoal do Cristovão. **Idioma: PT-PT** em respostas. Estilo directo, sem enchimento.

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2, SQLite
- **Frontend**: React 18 + TypeScript + Vite + TailwindCSS
- **DB local**: `backend/cristopher.db` (SQLite, **NUNCA commitar** — `.gitignore`)
- **Uploads**: `backend/uploads/` (recibos de gastos, **NUNCA commitar**)

## Estrutura

```
backend/
  main.py              FastAPI app + migrations inline + auto-start do app_tracker
  database.py          engine + get_db
  models.py            todos os SQLAlchemy models
  schemas.py           Pydantic schemas
  routers/             1 router por feature (events, expenses, lol, …)
  ai_config.py         API keys vêm de .env (AI_API_KEY, etc.)
  app_tracker.py       tracker de uso de apps macOS (só corre em macOS)
  screen_time_reader.py  lê knowledgeC.db da Apple
  scripts/             scripts auxiliares (NÃO confundir com /scripts root)
frontend/src/
  App.tsx              shell + sidebar drawer (mobile) + rotas
  api.ts               todas as chamadas ao backend (uma constante por feature)
  pages/               1 ficheiro por página
scripts/launchd/       LaunchAgents para autostart no Mac (install.sh, uninstall.sh, status.sh)
```

## Como correr localmente (Mac do utilizador)

Está autostart via LaunchAgent. Para ver estado: `./scripts/launchd/status.sh`. Para reinstalar: `./scripts/launchd/install.sh`.

Manualmente:
```bash
cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```
- Backend: http://localhost:8000 (docs em /docs)
- Frontend: http://localhost:5173

## Como correr em Codespaces (programar no iPad em viagem)

O `.devcontainer/devcontainer.json` instala dependências automaticamente. Após o codespace arrancar:
1. Abre 2 terminais
2. Terminal 1: `cd backend && source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000`
3. Terminal 2: `cd frontend && npm run dev`
4. O VS Code mostra notificação "Open in Browser" para porta 5173 — carrega para abrir a app

**Features que NÃO funcionam em Codespaces** (precisam do macOS local):
- App tracker (`/api/app-usage`)
- LoL client/LCU API (`/api/lol/champ-select`, `/api/lol/riot/live*`)
- VS Code Activity (`/api/code-activity`)
- Apple Calendar import/export (`/api/events/apple-calendars`)
- Screen Time reader (`/api/screen-time`)

Tudo o resto funciona (gastos, calendário, notas, mood, hábitos, viagens, investimentos…).

## Variáveis de ambiente (`backend/.env`)

```
FMP_API_KEY=                 # opcional (fundamentals)
FINNHUB_API_KEY=             # opcional (earnings)
AI_API_KEY=                  # iaedu.pt agent (Ideas → Todos, signals)
ALLOWED_ORIGINS=             # CORS extra (separados por vírgula). Vazio = só localhost/Tailscale
DATABASE_URL=sqlite:///./cristopher.db
UPLOADS_DIR=uploads
TRACKER_AUTOSTART=1          # 1 em macOS local; 0 em Codespaces (auto-skipped em Linux)
```

## Convenções

- **Sem comentários a explicar o óbvio**. Só comentar o que não-óbvio.
- **Endpoints novos**: criar router em `backend/routers/<nome>.py`, registar em `main.py`. Prefixar URL com `/api`.
- **Models novos**: adicionar em `backend/models.py`. Para colunas novas em models existentes, adicionar migration inline em `main.py` (já tem padrão: `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`).
- **API frontend**: adicionar interface em `api.ts` (uma const por feature, ex: `expensesApi`, `lolApi`).
- **Páginas novas**: `frontend/src/pages/<Nome>Page.tsx`, registar rota e nav em `App.tsx`.
- **Mobile-first**: novos layouts devem usar `flex-wrap`, `grid-cols-1 sm:grid-cols-2 lg:grid-cols-N`. Modais sempre `max-w-[90vw]`. Tabelas em `<div class="overflow-x-auto">`.
- **TypeScript**: há erros pré-existentes em CalendarPage/Dashboard/LolPage que NÃO bloqueiam o build (`tsc --noEmit` falha mas `vite build` passa). Não tentar resolver sem o utilizador pedir.

## Repo & Deploy

- Repo: https://github.com/Leonardomf02/Cristopher (público)
- Sem deploy online — corre localmente no Mac via LaunchAgent + Tailscale para acesso mobile/iPad
- Em viagem: GitHub Codespaces (free tier 60h/mês)

## Notas IA (registo no fim de tarefas não-triviais)

No fim de cada tarefa não-trivial (≥1 ficheiro editado ou ≥3 passos significativos), regista uma Nota IA via:

```bash
printf '%s\n' \
  "bullet 1 — descrição concreta da feature" \
  "bullet 2 — outra mudança visível" \
  | backend/scripts/log_ai_note.sh
```

O script detecta automaticamente o ambiente:
- **No Mac do utilizador** → POST directo ao backend Cristopher (DB local).
- **Em Codespace** → anexa as notas a `ai-notes-pending.md` no root e faz commit + push automático. Quando o utilizador voltar ao Mac, corre `backend/scripts/process_pending_ai_notes.sh` que processa cada bloco e esvazia o ficheiro.

**Como escrever os bullets** (mesmo tom das Notas IA do site):
- Cada bullet descreve UMA funcionalidade visível para o utilizador, não um ficheiro.
- Verbo concreto à cabeça ("adicionei", "mudei", "corrigi", "tirei", "substituí") ou descrição da feature.
- Máx ~20 palavras por bullet, 3-5 bullets no total. Direto, sem enchimento.
- Foca no QUE muda para o utilizador e impacto visível, NÃO em como foi feito.
- **Proibido**: caminhos tipo `frontend/src/pages/...`, "ajustes em X", "implementada API para...".
- **Proibido** detalhes de implementação: nomes de funções/endpoints/processos, "troquei pidfile por pgrep", "refactor do X", nomes de ficheiros, libs ou flags.
- Se o bug tinha causa técnica complicada, resume em UMA frase em linguagem de utilizador (ex: "tracker estava a duplicar e a contar tudo várias vezes") em vez de explicar a fix.
- Exemplos do tom certo:
  - "renomeei a secção Tudo para Reminders em todo o lado"
  - "ao abrir Reminders, a app abre a última lista que usei"
  - "corrigi o valor errado de investimentos no dashboard (somava snapshots duplicados)"

**Ignorar (não criar nota)**:
- Responder a perguntas sem editar código.
- Pesquisas/análises sem alterações no projecto.
- Correcções de typos numa única linha.

## Onde tens dúvida, pergunta — não inventes
