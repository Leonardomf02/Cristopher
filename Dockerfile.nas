# Imagem do Cristopher para a NAS QNAP do Pedro (TS-431KX, ARMv7).
#
# Uma imagem só: o FastAPI serve a API e o build do React na mesma porta.
#
# A NAS usa páginas de memória de 32K. O Debian compila quase tudo alinhado a 64K
# (compatível), mas a zlib e a bzip2 vêm a 4K e o kernel recusa-as com
# "ELF load command address/offset not page-aligned". O Python carrega as duas,
# por isso recompilamo-las. O pdftotext e o tesseract ficam de fora: carregam 10 e
# 9 bibliotecas a 4K cada um (importar PDF e OCR de recibos só no Mac).
#
# Construir e exportar no formato que a Container Station aceita:
#   ./build-nas.sh

# --- 1) frontend: corre na arquitetura nativa (é só ficheiros estáticos) ---
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend
WORKDIR /front
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# vazio = mesma origem: o frontend chama /api do próprio servidor que o serviu
ENV VITE_API_URL=""
RUN npm run build

# --- 2) builder armv7: bibliotecas realinhadas + wheels ---
FROM python:3.12-slim AS builder
# 64K (0x10000) é o alinhamento com que vêm a libc e as restantes bibliotecas que
# já funcionam na NAS — logo, comprovadamente aceite por um kernel de páginas 32K.
ENV ALIGN="-Wl,-z,max-page-size=0x10000"

# libffi: o cffi 2.0 (do curl_cffi) não tem wheel armv7 e compila-se.
# libjpeg/zlib/freetype/png: o pillow (do reportlab) também.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates libffi-dev \
        libjpeg-dev zlib1g-dev libfreetype6-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN curl -fsSL https://zlib.net/fossils/zlib-1.3.1.tar.gz -o zlib.tar.gz \
    && tar xzf zlib.tar.gz && cd zlib-1.3.1 \
    && CFLAGS="-O2 -fPIC $ALIGN" LDFLAGS="$ALIGN" ./configure --prefix=/patched \
    && make -j"$(nproc)" && make install

# o Makefile da bzip2 não usa LDFLAGS, daí o flag ir no CFLAGS
RUN curl -fsSL https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz -o bzip2.tar.gz \
    && tar xzf bzip2.tar.gz && cd bzip2-1.0.8 \
    && make -f Makefile-libbz2_so CFLAGS="-O2 -fPIC -D_FILE_OFFSET_BITS=64 $ALIGN" \
    && mkdir -p /patched/lib && cp libbz2.so.1.0.8 /patched/lib/

# uvicorn sem [standard]: o uvloop e o httptools não têm wheel armv7 e não fazem
# falta. O pytest também não vai.
COPY backend/requirements.txt .
RUN sed -e 's/uvicorn\[standard\]/uvicorn/' -e '/^pytest/d' requirements.txt > req-nas.txt \
    && pip wheel --no-cache-dir -r req-nas.txt -w /wheels

# --- 3) runtime armv7: sem compilador, com as bibliotecas corrigidas ---
FROM python:3.12-slim AS runtime
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo libfreetype6 libpng16-16t64 tzdata \
    && rm -rf /var/lib/apt/lists/*

# sem isto o contentor corre em UTC e os trabalhos diários saem à hora errada
ENV TZ=Europe/Lisbon
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# substituir as duas bibliotecas mal alinhadas pelas versões de 64K
COPY --from=builder /patched/lib/libz.so.1.3.1 /usr/lib/arm-linux-gnueabihf/libz.so.1.3.1
COPY --from=builder /patched/lib/libbz2.so.1.0.8 /usr/lib/arm-linux-gnueabihf/libbz2.so.1.0.4

COPY --from=builder /wheels /wheels
COPY --from=builder /src/req-nas.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r req-nas.txt \
    && rm -rf /wheels req-nas.txt

COPY backend/*.py ./
COPY backend/routers ./routers
COPY backend/deals_sources ./deals_sources
COPY --from=frontend /front/dist ./static

# Tudo o que é estado vive no volume /data, fora da imagem: a base, os recibos,
# as cópias, o token do Garmin, a chave do banco e as chaves dos avisos.
# CLOUD=1 desliga o que só existe no Mac (tracker, Screen Time, Reminders).
# Sem modelo local: o Ollama não existe para ARM de 32 bits.
ENV CLOUD=1 \
    TRACKER_AUTOSTART=0 \
    LOCAL_AI=0 \
    DATABASE_URL=sqlite:////data/cristopher.db \
    UPLOADS_DIR=/data/uploads \
    BACKUP_DIR=/data/backups \
    GARMIN_TOKENS_DIR=/data/garmin \
    ENABLEBANKING_KEY_PATH=/data/enablebanking.pem \
    PUSH_KEYS_DIR=/data \
    STATIC_DIR=/app/static
RUN mkdir -p /data

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
