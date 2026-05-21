"""Extracção de ícones de apps macOS por bundle_id.

Estratégia:
1. `mdfind kMDItemCFBundleIdentifier == '<bundle>'` → caminho do .app
2. Lê o `CFBundleIconFile`/`CFBundleIconName` do Info.plist
3. Converte o .icns para PNG (256px) com `sips` e cacheia em disco
4. Devolve o PNG

A cache fica em `<UPLOADS_DIR>/app_icons/<safe_bundle>.png`. Em falha devolve None
e o frontend usa um fallback letrado.
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "uploads"))
ICONS_DIR = UPLOADS_DIR / "app_icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

_SAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_name(bundle_id: str) -> str:
    return _SAFE_RE.sub("_", bundle_id)[:120]


def _find_app_path(bundle_id: str) -> Optional[Path]:
    # `c` no fim do operador → case-insensitive (LoL tem bundle id lowercase
    # no .app mas knowledgeC reporta mixed case).
    try:
        result = subprocess.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'c"],
            capture_output=True, text=True, timeout=4,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.endswith(".app") and Path(line).exists() and "/Trash/" not in line:
            return Path(line)
    return None


def _read_icon_file(app_path: Path) -> Optional[Path]:
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        return None
    try:
        with open(plist_path, "rb") as f:
            info = plistlib.load(f)
    except Exception:
        return None
    resources = app_path / "Contents" / "Resources"
    candidates: list[str] = []
    icon_name = info.get("CFBundleIconFile") or info.get("CFBundleIconName")
    if icon_name:
        candidates.append(icon_name)
        if not icon_name.endswith(".icns"):
            candidates.append(icon_name + ".icns")
    candidates.extend(["AppIcon.icns", "Icon.icns", "app.icns"])
    for name in candidates:
        p = resources / name
        if p.exists() and p.is_file():
            return p
    # último recurso: primeiro .icns que apareça
    try:
        for entry in resources.iterdir():
            if entry.suffix == ".icns":
                return entry
    except OSError:
        pass
    return None


def _icns_to_png(icns_path: Path, out_path: Path, size: int = 256) -> bool:
    try:
        subprocess.run(
            ["sips", "-s", "format", "png", "-z", str(size), str(size),
             str(icns_path), "--out", str(out_path)],
            capture_output=True, timeout=8, check=True,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        return False
    return out_path.exists() and out_path.stat().st_size > 0


@lru_cache(maxsize=512)
def get_icon_png_path(bundle_id: str) -> Optional[str]:
    """Devolve o caminho do PNG (cache + extracção on-demand). None se falhar.

    Se o bundle for um sub-bundle (ex: com.riotgames.LeagueofLegends.LeagueClientUx)
    tenta também o parent (com.riotgames.LeagueofLegends).
    """
    if not bundle_id or bundle_id == "(unknown)":
        return None
    safe = _safe_name(bundle_id)
    out_path = ICONS_DIR / f"{safe}.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        return str(out_path)

    candidates = [bundle_id]
    parts = bundle_id.split(".")
    while len(parts) > 2:
        parts = parts[:-1]
        candidates.append(".".join(parts))

    for cand in candidates:
        app_path = _find_app_path(cand)
        if not app_path:
            continue
        icns = _read_icon_file(app_path)
        if not icns:
            continue
        if _icns_to_png(icns, out_path):
            return str(out_path)
    return None
