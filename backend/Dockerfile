# Backend FastAPI (multi-arch: corre em ARM64 da VM Oracle e em x86)
# As features macOS (Screen Time, app tracker, LCU) ficam inertes em Linux —
# os dados chegam via /api/ingest do agente local (CLOUD=1).
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Volumes persistentes: BD e uploads (ver DATABASE_URL e UPLOADS_DIR)
RUN mkdir -p /app/data /app/uploads

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
