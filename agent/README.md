# Agente local do Cristopher (modo híbrido)

O backend do Cristopher corre na NAS e está sempre online. Mas o **Screen
Time** (knowledgeC), o **tracker de apps ativas**, o champ select do LoL e os
Reminders da Apple só existem no Mac. Este agente lê esses dados localmente e
empurra-os para o backend da NAS.

```
Mac (quando ligado)                          Cloud (sempre online)
┌─────────────────────────┐                  ┌──────────────────────────┐
│ app_tracker.py  ──────┐  │   POST (token)   │  /api/ingest/app-usage   │
│                       ▼  │ ───────────────► │  /api/ingest/screen-time │
│ push_local.py  (loop)    │                  │  → grava nas tabelas      │
│ screen_time_reader ───┘  │                  │    normais do Cristopher  │
└─────────────────────────┘                  └──────────────────────────┘
```

Quando o Mac está desligado, a web continua online com os últimos dados; ao
ligar, o agente volta a sincronizar. A ingestão é **idempotente** (upsert).

## Instalar

```bash
CRISTOPHER_CLOUD_URL=https://<NAS_HOST>:8443 \
INGEST_TOKEN=<o mesmo INGEST_TOKEN definido no backend da NAS> \
./install.sh
```

Depois dá **Full Disk Access** ao Python indicado pelo script (necessário para
ler o Screen Time): System Settings → Privacy & Security → Full Disk Access.

## Comandos

```bash
tail -f ~/.cristopher-agent/agent.log               # ver o que está a empurrar
launchctl unload ~/Library/LaunchAgents/com.cristopher.agent.plist   # parar
launchctl load   ~/Library/LaunchAgents/com.cristopher.agent.plist   # arrancar
```

## O que sincroniza

| Dado | Origem local | Endpoint |
|---|---|---|
| Screen Time (Mac + iPhone/iPad) | `screen_time_reader` (knowledgeC) | `/api/ingest/screen-time` |
| Apps ativas no Mac | `app_tracker` → BD local do agente | `/api/ingest/app-usage` |
| Champ select do LoL | cliente do LoL (LCU) | `/api/ingest/lol-champ-select` |
| Reminders da Apple (nos dois sentidos) | `apple_reminders` (EventKit) | `/api/ingest/reminders/*` |

Os Reminders são imediatos: o agente fica pendurado em `/reminders/wait` e
sincroniza no segundo em que alguma coisa muda nas Listas. `AGENT_REMINDERS=0`
desliga.

Variáveis opcionais: `PUSH_INTERVAL` (s, default 300), `PUSH_SCREEN_DAYS`
(default 3), `PUSH_USAGE_HOURS` (default 48), `AGENT_DB`.

> O WakaTime não passa por aqui: já é um serviço cloud e o backend puxa
> diretamente com a API key. O jogo ao vivo do LoL também não: depende do cliente
> aberto. Estes mantêm-se nos fluxos próprios.
