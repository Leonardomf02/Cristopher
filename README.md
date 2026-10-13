# Cristopher

App pessoal para gerir o dia a dia: calendário, reminders, gastos, investimentos,
sono, relógio Garmin, LoL e mais umas coisas. Feita para mim, por isso muita
coisa assume o meu Mac, as minhas contas e os meus hábitos.

Backend em Python (FastAPI + SQLite), frontend em React + TypeScript + Vite +
Tailwind. Corre no Mac em desenvolvimento e numa NAS em produção.

## Correr localmente

Precisa de Python 3.12 e Node 20.

```bash
# backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # preencher o que se for usar

# frontend
cd ../frontend
npm install
```

Arrancar, em dois terminais:

```bash
cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8001
cd frontend && npm run dev
```

- App: http://localhost:3001
- API: http://localhost:8001/docs

A base (`backend/cristopher.db`) cria-se sozinha no primeiro arranque. As
migrações estão em `main.py` e correm sempre que o backend arranca.

### Arrancar sozinho no login (Mac)

```bash
./scripts/launchd/install.sh     # instala backend + frontend como LaunchAgents
./scripts/launchd/status.sh      # ver se estão a correr
./start.sh                       # reinicia os dois e abre o browser
./scripts/launchd/uninstall.sh
```

O backend arranca pelo `CristopherBackend.app`, porque é a única forma de lhe
dar Full Disk Access (Definições do Sistema → Privacidade e Segurança → Acesso
total ao disco). Sem isso não há Screen Time nem sono automático.

### Codespaces

O `.devcontainer` instala tudo. Depois é arrancar os dois comandos de cima (no
backend com `--host 0.0.0.0`) e abrir a porta 3001. O que depende do macOS não
funciona lá: tracker de apps, Screen Time, LoL ao vivo, actividade do VS Code e
Calendário/Reminders da Apple.

### Testes

```bash
cd backend && source venv/bin/activate && pytest
```

## O que há na app

**Hoje**
- Dashboard com duas vistas: Hoje (agenda, plano, sono, hábitos, como foi o dia) e Resumo (atalhos e revisão da semana).
- Calendário dia/semana/mês/ano, eventos fixos e flexíveis, tarefas repetidas, import/export do Calendário da Apple.
- Cronómetro de foco (Flow) com nota da sessão; a sessão entra no calendário quando pára.
- Planear Dia: a IA monta o dia a partir das tarefas e das horas de acordar/deitar medidas pelo relógio.
- Reminders sincronizados nos dois sentidos com o Reminders da Apple (listas, itens, ícone e cor).
- Perguntar: pergunta-se em português, a IA escreve o SQL e a app corre-o só em leitura.
- Pesquisa global e paleta de comandos (⌘K).
- Captura rápida por voz no iPhone ([docs/captura-rapida-ios.md](docs/captura-rapida-ios.md)).

**Trabalho**
- VS Code: ficheiros editados por projecto (pelo Local History do VS Code), horas do WakaTime e TODOs por projecto.
- Notas com pastas.

**Rotina**
- Hábitos com estatísticas e tipos de dia.
- Alimentação: três refeições com janela, score de comer a horas, suplementos e avisos.
- Sono: noites do relógio (ou estimadas pelo uso do Mac), sestas, análise das fases e saídas à noite.
- Relógio: leitura do dia, frequência cardíaca, stress, Body Battery, treinos e histórico com a régua de cada um.
- Screen Time do Mac e do iPhone, tracker de apps, médias por dia da semana e metas por categoria.
- Humor e diário, e perguntas sobre os dias que fugiram ao padrão.

**Dinheiro**
- Gastos: banco ligado (Revolut, Caixa), import de CSV/PDF, recibos com OCR, categorias automáticas.
- Separa gasto, transferência, entrada e estorno; só o gasto conta para os totais.
- Período por mês ou desde o salário, orçamento com envelopes, reembolsos de amigos, contas divididas, Klarna.
- Saldos das contas, gastos por cidade e viagens detectadas pelas despesas.
- Investimentos: carteira do Trading 212 pela API (ou pelos extractos em PDF), sinais diários com IA, planeador, mais-valias e avisos dos 365 dias.
- Deals: vigia OLX, Facebook Marketplace, StandVirtual e Vinted com exigências em campos (ano, km, potência, cor) e preço justo do que se procura.
- Wishlist.

**Lazer**
- LoL: jogos sincronizados pela Riot, métricas por jogo, duelo contra o jungler adversário, sugestão de picks, champ select e treinador durante o jogo.
- Spotify: curadoria de playlists pela IA a partir de uma lista colada ou de um CSV do Exportify.
- Histórias: temas explicados pela IA em três níveis.
- Viagens com sítios a visitar e gastos de cada uma.

**Outros**
- O que a app acertou (`/acertos`): previsões de várias partes da app contra o que aconteceu.
- Avisos por Web Push (PWA instalada no telemóvel) ou Telegram.
- Login opcional com password.
- Cópias de segurança diárias, com cópia cifrada para fora do Mac.

## Configuração

Tudo em `backend/.env`. O [`.env.example`](backend/.env.example) tem todas as
variáveis comentadas. Nenhuma é obrigatória para a app abrir; sem uma chave, a
parte que precisa dela fica desligada.

### IA

Três degraus, por esta ordem: agente principal do iaedu.pt (`AI_API_KEY`),
agente de reserva (`FALLBACK_AI_API_KEY`) e um modelo local no Ollama. Se um
falha, passa ao seguinte.

```bash
brew install ollama
brew services start ollama
ollama pull qwen3.5:9b
```

O modelo local faz o trabalho barato (categorizar gastos, ver a cor de uma mota
numa foto). Pesquisa web e SQL ficam sempre nos agentes. Sem Ollama a app
continua a funcionar.

### Banco (Enable Banking)

1. Criar conta em https://enablebanking.com/cp/ e uma aplicação em **Production**
   (Sandbox só tem bancos de teste e não se troca depois), acesso AIS.
2. Guardar a chave privada em `backend/enablebanking.pem` (`chmod 600`).
3. Redirect URL: `https://localhost:3043/expenses`. Essa porta é servida pelo
   `backend/callback_https.py`, que precisa de um certificado local:
   ```bash
   brew install mkcert && mkcert -install
   cd frontend && mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem localhost 127.0.0.1 ::1
   ```
4. No painel, "Activate by linking accounts" e ligar **cada** conta que se quer
   ver (no modo gratuito, as que não estão ligadas lá não aparecem).
5. `ENABLEBANKING_APP_ID` no `.env`, reiniciar, e em Gastos → Orçamento → Banco
   escolher o banco.

Sincroniza todos os dias às 09:30. O consentimento caduca (90 a 180 dias) e a
app avisa antes.

### Relógio Garmin

```bash
cd backend && source venv/bin/activate
python scripts/garmin_login.py
```

Corre-se uma vez, à mão. Guarda o token em `~/.garminconnect` e a password não
fica em lado nenhum. O backend só lê o token, porque repetir logins bloqueia a
conta 48 horas. Se o token expirar, a app avisa e é correr o script outra vez.

### Trading 212

Na app do Trading 212: Definições → API → gerar chave (só leitura chega).
`T212_API_KEY=chave:segredo`. Na primeira vez, em Investimentos → Trading 212,
usar "Trazer histórico completo".

### LoL

`RIOT_API_KEY` de developer.riotgames.com. Para preencher as métricas e os
duelos dos jogos antigos (demora, mas pode ser interrompido):

```bash
python scripts/preenche_metricas_lol.py --todos
python scripts/preenche_duelos_lol.py --todos
```

O champ select e o jogo ao vivo vêm do cliente do LoL aberto no Mac.

### Outras chaves

- `WAKATIME_API_KEY`: horas de código.
- `FMP_API_KEY`, `FINNHUB_API_KEY`: fundamentais e resultados das empresas ([links](backend/scripts/SETUP_KEYS.md)).
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`: avisos pelo Telegram.
- `BACKUP_OFFSITE_DIR` + `BACKUP_PASSPHRASE`: cópia cifrada (AES-256) para uma pasta sincronizada. Sem a frase não se envia nada.

### Permissões no Mac

- **Acesso total ao disco** para o backend (ou para o agente): Screen Time, sono estimado, ícones e cores dos Reminders.
- **Lembretes**: sincronização com o Reminders da Apple.
- **Calendários**: import/export do Calendário da Apple.

## Produção (NAS)

A app corre num contentor numa NAS QNAP (ARM de 32 bits). Uma imagem só: o
FastAPI serve a API e o build do React. Guia completo em
[DEPLOY-NAS.md](DEPLOY-NAS.md).

```bash
IMG=cristopher:vN ./build-nas.sh /tmp/x.tar
./deploy-nas.sh /tmp/x.tar
```

Depois importa-se na Container Station e muda-se a etiqueta no YAML. Etiqueta
nova sempre, senão a Container Station fica com a imagem antiga em cache.

- Os dados vivem em `/data` no contentor (base, recibos, cópias, tokens, chaves).
- `CLOUD=1` desliga o que só existe no Mac; `LOCAL_AI=0` porque não há Ollama para ARM de 32 bits.
- Com `CRISTOPHER_PASSWORD` é obrigatório `JWT_SECRET`.
- `nas-compose.yml` e `.env.nas` não vão para o git (ver [.env.nas.example](.env.nas.example)).

### Agente do Mac

Com a app na NAS, o que só o Mac vê (Screen Time, apps activas, champ select do
LoL, Reminders da Apple) chega por um agente que corre no Mac e envia para a
NAS. Instalação em [agent/README.md](agent/README.md).

## Estrutura

```
backend/
  main.py            app FastAPI, migrações e trabalhos agendados
  models.py          modelos SQLAlchemy
  schemas.py         schemas Pydantic
  routers/           um router por secção, tudo em /api
  ai.py              IA (agentes + modelo local)
  scripts/           login do Garmin, preenchimentos e arrumações da base
  tools/             pontes em Swift para o OCR e o Reminders (compilam sozinhas)
  tests/
frontend/src/
  App.tsx            menu e rotas
  api.ts             chamadas ao backend
  pages/             uma página por secção
agent/               agente do Mac para quando a app está na NAS
scripts/launchd/     arranque automático no Mac
docs/                captura rápida no iPhone
```

## Notas

- `cristopher.db`, `uploads/`, `.env`, chaves `.pem` e tokens nunca vão para o
  git. O repositório é público.
- Na NAS a base verdadeira é a de lá; a do Mac é uma cópia antiga.
- O `tsc --noEmit` tem erros antigos que não impedem o `vite build`.
