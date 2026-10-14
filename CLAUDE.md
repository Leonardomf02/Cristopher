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

Atalho: `./start.sh` arranca backend + frontend (mata o que estiver nas portas) e abre o browser.

Manualmente:
```bash
cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8001
cd frontend && npm run dev
```
- Backend: http://localhost:8001 (docs em /docs)
- Frontend: http://localhost:3001

## Como correr em Codespaces (programar no iPad em viagem)

O `.devcontainer/devcontainer.json` instala dependências automaticamente. Após o codespace arrancar:
1. Abre 2 terminais
2. Terminal 1: `cd backend && source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8001`
3. Terminal 2: `cd frontend && npm run dev`
4. O VS Code mostra notificação "Open in Browser" para porta 3001 — carrega para abrir a app

**Features que NÃO funcionam em Codespaces** (precisam do macOS local):
- App tracker (`/api/app-usage`)
- LoL client/LCU API (`/api/lol/champ-select`, `/api/lol/riot/live*`)
- VS Code Activity (`/api/code-activity`)
- Apple Calendar import/export (`/api/events/apple-calendars`)
- Screen Time reader (`/api/screen-time`)

Tudo o resto funciona (gastos, calendário, notas, mood, hábitos, viagens, investimentos…).

## Na NAS do Pedro (produção)

A app corre num contentor na NAS QNAP do Pedro (TS-431KX, **ARM de 32 bits**,
páginas de 32K), com a mesma receita do Cinespot. Guia: [`DEPLOY-NAS.md`](DEPLOY-NAS.md).
**Sem Tailscale** — é uma porta aberta no router pelo Pedro.

- **https://<NAS_HOST>:8443** → reverse proxy → contentor na 9011. O `NAS_HOST` vive no
  `.env.nas` (fora do git): o repo é público e aquilo é uma porta aberta em casa do Pedro.
- Uma imagem só: o FastAPI serve a API e o build do React (`STATIC_DIR`).
- Actualizar: `IMG=cristopher:vN ./build-nas.sh /tmp/x.tar && ./deploy-nas.sh /tmp/x.tar`,
  importar na Container Station, mudar a etiqueta no YAML. **Etiqueta nova sempre.**
- **Estado vive em `/data`** (base, recibos, cópias, token do Garmin, `.pem` do
  banco, chaves dos avisos), tudo por variáveis de ambiente. Um caminho novo ao
  lado do código perde-se na versão seguinte da imagem.
- `CLOUD=1` desliga o que só existe no Mac (tracker, Screen Time, Reminders,
  Calendário da Apple, LoL ao vivo). O tracker e o Screen Time chegam pelo agente
  (`agent/`, `/api/ingest/*`). `LOCAL_AI=0`: o Ollama não existe para ARM de 32 bits.
- **Dependência nova tem de passar o `build-nas.sh`**: ele carrega a app dentro da
  imagem e recusa-se a exportar se alguma biblioteca carregada estiver abaixo de
  32K. O `pdftotext` e o `tesseract` do Debian não passam (10 e 9 bibliotecas a 4K)
  e por isso não estão na imagem.
- Com password (`CRISTOPHER_PASSWORD`) a app exige `JWT_SECRET` ou não arranca, o
  `/docs` fecha e o `/uploads` passa a pedir sessão.
- **Depois da mudança, a base verdadeira é a da NAS.** A `backend/cristopher.db`
  do Mac fica uma cópia velha; o `deploy-nas.sh --dados` recusa-se a pisar a da NAS.
- `nas-compose.yml` e `.env.nas` estão fora do git (repositório público).

## Alimentação: comer as principais a horas

Três refeições com janela (pequeno-almoço, almoço, jantar), editáveis na página.
O que se mede é **comer a horas**, e o score diz isso: dentro da janela vale
inteiro, fora vale metade, falhada vale zero — e a percentagem do dia é só sobre
as refeições **já decididas**, porque um almoço às 13h não é um almoço falhado só
por ainda não ter chegado o jantar.

Os **lanches ficam registados e não contam** para o score: a contar, bastava
petiscar para o dia parecer bom.

Os dias **anteriores ao primeiro registo não são dias falhados** — é a app que
ainda não existia. Sem isso, a média da semana nascia a dizer 7%.

O que se comeu tem **autocomplete por refeição** (`/meals/suggestions`), do mais
repetido para o menos: o que se come ao pequeno-almoço não é o que se come ao
jantar, e uma lista única enchia-se de coisas que nunca serviam.

**Suplementos** vivem na mesma página (`supplements`, `supplement_logs`): lista
que ele monta — proteína e creatina são só o que vem proposto à primeira e
apagam-se como qualquer outro. Cada um é um check por dia (carregar outra vez
desmarca), com dose e, se quiser, uma hora que dispara aviso. **Não entram no
score das refeições**: o que ali se mede é comer a horas, e um dia sem proteína
não é um almoço falhado.

Avisos (trabalho `avisos_refeicoes`, de 5 em 5 minutos): um quando a janela abre
e outro 20 minutos antes de fechar, **só se ainda não estiver marcada**. Cada um
sai uma vez por dia e a marca fica em `meal_notices` — em memória, um reinício do
backend transformava-os em spam de cinco em cinco minutos.

## LoL: o champ select vem do Mac (`lol_live.py`)

O cliente do LoL fala por uma porta local e só o Mac o vê; com a app na NAS, o
champ select desaparecia. O agente lê-o no Mac e empurra-o
(`POST /api/ingest/lol-champ-select`) de 3 em 3 segundos durante o draft, de 12
em 12 com o cliente aberto, e uma vez quando fecha.

O estado vive **em memória e caduca aos 25 segundos**: um champ select de há dez
minutos é mentira, e mais vale dizer que não há nada. No Mac, o cliente local
continua a ganhar — o empurrão é só a rede de segurança de quem não está lá.

## Variáveis de ambiente (`backend/.env`)

```
FMP_API_KEY=                 # opcional (fundamentals)
FINNHUB_API_KEY=             # opcional (earnings)
T212_API_KEY=                # opcional: carteira do Trading 212 pela API (chave:segredo)
AI_API_KEY=                  # agente iaedu.pt — 1º degrau da cascata (ver `ai.py`)
FALLBACK_AI_API_KEY=         # 2º agente iaedu.pt — 2º degrau, quando o principal falha/rate-limita
AI_LOCAL_TIMEOUT=60          # tecto (s) para o 3º degrau, o modelo local
RIOT_API_KEY=                # chave da Riot (estava escrita no código, num repo público)
FALLBACK_AI_API_URL=         # URL do agente de fallback (tem default)
FALLBACK_AI_CHANNEL_ID=      # channel id do fallback (tem default)
ALLOWED_ORIGINS=             # CORS extra (separados por vírgula). Vazio = só localhost/Tailscale
FB_MARKETPLACE_CITY=         # opcional: slug de cidade do FB Marketplace nos Deals (default: lisbon, raio ~100km)
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
- **Nenhum segredo em ficheiros do git**, nem como valor por omissão no código: a
  chave da Riot esteve escrita em `routers/lol.py` de Maio a Outubro de 2026. Há um
  pre-commit com gitleaks (`scripts/git-hooks/pre-commit`, regras em
  `.gitleaks.toml`); num clone novo: `git config core.hooksPath scripts/git-hooks`.
  Varrer o histórico: `gitleaks git . --log-opts=--all`.
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

## Gasto, entrada, transferência e estorno

Nem tudo o que passa na conta é dinheiro gasto. Cada despesa tem um `kind`
(`backend/expense_kind.py`):

- **spend** — consumo a sério. **Só isto conta** para os totais, para os tectos do
  orçamento, para a previsão, para os envelopes e para a régua das anomalias.
- **transfer** — dinheiro dele a mudar de sítio (Trading 212, Finst). Mandar 300€
  para a corretora não é gastar 300€. O Revolut **não** entra nesta regra pelo
  nome: é o banco dele, e o nome aparece em comissões e levantamentos, que são
  gastos. Entra pelo **carregamento**: a Caixa corta as descrições a vinte e um
  caracteres e passar dinheiro da conta dela para o Revolut aparece como
  `CAR WAL CRT DEB REVOL` — eram 15 movimentos e 2.235€ contados como consumo, e
  a IA das lojas, obrigada a responder com uma categoria de despesa, chamou-lhes
  "viagens". **O que não é gasto já nem sequer vai à IA das lojas**: não há loja
  nenhuma do outro lado de uma transferência.
- **income** — reembolsos, vendas na Vinted, dinheiro de amigos.
- **reversal** — a compra que voltou atrás; aparece a débito e a crédito e o par
  anula-se. Detectado por valor simétrico + mesmo sítio até 21 dias depois.
  "Mesmo sítio" é a mesma chave de loja das regras de categoria: a Caixa escreve
  a compra como `GOPRO.C` e a devolução como `CR VCHER CRT DB GOPRO`, e comparar
  a primeira palavra dava "goproc" contra "vcher". No MB Way o sítio é o número.

Antes disto a app dizia que em Julho ele tinha gasto 332€ — na verdade gastou
**1.437€**, e a diferença eram 1.091€ que voltaram das corretoras e 587€ de
compras revertidas. Levantar dinheiro continua a contar como gasto: ele não
regista o que faz com o dinheiro vivo.

O tipo é escolhido pela app na sincronização e nas importações, e pode ser
corrigido à mão (`PUT /api/expenses/{id}` com `kind`). `GET /api/expenses/movements`
devolve os quatro totais, mas **saiu da página** a pedido dele: os quatro números
por cima da lista repetiam os cartões do topo e discordavam deles.

Quem passou a mandar são os cartões, e agora respeitam o tipo: **o "Gasto" é um
número só** — o que é `spend`, e mais nada. Somava tudo o que era positivo, o que
lhe dava 851,68€ em Agosto quando saíram 651,68€ (os outros 200€ foram para o
Revolut), e por baixo escrevia "−853,41€ depois dos reembolsos" — que é o gasto
menos as **entradas**, e a bolsa da faculdade não é um reembolso. O que voltou
atrás já não está lá dentro: as duas pernas de um estorno anulam-se pelo `kind`.
O mesmo vale para a média por dia e para a comparação com o mês passado.

O **Restante** é o que entrou na conta menos o que saiu — as duas coisas
medidas. O "Rendimento" é escrito à mão e fica para trás: em Agosto herdava os
1.090,98€ de Julho quando tinham entrado 1.705,09€, e somá-lo às entradas
contava a bolsa duas vezes (o cartão dizia **2.144,39€**). Sem entradas medidas
— meses antigos, importados de PDF — vale o declarado. O Rendimento continua a
ser a base do **Orçamento**, onde os envelopes são percentagens dele; os três
cartões dizem no `title` o que contam.

Para reclassificar o histórico: `python scripts/classifica_movimentos.py --aplicar`.

Os gastos por cidade têm **aba própria (Viagens)**, com o mapa e a lista de todas
as cidades lado a lado. Estavam no fundo da aba do Ano, por baixo das tabelas
todas, e mostravam só as oito primeiras. A aba cabe na janela: o mapa desenha-se pela
**altura que sobra** (`preserveAspectRatio` + `h-full`, sem `height` inline, que
ganharia à classe) — a desenhar-se pela largura, numa coluna de 1000px ficava com
500px de altura e punha a página a rolar.

O **Resumo** dos Gastos cabe na janela sem rolar: a comparação com o mês passado
à esquerda, as categorias à direita, e é a **lista das categorias** que rola
dentro do cartão. O gráfico de gastos por dia da semana saiu — dizia a mediana de
cada dia da semana, o que nunca mudou nada. Só esta aba se prende à janela; as
transacções, o ano e o orçamento têm listas que têm mesmo de rolar.

## Gastos desde o salário, e categorias dele

O mês dele não começa no dia 1: a bolsa (1.090,98€, `TRF UNIVERSIDADE DA B`)
entra a 24, 26, 27 ou 28. Nas **Transações** há "Mês | Desde o salário"
(`localStorage` `gastos_periodo`); no segundo, o período vai do dia em que o
salário entrou à véspera do seguinte, e os cartões do topo passam a contar esse
período — não há uma segunda fila de números a discordar da primeira. O
Rendimento dá lugar ao cartão **Salário**, e por isso o **Recebido** passa a ser
só o que entrou além dele (somá-lo outra vez dava 1.206,23€) e o Restante é
salário + recebido − gasto. As setas
do cabeçalho andam de salário em salário. O selector vive na fila das Transações
(ao lado do título ele não o quis), mas **manda na página toda**: cartões,
cabeçalho e Resumo, que soma as categorias da própria lista e compara com o
salário anterior, e o **Plano do Salário** do Orçamento (`/budgets/salary-plan`
com `start_date`/`end_date`/`salary`). O salto do Ano para as Transações volta ao
mês. Antes valia só nas Transações e ao passar ao Resumo os cartões voltavam ao
mês sem aviso.

Os **Envelopes da semana** e os **Limites por categoria** saíram da página a
pedido dele (os endpoints ficam). Quem manda no orçamento é o Plano do Salário:
**um grupo por categoria, a somar 100%** — 70% para gastar e 30% para investir,
com os valores pensados a partir de Abril-Setembro sem as compras pontuais
(`main.PLANO_SALARIO_2026_10`). Foi posto uma vez por migração
(`_migrate_plano_salario_100`, marca em `api_cache`); daí em diante é dele, e cada
grupo edita-se em % ou em € por mês. Gasto do plano = gasto líquido, como os cartões.

O dia lê-se da conta (`salario.py`, `GET /api/expenses/paydays`): a maior entrada
do mês que chegue a **80% do Rendimento declarado** — os 598€ que a universidade
mandou a 3 de Agosto não são o salário. Corrige-se à mão no lápis do cartão
Salário (`PUT /paydays`, tabela `salary_paydays`), com data + ✓ — gravar a cada
mudança do campo apanhava o dia a meio de ser escrito. Uma barra própria por cima
da lista e um botão "É o salário" no editar foram tentados e ele tirou os dois
(o `PUT` continua a aceitar `amount`): num mês que já tinha salário
substitui-o, num que não tinha (o banco ainda não sincronizou) abre o período.
Meses sem banco levam o dia do costume (a mediana), **menos o corrente** — aí o
salário pode estar só atrasado.

**O Restante conta as devoluções soltas.** Um estorno cujo par ficou noutro
período (a GoPro comprada a 7 de Setembro e devolvida a 24, no dia do salário) não
é Gasto nem Recebido, mas é dinheiro que entrou na conta — sem isto o Restante
ficava 59,99€ abaixo do banco. Quando ele desconfiar do Restante, a forma de
tirar a limpo é conta a conta: o `bank_accounts.balance` de uma sincronização
mais os movimentos depois dela tem de dar o saldo de hoje. Na reconciliação de
Outubro bateu ao cêntimo, e as duas diferenças eram um movimento pago da
**segunda conta da Caixa** (que ele não somava) e outro do Revolut ainda pendente
quando a NAS sincronizou (os pendentes não entram; vêm na passagem seguinte).

**Categorias novas** criam-se no editar gasto (botão "Nova"; tabela
`expense_categories`). As de origem continuam no código; o frontend junta as
duas em `expenseCategories.ts` (`useCategorias`, `infoCategoria`) — usar isso e
não o `EXPENSE_CATEGORIES` cru. Uma categoria só se apaga vazia. A IA continua a
escolher só das de origem; as regras de loja aceitam as dele
(`bank_categories.categoria_valida`).

## O que há nas contas (por baixo do título dos Gastos)

"Revolut €60.66 · Caixa €384.29 · total €444.95", debaixo de "Gastos", em
todas as abas (`GET /api/banking/balances`). Não vai para os cartões porque não é
do mês que se está a ver — é o saldo disponível da **última sincronização** (o
`title` diz a hora). Soma-se por ligação: o Revolut traz uma conta por moeda (o
que não é euro vai à taxa de hoje; sem taxa fica fora da soma e diz-se). A Caixa
traz também uma conta **sem IBAN**, que é o cartão (começou a 150€ e desce com as
compras): **não entra na soma** — ele conta só a conta à ordem — e aparece só no
`title`. Uma conta a 0€ passou a gravar o zero — o `or` antigo guardava o saldo
anterior.

## Contas pagas por ele, e a parte que os amigos devolvem

O gás da casa (`CHAMATENCAO`, 35,60€ a 8 de Setembro) paga-o ele, e no mesmo dia
o Rodrigo e o Gabriel mandam 11,87€ cada. Sem ligação, a app contava 35,60€ de
gasto **e** 23,74€ de entradas. Ligar um reembolso (`expenses.reimburses_id`)
faz dele um **gasto negativo da categoria da conta** — por isso nenhuma soma de
`spend` da app precisou de mudar: o gás passa a valer 11,86€ em todo o lado e o
dinheiro sai das entradas. Consequência a saber: no frontend **já não se filtra
o gasto por `amount > 0`**. Um reembolso que chegue no mês seguinte desconta
nesse mês (é quando o dinheiro entra).

`reembolsos.py` sugere — **nunca liga sozinho**: entradas que sejam metade, um
terço… um sexto da conta, ao cêntimo, até 14 dias depois. **Só aparecem no
editar da transação** (a conta mostra quem parece ter pago, a entrada vem com a
conta já escolhida), com "Descontar" e "não é" (`reimbursement_dismissed`, para
não voltarem); na lista é só um ícone (`HandCoins`) nas duas pontas. Uma faixa
por cima da lista com as sugestões todas foi tentada e ele não a quis.

**Uma entrada pode descontar em várias contas**: levantou 70€ + 30€
para o chá e o Rafael mandou 75€ — nenhuma das duas sozinha leva 75€. No editar
da entrada escolhem-se as contas (lista com caixas) e o valor reparte-se na
proporção do que falta a cada uma (`reembolsos.reparte`, tabela
`reimbursement_links`; `reimburses_id` fica a primeira, que dá a categoria). O que
cada conta já recebeu vem sempre dos `links`, nunca do valor da entrada. Quando nenhuma conta sozinha
serve, a sugestão procura entre as que ele marcou como divididas uma combinação
cujo que-falta some o valor (70€ + 5€ = os 75€ do Rafael), e a repartição faz-se
pelo que os outros devem a cada uma, não pelo valor das contas. O editar de uma
conta tem ainda **"Paguei por mais pessoas"**, por igual
(`split_people`, N com ele) ou **"a minha parte é X€"** (`my_share`) quando não é
por igual: a janela alarga para 45 dias e a pastilha
**"A receber"** soma o que falta. Os reembolsos ficam fora dos estornos e do
`classifica_movimentos`, seguem a categoria da conta quando ela muda, e voltam a
ser entradas se a conta for apagada.

## Wishlist: "Comprei" liga a uma transacção, nunca cria uma

A compra já está na conta — o banco trouxe-a. O "Comprei" criava um gasto novo
com o preço da wishlist e a data de hoje, e a viseira passou a contar duas vezes
(e pelo preço inteiro, quando ele pagou uma prestação da Klarna de vinte e tal
euros). Agora abre a lista das transacções (`GET /wishlist/{id}/candidates`,
ordenadas pelo valor: o preço, ou o total de um movimento marcado como Klarna —
o banco escreve a loja, não o produto) e liga-se a uma (`expense_id`). Nos
comprados mostra-se o que saiu de facto, e com Klarna "€X × N (k/N pagas)".
Desfazer só desliga; apaga apenas os gastos que a wishlist antiga inventou
(nota "Da wishlist" e sem `bank_tx_id`), e esses aparecem com um aviso para
escolher a transacção verdadeira.

## Klarna: o movimento é a prestação, e as outras procuram-se na conta

O banco não traz a compra, traz as prestações: a youget.pt foram 106,63€ a 18 de
Julho, 106,63€ a 19 de Agosto e 106,64€ a **12** de Setembro, cada uma um
movimento à parte. Por isso marcar um movimento como Klarna
(`expenses.klarna_installments`, vazio = não é) **não divide o valor por nada** —
ele já é a prestação.

**Pago é o que o banco já mostra, não o que o calendário diz** (`klarna.py`). A
Klarna cobra quando quer e ele pode pagar adiantado: a contar só pelas datas, a
app mandava guardar uma prestação que já tinha saído. As outras prestações do
plano são movimentos de **mesma loja e mesmo valor** (±5 cêntimos, que a última
leva os que sobram da divisão), para a frente e **para trás** — marcar a segunda
encontra a primeira. A loja compara-se pela chave das regras sem espaços
(`youget.pt` e `you Get`), e uma cobrança que só diz "Klarna" serve a qualquer
plano. As datas (mesmo dia dos meses seguintes) ficam para o que ainda não
apareceu; o que passou da data sem aparecer dá-se por pago, senão uma loja com
outro nome ficava a dever para sempre.

`GET /api/expenses/klarna` soma por mês o que falta e diz que prestação é cada
movimento (as etiquetas `Klarna 2/3`). Aparece em dois sítios: uma linha no
cartão **Restante** com o que vence no mês que se está a ver (é dinheiro que já
tem dono), e "Klarna | Out €34.35 | Nov €34.35" nas Transações, **na mesma linha dos botões de
importar e com o feitio deles** (uma pastilha rosa). Numa caixa só para ela por
cima da lista, ou como texto solto ao lado dos botões, ele não gostou. `GET /api/expenses/{id}/klarna?vezes=N` é o mesmo para um gasto só,
antes de gravar. Nada disto mexe em totais: cada prestação já conta como gasto no
mês em que o banco a cobra.

## Deals: exigências em campos, e o preço do que ele quer

O caça-deals só tinha um campo de texto solto (`ai_context`) que ia no prompt e
mais nada. "Quero 35 kW, preta, 2021-2024, até 10 mil km" era uma frase que a IA
podia ler mal — e lia. Agora são **campos** (`deal_watches.criteria_json`,
editáveis na página): intervalo de anos, tecto de quilómetros, potência, cores,
palavras obrigatórias e palavras proibidas.

`deal_attrs.py` tira do texto o ano, os km, a potência e a cor com regras — é
português de anúncio, não é prosa. Nos 741 anúncios da MT-07 lê o ano em 73%
deles e os km em 32%. Duas armadilhas que custaram sangue:
- **"MT-07 35kw" dava 7 kW** e **"2020 35 KW" dava 20** — a regex agarrava
  dígitos do modelo e do ano. Precisa de fronteira antes do número.
- **na descrição o ano precisa de pista** ("Ano: 2017", "de 2015", "04/2023").
  Sem isso, "Ano 2017 … Preço 5200" dava 2023 e "de 2015" dava 2024. No título
  não é preciso: o que lá está é o ano da mota.

**O OLX vai por `curl_cffi` a imitar o Chrome, não por `httpx`.** Dentro da
imagem da NAS o OLX responde **403** ao `httpx` (a impressão digital do TLS é
outra) e o mesmo pedido do Mac passava: foram oito dias sem um anúncio novo na
NAS sem ninguém dar por isso. O **Vinted** mudou a API e só a `vinted-scraper` 5
a conhece (que puxa o `httpx` 0.28); o estado vem na segunda linha do cartão e o
URL vem relativo.

**Quantos anúncios se vão buscar**: eram 25 por fonte, e o OLX tem **738** para
"Yamaha MT 07" — a app via 25 e concluía que não havia nada. Agora são 150 (o OLX
pagina, `_POR_PAGINA=50`), e isso só é possível porque **quem já falha uma
exigência nem chega a ir à IA**: pedir-lhe para avaliar uma mota de 2016 quando
ele quer 2021-2024 é gastar quota para confirmar o que uma regra já sabe. Esse
atalho só se aplica quando o que falha é o **ano, os km ou a potência** — isso
prova que aquilo é um veículo. Um par de piscas LED "falhava a cor" e ia parar à
lista como se fosse a mota.

Dois falsos positivos que quase o mandavam ver uma mota errada, ambos com teste:
- **"Revisões de 5 em 5 mil km"** numa mota com 25.000 km era lido como 5.000, e
  ela passava a cumprir um limite de 10.000. Vale o **primeiro** número de
  quilómetros do texto, e expressões de intervalo desqualificam o que vem a
  seguir.
- **"Símbolos Yamaha em preto"** e **"farol traseiro preto"** faziam a mota preta.
  Na descrição a cor só conta com pista ("cor:", "mota azul"); no título conta
  sempre.

**Fontes escolhem-se à vontade** (`sources` é csv): OLX, Facebook Marketplace,
StandVirtual, Vinted, IA-web. O **StandVirtual** (`deals_sources/standvirtual.py`)
é a melhor delas para veículos e a razão é esta: o ano, os quilómetros e a
potência **vêm em campos**, não em texto. A página é Next.js e os resultados vêm
no `__NEXT_DATA__`. A potência vem em cavalos e converte-se a kW, mas arredondada
à classe legal (`deal_attrs.classe_de_potencia`): 45 cv dão 33 kW e sem isso uma
A2 a sério falhava um pedido de "exactamente 35 kW".

O **Facebook devolve 24 resultados por pesquisa e não pagina** — sem login não há
mais. Duas consequências, ambas já tratadas:
- Pergunta-se de várias maneiras (`deal_criteria.pesquisas_alternativas`, tiradas
  dos próprios critérios): "yamaha mt 07" e "yamaha mt-07" são pesquisas
  diferentes para o Facebook, e um dos anúncios que ele queria só aparecia em
  "yamaha mt-07 35kw". Passou de 24 para 59 anúncios.
- **Não aparecer não quer dizer vendido.** Como quase tudo sai da vista em dias,
  antes de marcar um anúncio do Facebook como ido vai-se ver a página do item
  (`facebook.esta_vivo`). Estavam **19 anúncios vivos dados como vendidos**.

**A cor sai da foto, porque no texto não está.** De 780 anúncios guardados,
**zero dizem a cor** — era a única exigência dele que ficava eternamente em "o
anúncio não diz". O modelo local vê imagens (`deal_vision.py`, `qwen3.5:9b`),
corre no Mac, não gasta quota e demora ~5 segundos. Nos anúncios reais dele:
azul → azul, preta → preta, prateada → cinzento, e uma fotografia de uma piscina
que o Facebook mete no meio → "nenhuma", em vez de inventar. Só se olha para a
foto quando o watch **pede** uma cor, quando o texto não a deu, e só a quem já
passa as outras exigências — 12 por passagem. A app diz quando a cor veio da
foto (`attr_color_src`), porque um palpite de uma imagem não é o mesmo que o
vendedor tê-lo escrito.

Cuidado com as fotos do Facebook: os URLs são assinados e **caducam** (passam a
devolver 21 bytes de "URL signature expired"), e a página do item traz dezenas de
imagens de outros anúncios — a do próprio anúncio é a do `og:image`.

Os atributos são **relidos a cada passagem**, não só quando o anúncio entra: uma
MT-07 limitada ficou marcada como 55 kW porque a linha já existia quando a
leitura foi corrigida.

No StandVirtual, o **kW escrito ganha aos cavalos do motor**: uma A2 traz
`engine_power = 75 cv` (o motor é o mesmo) e "35 Kw" no título. Converter os
cavalos dava 55 e mandava fora exactamente a mota que ele procura.

`ai_match` é sobre **a identidade do produto**, não sobre as exigências. Uma
MT-07 de 2016 continua a ser uma MT-07 (`match=true`) mesmo que ele só queira de
2021 para cima — quem trata disso é o veredicto dos critérios. Misturar as duas
coisas encolhia a amostra do preço justo e escondia o que devia estar visível.

`deal_criteria.py` confronta cada anúncio com as exigências e dá **três**
respostas, não duas: cumpre, não cumpre, **o anúncio não diz**. Um vendedor que
não escreve os quilómetros não é um anúncio que falha os quilómetros — fica
marcado a amarelo e continua na lista, mais abaixo. Só o que **falha** sai da
triagem. As exigências já verificadas vão no prompt em vez de se pedir à IA que
as descubra: ela decide o que é julgamento, não o que uma regex acerta.

**O preço justo passou a ser do que ele quer.** A "mediana do costume" era a
mediana de tudo o que a pesquisa trouxe — MT-09, MT-10 e um suporte de alumínio
de 20€, de 1€ a 8.990€. Agora compara-se com as do mesmo ano (alargando a janela
só se não houver seis), e havendo quilómetros que cheguem separa-se pela metade
parecida; a app diz sempre com que amostra chegou lá ("uma de 2016 anda nos
5.200€"). A diferença não é cosmética: a de 2016 a 5.600€ aparecia como **"900€
abaixo do costume"** quando está **400€ acima** do que vale uma de 2016.

## LoL: desempenho medido, não adivinhado

Durante 488 jogos a app só guardava quem ganhou. Com winrate não se prova nada:
o efeito do tilt (54,5% sem derrotas atrás contra 41,7% depois de duas) dá
z=1,65, e Wukong contra Lee Sin dá z=1,62 — os dois abaixo do limiar. A 40 jogos
por mês, provar qualquer um levaria mais de um ano.

A Riot mandava CS, ouro, dano, visão e abates da equipa em cada partida e a app
deitava-os fora (`riot_api.parse_match` lia-os só para o painel ao vivo). Agora
ficam em `lol_games`, e os 488 jogos antigos foram preenchidos de uma vez com
`scripts/preenche_metricas_lol.py --todos` (~10 min; pode ser interrompido e
retomado, só pede os que faltam).

São contínuos, por isso cada jogo é uma medição em vez de uma moeda ao ar e ~30
jogos chegam. `GET /api/lol/performance` parte a amostra (tilt, ordem do jogo no
dia, sono, hora, campeão a campeão) e passa cada métrica por Mann-Whitney com
correcção de empates (`lol_performance.py`) — sem dependências novas, como o
`garmin_insights`. **Só sai o que tem p ≤ 0,05**; o resto fica no "o que foi
testado e não deu nada", de propósito.

O que os dados dele dizem, com prova: de Lee Sin faz **+36% de visão por minuto**,
de Khazix **+15% de ouro** e +16% de dano mas menos participação nos abates, de
Jarvan participa em mais abates e **morre mais**, de Wukong **morre menos 29%** —
é o campeão mais seguro dele. De Sylas é pior em tudo (CS, ouro e visão).

E o que **não** apareceu, que é igualmente informação: o tilt não passa o teste
nem nestas métricas (301 jogos contra 75). Depois de duas derrotas ele perde mais
mas **não joga pior** — a queda de winrate não vem do desempenho dele.

## LoL: a régua é o jungler adversário

A app comparava-o só com ele próprio. "6,24 CS por minuto" não diz nada — é bom,
é mau, é normal para Master? A Riot **não publica referências por elo, nenhuma**,
e as dos sites são de outra amostra, outro patch e outro elo.

Mas em cada partida há um jungler do mesmo elo, no mesmo patch, no mesmo jogo, a
jogar contra ele. São 500 comparações emparelhadas de graça, e estavam a ser
deitadas fora: a Riot manda **128 campos de `challenges` por participante**, para
os dez jogadores, e a app guardava sete, só dele.

Ficam em `lol_duels` (tabela à parte, colunas nomeadas, mais `challenges_json`
com a cauda dos 128 para acrescentar métricas sem re-sincronizar). Preenche-se com
`python scripts/preenche_duelos_lol.py --todos` (~25 min por 500 jogos,
retomável).

**A sincronização cura-se sozinha.** `_guarda_duelos` não trata só dos jogos
acabados de importar — vai à base buscar os jogos de jungle dos últimos 30 dias
que ainda não têm duelo, com um tecto por passagem. Tratar só dos novos era uma
fuga silenciosa: um jogo em que a Riot recusasse o pedido ficava sem duelo **para
sempre**, porque nunca mais era tentado. E se mesmo assim se acumularem quinze ou
mais, o `/api/health/data` acusa — é o mesmo princípio dos 56 dias de sinais
parados sem ninguém dar por nada.

O teste é **Wilcoxon signed-rank emparelhado** (`lol_duel.py`) e não Mann-Whitney:
não são dois grupos de jogadores, é o mesmo jogo medido duas vezes, por isso tudo
o que varia de jogo para jogo cancela-se. A percentagem de "ganhas" é sobre os
jogos **que se decidiram** — nos abates em laners cedo há 30% de empates, e
contá-los dava a leitura ao contrário do que o p-value diz.

**A divisão que interessa, e que nenhum tracker faz**: o que acontece antes de o
jogo se decidir contra o que se acumula até ao fim. Fazer mais dragões não é
conselho — é a descrição de ter ganho. Perder CS de selva aos 10 minutos é
conselho. Nos jogos dele o ouro contra o jungler adversário está a **+256 nas
vitórias e −296 nas derrotas aos 10 minutos, e a +705 contra −754 aos 15**: é
naquela janela que os jogos ganhos deixam de se parecer com os perdidos.

O que os 495 jogos dele dizem, com prova. Contra ele: **wards de controlo, onde
ganha 22% dos jogos que se decidem** — a coisa mais barata de corrigir em todo o
jogo; **−6 de CS de selva aos 10 minutos**; menos visão e menos CS por minuto;
mais mortes e mais tempo morto. A favor dele: **abates em laners cedo (ganha
64%)**, selva do adversário comida, participação em abates, dano por minuto, e
**+81 de ouro aos 10 minutos**.

Esse último par diz o essencial sobre ele: aos 10 minutos está **+81 em ouro e
−219 em XP**. Troca farm por ganks, ganha o ouro e paga em níveis. Placas de
torre, dragões e ouro por minuto ao fim do jogo não passam o teste — nisso está a
par do adversário, e isso também é resposta.

**De que lado ele está numa métrica decide-se pelo sinal do teste, não pela
mediana.** Nos abates em laners cedo a mediana da diferença é zero (23% dos jogos
empatam) e ele ganha 64% dos que se decidem: a olhar para a mediana, a métrica
aparecia a vermelho — contra ele — apesar de o teste dizer o contrário. Pela
mesma razão, a percentagem mostrada é sobre os jogos **que se decidiram**, que
são os mesmos que o teste usa.

Por campeão, a Diana é o **único** onde ele ganha o farm inicial (+2,4 de CS de
selva aos 10, três mortes a menos); o Jarvan, o mais jogado de todos, é −11,3 e
**+5 mortes**.

## LoL: escolher campeão, e porquê são sempre os mesmos

`suggest_picks` percorria a tabela dos jogos dele, por isso **um campeão que ele
nunca jogou de jungle não podia ser sugerido**. Ele tem o Talon com 177 mil pontos
de maestria e tier 2 no patch, e a app nunca lho ia dizer — enquanto lhe sugeria
Lee Sin, onde tem 44,9% em 98 jogos, quatro pontos abaixo da média Master.

E os pesos estavam ao contrário: um matchup pessoal com 1-4 jogos mexia ±30 no
resultado e o meta global, com milhares de jogos, mexia ±8. Nos 500 jogos há 234
pares de matchup e **um** com dez jogos ou mais.

`lol_picks.py` dá um winrate esperado em **pontos percentuais**, somado de
parcelas que se lêem uma a uma: `meta + matchup + à-vontade + composição`. Um
"score 87" escondia que entre o primeiro e o quinto vão 1 a 2 pontos.

**Duas listas, de propósito.** No pool dele a maestria já não separa ninguém (são
todos campeões que domina) e quem decide é o matchup; fora do pool a conta é
outra — só vale se o ganho pagar o que custa pegar num campeão novo. Esse custo
vem de uma medição (iTero, 1M+ jogos): 41,5% de winrate abaixo de 5 mil pontos de
maestria contra 54,5% acima de 500 mil, **mas com a curva a saturar cedo** — de 75
mil para 175 mil o ganho é menos de 1pp, por isso os campeões que ele já sabe
jogar não levam castigo nenhum. Há ainda uma terceira lista, para fora do champ
select: contra a distribuição real dos junglers que ele apanha, quais rendiam
mais nos próximos cem jogos.

**O winrate dele por campeão não entra na conta, e isso mediu-se.** A variância
dos "edges" (winrate dele menos o do elo) nos nove campeões com amostra é de
5,9pp de desvio; o ruído que se esperaria só por acaso, dado o número de jogos de
cada um, é de **10,6pp**. O ruído é maior do que o sinal: a diferença entre os
61,9% de Diana e os 44,9% de Lee Sin é indistinguível de uma moeda ao ar, e o
encolhimento óptimo dá praticamente zero — por isso é zero, e não um número
escolhido a olho. É a mesma lição que o resto do LoL já tinha aprendido: com
winrate não se prova nada.

Sem isso, o Wukong levava +5,2pp e aparecia em primeiro contra **onze dos doze**
junglers que ele mais encontra, com os matchups (±2pp, medidos em milhares de
jogos) a nunca conseguirem compensar uma vantagem que não existe. Com o termo a
zero, o primeiro lugar passa a ser de cinco campeões diferentes conforme o
adversário, que é o que se queria.

As medidas contínuas do duelo **separam** mesmo os campeões (dano por minuto, CS
por minuto, visão), mas separam **o campeão** e não ele: o Kha'Zix faz mais dano
que o Wukong porque é um assassino. Sem uma referência por campeão e por elo —
que a Riot não publica — não há como isolar as duas coisas. O edge continua na
aba Duelo, onde é informação sobre ele; só não manda em decisões. E cada linha da
recomendação mostra o winrate dele ao lado, para ele decidir com os dois números
à vista.

Quatro coisas que custaram a acertar:

- **`fetch_external_counters` estava morta e ninguém deu por isso.** Chamava
  `_fetch_opgg_matchups`, que já não existia; o `NameError` rebentava na
  avaliação do argumento, **antes** do `asyncio.gather(return_exceptions=True)`,
  por isso a função inteira falhava e quem chamava mostrava listas vazias em vez
  de um erro.
- **Dos três números que a lolalytics manda por matchup, só um serve.** Medido em
  21 pares de junglers, quanto é que `X(A vs B) + X(B vs A)` se afasta de zero (um
  efeito de matchup a sério é antissimétrico): o winrate cru dá **+5,20pp** de
  viés (a média deles é 52,59%, não 50%), o `d1` dá **+10,09pp**, e o `d2` dá
  **+0,68pp**. É o `d2` — e é por ele ser antissimétrico que se pode consultar o
  **inimigo** e inverter o sinal, cinco pedidos em vez de sessenta e oito, que é a
  diferença entre caber num champ select e não caber.
- **Tudo o que é winrate encolhe pela amostra.** O do meta (o Gragas jungle tem
  57,5% em 3.083 jogos e o Lee Sin 49,1% em 54.770 — o primeiro é o winrate de
  quem o domina tanto quanto o do campeão), o de cada matchup ("Teemo jungle ganha
  8,4pp ao Viego" em 40 jogos), e o à-vontade dele.
- **O resultado é travado em [40, 60].** Somar −6 de "nunca jogaste isto" a um
  campeão que já está nos 45,6% dava 39%, e nunca se mediu nada assim.

**Nada disto promete muito, de propósito.** Nenhum modelo publicado passa dos 60%
de acerto a prever o resultado só pelo draft (Kim et al., UW), e é de lá que vem
a forma de combinar os matchups: média ponderada pelo número de jogos de cada um,
não uma soma de deltas.

**Duas previsões do mesmo dia com o mesmo campeão davam as duas o mesmo jogo**, e
o `match_id` é único: o `/predictions/stats` respondia 500. Ele joga dois Sylas no
mesmo dia com frequência. Um jogo só pode resolver uma previsão.

## A IA está toda no `ai.py`

Havia três caminhos para a mesma coisa: o `ai_config` (agente + reserva), o
`local_ai` (Ollama) e **uma cópia inteira dentro dos sinais de investimento**. A
cópia tinha um bug que o original não tinha — tratava um 404 como fatal e saltava
por cima da reserva. Quando o agente principal foi apagado do lado do iaedu.pt,
os sinais saíram **doze dias seguidos sem narração** enquanto o resto da app
continuava a funcionar pela reserva sem ninguém dar por nada.

Agora há uma porta só, `ai.pergunta()` / `ai.pergunta_async()`, com três degraus:

1. **agente principal** (iaedu.pt)
2. **agente de reserva** (2º agente iaedu.pt)
3. **modelo local** (Ollama no Mac) — o degrau que faltava

Nenhum código de erro trava a cascata: 404, 401, 429 ou 500 passam todos ao
degrau seguinte. `ai_config.py` ficou como casca fina que reencaminha, porque
quinze módulos importam de lá; **código novo importa de `ai`**.

O terceiro degrau leva **trela curta** (`AI_LOCAL_TIMEOUT`, 60s por omissão). O
modelo local gera a ~14 tokens/s e sem tecto uma página que dizia "IA
indisponível" em 5 segundos passava a ficar pendurada 200 — foi exactamente o que
aconteceu ao `/api/lol/jungle/tips` na primeira versão disto. Quem tem tempo (os
trabalhos da noite) pede um timeout maior. Quem não faz sentido sem pesquisa web
passa `permite_local=False`.

**A app diz quando anda na rede de segurança**: `ai_status()` devolve `engine` e
`degraded`, `/api/health/data` põe isso nos `problems`, e a primeira vez em cada
dia que a resposta vem do modelo local sai um aviso. Era isto que faltava para os
doze dias não voltarem a acontecer.

Nos testes o degrau local está desligado (`tests/conftest.py`, `LOCAL_AI=0`).

## Modelo local (Ollama)

Nem tudo o que a app pede à IA precisa de um modelo grande com pesquisa web. Pôr
"Żabka" em `groceries` é escolher de uma lista de dez palavras — isso corre no
Mac, de graça, sem fila e sem sair da máquina (`backend/local_ai.py`, `qwen3.5:9b`).

O modelo foi escolhido a medir, não a ler comparações: nas 25 lojas do extracto
dele o Qwen acerta 23 e o llama3:8b — que estava cá antes — acerta 15, com o Lidl
e a Żabka em `food`. Cada uma dessas viraria uma regra permanente e errada. Em
português o llama3 respondia na primeira pessoa ("Dormi apenas 5 horas"), como se
fosse ele o próprio. Ocupa 6,6 GB em disco e ~9 GB de RAM a correr, na GPU.

Duas coisas sem as quais isto não funciona, e que não dão erro nenhum quando
faltam:
- **`think: false`** — o Qwen3.5 raciocina, e com `format: json` manda a resposta
  para o campo `thinking` e devolve `response` vazio. Tudo o que é local passava
  a devolver `None` em silêncio.
- **`num_ctx: 32768`** (`OLLAMA_NUM_CTX`) — o Ollama corta o prompt a 4096 sem
  avisar e o modelo responde na mesma a partir de metade do texto. Num teste com
  60 anúncios, aos 4096 inventou o preço e o código de contacto; aos 32k acertou.

Só há um modelo instalado, de propósito — é o único que a app usa.

Onde entra:
- **categorizar gastos importados** (CSV/PDF) — local primeiro, agente se falhar.
- **regras de lojas do banco** — ao contrário: **agente primeiro**. Cada resposta
  vira uma regra permanente e uma regra errada fica errada para sempre (o modelo
  local mandou a De Lijn, transportes belgas, para "other"). É uma chamada por
  dia, não há quota a poupar. O local fica como rede quando o agente está em baixo.

Fica sempre no agente o que só ele faz: pesquisa web (deals, histórias, sinais) e
o SQL do Perguntar.

Serviço: `brew services start ollama`. Com ele desligado tudo continua a
funcionar pelo caminho do costume — `local_ai.pergunta()` devolve vazio e quem
chama cai no agente. `LOCAL_AI=0` desliga de vez.

## Quota de IA: quem gasta o quê

O agente iaedu.pt é partilhado por 22 chamadas em 15 módulos e é o recurso mais
escasso da app. `backend/ai_budget.py` conta as chamadas por parte da app e por
dia e dá a cada uma um tecto (`deals` 12/dia, `sinais` 20, `lojas_banco` 6, …).
O que ele pede à mão — Perguntar, captura rápida — nunca é travado.

Quando os Deals chegam ao tecto, os anúncios ficam guardados **sem nota** e vão à
IA na passagem seguinte, em vez de deixarem o Perguntar e o diário sem quota. E
com o preço habitual já conhecido (≥12 anúncios), o que está acima do percentil
70 nem chega a ir à IA — nunca seria um achado.

`GET /api/health/data` traz `ai` com o gasto de hoje por parte da app.

## Planeador: o plano fecha-se sozinho

Em nove planos, zero blocos marcados — pedir para carimbar o dia não funciona. O
trabalho `fecha_planos` (08:45) marca como feitos os blocos que o tracker
confirma (≥60% do bloco cumprido), nos últimos três dias. Um bloco que ele tenha
carimbado à mão nunca é desmarcado, e um dia com o Mac desligado fica "por saber"
em vez de "falhado".

`GET /api/day-planner/recurring` mostra o que se repete: por cada coisa que ele
põe no plano, quantas vezes planeou e quantas aconteceram — Trabalho 27 vezes
planeado e 1 cumprido, Gym 8 e 1. Isso e o "o que aconteceu mesmo"
(`/plans/{data}/reality`) **saíram da página** a pedido dele: enchiam a coluna do
horário e empurravam o plano para fora do ecrã. Os endpoints ficam, e o
`fecha_planos` continua a carimbar o dia — só não está à vista.

**As horas do dia já não se perguntam.** Havia dois campos, "acordo às" e
"deito-me", que ele tinha de acertar à mão — e o relógio mede as duas coisas.
`wake_time` e `day_end` são opcionais no pedido: sem eles, a hora de acordar é a
da noite medida (ou a mediana das últimas semanas) e a de deitar é a mediana das
noites, feita na escala contínua para 23h e 01h não darem meio-dia.
`GET /api/day-planner/day-bounds` é o que a página mostra por cima do botão, e
diz se aquilo foi medido hoje ou é o costume dele.

**A página "O Dia" saiu do menu**: os seis números dela (sono, código, ecrã,
jogos, gastos, humor) passaram para a barra do Planear Dia, ao lado do plano, que
é onde dizem alguma coisa. A rota `/day/{data}` **fica viva** — é para lá que o
painel de avisos manda quando pergunta "ontem dormiste 2.6h, o que aconteceu?", e
a linha do tempo do dia não existe em mais lado nenhum.

A página inteira cabe na janela sem rolar: barra fina em cima, à esquerda as
atividades (uma linha cada) com **"como queres o dia" sempre à vista** por baixo
— é a nota que manda no plano da IA, e atrás de um botão não era relida nem
corrigida — e à direita o horário a esticar até ao fundo.

## Ecrã: a média por dia da semana, categoria a categoria

A pergunta não é quanto usou ontem — é se às quintas trabalha mais e ao domingo
menos. Está na aba **Estatísticas** e responde a isso por categoria (fichas para
escolher, ou "Tudo"), no período escolhido na aba. Substituiu a média por dia da
semana que já lá estava, que dizia o mesmo mas só do total. Ao lado do título vai
a **média de todos os dias** e a linha tracejada atravessa as barras — sem ela,
sete números não dizem qual é o dia acima do costume.

Dias sem leitura nenhuma não entram na conta — o Mac desligado puxava a média
para baixo. O mesmo vale para a "Média / dia" do Resumo, que dividia pelos dias do
período e dizia 3h14 ao lado de uma linha de média de 8h51 no gráfico.

**Na NAS a página abre sempre**: as horas medidas chegam pelo agente, e o
`/screen-time/health` responde `apple_local: false` em vez de pedir acesso a um
`knowledgeC.db` que ali nunca vai existir (a página mandava dar Full Disk Access
a um `/root/Library/...`). O botão "Apple" (a leitura aproximada da Apple) só
aparece onde o ficheiro está, que é no Mac. Os dados já existiam (`/screen-time/timeseries-stacked?bucket=day`);
a conta é no browser. Em 90 dias, "Productivity & Finance" vai de 2h06 à quinta a
42min ao domingo.

## LoL: o que uma auditoria ao algoritmo encontrou

O modelo das picks foi auditado a sério — contra a literatura, contra as fontes,
e contra os 500 jogos dele. Três coisas estavam mal e uma faltava.

**Os efeitos de matchup estavam sobrestimados a dobrar.** Em 588 matchups de dez
junglers em Master+: variância observada dos `d2` **8,96pp²**, ruído esperado pela
amostra **6,50pp²** — ou seja **73% do que a lolalytics mostra como efeito de
matchup é ruído amostral**. O encolhimento óptimo é `n/(n+1015)`; estava
`n/(n+200)`, escolhido a olho. Um matchup mediano (610 jogos) retinha 75% quando
devia reter 38%.

O modelo de ruído confirma-se de fora: os mesmos matchups em Master+ e Diamond+
discordam 2,07pp, que é a ordem de grandeza que `2500/n` prevê. **E o desacordo
entre elos é todo ruído** — os matchups não mudam materialmente de Diamond para
Master. (Cuidado ao repetir esta medição: `diamond_plus` **contém** `master_plus`,
por isso as duas amostras não são independentes.) A região é ignorada pela
lolalytics nos counters: `region=euw` e `region=all` devolvem exactamente os
mesmos 9 milhões de jogos.

**Somava percentagens, e isso é errado.** Um bónus de +2pp não vale o mesmo a
partir de 50% e de 57%, e somando o suficiente sai-se de [0, 100] — era por isso
que ali estava um corte artificial em [40, 60]. A forma certa é a do modelo de
Bradley-Terry (que é o mesmo que o Elo e que uma regressão logística): as forças
somam-se em **log-odds**. Perto de 50% a diferença é de décimas, o que confirma
que o corte não escondia um erro grande — escondia um erro de forma.

**Não dá para validar o modelo com os jogos dele, e isso é uma conclusão, não uma
desculpa.** Nos 474 jogos com matchup medido, o terço de matchups bons dá 48,7% de
winrate e o terço de maus dá 50,0% — sinal invertido, p=0,82. Mas com 158 jogos
por terço só se detectam diferenças de **15,8pp ou mais**, e o matchup vale ±2pp:
provar isso precisaria de ~9.800 jogos por grupo. "Não provado" aqui quer dizer
"impossível de ver daqui". Os matchups ficam porque estão medidos em milhões de
jogos do lado da lolalytics — trocar evidência externa forte por ausência de
evidência interna seria o erro contrário.

**Quanto pesa cada parcela**, medido: a força do campeão no patch tem amplitude de
11,3pp, o custo de aprender 6pp, o matchup 4,5pp, a composição ~0. É o meta que
decide o ranking e o matchup que afina — que é exactamente o que a literatura
mede. O tecto realista: **~56% de acerto a prever o resultado só pelo draft**
(LoLDraftAI 55,90% num holdout de 32.930 jogos; a regressão logística da
LoLTheory, com 14.490 features por amostra, 54-56%). Um modelo aditivo com três
termos não vai bater isso, e não finge que vai.

**Synergy: a u.gg tem, a lolalytics não.** A lolalytics mostra synergy no site
mas o `ep=counter` devolve sempre counters, mesmo com o `vslane` de um aliado —
com Jarvan IV, a Orianna dá +0,09, e se fosse a synergy dos dois seria das
maiores do jogo. Quem a expõe é a u.gg, num JSON estático que a página da duo
tier list carrega: `stats2.u.gg/lol/1.5/duos/world/{patch}/ranked_solo_5x5/
{tier}/1.5.0.json`, com os grupos `mid_jungle`, `top_jungle` e `jungle_supp`
(só `diamond_plus` e `emerald_plus` respondem; os outros dão 403, e pedidos
seguidos também — daí a pausa entre elos e a cache de 12h).

Vale a pena confiar nisto, e prova-se de fora: os mesmos pares medidos em
Diamond+ e em Esmeralda+ correlacionam **+0,865** com desacordo de 0,65pp — dois
elos independentes a dizer o mesmo. Os matchups, para comparação, ficam-se pelos
0,60-0,76. Metade continua a ser ruído (variância 1,72pp² contra 0,87), por isso
encolhe-se como tudo: `n/(n+2951)`, e um par mediano (2.794 jogos) retém 49%.

**A synergy soma-se, o matchup faz média.** Dois aliados bons são duas vantagens;
vários inimigos são a mesma pergunta feita várias vezes. E a cobertura é dos
pares mais jogados — o Lee Sin aparece em 52, a Diana em 1 —, por isso o que não
está medido vale zero em vez de valer um palpite.

Nos campeões dele: **Jarvan IV + Syndra +2,33pp** (o segundo melhor par
mid/jungle do jogo) e + Lulu +2,36; Lee Sin + Gangplank +2,47 e + K'Sante −3,32.
Com a Syndra escolhida no mid, o Jarvan sobe de 49,6% para 50,7% e passa à frente
do Wukong e do Lee Sin — a synergy chega para mudar a ordem.

**Bans: medidos, e não valem nada — mas agora sabe-se porquê e por quanto.** A
pergunta óbvia ("contra quem perco mais?") não tem resposta: dos 19 junglers que
ele enfrentou dez ou mais vezes, 1 passa o teste, e com 19 testes espera-se
exactamente 1 falso positivo (o único "provado" é a favor dele — 83% contra Sylas
em 12 jogos). O que **dá** para medir é quanto cada inimigo lhe baixa o melhor
pick que lhe resta, vezes a frequência com que aparece — e um ban tira o campeão
aos **dois** lados, o que é fácil de esquecer: banir o Lee Sin é ficar sem Lee
Sin.

Resultado: **o melhor ban vale +0,03pp por jogo**. Uma vitória extra em três mil
partidas. A razão é boa e é informação: contra qualquer um deles ele tem sempre
uma resposta acima dos 50% — o pool é largo o suficiente para o ban não decidir
nada. A lista fica na aba Duelo com o número à frente, para se ver que não vale a
pena, em vez de não existir e parecer que ninguém pensou nisso.

## LoL: o lado do mapa é o maior efeito que há para medir

**Red 57,6% (236 jogos), blue 45,2% (263) — 12,4 pontos, z=2,76.** Quatro a seis
vezes maior do que qualquer matchup, e a app não o usava em lado nenhum. E o lado
é **sorteado**: não há selecção pelo meio, é uma experiência aleatorizada de graça,
ao contrário de tudo o resto que a app mede.

Duas honestidades obrigatórias, porque o efeito foi descoberto nestes mesmos
dados. Partindo a amostra ao meio no tempo, os primeiros 249 jogos dão **+16,5pp**
e os últimos 250 dão **+8,4pp**: a direcção aguenta-se, a magnitude encolhe, e a
previsão fora da amostra (54,0%, p=0,11) já não passa o limiar. O efeito verdadeiro
é provavelmente ~8pp, não 12.

**O mecanismo é que se aguenta**, e é ele que interessa: de red ele passa ~4,5pp
mais do início do jogo na metade inimiga do mapa, e isso sobrevive às duas metades
(z=2,87 e z=2,75). Não é farm — o CS de selva aos 10 é igual dos dois lados
(−5,8 e −6,1). É decisão. De red faz **+0,50 dragões** em relação ao jungler
adversário e de blue faz **−0,36** (z=4,03), mais takedowns aos 10 (+1,58 contra
+0,14) e mais placas de torre.

E o mais útil: **o lado azul é o que tem a vantagem estrutural no dragão** — a
pit fica do lado dele e o pathing inicial é mais fluido. Ele ganha do lado que
tem a desvantagem. Não é o mapa, é ele a jogar em casa quando está de blue.

Isto não entra na escolha do campeão (o lado não se escolhe), mas é o número que
mais lhe muda o jogo — e está na aba Duelo, com a incerteza escrita ao lado.

## LoL: escolher às cegas

De blue pica-se primeiro, e nessa altura o jungler adversário ainda não existe. A
pergunta deixa de ser "quem é bom contra ele" e passa a ser "quem tem menos
maneiras de correr mal" — o melhor blind pick não é o mais forte, é o que tem a
banda mais larga de matchups pares.

`lol_picks._exposicao_a_counters` mede isso como o desvio dos efeitos de matchup
**já limpo do ruído amostral**: sem essa correcção, um campeão com matchups de
amostra pequena parecia volátil só por isso. Em Master+ o ruído sozinho vale
2,55pp de desvio, por isso quem fica abaixo disso não tem hard counters
detectáveis (Graves, Talon, Jarvan IV, Lee Sin, Kha'Zix — quatro deles do pool
dele) e quem fica muito acima tem (Kayn 3,42, Sylas 3,32).

## LoL: dizer-lhe durante o jogo, não depois

A app descobriu que ele põe zero control wards, que perde o dragão do lado azul
e que aos dez minutos troca XP por ouro — e nada disso lhe chegava a não ser que
abrisse a aba das estatísticas depois de o jogo acabar. Um facto sobre o passado
só vale se aparecer enquanto ainda dá para fazer diferente.

`lol_coach.py` lê o estado do jogo no **cliente local** (o mesmo `allgamedata` da
porta 2999 que o `live_winprob` já usava — a API da Riot só sabe da partida
depois de ela acabar) e cruza-o com o que o duelo mediu. Duas regras que valem
mais do que qualquer aviso:

* **só entra o que passou um teste nos jogos dele.** Nada de conselhos gerais de
  guia da internet: se a app não o mediu nele, cala-se. Sem medidas na base, o
  treinador não diz uma única coisa, por pior que o jogo esteja;
* **cada aviso traz o número que o sustenta.** "Compra uma control ward" é uma
  ordem; "0 control wards aos 12 minutos, e perdes esse duelo em 78% dos jogos em
  que se decide" é uma razão. A segunda muda comportamento, a primeira irrita.

O que ele vê, e quando:

| quando | aviso |
|---|---|
| primeiros 6 min | o lado que lhe calhou, com o winrate de cada um e a causa |
| a partir dos 8 min | control ward em falta (o achado mais forte, z=−10,4) |
| aos 10-12 min | farm abaixo do costume dele, com o número |
| a partir dos 8 min | dragões atrás, **só do lado em que ele os perde** |

O aviso do lado desaparece aos 6 minutos de propósito: aos vinte já não há nada
a fazer com essa informação, e um aviso que persegue o jogo todo passa a ruído.

**Vai por notificação do Mac, porque ele joga em ecrã inteiro.** A página do LoL
mostra o mesmo painel (polling de 15s, que é barato — fala com o cliente local,
não com a Riot), mas contar com um segundo monitor era desenhar para o caso
improvável. O trabalho `treinador_lol` corre de minuto a minuto, só faz alguma
coisa com o jogo a decorrer, e **diz cada coisa uma vez por partida** — a
repetição é o que faz as pessoas desligarem os avisos.

Duas armadilhas que uma revisão apanhou antes de o código ver um jogo a sério:

* **o cliente não manda o nome sempre no mesmo campo.** Conforme a versão, o
  `activePlayer` traz `riotId`, `summonerName` ou `riotIdGameName` — o
  `live_winprob` já tinha os três, e não é por acaso. Ler só um deles é não
  encontrar o jogador na lista, e isso aqui não dá erro: a app cala-se e parece
  que não havia nada a dizer;
* **o cliente não dá um id de partida**, e a memória do que já foi dito tem de se
  apagar entre jogos. Ao princípio a chave era o campeão mais o tempo a dividir
  por uma hora — o que dava a mesma chave a todos os jogos de Jarvan, e o segundo
  Jarvan seguido saía mudo. O que serve é o relógio: **quando o tempo de jogo
  anda para trás, começou outra partida**.

## LoL ao vivo: quota da Riot e previsões

A análise ao vivo pede, por cada um dos 10 jogadores, rank + maestria + lista de
jogos + 5 jogos em detalhe (~80 pedidos) e a página refrescava de 90 em 90
segundos: ~1.600 pedidos numa partida, com uma chave que dá 100 por 2 minutos.
Eram 26.871 linhas de "Rate limited" no log, metade do ficheiro.

Nada disso muda a meio da partida, por isso `riot_api.py` guarda os dados **por
jogador** (30 min) e a cache é limpa quando começa uma partida nova. Uma partida
inteira passou a custar uma leitura por jogador. Jogadores sem `puuid` deixaram
de ser pedidos (eram 743 pedidos a devolver 400 em ciclo).

As previsões pararam a 17 de Junho porque só se gravavam com a página do LoL
aberta — ele jogou 37 partidas em Julho e nenhuma foi prevista. O trabalho
`previsao_lol` corre de 5 em 5 minutos, mas só faz alguma coisa se o **cliente
do LoL estiver aberto** (lockfile); com ele fechado não fala com a Riot.

## O jogador do outro lado: em champ select não existe

Saber quem está do outro lado em champ select é impossível, e não é o modo
stream — é sempre assim. Medido no cliente dele, a meio de um draft com campeões
já escolhidos: as cinco cadeiras inimigas vêm com `nameVisibilityType: HIDDEN`,
`puuid` **e** `obfuscatedPuuid` vazios e `summonerId: 0`. Os colegas de equipa
dele vêm iguais, com apenas o `obfuscatedPuuid` preenchido — que não se resolve
em ninguém. Só ele próprio vem `UNHIDDEN`. Do inimigo, o cliente manda o
`championId` e mais nada.

O `puuid` só aparece quando o jogo arranca, pelo spectator — que é de onde a
análise ao vivo já tira tudo o resto. É lá que vive **o que aquele jogador já
fez contra o campeão que ele tem em mãos**: com o campeão que tem agora, e com
todos os campeões (`riot_api.historico_do_adversario`, no painel do jogo ao
vivo).

A Riot não responde a "os jogos dele contra X": dá a lista dos últimos jogos e
cada jogo em detalhe, por isso a conta custa **um pedido por jogo** e a amostra é
o que couber nos ~20 ranked que a lista dá. Apanhar o campeão dele uma vez em
vinte já é sorte — daí a apresentação: os jogos aparecem **um a um**, com o
campeão, o KDA e a data, e diz-se sempre quantos foram lidos. Um winrate de um
jogo não é um winrate.

Três coisas que a mantêm barata:
- **só o adversário directo** (o do mesmo papel; sem papéis atribuídos, o smite
  aponta o jungler). Perguntar o mesmo aos cinco não dá mais informação, dá rate
  limit;
- **os jogos já lidos não se pedem outra vez**: a análise ao vivo já pede 5 jogos
  em detalhe por jogador e guarda-os em versão reduzida (`_resumo_da_partida`, ~1
  KB em vez dos ~100 KB do JSON da Riot — guardar o original enchia a memória do
  backend para nada);
- **quem não tem dados públicos não se pergunta**: com o perfil privado ou em
  modo stream a Riot devolve vazio, e isso já se sabe antes (`data_available`).

## Viagens detectadas pelas despesas

`backend/home_base.py` deduz **onde ele vive em cada mês** (o país com mais dias
de despesas, com uma janela de ±25 dias para o mês de mudança não se enganar) e
trata como viagem tudo o que sai de lá. Sem isto o critério era "país ≠ Portugal"
e o Erasmus inteiro aparecia como uma viagem à Polónia.

Armadilhas já tratadas: a Vinted é lituana, a Apple factura de Cork e a Ryanair
de Dublin — comprar online não prova presença, por isso esses movimentos não
contam para a localização (`SEM_LOCALIZACAO`). Códigos de país inventados que o
Revolut manda ("0TL", "BAR", letras soltas) também não passam.

O trabalho `viagens` corre todos os dias às 10:00, depois do banco. `POST
/api/trips/detect` mostra o que encontrou (`?apply=true` grava). A resposta traz
`looks_like_home`: viagens antigas cujo destino é a casa desse mês — restos do
detector antigo, para apagar à mão.

Voos e alojamento comprados semanas antes ficam fora das datas da viagem e não se
ligam sozinhos; para esses continua a haver `POST /api/trips/link-expenses`.

## Dashboard: duas vistas, e a escolha fica guardada

Empilhado, o dashboard eram dois ecrãs e meio de scroll. Agora tem **Hoje**
(agenda à esquerda, e à direita o plano, o sono, o tipo de dia, os hábitos e o
"como foi o dia") e **Resumo** (os seis cartões de atalho e a Weekly Review, que
nesta vista abre por omissão — é ela o conteúdo, não um extra). A vista fica em
`localStorage` (`dashboard_vista`), como o Calendário faz com a dele.

**Carregar numa barra abre as apps que a fazem** — "que apps é que dão as 2h45 de
Productivity & Finance às quartas" não tinha resposta na app. `GET
/screen-time/by-app` aceita `weekday` (0 = segunda) e `category`, e com uma
categoria escolhida conta **só os segundos dessa categoria**: o browser tem
separadores em várias e somá-lo inteiro mentia. Às quartas dele: VS Code 11h34,
Brave 4h13, Firefox 1h33.

**8h34 de código não são 8h34 à frente do editor.** O WakaTime conta o que o
editor reporta, e na quarta de 12 de Agosto **8h20 disso foram do Claude Code** a
correr no terminal enquanto ele fazia outra coisa — 14 minutos é que foram do VS
Code. O tracker do Mac conta a app que está à frente (nesse dia: Brave 2h49, VS
Code 1h15), e o Brave cai em "Other", não em "Productivity & Finance". São réguas
diferentes, não um erro.

A coluna do dia foi encolhida até caber sem rolar: os cabeçalhos e as linhas dos
cartões levam `py-3`/`py-2` em vez de `p-4`/`p-2.5`. São ~120px, que era o que
faltava — acrescentar aqui uma linha é voltar a pôr a coluna a rolar. A folga que
sobra vai para os cartões que são listas (o plano e os hábitos, com `flex-1`):
repartida pelos espaços entre eles ficavam buracos de ar, e sem repartir ficava
um buraco no fundo da coluna.

No Resumo, os seis atalhos ficam numa linha só em ecrã largo e os números da
semana espalham-se por quatro ou cinco colunas — e **a coluna das viagens só
existe quando há viagens**: vazia, roubava 320px de largura à Weekly Review.

Cada vista cabe na janela, e **nenhum cartão tem scroll próprio**: quem rola é a
coluna, não o que está lá dentro. Dentro do cartão da agenda havia quatro scrolls
encaixados (atrasados, TODOs de código, sugestões, escolher pendentes), cada um
com o seu tecto — agora é uma lista só. As "Próximas Viagens" saíram da coluna do
dia (empurravam o "como foi o dia" para fora da janela) e estão no Resumo, ao
lado da Weekly Review, que é onde já vivia o cartão "Próxima viagem". O modal do
histórico de dias fica **fora das duas** — quem o abre é o "como foi o dia", que
vive na vista Hoje, mas ele é `fixed` e não pode depender da vista.

## O cronómetro do Flow: o que estava partido

Três coisas, todas no mesmo sítio (`FlowContext.tsx`):

- **um F5 e a sessão desaparecia** — o estado vivia só em memória. Fica em
  `localStorage` (`flow_sessao`) e ao voltar avança-se o relógio pelo tempo real
  que passou: o cronómetro conta com a página fechada, que é o que acontece na
  vida. Em pausa, não conta.
- **parar demorava** e ele carregava outra vez: `stopTimer` esperava por dois
  pedidos à rede antes de mexer no ecrã. Agora o ecrã pára primeiro e grava-se
  depois. Sem isso, cinco carregadas eram **cinco sessões e cinco blocos** no
  calendário — foi exactamente o que aconteceu (`aFecharRef` fecha a porta).
- **a sessão não aparecia no calendário**: o POST da sessão e o do bloco
  partilhavam o mesmo `try`, e uma falha comia as duas coisas. São dois pedidos
  independentes. E o bloco entra **já feito** — `completed` existia no model e
  não no `EventCreate`, por isso nascia sempre por fazer.

A **timeline da vista Dia estica-se ao que existe**: era fixa das 7h às 22h, e
uma sessão de flow à 01:00 caía fora — não aparecia em lado nenhum e parecia que
não tinha ficado registada. O intervalo passa a incluir a hora mais cedo e a mais
tarde do dia, mantendo as 7h-22h como mínimo.

Na vista Dia, a coluna da direita tem **exactamente a altura da timeline**: os
Flexíveis e o Começar agora ficam pelo conteúdo (com tecto) e são as **Sugestões**
que esticam e rolam por dentro — é a única lista que pode crescer sem fim. Antes
rolava a coluna inteira, e num ecrã sem altura fixa ela passava a timeline.

Na vista Dia há uma caixa **Começar agora**: escreve-se o nome, escolhe-se 25min
/ 50min / 1h30 / 2h ou **sem fim**, e o cronómetro arranca sem a coisa ter de
existir numa lista primeiro. O bloco entra na timeline quando ele parar, com o
tempo real.

Na agenda de hoje, o **editar e o apagar deixaram de responder** por duas razões
que se somavam: o menu do ▶ fechava-se com uma manta `fixed inset-0` que apanhava
o primeiro clique em qualquer outra coisa (agora fecha por `mousedown` fora, sem
tapar nada), e o apagar dependia do `confirm()` do browser — que o Chrome deixa
de mostrar assim que se marca "não voltar a mostrar diálogos", e a partir daí não
apagava nunca. Apagar é **um clique**, sem diálogo nenhum. Os botões também deixaram de estar
invisíveis até se passar por cima.

**A sessão tem nota.** Carregar no temporizador da sidebar abre um painel ao lado
dele, à mesma altura e do mesmo tamanho (mede-se o `#mini-timer`; no telemóvel
fica em baixo), e já não leva ao Planear Dia: cada Enter é uma linha com a hora a
que foi escrita (`15:18 organizar agenda`), e corrigir a linha não muda a hora.
A nota vive com o cronómetro em `flow_sessao`, por isso sobrevive a um F5. Ao
parar vai para `flow_sessions.notes` e para a **descrição do bloco** do
calendário, por baixo da linha `Flow:` — texto simples, que se lê em qualquer
sítio. No calendário, carregar num bloco com nota abre a nota
(`linhasDaDescricao`), e editar o bloco fica a um clique dali. Com nota, o bloco
entra mesmo que a sessão não chegue a um minuto.

## Tarefas flexíveis não acumulam para trás

Uma tarefa **flexível** que se repete ("Projeto CS" todos os dias úteis) e que não
foi feita num dia passado **não aparece nesse dia** — nem a primeira ocorrência,
nem as virtuais (`routers/events._expand_recurring`). O que ele quer é fazê-la
hoje; vê-la carimbada a vermelho em cada dia que passou é uma dívida que o
calendário não devia cobrar. Um compromisso com hora (fixo) continua a aparecer:
aconteceu, tenha ele carimbado ou não.

O **▶ de começar** (`ComecarTarefa.tsx`, um componente só para os quatro sítios:
sugestões do calendário, tarefas flexíveis do dia, agenda de hoje e reminders)
abre 25min / 50min / 1h30 / 2h ou **sem fim**. Sem fim é `work_minutes: 0` no
Flow — o cronómetro conta **para cima** e a sessão só fecha quando ele carrega em
parar, com o tempo real. Antes, "não sei quanto tempo isto demora" obrigava a
inventar um número.

**Começar não é riscar.** Chegou a marcar a tarefa como feita ao arrancar o
cronómetro, e está errado: começar não é ter feito. A tarefa fica na lista até
ele a carimbar.

Na agenda de hoje, a ordem é: o dia, os atrasados, as **Sugestões** e por fim os
**TODOs de código** — e é só esse último bloco que rola. Estica-se ao espaço que
sobra e o scroll acontece lá dentro; o resto da agenda fica quieto. **As
Sugestões fazem o mesmo**: repartem a altura com os TODOs e rolam por dentro.
Cortá-las na quarta (a primeira tentativa) escondia as outras sem forma de lá
chegar.

As listas de sugestões (dashboard e calendário) **filtram-se por lista** e os
TODOs de código **por projecto** — todos, ou um. O selector só aparece quando há
mais do que uma lista/projecto: com um só, não decide nada.

Nos **Reminders**, cada item tem a data à direita, na mesma linha do texto: nos
que estão por fazer é a de quando foi apontado, nos feitos é a de **quando foi
feito** (`list_items.checked_at`, carimbado pela app quando o check muda — quem
carimba um reminder não vai escrever a hora a seguir). O ano só aparece quando
não é este; o dia da semana e a hora ficam no title.

## Reminders da Apple: os dois lados são o mesmo lado

Os Reminders do Cristopher e o Reminders da Apple sincronizam-se nos dois
sentidos. O que ele escreve no iPhone aparece aqui; o que aponta aqui aparece no
iPhone. O botão *Apple* na página das Listas faz uma passagem à mão.

**Na NAS é o agente do Mac que faz a ponte**, porque a Apple não tem API nenhuma
para os Reminders (o CalDAV do iCloud deixou de os mostrar com os "Reminders
novos" do iOS 13) e só um aparelho da Apple lá escreve. A divisão é esta: **a NAS
decide, o Mac lê e escreve**. O agente manda o `dump` para
`/api/ingest/reminders/plan`, a NAS corre a mesma reconciliação de sempre
(`apple_reminders.planeia`) e devolve as operações; o Mac aplica-as e devolve os
ids em `/reminders/applied`. Os `ref` são `L<id>`/`I<id>` para a resposta poder
voltar noutro pedido.

**Imediato**: o agente fica pendurado em `/reminders/wait` (25s, abaixo dos 60s
do reverse proxy), que responde no segundo em que muda a impressão das Listas
(`apple_reminders.impressao`, o conteúdo de tudo o que vai para a Apple). Medido:
um reminder criado no Cristopher aparece na Apple em **0,9s**. O que muda no
iPhone chega em até ~25s, que é de quanto em quanto o agente relê a Apple. Com o
Mac desligado fica tudo guardado na NAS e passa quando ele acordar.

Duas armadilhas de ser em dois pedidos:
- **o que foi escrito na Apple tem de chegar à NAS antes de um plano novo**, senão
  o item sem `apple_id` era criado outra vez. O agente grava a resposta em
  `~/.cristopher-agent/reminders-aplicado.json` até a NAS a receber;
- **um item apagado entre o plano e a escrita** deixa na Apple um reminder que
  ninguém conhece — e que voltava a entrar como se viesse do iPhone. O
  `regista_aplicado` põe-lhe uma lápide.

No Mac sem NAS continua o trabalho `sync_reminders` de hora a hora.

Cada lista espelha uma lista da Apple com o mesmo nome, e a ligação passa a viver
nos **ids** (`user_lists.apple_id`, `list_items.apple_id`). Mudar o nome de um dos
lados não desliga nada, e **o nome novo passa para o outro lado**. Quem mudou
sabe-se por `user_lists.apple_name`, o último nome que os dois tinham em comum: o
lado que já não o tem foi o que mudou. Se mudaram os dois, ganha o Cristopher. O
nome em comum só avança depois de a Apple confirmar a renomeação — se falhar, a
passagem seguinte tenta outra vez em vez de trazer o nome velho de volta.

**O ícone e a cor também passam, nos dois sentidos** (`apple_icon`,
`apple_color`, com a mesma regra do nome). O EventKit não os conhece: lêem-se da
base da própria app Lembretes (`ZREMCDBASELIST.ZBADGEEMBLEM` e o `daHexString`
dentro do `ZCOLOR`, só leitura, com o Full Disk Access do agente) e escrevem-se
por AppleScript (`emblem`/`color` da lista, procurada com `whose` — uma lista
acabada de criar pelo EventKit ainda não se encontra pelo id directo). **O emoji
vai como `{"Emoji" : "🛒"}`, não cru**: o `emblem` do AppleScript é o nome de um
símbolo ("cart"), e "🛒" cru é um símbolo que não existe — a app aceitava sem
erro, gravava, e desenhava o ícone por omissão. A cor passava e os ícones ficavam
todos iguais. É o formato do `REMListBadge` (`initWithEmoji:`), confirmado pela
própria framework. Os que ficaram gravados crus são reescritos pelo agente
(`repara_emblemas`), porque do lado do Cristopher já contavam como enviados.
**Ler por AppleScript
abria a app Lembretes** a cada passagem do agente (de 25 em 25 segundos) — por
isso só se escreve por lá, e só quando há um ícone ou uma cor a mudar. Um símbolo
escolhido no iPhone (não emoji) não se mostra aqui e não apaga o emoji daqui.

**Apagar uma lista aqui apaga-a na Apple** (a lista leva uma lápide com o id dela,
como os itens). Sem isso ela voltava na passagem seguinte, vazia, como se tivesse
sido criada no iPhone — e voltava sempre. Listas partilhadas só de leitura não se
apagam de lá: só deixam de ser importadas.

Mover um reminder de lista (arrastar para a lista, ou "Mover para" no painel
dele) é um `list_id` novo no `PUT /lists/items/{id}`; na Apple é o mesmo reminder
a mudar de lista, não um apagado e outro criado.

**Quem ganha um conflito é a edição mais recente.** Compara-se o conteúdo dos dois
lados: igual, não se toca em nada; diferente, ganha o que tem a data de alteração
mais tarde. Empate ao segundo fica para o Cristopher.

**Apagar propaga**, e é por isso que existe `reminder_tombstones`: um item apagado
aqui deixa uma lápide que manda apagar o reminder na passagem seguinte. Sem ela o
item voltava a nascer — "não existe deste lado" é exactamente o que também se
parece com "acabou de ser criado do outro".

Três decisões que evitam perder trabalho ou encher a app de lixo:

- **uma lista da Apple que desaparece não leva os itens a reboque.** Se o
  `apple_id` de uma lista já não existe do outro lado, ela é recriada e os itens
  voltam a ser enviados, na mesma passagem. Apagar aqui seria perder o que ele
  escreveu por causa de um engano no iPhone;
- **o que foi feito há mais de 30 dias não se importa.** A lista "Lembretes" dele
  tem 218 coisas feitas desde 2024 e despejá-las nas Listas enterrava as que
  interessam. Isto só trava a *importação* — o que já está ligado sincroniza para
  sempre;
- **listas partilhadas só de leitura nunca recebem escritas**: de lá só se lê.

**A conversa com a Apple é pelo EventKit** (`tools/reminders.swift`, compilado à
primeira utilização como o `tools/ocr`), não por AppleScript. Não é preferência:
ler os 250 reminders dele leva **0,6s pelo EventKit e 37s por AppleScript**, onde
cada propriedade é um Apple Event à parte, e uma escrita à conta leva ~8s. As
escritas vão todas numa transacção só.

Duas armadilhas que custaram a apanhar:

- **as horas.** O `func.now()` do SQLite grava em **UTC** e as datas da Apple são
  **locais** — sem converter, uma hora de diferença decidia os conflitos e uma
  edição de há 20 minutos no Mac perdia para uma de há 40 no iPhone. O binário
  manda o fuso explícito e o Python normaliza;
- **os alarmes.** Um reminder sem alarme não toca no telemóvel, mas pôr alarme em
  tudo era despejar notificações de coisas de 2024 na primeira passagem. Só leva
  alarme o que tem hora e ainda está para vir.

O macOS tem de dar acesso aos Reminders a quem corre isto (o agente, sob o
LaunchAgent). Sem ele, a página diz o que fazer em vez de falhar calada:
Definições do Sistema → Privacidade e Segurança → Lembretes.

## O caminho da base só existe num sítio (`database.DB_PATH`)

Na NAS a base é `/data/cristopher.db`. O Perguntar, a cache e o histórico dos
sinais (regime, sentimento, funding, calibração) abriam `"cristopher.db"` escrito
à mão — e na NAS isso é uma base vazia ao lado do código: o Perguntar respondia
"no such table: expenses" e os sinais gravavam num ficheiro que desaparecia na
imagem seguinte. **Quem abre a base com o `sqlite3` directo usa
`database.DB_PATH`.**

## Perguntar e "A app pergunta-te"

**Perguntar** (`/ask`): a IA escreve o SQL, a app corre-o numa ligação só de
leitura. A conversa continua — cada pergunta leva as 3 anteriores (com o SQL
delas), o que permite "e no mês passado?". O botão *nova conversa* corta o fio.

**A app pergunta-te** (painel de avisos): pega nos dias que fugiram ao padrão
(`/dashboard/anomalies`) e transforma-os em perguntas concretas ("Ontem dormiste
2.6h quando costumas dormir 7.7h — o que aconteceu?"). A resposta vai para o
diário desse dia. Máximo duas perguntas do mesmo tipo, para uma semana de compras
não esconder a noite mal dormida. "Não interessa" arruma a pergunta para sempre
(tabela `day_questions`).

## Cópias de segurança

Todos os dias às 5h (`backup_db`): `VACUUM INTO` + gzip, guardadas em
`~/Library/Application Support/Cristopher/backups`, com rotação de 30 dias.

Isso protege de um engano a apagar ficheiros, mas não de um disco que morre. Para
uma cópia **fora do Mac**, pôr em `backend/.env`:

```
BACKUP_OFFSITE_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/Cristopher
BACKUP_PASSPHRASE=<uma frase longa, guardada num gestor de palavras-passe>
```

A cópia vai cifrada com AES-256-GCM (chave derivada por scrypt). **Sem
`BACKUP_PASSPHRASE` não se envia nada** — mandar movimentos do banco, notas e
sono em claro para uma pasta sincronizada era pior do que não ter cópia. Se a
frase se perder, a cópia de fora deixa de abrir: guardá-la num sítio seguro.

Para restaurar: `python -c "import backup; print(backup.restaura('<nome>'))"`
(aceita os dois formatos; devolve um ficheiro à parte, nunca escreve por cima da
base a correr). O painel de avisos mostra a idade das duas cópias e acusa a de
fora quando ela está ligada e parada há mais de 48h.

## Carteira do Trading 212 (posições automáticas)

As posições vinham dos extractos mensais em PDF e ficavam paradas no último que
foi carregado. Com a API oficial passam a ser lidas todos os dias.

1. Na app do Trading 212: **Definições → API** → gerar chave. Guardar a chave e o
   segredo (só aparecem uma vez). Bastam as permissões de leitura.
2. `backend/.env`: `T212_API_KEY=chave:segredo` (as chaves antigas, de valor
   único, também servem — vão em claro no cabeçalho, como a API antiga pedia).
3. Reiniciar o backend e ir a **Investimentos → Trading 212 → Sincronizar agora**.
   Na primeira vez usar **"Trazer histórico completo"**, que varre as ordens,
   dividendos e movimentos todos (~1 min por causa dos limites de pedidos).

Depois disso o trabalho `sync_t212` corre todos os dias às 18:05, antes do
`precos_carteira` das 18:15 (não vale a pena cotar quantidades velhas).

- **Duplicados**: cada ordem e cada movimento traz um id do broker
  (`external_id`); o que já tinha entrado pelos PDF é reconhecido por instante +
  valor e ligado em vez de duplicado.
- **Posições vendidas**: cada leitura traz a carteira inteira, por isso a app
  considera só o snapshot mais recente de cada corretora — um instrumento que
  desapareça deixa de contar, em vez de ficar como posição fantasma.
- **Câmbio**: a API não o devolve nas posições, mas dá o valor na moeda do
  instrumento e em euros; a app deriva-o da divisão (em GBX dá ~87, igual ao que
  os extractos traziam).
- A importação de PDF continua a existir para meses antigos.

## Banco ligado (despesas automáticas)

As despesas podem entrar sozinhas via **Enable Banking** (modo gratuito "restricted
production", pensado para ligar as próprias contas). O GoCardless/Nordigen deixou
de aceitar registos novos em Julho de 2025.

1. Criar conta em https://enablebanking.com/cp/ (self-serve, grátis).
2. **Applications → New application**: escolher ambiente **Production** (atenção:
   *Sandbox* só dá acesso a bancos falsos — BBVA de teste e "Mock ASPSP" — e o
   ambiente não se troca depois, obriga a registar outra aplicação), tipo de
   acesso AIS, e gerar/carregar um certificado auto-assinado — o painel dá a
   chave privada (`.pem`) para descarregar. Guardar em `backend/enablebanking.pem`
   (chmod 600). Para confirmar em que ambiente ficou: `GET /api/banking/status`
   devolve `app.environment` e avisa em `warning`.
   Em **Redirect URLs** pôr `https://localhost:3043/expenses` — produção não
   aceita `http`. Essa porta é servida por `backend/callback_https.py`, que só
   reencaminha para `http://localhost:3001` com o código que o banco anexa.
   Precisa de certificado local (uma vez):
   ```
   brew install mkcert && mkcert -install        # pede a password do Mac
   cd frontend && mkcert -cert-file certs/localhost.pem \
                         -key-file certs/localhost-key.pem localhost 127.0.0.1 ::1
   ```
   Sem `mkcert -install` continua a funcionar, mas o browser avisa uma vez que o
   certificado não é conhecido.
3. Na aplicação, carregar em **"Activate by linking accounts"** e ligar a conta do
   Revolut — é isto que activa a aplicação no modo gratuito restrito.
   **Cada conta tem de ser ligada aí**: no modo restrito a API compara as contas
   que o banco devolve com as que estão ligadas à aplicação e retira as outras.
   Para juntar a Caixa Geral de Depósitos (ou outro banco), carregar outra vez
   em "Activate by linking accounts" e ligar essa conta, e só depois usar
   "ligar outro banco" no cartão do Banco.
4. Pôr em `backend/.env`:
   ```
   ENABLEBANKING_APP_ID=<id da aplicação>
   ENABLEBANKING_KEY_PATH=enablebanking.pem
   ```
5. Reiniciar o backend e ir a **Gastos → Orçamento → Banco → escolher banco**.
   Aprovar no site do banco; ao voltar (com `?code=…` no endereço) a app conclui
   a ligação sozinha e importa logo os 90 dias que o banco expõe. Se o regresso
   falhar, o cartão tem uma caixa para colar o endereço a que o banco devolveu.

Categorias: há regras fixas para as lojas conhecidas, e o que sobra em "Outro"
vai uma vez à IA (trabalho `lojas_banco`, 09:45) e fica guardado em
`merchant_rules`. Corrigir a categoria de uma despesa do banco cria uma regra
`manual` que manda sobre tudo o resto e arruma as despesas iguais que já lá
estavam — **só quando ele marca a caixa** "pôr também os outros movimentos de…"
no editar gasto (`apply_to_similar`, desligada por omissão). Era automático, e um
pagamento à associação de estudantes que desta vez era Saúde levava todos os
outros da associação atrás.

**A mesma loja tinha duas identidades, e por isso a correcção não pegava.** A
Caixa prefixa cada linha com o tipo de operação e corta o resultado aos 21
caracteres: `COMPRAS C.DEB INTER F` e `Inter Figueira Da Foz` são a mesma bomba
do Intermarché, e ele teve de as corrigir uma a uma — pior, corrigiu-as para
categorias diferentes. Duas coisas resolvem isto:

- **o prefixo da operação não faz parte do nome da loja** (`COMPRAS C.DEB …`,
  `COMPRA …`). O `CAR WAL CRT DEB …` fica de fora de propósito: o tipo do
  movimento lê-se da descrição inteira e mexer nela punha o carregamento do
  Revolut a contar como gasto outra vez;
- **um nome cortado encontra a loja inteira** (`bank_categories._por_prefixo`):
  o corte da Caixa cai a meio da palavra, por isso uma chave que seja prefixo da
  outra é a mesma loja. Mínimo de 6 caracteres — "cont" apanhava o Continente e
  a Conad — e ganha a chave mais comprida, com as correcções dele à frente das
  da IA. Nas 10 descrições onde isto pega (`mcdonal` ↔ McDonald's, `vodafo` ↔
  Vodafone, `carrefo` ↔ Carrefour, `apple c` ↔ apple.com/bill) não há um único
  falso positivo, e `INTERSP` (Intersport) não se mistura com `INTER F`.

**No MB Way a loja é o número de telefone.** A chave tirava os números, por isso
`Trf Mbway 963XXX836` (o ginásio) e `Trf Mbway 927XXX207` (um amigo) eram a mesma
"loja", e corrigir uma mudava todas. A chave passa a ser `mbway 963xxx836` — o
número com o meio tapado, como a Caixa o mostra, e o mesmo quando vem inteiro.
Corrigir a do ginásio para Subscrições arruma as anteriores e as que vierem, e
não toca nas dos amigos. As regras dele vêem-se, mudam-se e apagam-se em **Gastos
→ Banco → as tuas regras** (`/api/banking/rules`); ao editar um movimento do
banco a página diz que os iguais vão atrás.

**Noite** (`nightlife`) é a categoria de sair à noite — discotecas, clubes, bares
à noite. Os bares e clubes saíram de Entretenimento. Nos envelopes vive com o
Entretenimento (migração `_migrate_categoria_noite`, só enquanto não houver gastos
nela).

Para passar as regras que já existem à régua nova:
`python scripts/arruma_regras_de_loja.py --aplicar`. Junta as que ficaram
iguais, e entre duas correcções dele da mesma loja fica **a mais recente** — é a
mesma regra de desempate da sincronização dos Reminders.

O Revolut só entrega o histórico **completo nos primeiros 5 minutos** a seguir à
autorização; passado isso são 90 dias. Por isso a ligação sincroniza logo 2 anos
nesse instante. Pede-se o consentimento máximo que o banco dá (180 dias no
Revolut) e a app avisa 14 dias antes de caducar, com botão para renovar.

**Cada banco expõe uma janela de histórico diferente, e não a anuncia.** O
Revolut aceita dois anos; a **Caixa Geral de Depósitos recusa tudo o que passe
dos 90 dias** — e recusa o pedido *inteiro* com um 422
(`WRONG_TRANSACTIONS_PERIOD`) em vez de devolver o que tem. Como a ligação nova
pede 730 dias de propósito (para apanhar a janela dos 5 minutos do Revolut), a
CGD ficou **ligada com zero movimentos** e o erro só aparecia no log. Agora
`openbanking.transacoes` encolhe o pedido até o banco o aceitar (730 → 365 → 180
→ 90 → 30 → 7) e guarda a janela que resultou por conta, porque cada tentativa
gasta uma das ~4 leituras diárias que o banco permite.

**Zero contas numa sessão válida é o modo restrito, não uma autorização falhada.**
No modo gratuito a API compara as contas que o banco devolve com as que estão
ligadas à aplicação no painel e retira as outras — a sessão vem bem, vazia. E o
código do banco é de **uso único**: como a app conclui sozinha ao voltar, colar o
mesmo endereço a seguir dá sempre `WRONG_AUTHORIZATION_CODE`, que não tem nada a
ver com o problema. As duas coisas passaram a ter mensagem própria; a segunda
nem chega a ser enviada.

Outros cuidados já tratados:
- **Moedas**: as contas em PLN/GBP são convertidas a euros à taxa do BCE do dia
  do movimento (`fx_historico.py`); a nota guarda o valor original. Sem taxa
  fiável o movimento não entra.
- **Limite de pedidos**: o banco só deixa ler cada conta ~4x/dia sem o
  utilizador presente — há uma folga mínima de 5h entre leituras (`force=true`
  quando é ele a carregar no botão).
- **Apagar fica apagado**: uma despesa do banco apagada vai para
  `bank_ignored_tx` e não volta na sincronização seguinte.
- **Transferências dele para ele** (topups, envios para si próprio) e
  movimentos de 0€ não entram.

Depois disso o trabalho `sync_banco` corre todos os dias às 09:30. O banco só
expõe ~90 dias de histórico, mas cada sincronização grava na base local — o
histórico fica permanente. Movimentos que já tinham vindo dos extractos manuais
são reconhecidos (mesmo dia + mesmo valor) e ligados em vez de duplicados.

O consentimento caduca (PSD2, até 90-180 dias conforme o banco); a app mostra
quantos dias faltam e marca a ligação como `expirado` quando o banco recusa.

## Relógio Garmin (sono medido em vez de adivinhado)

O sono era **adivinhado** pelo buraco de actividade no Mac (`knowledgeC.db` ou as
paragens do portátil), com deitar = última actividade + 45min. Esse palpite
alimentava as correlações, as anomalias, o planeador e até a hora a que os
trabalhos diários correm (`scheduler.hora_de_acordar`). Com um Forerunner 70 no
pulso, passa a ser medição: fases, pontuação, HRV nocturna, body battery, stress,
frequência cardíaca em repouso e os treinos.

A API oficial da Garmin não serve — o programa de developers exige uma entidade
legal e recusa uso pessoal. Usa-se a biblioteca `garminconnect`, que faz o mesmo
login que a app Android.

**O login é a única parte perigosa.** O limite de pedidos da Garmin é no login, é
por conta (mudar de rede não safa) e bloqueia 48 horas. Por isso:

1. `python scripts/garmin_login.py` corre **à mão, uma vez**. Pede email, password
   e o código de verificação se houver, e grava o token em `~/.garminconnect`.
   A password não fica em lado nenhum — nem no `.env`.
2. O backend só carrega esse token (`garmin_api.cliente()` cria o cliente **sem**
   credenciais, para não haver forma de tentar um login novo em ciclo).
3. Se o token expirar, o trabalho falha com a mensagem certa e avisa uma vez por
   dia; é preciso correr o script outra vez.

`.env`: `GARMIN_SYNC=1` (0 desliga) e `GARMIN_TOKENS_DIR` (por omissão
`~/.garminconnect`).

O trabalho `sync_garmin` corre de **15 em 15 minutos**, mas quase sempre não faz
nada: o relógio não tem Wi-Fi e só há dados novos depois de ele passar pelo
telemóvel, por isso a primeira coisa é perguntar *quando é que isso aconteceu
pela última vez* — um pedido só (`lastUsedDeviceUploadTime`). Se o carimbo não
mudou, acaba ali; se mudou, vai buscar tudo. De 6 em 6 horas lê na mesma, porque
a prontidão e a idade de fitness são calculadas do lado da Garmin e mudam sem o
relógio sincronizar.

Resultado: **não é preciso carregar em Sincronizar na app**. Os dados aparecem
poucos minutos depois de chegarem à Garmin. O botão fica para quem não quer
esperar. Cada passagem trata hoje, ontem e os dias em falta da última semana; é
tudo upsert por data, correr duas vezes não duplica.

Onde ficam os dados: `garmin_days` (uma linha por dia, com colunas nomeadas para
o Perguntar poder escrever SQL sobre elas), `garmin_activities` (treinos) e
`garmin_series` (stress, body battery e FC ao longo do dia, em JSON — guardado
desde já para cruzamentos futuros sem ter de re-sincronizar).

**Precedência do sono**: `manual` > `garmin` > `power` > `auto`. Uma noite que ele
escreveu à mão nunca é tocada; um palpite do Mac é substituído quando chega a
medição. O `reconcile` (que corrige noites pela paragem do Mac) passa ao lado das
noites `garmin`.

### A página do Sono já não se preenche à mão

Deixou de haver "Registar Sono": o botão, o formulário e o "estimar pelo uso do
PC" saíram da página. As noites entram sozinhas — pelo relógio, ou pelo palpite
do Mac quando ele não o levou ao pulso — e a página passou a ser só de leitura.
Os endpoints de escrita (`POST/PUT/DELETE /api/sleep`) ficam, porque outras
partes da app usam-nos.

A **qualidade 1-5 de estrelas desapareceu**: mostra-se a pontuação do relógio,
0-100 (a de 12 de Agosto foi 74). É ela que dá a cor da barra de cada noite no
gráfico — vermelho abaixo de 60, verde acima de 80 — e as noites sem relógio
ficam roxas, para não parecerem uma noite julgada. O cartão da qualidade passou a
ser a média das pontuações medidas, e diz de quantas noites veio.

**A noite está aberta na própria página**, não atrás de um clique: à esquerda vê-se
tudo o que o relógio mediu nela — fases, o que o corpo pedia, despertares, sestas,
stress a dormir, respiração, oxigénio, temperatura da pele, HRV, frequência em
repouso, Body Battery ao acordar e a prontidão da manhã, mais a frase da Garmin
traduzida ("noite reparadora"). Numa noite sem relógio, diz-se que o número é a
estimativa pelo uso do Mac em vez de mostrar caixas vazias.

À direita, **as noites são uma linha cada**, das 18h da véspera à meia-noite
seguinte: vê-se a que horas se deitou, quanto durou, e — quando o relógio esteve
no pulso — como a noite foi por dentro, com as fases a colorir a própria barra. Clicar numa muda a que
está aberta. A lista de "entradas recentes" e o gráfico de barras que estavam aqui
mostravam as mesmas horas duas vezes e nenhum deles dizia isto.

Nos números, a etiqueta fica à esquerda e o valor à direita, na mesma linha (o
estilo das faixas de stress). Com a etiqueta por cima do valor ocupava-se o dobro
da altura para dizer o mesmo — e é por isso que o painel da noite cabe inteiro.

**As sestas contam.** Em 14 de Agosto foram 7h15 na cama e mais **2h24** ao fim
da tarde, e a página dizia só as 7h15 — a sesta não entra no `sleep_hours` da
noite. Agora tem cartão próprio (média e em quantos dias), a média das noites
diz também quanto dá **com as sestas**, e cada uma aparece no painel da noite com
a hora, a duração e o que devolveu ao Body Battery. O `nap_min` do dia só sabe o
total: a hora de cada sesta vem dos eventos do body battery
(`garmin_series.events_json`), e é por isso que `GET /api/garmin/history` passou
a trazer `naps` além de `nap_min`.

A sesta fica sempre no dia em que a Garmin a contou (o dia em que ele acordou),
para o cartão, o painel e a linha dizerem todos o mesmo. **A página do relógio
tem o mesmo**: "A noite passada" ganhou o terceiro número grande (a sesta) e uma
linha por sesta com a hora, em vez do total mudo que lá estava. O sono **com a
sesta** vai no cabeçalho do painel, ao lado das horas da noite: ali dentro, uma
linha de texto a mais é a diferença entre a coluna caber e "os números do dia"
passarem a rolar — foi o que aconteceu à primeira.

**A lista das noites deixou de ser um mostrador de 24h**: cada linha vai das 18h
da véspera à meia-noite seguinte, **30 horas**. Com as 24h do costume a sesta das
18:17 transbordava e dava a volta ao mostrador — aparecia no princípio da linha,
*antes* da noite que tinha acontecido horas antes dela. Com 30 horas, a noite
está sempre na primeira metade e as sestas do dia a seguir a ela, que é a ordem
em que aconteceram. O gráfico do **Ritmo** continua nas 24h de 18h a 18h: ali a
pergunta é a hora a que ele se deita, e não há sestas.

**O painel da noite cabe sem rolar e sem sobrar**, que são dois problemas
seguidos e não um: as medidas estão a **duas colunas** (com uma coluna só eram
dez linhas e transbordava num portátil) e as medidas **repartem a altura que
sobra** (`content-between`, como os painéis do relógio), senão num ecrã alto
ficava meio painel vazio por baixo. **Uma medida por linha** e o valor encostado
à direita — a duas colunas, os números ficavam uns a meio do painel e outros na
ponta, e o "0" dos despertares aparecia desalinhado de tudo o resto. As fases
são a única coisa a duas colunas, como sempre foram.

Três números grandes lado a lado (dormiu, pontuação, sesta), e por baixo a linha
que os põe em contexto: o sono **ao todo** contando a sesta, e quanto essa noite
fugiu ao **costume dele** — a mediana das noites medidas do período, que só
aparece a partir de três noites. Um "7h15" sozinho não diz se foi muito ou pouco.

### A secção Análise: as noites em conjunto

As fases estavam medidas e não eram usadas para nada — via-se a noite de ontem e
mais nada. A terceira secção da página do Sono (`GET /api/sleep/analysis`, que é
`garmin_insights.estatisticas_do_sono`, para a régua da app ser uma só) responde
a três perguntas:

- **de que é feita uma noite dele** — mediana da fatia de cada fase, com a faixa
  típica de adulto ao lado (profundo 13–23%, leve 44–55%, REM 21–31%). É a única
  comparação da app que não é com o histórico dele, e diz-se isso;
- **o que anda junto com a pontuação** — Spearman entre a pontuação da noite e as
  fatias, as horas, a eficiência, os despertares, a hora de deitar, o stress a
  dormir e a respiração. Passa com `p ≤ 0,05` e `|ρ| ≥ 0,3`; **o que foi testado e
  não deu fica escrito**, como no LoL;
- **as noites boas contra as más** — mediana de cada medida nas noites acima de 80
  e abaixo de 60. Não é um teste, são dois grupos lado a lado, e só se mostra com
  pelo menos três noites de cada lado.

**O que este modelo não mede**, e portanto nunca vai aparecer: andares subidos e
elevação (não tem barómetro), limiar de lactato, Endurance Score, Hill Score. E
o estado de HRV e a prontidão só existem depois de ~19 noites com o relógio no
pulso — até lá a página diz quantas faltam em vez de mostrar caixas vazias.

### Saídas à noite, e se bebeu

`night_outs` (uma linha por noite em que saiu, `drank` 1/0; sem linha = ficou em
casa, que é o costume, por isso não se pergunta). `date` é o dia em que a noite
**começou** — sábado à noite é sábado — e a noite de sono que ela afecta é a do
`GarminDay` de date+1. Marca-se com 🌙 Saí / 🍺 Bebi no cabeçalho do cartão "Sono
desta noite" do Dashboard (a noite de ontem; uma linha a mais punha a coluna a
rolar) e no cabeçalho da noite aberta na página do Sono, para qualquer noite para
trás. Na lista das noites aparece o ícone ao lado da data.

Um gasto na **Noite** entre as 18h e as 6h da manhã seguinte acende o "Saí" a
verde como pista — **nunca marca sozinho**: pagar a entrada a um amigo não é ter
saído. Na Análise do Sono, "Depois de beber" compara a noite seguinte com as
noites em casa (medianas; Mann-Whitney só a partir de 8 de cada lado). As saídas
sem beber ficam fora dos dois grupos: deitar às 4h sóbrio é outra pergunta.

"Bebi" abre ali mesmo três níveis (`drink_level`: 1 pouco, 2 médio, 3 muito), no
próprio cabeçalho e não num menu por cima — os dois cartões onde vive têm
`overflow-hidden` e cortavam-no. As noites antigas ficam com o nível a NULL.

### O gym marca-se pelo relógio

Um treino de ginásio no relógio (`garmin_sync.TIPOS_DE_GINASIO`, ≥15 min) marca
o hábito cujo nome diga gym/ginásio nesse dia, com a hora a que acabou e a nota
"pelo relógio". Cada treino passa por aqui **uma vez** (`garmin_activities.habit_checked`):
um gym desmarcado à mão não volta na sincronização seguinte. Os treinos vinham
só da última semana; a primeira sincronização depois disto vai buscá-los todos
desde o primeiro dia do relógio (`CHAVE_TREINOS_TODOS`), e é isso que marca o
gym dos dias para trás — o de 9 de Setembro nem estava na base.

### Health Snapshot: só existe em GraphQL

Os dois minutos parado que ele grava no relógio **não são uma actividade** e não
estão em nenhum endpoint REST: `activitylist-service` devolve zero e todos os
caminhos `/wellness-service/wellness/healthSnapshot*` dão 404. Saem só pelo
gateway GraphQL do Garmin Connect:

```
query{healthSnapshotScalar(startDate:"2026-08-10", endDate:"2026-08-12")}
```

Vale a pena porque traz **HRV (RMSSD e SDRR) sem esperar pelas 19 noites** de
linha de base, mais FC, SpO2, respiração e stress dos mesmos dois minutos. Fica
em `garmin_snapshots`, uma linha por medição, e as medidas vêm numa lista de
resumos (`summaryTypeDataList`) em vez de campos próprios.

### A leitura do dia (secção "Leitura")

A página do relógio tem três secções: **Leitura** (a análise, e é a que abre, com
os cinco cartões e a linha do dia por cima), **Medições** (a frequência cardíaca,
a noite, o stress, a bateria, a semana) e **Histórico** (as séries, o corpo e os
treinos).

Na Leitura não há uma regra por métrica. Há **uma** régua aplicada a todas por
igual: mediana e desvio absoluto mediano dos últimos 90 dias dele, e o desvio
robusto de cada dia contra isso (`garmin_insights.METRICAS`). Acrescentar uma
métrica é acrescentar uma linha na tabela, não escrever mais um `if`. E a régua é
dele: 5h30 num histórico de 8h é notícia, num histórico de 5h30 não é. Mediana e
MAD em vez de média e desvio-padrão, para uma noite de 14h não calar as noites
curtas que venham a seguir.

Uma métrica pode ser **uma conta em vez de uma coluna** (`Metrica.calcula`), e é
por isso que as fases da noite entram como **fatia** e não em minutos: numa noite
de 9h o sono profundo é maior em minutos sem a noite ser melhor, e a duração já é
medida à parte. Estão na régua a fatia de profundo, de leve e de REM, o tempo na
cama passado a dormir, os despertares, a **hora de deitar** (numa escala de 18h a
42h, senão a mediana de quem se deita às 23h e à 01h dava meio-dia), o que a noite
carregou de bateria, o tempo em repouso, os minutos de intensidade e a prontidão.

Cada métrica leva um **piso de variação** (`mad_min`): quem quase nunca acorda a
meio da noite tem MAD zero, e sem piso um único despertar virava "muito acima do
costume" — a régua ficava tão apertada que media ruído.

Só há três coisas fora dessa régua, e por boas razões:
- **distâncias a alvos que não são meus** — o sono que o corpo pediu naquela noite
  e os 75 minutos de exercício intenso por semana vêm do relógio; aqui só se faz
  a subtracção;
- **o sinal de doença** — frequência em repouso acima e HRV abaixo dois dias
  seguidos, que é o padrão conhecido de infecção a incubar e que o relógio não dá;
- **as correlações**, que são correlação de Spearman com teste de significância
  (`p ≤ 0,05`, `|ρ| ≥ 0,3`, mínimo 14 dias) entre o relógio e o resto da app —
  ecrã na hora antes de deitar, jogos de LoL, horas de código, gasto do dia. Nada
  disto é uma conclusão escrita à mão: ou sai dos dados ou não aparece. Há pares
  **dentro do próprio relógio** (`_do_relogio`), porque "a que horas te deitas
  contra o sono profundo que tens" é a pergunta mais accionável de todas — e é
  outra pergunta que a régua dos desvios não responde.

**O modelo local não toca nos números.** Tentou-se deixá-lo reescrever os factos
e o llama3 inverteu um condicional: "com o alvo cumprido a idade descia de 21
para 18" saiu como "isso fez a idade descer de 21 para 18" — o contrário do que
os dados dizem. Ficou com o que faz bem e não pode estragar: escolher o **tema**
do dia de uma lista fechada (e só quando não há sinal forte, porque a prioridade
de "podes estar a adoecer" não se põe a votos) e escrever uma **frase de ligação
onde os algarismos são proibidos** — se vier um dígito, a frase é deitada fora.

Com o Ollama desligado continua a haver leitura, feita só das regras. A resposta
do modelo fica em cache com o conteúdo dos factos como chave, por isso morre
sozinha quando o dia muda de facto.

### A frequência cardíaca do dia inteiro

O relógio mede a frequência cardíaca **de 2 em 2 minutos** — são ~700 leituras
por dia — e elas já estavam guardadas (`garmin_series.hr_json`, vinham do
`get_heart_rates`) sem nada as mostrar. Agora são um gráfico na secção Dia, com o
eixo do tempo a sério: um intervalo com o relógio fora do pulso ocupa o espaço
que ocupou, e buracos de mais de 15 minutos **partem a linha** em vez de a ligar
por cima do vazio. Os treinos aparecem sombreados por cima da curva, e a linha
tracejada é a frequência em repouso desse dia.

As **zonas** vêm da própria conta (`get_heart_rate_zones`, perfil `DEFAULT`):
pisos 98/118/137/157/176 e máxima 196. Não é por dia — muda quando ele mexe no
perfil — por isso é pedida uma vez por mês (`garmin_sync.CHAVE_ZONAS_FC`, cache
de 30 dias) e o router só lê da base, como o resto da página. O tempo em cada
zona sai das leituras: cada amostra vale o tempo até à seguinte, **com tecto de 5
minutos**, senão um buraco de seis horas contava como seis horas na zona da
última leitura antes de ele o tirar do pulso. O `restingHeartRateUsed` que vem
com as zonas é o do perfil (87) e está velho — o repouso mostrado é o medido no
dia (53).

No histórico há a faixa **mín–máx de cada dia** com a linha do repouso por dentro,
que é onde se vê um dia de treino sem ele esconder o resto.

### A linha do dia: sestas e movimento que não estavam em lado nenhum

Uma **caminhada de 25 minutos** aparecia na app da Garmin e não na app dele:
`get_activities_by_date` devolve **vazio** nesses dias, porque aquilo não é um
treino gravado — é **Move IQ**, o que o relógio detecta sozinho, e vive noutro
endereço (`get_all_day_events`). Fica em `garmin_activities` com `auto=1` e um id
feito da hora de início, e a tabela dos treinos mostra-a marcada como
"detectado". Cuidado com o campo `duration`: no Move IQ vem em **minutos**, e nas
actividades gravadas o mesmo nome vem em segundos.

A **hora a que ele acordou e a sesta da tarde** também não estão em campo nenhum
do sono. Saem de `get_body_battery_events`, que é o que a Garmin usa para
explicar as subidas e descidas do Body Battery: `SLEEP` (01:30, 5h29, +60) e
`NAP` (11:28, 1h18, +8). Guardam-se em `garmin_series.events_json` e são a "linha
do dia" da página: uma barra de 00:00 a 24:00 com os blocos, e as mesmas sombras
por cima da curva da frequência cardíaca — é o mesmo dia contado duas vezes, por
isso é a mesma lista.

### A leitura do dia é escrita pelo agente, com os números presos

A leitura era uma frase do modelo local sem algarismos, e com poucos dias medidos
não havia régua nenhuma: a página mostrava um facto e mais nada. Mudaram duas
coisas.

**Factos que não precisam de histórico** (`kind: "dia"`): a sesta, o movimento
detectado, as fases da noite, o body battery de início e fim, e o tempo em
repouso contra o tempo em stress. Não competem com o que fugiu ao padrão —
aparecem por baixo, sob "o dia, contado" — mas são o que impede a leitura de
estar vazia enquanto o histórico não chega aos 8 dias.

**O texto passa a ser do agente** (`feature="relogio"`, tecto de 8/dia, cache de
7 dias com os factos como chave), e não do modelo local, que não serve para isto.
A trela é a mesma de sempre: **todo o algarismo que ele escreva tem de existir
nos factos ou no contexto** — se aparecer um número que ninguém mediu, o texto é
deitado fora inteiro e a página cai na versão das regras. O contexto leva o que a
app sabe do mesmo dia (ecrã antes de dormir, jogos, código, passos, calorias,
prontidão) e diz-lhe quantos dias medidos existem, para ele não falar do "teu
costume" quando ainda não há costume nenhum.

**As duas listas de factos têm ambas rótulo** — "o que saiu do costume" e "o dia,
como foi". Só a segunda tinha, e a divisão não se percebia: em cima está o que foi
comparado com alguma coisa (o histórico dele ou um alvo do relógio), em baixo o
dia como foi, que não se compara com nada. A Leitura também não faz a página
rolar: os dois painéis esticam até ao fundo da janela e o scroll é dentro deles,
como nas Medições — daí o `shrink-0` em cada bloco de texto lá dentro.

**São pontos, não um parágrafo.** O texto corrido não se lia — 3 a 4 pontos de no
máximo 14 palavras, um por linha, uma ideia cada. O agente nem sempre obedece
(manda uma introdução antes, usa "•" ou numera), por isso `_pontos()` tira o
marcador, deita fora o que não for ponto e, se vier mesmo um parágrafo, parte-o
em frases — a página nunca recebe um bloco de texto.

No meio disto apareceu um erro antigo: `_horas_de_codigo` somava a tabela do
WakaTime toda, que reparte o dia por projecto, linguagem, editor, máquina e
dependência — **um dia de 8h34 dava 119h51**. Só `kind='project'` conta. Isso não
afectava só o texto: alimentava as correlações do relógio com o resto da app.

### O que o Garmin Connect mostrava e a app não

Estes números já estavam todos na base — faltava-lhes sítio na página:

- **as quatro faixas de stress** do dia (repouso 12h28, baixo 6h47, médio 1h29,
  alto 36min, média 26), que é como a app da Garmin conta o dia;
- **o que carregou a bateria do corpo**: 93 ao acordar → 25 ao fim, +73 e −81,
  e dentro disso `+60 do sono` e `+8 da sesta` — esse detalhe por bloco vem dos
  eventos, não do resumo do dia, e também aparece na linha do dia;
- **a semana**, como o widget do Garmin Connect: passos somados, distância e
  **média por dia** dos sete dias até ao dia que se está a ver (6 381 passos,
  5,4 km, 3 191/dia). O `/history` passou a devolver distância, calorias e
  minutos de intensidade para isto não precisar de outro pedido.

### O Histórico: os dias em conjunto, cada gráfico com a sua régua

O Histórico mostrava quatro coisas — a semana, barras de horas de sono, HRV e
frequência em repouso a partilhar o mesmo eixo, e a faixa mín–máx da frequência.
Tudo o resto que o relógio mede **todos os dias** (as quatro faixas de stress, o
body battery, os passos contra a meta, os minutos de intensidade, a prontidão, as
fases da noite) só existia para **um** dia de cada vez, nas Medições. Estava
guardado e não tinha vista nenhuma ao longo do tempo.

**O HRV estava a ser lido ao contrário.** Uma linha de valores nocturnos crus não
diz nada: uma noite varia 15-30% por ruído normal, e o que se lê é a **média
móvel de 7 dias contra a faixa pessoal** — é assim que o próprio relógio decide o
estado. Agora a noite são pontos e a linha é a média; e o HRV saiu do eixo da
frequência em repouso, onde estava por os números serem parecidos **por acaso**
(~52 ms e ~54 bpm).

**Todos os gráficos levam a mesma régua** (`GET /api/garmin/baselines`,
`garmin_insights.regua`): a faixa é `mediana ± 1,4826·MAD`, que é de propósito a
mesma fronteira do `_desvio` — **estar fora da faixa é exactamente ter |z| > 1**,
por isso o gráfico e os factos da Leitura nunca discordam sobre o mesmo dia.
Abaixo de `MINIMO_BASELINE` noites não se desenha faixa nenhuma: diz-se quantas
faltam, em vez de inventar uma régua a partir de três dias. No HRV, a faixa do
relógio ganha à da app **assim que existir** — hoje vem a NULL, que é o que
acontece antes das ~19 noites de linha de base.

Duas armadilhas que custaram a apanhar:

- **a média móvel do primeiro dia da janela precisa dos 6 dias anteriores a ela.**
  Sem os ler, o gráfico começa sempre com um buraco e ninguém repara, porque o
  resto da linha está lá. O `/history` lê `days + 6` e devolve só os `days`;
- **com valores todos iguais o MAD dá zero** e o `_desvio` cai no seu recurso dos
  15% da mediana — deixa de ver o que quer que seja. Foi um teste com doze dias
  idênticos que o mostrou: a régua precisa de ruído para ter largura, e é por isso
  que cada métrica leva um piso de variação.

Os dias com a frequência acima e o HRV abaixo **dois dias seguidos** aparecem
marcados no gráfico da frequência. É a regra do sinal de doença, que passou a
viver num sítio só (`_fora_do_normal`) em vez de existir uma cópia para a página
e outra para a Leitura.

Os minutos de intensidade são a **soma dos 7 dias** contra o alvo de 150, com o
vigoroso a contar a dobrar, porque é assim que a Garmin os conta — um dia sozinho
não diz nada sobre um alvo semanal.

O painel dos sete dias está no **fim** dos gráficos: em cima, a linha da grelha
ficava com a altura de um gráfico e três linhas de texto a boiar nela. E os
gráficos aqui têm **altura fixa** em vez de `flex-1`: são dez painéis numa grelha
`auto-rows-min`, e a esticar cada linha ficava com a altura do painel mais alto.

### A página do relógio cabe no ecrã, e é por isso que está partida em duas

Com tudo na mesma vista — cartões, linha do dia, e nove painéis — o gráfico da
frequência cardíaca ficava com 99px de altura, ilegível. A solução não foi dar
scroll: foi separar. A **Leitura** abre com os cartões e a linha do dia por cima
(o estado do dia), e as **Medições** levam só os painéis, em três linhas que
dividem a altura da janela, com a frequência cardíaca a levar a maior. Nenhuma
das duas faz a página crescer.

São **quatro painéis grandes**, não nove pequenos. À esquerda, dois gráficos do
**mesmo tamanho** (duas linhas iguais, ambos a duas colunas): a frequência
cardíaca em cima, o Body Battery e o stress em baixo — nada de números a roubar
largura ao gráfico. À direita, o que se lê em números: a noite passada em cima,
com a altura que o conteúdo pedir (são oito medidas — espremidas obrigavam a
rolar lá dentro), e "os números do dia" em baixo, com a bateria (93 → 25, +73,
−81, do sono +60, da sesta +8) e as quatro faixas de stress.

Ao mexer nisto:
- a página tem `lg:h-[calc(100dvh-4rem)]` (a altura da janela menos o padding do
  shell). Um `h-full` resolveria contra um pai que cresce com o conteúdo;
- os gráficos precisam de `h-0 flex-1` no contentor — com `h-auto` o Recharts
  mede um pai que ainda não tem altura e o gráfico fica achatado com espaço
  morto por baixo;
- **conteúdo de texto dentro de um painel leva `shrink-0`**. Sem isso o flex
  encolhe-o abaixo do que ele mede e corta-o *em silêncio*: o `scrollHeight`
  continua igual ao `clientHeight`, por isso nem sequer aparece scroll a
  denunciar o que ficou de fora;
- as colunas das Medições são 3, ou 4 quando há Health Snapshot;
- **a coluna da direita cabe por pouco** num portátil de 800px de altura: a
  noite (257px) mais os números (153px) mais os cabeçalhos enchem-na quase toda.
  Acrescentar uma linha de texto a qualquer um dos dois é a diferença entre caber
  e cortar — medir antes de acrescentar;
- por isso os passos, a distância, as calorias e os minutos intensos em "os
  números do dia" só aparecem **acima de 860px de altura de janela**
  (`[@media(min-height:860px)]:grid`): num ecrã grande enchem o painel que ficava
  meio vazio, e num pequeno não existem em vez de obrigarem a rolar.

As zonas de esforço aparecem com o intervalo de batimentos a que correspondem
("Z1 aquecimento 98–118"), porque "Z1" sozinho não diz nada a quem não treina
por zonas.

O estado da sincronização ("o relógio falou com o telemóvel às…") era uma linha
no fim da página a roubar altura ao gráfico; passou para o `title` do botão
Sincronizar. No telemóvel nada disto se aplica: volta tudo ao empilhado normal.
