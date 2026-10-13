"""Corre DENTRO da imagem armv7 (ver build-nas.sh): carrega a app e os módulos
que ela só importa a meio do caminho, e confirma que nenhuma biblioteca ELF que
ficou carregada está alinhada abaixo de 32K — a NAS recusava-a.

Olhar só para os nomes (como no Cinespot) deixa passar uma dependência nova. Aqui
conta o que foi mesmo carregado: o que está mapeado no processo, mais as
dependências (ldd) de cada módulo nativo importado.
"""
import glob
import os
import struct
import subprocess
import sys
import tempfile

pasta = tempfile.mkdtemp()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{pasta}/verifica.db",
    "UPLOADS_DIR": f"{pasta}/uploads",
    "BACKUP_DIR": f"{pasta}/backups",
    "PUSH_KEYS_DIR": pasta,
    "CRISTOPHER_PASSWORD": "",
})
sys.path.insert(0, "/app")
os.chdir("/app")

import main  # noqa: E402,F401  (as rotas, os modelos e as migrações)

# importados só quando uma rota ou um trabalho precisa deles
import bz2, lzma, zlib, ssl, sqlite3  # noqa: E401,E402
import garminconnect, pywebpush, py_vapid, icalendar, feedparser, vinted_scraper  # noqa: E401,E402
from curl_cffi import requests as _curl  # noqa: E402,F401
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402,F401
from reportlab.pdfgen import canvas as _canvas  # noqa: E402,F401
from PIL import Image  # noqa: E402,F401

zlib.compress(b"x" * 1000)
bz2.compress(b"x" * 1000)


def alinhamento(caminho):
    try:
        with open(caminho, "rb") as f:
            d = f.read(65536)
    except OSError:
        return None
    if len(d) < 52 or d[:4] != b"\x7fELF" or d[4] != 1:
        return None
    phoff = struct.unpack_from("<I", d, 28)[0]
    ent = struct.unpack_from("<H", d, 42)[0]
    num = struct.unpack_from("<H", d, 44)[0]
    m = 0
    for i in range(num):
        b = phoff + i * ent
        if b + 32 > len(d):
            break
        if struct.unpack_from("<I", d, b)[0] == 1:
            m = max(m, struct.unpack_from("<I", d, b + 28)[0])
    return m


carregadas = {os.path.realpath(sys.executable)}
with open("/proc/self/maps") as f:
    for linha in f:
        partes = linha.split()
        if len(partes) >= 6 and partes[5].startswith("/"):
            carregadas.add(os.path.realpath(partes[5]))

nativos = {os.path.realpath(m.__file__) for m in list(sys.modules.values())
           if getattr(m, "__file__", None) and m.__file__.endswith(".so")}
for so in nativos | {os.path.realpath(sys.executable)}:
    carregadas.add(so)
    saida = subprocess.run(["ldd", so], capture_output=True, text=True).stdout
    for linha in saida.splitlines():
        if "=>" in linha:
            alvo = linha.split("=>")[1].strip().split(" (")[0]
            if alvo.startswith("/"):
                carregadas.add(os.path.realpath(alvo))

maus = []
contadas = 0
for caminho in sorted(carregadas):
    a = alinhamento(caminho)
    if a is None:
        continue
    contadas += 1
    if a < 0x8000:
        maus.append((caminho, a))

print(f"   {contadas} bibliotecas carregadas ({len(nativos)} módulos nativos)")
if maus:
    print("   FALHA - abaixo de 32K:")
    for caminho, a in maus:
        print(f"     {a // 1024}K  {caminho}")
    sys.exit(1)
print("   OK - todas >= 32K")
