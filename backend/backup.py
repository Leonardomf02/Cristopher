"""Cópias de segurança da base de dados.

Não havia nenhuma. A base tem ~6 meses de coisas que não existem em mais lado
nenhum: o banco só expõe 90 dias de movimentos, o WakaTime gratuito 14, o
knowledgeC da Apple ~4 semanas, e as sessões do tracker nunca saíram deste Mac.
Um disco que morre levava tudo.

`VACUUM INTO` (em vez de copiar o ficheiro) porque a base está sempre aberta:
copiar à bruta apanha um ficheiro a meio de uma escrita. O SQLite escreve uma
cópia consistente, e o gzip a seguir tira-lhe ~80% do tamanho.

E depois uma cópia **fora deste Mac**: as cópias locais protegiam de um engano a
apagar ficheiros, mas não de um disco que morre nem de um portátil roubado — que
é precisamente o risco que a base não pode correr. Como o destino é uma pasta
sincronizada (iCloud Drive, por omissão), a cópia vai cifrada com AES-256-GCM e
uma palavra-passe que só existe no `.env`: quem chegar ao ficheiro na nuvem
encontra ruído.
"""
from __future__ import annotations

import gzip
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent

# Cabeçalho do ficheiro cifrado: marca + sal do scrypt + nonce do GCM.
_MAGIA = b"CRISTOPHER1"
_SAL = 16
_NONCE = 12
_SUFIXO_CIFRADO = ".enc"


def caminho_da_base() -> Path:
    url = os.getenv("DATABASE_URL", "sqlite:///./cristopher.db")
    ficheiro = url.replace("sqlite:///", "")
    p = Path(ficheiro)
    return p if p.is_absolute() else (_BASE_DIR / ficheiro).resolve()


def pasta() -> Path:
    """Onde ficam as cópias. Fora da pasta do projecto por omissão — uma cópia
    dentro do que se está a editar não protege de enganos com o `git clean`."""
    destino = os.getenv("BACKUP_DIR", "").strip()
    p = Path(destino).expanduser() if destino else Path.home() / "Library" / "Application Support" / "Cristopher" / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _guardar_dias() -> int:
    try:
        return max(1, int(os.getenv("BACKUP_KEEP_DAYS", "30")))
    except ValueError:
        return 30


# ── Cópia fora deste Mac ─────────────────────────────────────────

def pasta_fora() -> Optional[Path]:
    """Onde fica a cópia fora do Mac. Vazio = desligado."""
    destino = os.getenv("BACKUP_OFFSITE_DIR", "").strip()
    return Path(destino).expanduser() if destino else None


def _passe() -> str:
    return os.getenv("BACKUP_PASSPHRASE", "").strip()


def fora_ligado() -> bool:
    return pasta_fora() is not None and bool(_passe())


def _chave(passe: str, sal: bytes) -> bytes:
    """scrypt com os parâmetros recomendados — o suficiente para uma palavra-passe
    escolhida por uma pessoa não ser adivinhada à força.

    O `maxmem` é preciso: n=2^15 pede 32MB e o limite por omissão do OpenSSL é
    exactamente esse, o que fazia a cifra falhar sem nada de errado."""
    import hashlib
    return hashlib.scrypt(passe.encode("utf-8"), salt=sal, n=2 ** 15, r=8, p=1,
                          dklen=32, maxmem=96 * 1024 * 1024)


def cifra(origem: Path, destino: Path, passe: str) -> Path:
    """AES-256-GCM. O GCM traz a etiqueta de autenticidade, por isso um ficheiro
    corrompido ou adulterado falha a decifrar em vez de devolver lixo."""
    import os as _os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    sal, nonce = _os.urandom(_SAL), _os.urandom(_NONCE)
    dados = origem.read_bytes()
    cifrado = AESGCM(_chave(passe, sal)).encrypt(nonce, dados, _MAGIA)
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    parcial.write_bytes(_MAGIA + sal + nonce + cifrado)
    parcial.replace(destino)
    return destino


def decifra(origem: Path, destino: Path, passe: str) -> Path:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    bruto = origem.read_bytes()
    if not bruto.startswith(_MAGIA):
        raise ValueError("não é uma cópia cifrada do Cristopher")
    i = len(_MAGIA)
    sal, nonce = bruto[i:i + _SAL], bruto[i + _SAL:i + _SAL + _NONCE]
    corpo = bruto[i + _SAL + _NONCE:]
    try:
        dados = AESGCM(_chave(passe, sal)).decrypt(nonce, corpo, _MAGIA)
    except Exception:
        raise ValueError("palavra-passe errada ou ficheiro corrompido")
    destino.write_bytes(dados)
    return destino


def copias_fora() -> list[dict]:
    pasta = pasta_fora()
    if pasta is None or not pasta.exists():
        return []
    out = []
    for f in sorted(pasta.glob(f"cristopher-*.db.gz{_SUFIXO_CIFRADO}"), reverse=True):
        try:
            st = f.stat()
        except OSError:
            continue
        out.append({
            "name": f.name, "path": str(f), "bytes": st.st_size,
            "mb": round(st.st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        })
    return out


def envia_para_fora(local: Path) -> dict:
    """Leva uma cópia local para a pasta de fora, cifrada. Nunca rebenta o
    trabalho de quem chama: devolve sempre o que aconteceu."""
    pasta = pasta_fora()
    if pasta is None:
        return {"enabled": False, "sent": False, "reason": "BACKUP_OFFSITE_DIR vazio"}
    passe = _passe()
    if not passe:
        # Escrever a vida dele em claro numa pasta sincronizada seria pior do que
        # não ter cópia nenhuma — isto é recusa, não falha.
        return {"enabled": False, "sent": False,
                "reason": "falta BACKUP_PASSPHRASE — sem ela não se manda nada para a nuvem"}
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / (local.name + _SUFIXO_CIFRADO)
        cifra(local, destino, passe)
        apagadas = _arruma_fora(datetime.now())
        return {"enabled": True, "sent": True, "file": destino.name, "dir": str(pasta),
                "mb": round(destino.stat().st_size / 1024 / 1024, 2), "pruned": apagadas}
    except Exception as ex:                                  # noqa: BLE001
        logger.warning(f"[backup] cópia fora do Mac falhou: {ex}")
        return {"enabled": True, "sent": False, "reason": str(ex)[:200]}


def _arruma_fora(agora: datetime) -> int:
    limite = _guardar_dias() * 86400
    apagadas = 0
    for c in copias_fora()[1:]:
        try:
            if agora.timestamp() - Path(c["path"]).stat().st_mtime > limite:
                Path(c["path"]).unlink()
                apagadas += 1
        except OSError:
            continue
    return apagadas


def estado_fora() -> dict:
    pasta = pasta_fora()
    todas = copias_fora()
    ultima = todas[0] if todas else None
    horas = None
    if ultima:
        horas = round((datetime.now() - datetime.fromisoformat(ultima["created_at"])).total_seconds() / 3600, 1)
    ligado = fora_ligado()
    return {
        "enabled": ligado,
        "dir": str(pasta) if pasta else "",
        "has_passphrase": bool(_passe()),
        "count": len(todas),
        "last": ultima,
        "hours_ago": horas,
        # Só é problema quando ele o ligou e deixou de funcionar.
        "stale": bool(ligado and (ultima is None or (horas is not None and horas > 48))),
        "backups": todas[:5],
    }


def copias() -> list[dict]:
    """As cópias existentes, da mais recente para a mais antiga."""
    out = []
    for f in sorted(pasta().glob("cristopher-*.db.gz"), reverse=True):
        try:
            st = f.stat()
        except OSError:
            continue
        out.append({
            "name": f.name,
            "path": str(f),
            "bytes": st.st_size,
            "mb": round(st.st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        })
    return out


def _arruma(agora: datetime) -> int:
    """Apaga o que passou da validade, mas nunca a última cópia — se o Mac
    estiver semanas desligado, a limpeza não pode deixar-nos sem nada."""
    limite = _guardar_dias() * 86400
    apagadas = 0
    todas = copias()
    for c in todas[1:]:
        if agora.timestamp() - Path(c["path"]).stat().st_mtime > limite:
            try:
                Path(c["path"]).unlink()
                apagadas += 1
            except OSError as ex:
                logger.warning(f"[backup] não deu para apagar {c['name']}: {ex}")
    return apagadas


def _espaco_livre(destino: Path) -> int:
    try:
        return shutil.disk_usage(destino).free
    except OSError:
        return 1 << 60


def cria_copia() -> dict:
    """Faz uma cópia consistente e comprimida. Devolve o resumo do que fez."""
    origem = caminho_da_base()
    if not origem.exists():
        raise FileNotFoundError(f"base não encontrada: {origem}")

    agora = datetime.now()
    destino = pasta() / f"cristopher-{agora:%Y%m%d-%H%M}.db.gz"
    tamanho_base = origem.stat().st_size
    # A cópia intermédia é do tamanho da base; sem folga o VACUUM rebenta a meio
    # e ainda deixa lixo no disco.
    if _espaco_livre(destino.parent) < tamanho_base * 2:
        raise OSError("sem espaço em disco para a cópia")

    temporario = Path(tempfile.mkdtemp(prefix="cristopher-backup-")) / "copia.db"
    try:
        con = sqlite3.connect(f"file:{origem}?mode=ro", uri=True, timeout=30)
        try:
            con.execute("VACUUM INTO ?", (str(temporario),))
        finally:
            con.close()

        # Confere que a cópia abre e tem as tabelas todas antes de a dar por boa.
        verifica = sqlite3.connect(f"file:{temporario}?mode=ro", uri=True)
        try:
            tabelas = verifica.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
            if not tabelas:
                raise sqlite3.DatabaseError("a cópia saiu vazia")
        finally:
            verifica.close()

        # Escreve para .parcial e só depois renomeia: uma cópia interrompida a
        # meio nunca fica com nome de cópia boa.
        parcial = destino.with_suffix(destino.suffix + ".parcial")
        with open(temporario, "rb") as entrada, gzip.open(parcial, "wb", compresslevel=6) as saida:
            shutil.copyfileobj(entrada, saida, length=1024 * 1024)
        parcial.replace(destino)
    finally:
        shutil.rmtree(temporario.parent, ignore_errors=True)

    comprimido = destino.stat().st_size
    apagadas = _arruma(agora)
    return {
        "file": destino.name,
        "path": str(destino),
        "bytes": comprimido,
        "mb": round(comprimido / 1024 / 1024, 2),
        "source_mb": round(tamanho_base / 1024 / 1024, 2),
        "tables": tabelas,
        "pruned": apagadas,
        "created_at": agora.isoformat(timespec="seconds"),
        "offsite": envia_para_fora(destino),
    }


def estado() -> dict:
    """Para o painel de saúde: quando foi a última e se está atrasada."""
    todas = copias()
    ultima = todas[0] if todas else None
    horas = None
    if ultima:
        horas = round((datetime.now() - datetime.fromisoformat(ultima["created_at"])).total_seconds() / 3600, 1)
    return {
        "dir": str(pasta()),
        "count": len(todas),
        "keep_days": _guardar_dias(),
        "total_mb": round(sum(c["bytes"] for c in todas) / 1024 / 1024, 2),
        "last": ultima,
        "hours_ago": horas,
        "stale": ultima is None or (horas is not None and horas > 48),
        "backups": todas[:10],
        "offsite": estado_fora(),
    }


def restaura(nome: str, *, destino: Optional[Path] = None) -> Path:
    """Descomprime uma cópia para um ficheiro à parte (nunca por cima da base a
    correr — trocar é decisão dele, com o backend parado).

    Aceita tanto as cópias locais como as cifradas que foram para fora do Mac."""
    cifrada = nome.endswith(_SUFIXO_CIFRADO)
    base = pasta_fora() if cifrada else pasta()
    if base is None:
        raise FileNotFoundError("não há pasta de cópias fora do Mac configurada")
    origem = base / nome
    if not origem.exists() or origem.parent != base:
        raise FileNotFoundError(f"cópia não encontrada: {nome}")

    temporario = None
    if cifrada:
        passe = _passe()
        if not passe:
            raise ValueError("falta BACKUP_PASSPHRASE para abrir esta cópia")
        temporario = Path(tempfile.mkdtemp(prefix="cristopher-restauro-")) / "copia.db.gz"
        decifra(origem, temporario, passe)
        origem = temporario

    limpo = nome.replace(_SUFIXO_CIFRADO, "")
    alvo = destino or (pasta() / limpo.replace(".db.gz", "-restaurada.db"))
    try:
        with gzip.open(origem, "rb") as entrada, open(alvo, "wb") as saida:
            shutil.copyfileobj(entrada, saida, length=1024 * 1024)
    finally:
        if temporario is not None:
            shutil.rmtree(temporario.parent, ignore_errors=True)
    return alvo
