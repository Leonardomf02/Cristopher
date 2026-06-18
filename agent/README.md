# Agente local do Cristopher (modo híbrido)

O backend do Cristopher corre na cloud (Oracle) e está sempre online. Mas o
**Screen Time** (knowledgeC) e o **tracker de apps ativas** só existem no teu
Mac. Este agente lê esses dados localmente e empurra-os para o backend cloud.

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
CRISTOPHER_CLOUD_URL=https://cristopher-api.duckdns.org \
INGEST_TOKEN=<o mesmo INGEST_TOKEN definido no backend cloud> \
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

Variáveis opcionais: `PUSH_INTERVAL` (s, default 300), `PUSH_SCREEN_DAYS`
(default 3), `PUSH_USAGE_HOURS` (default 48), `AGENT_DB`.

> LoL e VS Code/WakaTime não passam por aqui: o WakaTime já é um serviço cloud
> (o backend puxa diretamente com a tua API key) e o LoL depende do cliente
> aberto. Estes mantêm-se nos fluxos próprios.
