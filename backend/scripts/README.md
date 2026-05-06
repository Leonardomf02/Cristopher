# Daily Investment Signal

Gera diariamente uma análise de mercado + sugestões via agente iaedu.pt.

## Setup

Se ainda não instalaste as deps novas (`feedparser`):

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
```

A chave da API iaedu.pt já está hardcoded em `routers/investment_signals.py` (mesma que já era usada em `ai-suggestions`).

## Testar manualmente

```bash
cd backend
source venv/bin/activate
python scripts/daily_signal.py
```

Logs detalhados aparecem na consola.

## Agendar (todos os dias às 09:00)

```bash
cp scripts/com.cristopher.daily-signal.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cristopher.daily-signal.plist
```

Verificar:
```bash
launchctl list | grep cristopher
```

Parar:
```bash
launchctl unload ~/Library/LaunchAgents/com.cristopher.daily-signal.plist
```

Logs em `scripts/daily_signal.log` e `scripts/daily_signal.err.log`.

## Forçar execução agora

```bash
launchctl start com.cristopher.daily-signal
# ou
./scripts/run_daily_signal.sh
```
