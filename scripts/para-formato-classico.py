"""Converte um tar OCI/docker-archive moderno para o formato Docker clássico
(<id>/layer.tar + json + VERSION + repositories), que é o que a Container Station aceita."""

import gzip
import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path

origem, destino = Path(sys.argv[1]), Path(sys.argv[2])
trabalho = Path(sys.argv[3])

if trabalho.exists():
    shutil.rmtree(trabalho)
extraido = trabalho / "extraido"
saida = trabalho / "saida"
extraido.mkdir(parents=True)
saida.mkdir(parents=True)

print("1. extrair...")
with tarfile.open(origem) as t:
    t.extractall(extraido, filter="data")

manifesto = json.loads((extraido / "manifest.json").read_text())[0]
config_rel = manifesto["Config"]
config_bytes = (extraido / config_rel).read_bytes()
config_hash = hashlib.sha256(config_bytes).hexdigest()
config_nome = f"{config_hash}.json"
(saida / config_nome).write_bytes(config_bytes)
config = json.loads(config_bytes)

print(f"2. {len(manifesto['Layers'])} camadas -> formato clássico")
ids, anterior = [], None
for i, camada_rel in enumerate(manifesto["Layers"]):
    bruto = (extraido / camada_rel).read_bytes()
    # as camadas OCI vêm comprimidas; o formato clássico exige tar puro
    if bruto[:2] == b"\x1f\x8b":
        bruto = gzip.decompress(bruto)

    # id determinístico a partir do conteúdo + posição
    lid = hashlib.sha256(f"{i}".encode() + bruto[:4096]).hexdigest()
    ids.append(lid)

    d = saida / lid
    d.mkdir()
    (d / "VERSION").write_text("1.0")
    (d / "layer.tar").write_bytes(bruto)

    meta = {"id": lid, "created": config.get("created", "1970-01-01T00:00:00Z")}
    if anterior:
        meta["parent"] = anterior
    # a última camada carrega a configuração da imagem
    if i == len(manifesto["Layers"]) - 1:
        meta["config"] = config.get("config", {})
        meta["architecture"] = config.get("architecture")
        meta["os"] = config.get("os")
    (d / "json").write_text(json.dumps(meta))
    anterior = lid
    print(f"   camada {i + 1}/{len(manifesto['Layers'])}  {len(bruto) // 1048576} MB")

repo_tags = manifesto.get("RepoTags") or ["cinespot:latest"]
(saida / "manifest.json").write_text(
    json.dumps([{
        "Config": config_nome,
        "RepoTags": repo_tags,
        "Layers": [f"{i}/layer.tar" for i in ids],
    }])
)

nome, tag = repo_tags[0].rsplit(":", 1)
(saida / "repositories").write_text(json.dumps({nome: {tag: ids[-1]}}))

print("3. empacotar...")
with tarfile.open(destino, "w") as t:
    for p in sorted(saida.iterdir()):
        t.add(p, arcname=p.name)

print(f"pronto: {destino}  ({destino.stat().st_size // 1048576} MB)")
