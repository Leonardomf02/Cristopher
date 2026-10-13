"""Cópia cifrada fora do Mac.

Uma cópia que não se consegue reabrir não é uma cópia. Estes testes fecham o
ciclo inteiro — base real → gzip → cifrada → decifrada → base a abrir — e fixam
as recusas que existem de propósito (sem palavra-passe não vai nada para uma
pasta sincronizada).

Corre sozinho:  python tests/test_backup_offsite.py
"""
import os
import sys
import gzip
import shutil
import sqlite3
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backup


def _ambiente(**variaveis):
    """Põe as variáveis, devolve uma função que repõe o que lá estava."""
    antigos = {k: os.environ.get(k) for k in variaveis}
    for k, v in variaveis.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    def repoe():
        for k, v in antigos.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return repoe


def _base_de_mentira(caminho: Path) -> None:
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE gastos (id INTEGER PRIMARY KEY, descricao TEXT, valor REAL)")
    con.executemany("INSERT INTO gastos (descricao, valor) VALUES (?, ?)",
                    [("lidl", 12.4), ("café", 1.1), ("comboio", 3.5)])
    con.commit()
    con.close()


def test_cifra_e_decifra_devolve_o_mesmo():
    tmp = Path(tempfile.mkdtemp())
    try:
        origem = tmp / "dados.bin"
        origem.write_bytes(b"a vida dele em bytes" * 1000)
        cifrado = tmp / "dados.bin.enc"
        backup.cifra(origem, cifrado, "palavra-passe-boa")

        # O ficheiro que vai para a nuvem não pode ter nada legível lá dentro.
        assert b"a vida dele" not in cifrado.read_bytes()

        de_volta = tmp / "de-volta.bin"
        backup.decifra(cifrado, de_volta, "palavra-passe-boa")
        assert de_volta.read_bytes() == origem.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_passe_errada_nao_devolve_lixo():
    tmp = Path(tempfile.mkdtemp())
    try:
        origem = tmp / "dados.bin"
        origem.write_bytes(b"segredo")
        cifrado = tmp / "dados.bin.enc"
        backup.cifra(origem, cifrado, "certa")
        try:
            backup.decifra(cifrado, tmp / "x.bin", "errada")
            assert False, "devia ter recusado"
        except ValueError as ex:
            assert "passe" in str(ex).lower() or "corrompido" in str(ex).lower()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ficheiro_adulterado_e_recusado():
    tmp = Path(tempfile.mkdtemp())
    try:
        origem = tmp / "dados.bin"
        origem.write_bytes(b"segredo" * 100)
        cifrado = tmp / "dados.bin.enc"
        backup.cifra(origem, cifrado, "certa")
        bruto = bytearray(cifrado.read_bytes())
        bruto[-1] ^= 0xFF                      # um bit trocado na nuvem
        cifrado.write_bytes(bytes(bruto))
        try:
            backup.decifra(cifrado, tmp / "x.bin", "certa")
            assert False, "devia ter recusado"
        except ValueError:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sem_passe_nao_manda_nada_para_a_nuvem():
    tmp = Path(tempfile.mkdtemp())
    repoe = _ambiente(BACKUP_OFFSITE_DIR=str(tmp / "nuvem"), BACKUP_PASSPHRASE=None)
    try:
        ficheiro = tmp / "copia.db.gz"
        ficheiro.write_bytes(b"x")
        r = backup.envia_para_fora(ficheiro)
        assert r["sent"] is False
        assert "BACKUP_PASSPHRASE" in r["reason"]
        assert not (tmp / "nuvem").exists()      # nem a pasta se cria
        assert backup.fora_ligado() is False
    finally:
        repoe()
        shutil.rmtree(tmp, ignore_errors=True)


def test_sem_pasta_e_so_desligado():
    repoe = _ambiente(BACKUP_OFFSITE_DIR=None, BACKUP_PASSPHRASE="seja-o-que-for")
    try:
        r = backup.envia_para_fora(Path("/tmp/nada.gz"))
        assert r["enabled"] is False and r["sent"] is False
        assert backup.estado_fora()["stale"] is False    # desligado não é problema
    finally:
        repoe()


def test_ciclo_completo():
    """Base real → cópia → cifrada para fora → restaurada → abre e tem tudo."""
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "cristopher.db"
    _base_de_mentira(base)
    repoe = _ambiente(
        DATABASE_URL=f"sqlite:///{base}",
        BACKUP_DIR=str(tmp / "locais"),
        BACKUP_OFFSITE_DIR=str(tmp / "nuvem"),
        BACKUP_PASSPHRASE="uma-passe-qualquer",
    )
    try:
        r = backup.cria_copia()
        assert r["offsite"]["sent"] is True
        assert r["offsite"]["file"].endswith(".db.gz.enc")

        estado = backup.estado()
        assert estado["offsite"]["enabled"] is True
        assert estado["offsite"]["count"] == 1
        assert estado["offsite"]["stale"] is False

        # Restaurar a partir da cópia que está fora do Mac
        nome = estado["offsite"]["last"]["name"]
        alvo = tmp / "restaurada.db"
        backup.restaura(nome, destino=alvo)
        con = sqlite3.connect(alvo)
        try:
            assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert con.execute("SELECT COUNT(*) FROM gastos").fetchone()[0] == 3
            assert con.execute("SELECT ROUND(SUM(valor), 2) FROM gastos").fetchone()[0] == 17.0
        finally:
            con.close()
    finally:
        repoe()
        shutil.rmtree(tmp, ignore_errors=True)


def test_copia_local_continua_a_restaurar():
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "cristopher.db"
    _base_de_mentira(base)
    repoe = _ambiente(
        DATABASE_URL=f"sqlite:///{base}",
        BACKUP_DIR=str(tmp / "locais"),
        BACKUP_OFFSITE_DIR=None,
        BACKUP_PASSPHRASE=None,
    )
    try:
        r = backup.cria_copia()
        assert r["offsite"]["enabled"] is False
        alvo = tmp / "restaurada.db"
        backup.restaura(r["file"], destino=alvo)
        con = sqlite3.connect(alvo)
        try:
            assert con.execute("SELECT COUNT(*) FROM gastos").fetchone()[0] == 3
        finally:
            con.close()
        # e o gzip continua a ser gzip
        with gzip.open(Path(r["path"]), "rb") as f:
            assert f.read(16).startswith(b"SQLite format 3")
    finally:
        repoe()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {nome}")
            except AssertionError as ex:
                falhas += 1
                print(f"  FALHA {nome}: {ex}")
    print(f"\n{falhas} falhas")
    sys.exit(1 if falhas else 0)
