# Captura rápida no telemóvel (Atalhos do iOS)

Ditar uma frase e ela entra na app — sem abrir nada.

```
"gastei 12,40 no lidl"          → despesa (Lidl · 12,40€ · groceries)
"lembra-me de pagar a luz amanhã" → reminder com data para amanhã
"hoje foi um dia 8"             → humor do dia a 8/10
qualquer outra coisa             → reminder na lista por omissão
```

A IA interpreta a frase; se estiver indisponível, há um interpretador local por
regras (apanha valores, "lembra-me de…" e "dia N") para nunca falhar.

## Endpoint

```
POST http://<mac>:8001/api/ingest/capture
Header:  X-Ingest-Token: <INGEST_TOKEN do backend/.env>
Body:    {"text": "gastei 12,40 no lidl"}
```

Resposta: `{"ok": true, "kind": "expense", "summary": "Lidl · 12.40€ (groceries)"}`

Podes forçar o tipo com `{"text": "…", "kind": "expense|reminder|mood|note"}`.

## Receita do Atalho (iOS/iPadOS)

1. **Atalhos → novo atalho → adicionar acção → "Pedir entrada"**
   (tipo: Texto, pergunta: "O quê?")
2. **"Obter conteúdo de URL"**
   - URL: `http://<ip-do-mac-ou-tailscale>:8001/api/ingest/capture`
   - Método: `POST`
   - Cabeçalhos: `X-Ingest-Token` = o token do `backend/.env`
   - Corpo do pedido: `JSON` → campo `text` = *Entrada fornecida*
3. **"Obter valor do dicionário"** → chave `summary`
4. **"Mostrar notificação"** com esse valor (confirmação do que entrou)
5. No atalho: **Adicionar ao ecrã principal** e/ou activar **"Usar com a Siri"**
   com a frase *"apontar"*.

Depois é só: *"Ei Siri, apontar"* → dizer a frase → notificação a confirmar.

## Notas

- O token está em `backend/.env` na chave `INGEST_TOKEN` (gerado na instalação).
  Sem token o endpoint devolve 401; sem `INGEST_TOKEN` definido devolve 503.
- Fora de casa, usa o endereço Tailscale do Mac em vez do IP local.
- O mesmo token serve o agente local (`/api/ingest/screen-time` e `/app-usage`).
