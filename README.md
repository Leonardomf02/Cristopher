# 🧠 Cristopher — Personal Life Manager

Uma app completa para gerir a tua vida: calendário, gastos, LoL tracker e viagens.

## Stack

- **Backend**: Python + FastAPI + SQLite
- **Frontend**: React + TypeScript + Tailwind CSS + Vite

## Como correr

### 1. Primeira vez (setup)

```bash
# Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### 2. Iniciar

```bash
# Opção A: Script automático
./start.sh

# Opção B: Manual (2 terminais)

# Terminal 1 - Backend
cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000

# Terminal 2 - Frontend
cd frontend && npm run dev
```

### 3. Abrir

- **App**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs

## Funcionalidades

### 📅 Calendário
- Vista dia, semana, mês e ano (estilo Apple Calendar)
- Eventos com hora fixa ou flexíveis (ex: Gym - qualquer hora do dia)
- Categorias: Gym, Trabalho, Pessoal, Estudo, Social, Saúde
- Marcar como completo

### 💰 Gastos
- Inserir gastos manualmente com categoria
- Upload de recibos/fotos
- Gráficos por categoria (pie chart)
- Resumo mensal com estatísticas
- Categorias: Comida, Transporte, Entretenimento, Subscrições, Compras, Saúde, Contas, Viagens

### ⚔️ LoL Tracker
- Registar vitórias e derrotas
- Champion jogado e adversário (com pesquisa)
- Role (Top, Jungle, Mid, ADC, Support)
- Marcar se a derrota foi culpa tua
- Estatísticas gerais e por champion
- Winrate tracker

### ✈️ Viagens
- Adicionar viagens com destino, datas e custos
- Sugestões automáticas de sítios para visitar (grátis e pagos)
- Destinos suportados: Stockholm, Paris, London, Lisbon, Barcelona, Rome, Tokyo, Amsterdam
- Adicionar os teus próprios sítios
- Tracker de gastos por viagem
- Marcar sítios como visitados
