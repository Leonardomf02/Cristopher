# Como ativar fundamentals + earnings + Telegram

Três integrações opcionais. Sem elas o sistema continua a funcionar — só não tens P/E, ROE, earnings calendar, ou push notifications.

## 1. Financial Modeling Prep (fundamentals) — 3 min

1. Vai a https://site.financialmodelingprep.com/developer
2. Clica **Get Free API Key** → cria conta com email
3. Confirma email → copia a chave do dashboard
4. Free tier: **250 requests/dia**

## 2. Finnhub (earnings calendar) — 3 min

1. Vai a https://finnhub.io
2. **Get free API key** → cria conta
3. Confirma email → key visível no dashboard
4. Free tier: **60 requests/min**, sem limite diário

## 3. Telegram bot (notificações push) — 5 min

1. Abre Telegram → procura **@BotFather** → escreve `/newbot` → segue as instruções (escolhe nome, escolhe username terminado em `_bot`).
2. **Copia o token** (formato `123456789:ABCdefGhIjK...`).
3. **Manda qualquer mensagem ao teu novo bot** (ex: "olá") — isto é necessário para o bot saber o teu chat_id.
4. Abre no browser:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Substitui `<TOKEN>` pelo do passo 2. Vais ver JSON com `"chat":{"id": 123456789, ...}` — esse número é o teu chat_id.

## Onde meter as keys

Cria/edita `backend/.env`:

```
FMP_API_KEY=cole_aqui_a_chave_fmp
FINNHUB_API_KEY=cole_aqui_a_chave_finnhub
TELEGRAM_BOT_TOKEN=cole_aqui_o_token_do_bot
TELEGRAM_CHAT_ID=cole_aqui_o_chat_id
```

Reinicia o backend.

## Verificar que tudo funciona

```bash
# Status agregado
curl http://localhost:8888/api/investments/signals/data-sources

# Test push notification (devias receber no Telegram em ~2s)
curl -X POST http://localhost:8888/api/investments/signals/test-notify

# Cache state
curl http://localhost:8888/api/investments/signals/cache-stats

# Preview fundamentals + earnings
curl http://localhost:8888/api/investments/signals/preview-fundamentals | jq .as_prompt
curl http://localhost:8888/api/investments/signals/preview-earnings | jq .as_prompt
```

## Limpar cache (se quiseres forçar refresh)

```bash
# Limpar tudo
curl -X POST 'http://localhost:8888/api/investments/signals/cache-clear'

# Limpar só fundamentals
curl -X POST 'http://localhost:8888/api/investments/signals/cache-clear?prefix=fundamentals:fmp'
```

## TTLs aplicados

| Source | TTL | Razão |
|---|---|---|
| FRED macro | 6h | Series só publicam diariamente |
| FMP fundamentals | 24h | Só mudam em earnings filings |
| Finnhub earnings calendar | 4h | Refresca durante o dia |
| On-chain crypto | 30m | Mexe lentamente |
| Yahoo prices | sem cache (real-time prefer) | |
