"""Entra na conta Garmin uma vez e guarda o token.

Correr só quando for preciso: no primeiro arranque, e outra vez se o token
expirar. A Garmin limita os LOGINS por conta e bloqueia 48 horas quem insiste —
por isso o backend nunca faz login sozinho, vive do token que este script grava.

    python scripts/garmin_login.py

A password é pedida no momento e não fica em lado nenhum (nem no .env, nem no
histórico da shell). Se a conta tiver verificação em dois passos, o código é
pedido a seguir.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import garmin_api


def main() -> int:
    from garminconnect import Garmin

    destino = garmin_api.token_dir()

    if garmin_api.tem_token():
        print(f"Já existe um token em {destino}.")
        if input("Fazer login outra vez? (s/N) ").strip().lower() not in ("s", "sim", "y"):
            return 0

    email = input("Email da conta Garmin: ").strip()
    if not email:
        print("Sem email não dá.")
        return 1
    password = getpass.getpass("Password: ")
    if not password:
        print("Sem password não dá.")
        return 1

    destino.mkdir(parents=True, exist_ok=True)
    api = Garmin(email=email, password=password, prompt_mfa=lambda: input("Código de verificação: ").strip())
    try:
        api.login(tokenstore=str(destino))       # grava o token ao entrar
    except Exception as e:
        nome = type(e).__name__
        if "TooManyRequests" in nome:
            print("\nA Garmin recusou por excesso de pedidos. O bloqueio é por conta e pode\n"
                  "durar horas — esperar e tentar de novo mais tarde, sem insistir.")
        elif "Authentication" in nome:
            print("\nEmail ou password errados.")
        else:
            print(f"\nFalhou: {nome}: {e}")
        return 1

    try:
        destino.chmod(0o700)
        for f in destino.glob("*.json"):
            f.chmod(0o600)
    except OSError:
        pass

    nome = getattr(api, "display_name", None) or email
    print(f"\nEntrou como {nome}. Token guardado em {destino}.")

    aparelhos = []
    try:
        aparelhos = api.get_devices() or []
    except Exception:
        pass
    for a in aparelhos:
        if isinstance(a, dict):
            print(f"  · {a.get('displayName') or a.get('productDisplayName')}")

    print("\nO backend passa a ler os dados sozinho. Para trazer já:\n"
          "  python -c \"import garmin_sync; print(garmin_sync.sincroniza(dias=3))\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
