"""Spotify Curator (offline) — curadoria de playlists pela IA.

Conta grátis não dá acesso à API do Spotify (desde Fev/Mar 2026 o dono da app tem de
ter Premium), por isso não há login nem write-back. Em vez disso o utilizador importa
as faixas manualmente (colar uma lista ou um CSV do Exportify), descreve o ESPÍRITO de
cada playlist, e o agente iaedu.pt (Opus) faz a curadoria: marca os intrusos, sugere
músicas novas que encaixam e dá um veredicto. Para cada sugestão devolve um link de
pesquisa do Spotify (substituto do "adicionar com 1 clique"). A última análise fica em
cache no registo da playlist."""

import csv
import io
import json
import re
import logging
from datetime import datetime
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from models import SpotifyPlaylist, SpotifyTrack, SpotifyOverview, SpotifySuggestion
from ai_config import ask_agent_async, extract_json

router = APIRouter(prefix="/api/spotify", tags=["Spotify"])
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────────────

class PlaylistIn(BaseModel):
    name: str
    vibe: str = ""
    is_favorites: bool = False


class PlaylistPatch(BaseModel):
    name: str | None = None
    vibe: str | None = None
    is_favorites: bool | None = None


class ImportIn(BaseModel):
    text: str
    mode: str = "replace"   # replace | append


class ImportLinkIn(BaseModel):
    url: str


# ── Helpers: parsing do import ───────────────────────────────────

_SEP = re.compile(r"\s+[-–—]\s+|\t")


def _uri_to_url(uri: str) -> str:
    uri = (uri or "").strip()
    if not uri:
        return ""
    if uri.startswith("http"):
        return uri
    if uri.startswith("spotify:track:"):
        return "https://open.spotify.com/track/" + uri.split(":")[-1]
    return ""


def _split_title_artist(s: str) -> tuple[str, str]:
    parts = _SEP.split(s, maxsplit=1)
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    return s.strip(), ""


def _parse_csv(raw: str) -> list[dict] | None:
    """Tenta ler um CSV de faixas (ex: Exportify). Devolve None se não parecer um."""
    try:
        reader = csv.DictReader(io.StringIO(raw))
    except csv.Error:
        return None
    if not reader.fieldnames:
        return None
    cols = {(c or "").lower().strip(): c for c in reader.fieldnames}

    def pick(*names: str) -> str | None:
        for n in names:
            if n in cols:
                return cols[n]
        return None

    c_title = pick("track name", "name", "title", "track", "song")
    if not c_title:
        return None
    c_artist = pick("artist name(s)", "artist name", "artist", "artists", "artist names")
    c_album = pick("album name", "album")
    c_uri = pick("track uri", "uri", "track url", "url", "link")

    out: list[dict] = []
    for row in reader:
        title = (row.get(c_title) or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "artist": (row.get(c_artist) or "").strip() if c_artist else "",
            "album": (row.get(c_album) or "").strip() if c_album else "",
            "spotify_url": _uri_to_url(row.get(c_uri) or "") if c_uri else "",
        })
    return out


def _parse_lines(raw: str) -> list[dict]:
    out: list[dict] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        # cabeçalhos perdidos / URIs / URLs sem nome → inúteis para a IA
        if s.lower().startswith(("track uri", "spotify:")):
            continue
        if s.startswith("http") and " " not in s:
            continue
        title, artist = _split_title_artist(s)
        if not title:
            continue
        out.append({"title": title, "artist": artist, "album": "", "spotify_url": ""})
    return out


def _parse_import(raw: str) -> list[dict]:
    raw = (raw or "").strip()
    if not raw:
        return []
    first = raw.splitlines()[0]
    if "," in first:
        rows = _parse_csv(raw)
        if rows:
            return rows
    return _parse_lines(raw)


# ── Helpers: importar pelo link público (sem API, sem Premium) ───
# A página embed do Spotify (open.spotify.com/embed/playlist/ID) traz a trackList no
# blob __NEXT_DATA__ — funciona para playlists PÚBLICAS, sem login. Pode vir incompleta
# em playlists muito grandes (o embed mostra um número limitado de faixas).

_PLAYLIST_ID = re.compile(r"playlist[/:]([A-Za-z0-9]+)")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _playlist_id_from_link(text: str) -> str | None:
    t = (text or "").strip()
    if "open.spotify.com/playlist" not in t and not t.startswith("spotify:playlist:"):
        return None
    m = _PLAYLIST_ID.search(t)
    return m.group(1) if m else None


async def _fetch_from_link(url: str) -> tuple[str, list[dict]]:
    """Devolve (nome_da_playlist, faixas) a partir de um link público. Levanta HTTPException
    com mensagem clara em qualquer falha (privada, formato mudou, sem rede)."""
    pid = _playlist_id_from_link(url)
    if not pid:
        raise HTTPException(status_code=400, detail="Link de playlist do Spotify inválido.")
    embed = f"https://open.spotify.com/embed/playlist/{pid}"
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(embed, headers={"User-Agent": _BROWSER_UA})
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Não consegui aceder ao Spotify (sem rede?).")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"O Spotify devolveu {r.status_code} — a playlist é pública?")
    m = _NEXT_DATA.search(r.text)
    if not m:
        raise HTTPException(status_code=502, detail="Não consegui ler a playlist (tem de ser pública).")
    try:
        entity = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise HTTPException(status_code=502, detail="Não consegui ler a playlist (privada ou formato mudou).")
    name = (entity.get("name") or entity.get("title") or "Playlist").strip()
    out: list[dict] = []
    for t in entity.get("trackList") or []:
        title = (t.get("title") or t.get("name") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "artist": (t.get("subtitle") or "").strip(),
            "album": "",
            "spotify_url": _uri_to_url(t.get("uri") or ""),
        })
    if not out:
        raise HTTPException(status_code=400, detail="A playlist parece vazia ou privada (tem de ser pública).")
    return name, out


# ── Helpers: serialização ────────────────────────────────────────

def _track_out(t: SpotifyTrack) -> dict:
    return {
        "id": t.id,
        "position": t.position,
        "title": t.title,
        "artist": t.artist,
        "album": t.album,
        "spotify_url": t.spotify_url,
    }


def _playlist_out(p: SpotifyPlaylist, track_count: int) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "vibe": p.vibe,
        "is_favorites": bool(p.is_favorites),
        "track_count": track_count,
        "analyzed_at": p.analyzed_at,
        "created_at": p.created_at,
    }


# ── Helpers: análise IA ──────────────────────────────────────────

def _build_prompt(name: str, vibe: str, is_favorites: bool, tracks: list[SpotifyTrack]) -> str:
    listing = "\n".join(
        f"{i + 1}. {t.title} — {t.artist}" if t.artist else f"{i + 1}. {t.title}"
        for i, t in enumerate(tracks)
    )
    vibe_line = vibe.strip() or "(não especificada — infere o espírito a partir das músicas)"
    if is_favorites:
        task = (
            "Esta é a lista de MÚSICAS GOSTADAS (favoritas), não uma playlist temática. "
            "Não marques intrusos por 'vibe'. Em INTRUSOS deixa [] (ou marca só faixas claramente "
            "fora do gosto geral). Em SUGESTÕES propõe músicas novas que ele provavelmente vai "
            "adorar, pelo padrão das favoritas. No VEREDICTO diz por que vibes/playlists estas "
            "favoritas se agrupam (ex: 'metade davam para a tua playlist triste')."
        )
    else:
        task = (
            "1. INTRUSOS: faixas que NÃO encaixam no espírito. Para cada uma dá o 'index' (número "
            "da lista) e uma razão curta e concreta. Sê criterioso — só o que realmente destoa. "
            "Se nada destoar, devolve [].\n"
            "2. SUGESTÕES: 8 a 15 músicas NOVAS (que não estão na lista) que encaixam mesmo bem. "
            "Para cada uma: título, artista e razão curta. Varia artistas.\n"
            "3. VEREDICTO: 1-2 frases sobre o estado da playlist."
        )
    return f"""És um curador musical exigente. Conheces bem música de todos os géneros (PT e internacional).

Playlist: "{name}"
Espírito/vibe pretendida: {vibe_line}

Faixas atuais ({len(tracks)}):
{listing}

Tarefa:
{task}

Responde APENAS com JSON válido, sem markdown à volta, neste formato exato:
{{"summary": "...", "intruders": [{{"index": 3, "reason": "..."}}], "additions": [{{"title": "...", "artist": "...", "reason": "..."}}]}}"""


def _search_url(title: str, artist: str) -> str:
    q = f"{title} {artist}".strip()
    return "https://open.spotify.com/search/" + quote(q)


def _normalize_analysis(parsed: dict, tracks: list[SpotifyTrack]) -> dict:
    summary = (parsed.get("summary") or "").strip()
    intruders_out = []
    for it in parsed.get("intruders") or []:
        if not isinstance(it, dict):
            continue
        idx = it.get("index")
        try:
            i = int(idx)
        except (TypeError, ValueError):
            continue
        if not (1 <= i <= len(tracks)):
            continue
        t = tracks[i - 1]
        intruders_out.append({
            "track_id": t.id,
            "title": t.title,
            "artist": t.artist,
            "reason": (it.get("reason") or "").strip(),
        })
    additions_out = []
    for a in parsed.get("additions") or []:
        if not isinstance(a, dict):
            continue
        title = (a.get("title") or "").strip()
        if not title:
            continue
        artist = (a.get("artist") or "").strip()
        additions_out.append({
            "title": title,
            "artist": artist,
            "reason": (a.get("reason") or "").strip(),
            "search_url": _search_url(title, artist),
        })
    return {"summary": summary, "intruders": intruders_out, "additions": additions_out}


# ── Helpers: Visão Geral (transversal a todas as playlists) ──────

import unicodedata

_DUP_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_DUP_FEAT = re.compile(r"\b(feat|ft|featuring|with|prod)\b.*", re.I)
_OVERVIEW_TRACK_CAP = 800   # teto de faixas a enviar à IA (prompt não pode crescer sem limite)


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = _DUP_BRACKETS.sub(" ", s)
    s = _DUP_FEAT.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _find_duplicates(collected: list[dict]) -> list[dict]:
    """Duplicado a sério = a MESMA faixa repetida DENTRO da mesma playlist (lixo claro).
    Estar em playlists diferentes NÃO é duplicado — uma triste tuga cabe na 'tugas' e na 'sad'.
    Determinístico (não precisa da IA). 'mortas' (indisponíveis) só com a API/Premium."""
    out = []
    for pl in collected:
        counts: dict[tuple[str, str], dict] = {}
        for t in pl["tracks"]:
            key = (_norm(t.title), _norm(t.artist))
            if not key[0]:
                continue
            entry = counts.setdefault(key, {"title": t.title, "artist": t.artist, "count": 0})
            entry["count"] += 1
        for entry in counts.values():
            if entry["count"] > 1:
                out.append({
                    "title": entry["title"],
                    "artist": entry["artist"],
                    "playlist": pl["name"],
                    "count": entry["count"],
                })
    out.sort(key=lambda d: -d["count"])
    return out


def _index_map(collected: list[dict]) -> dict[int, dict]:
    """Numera todas as faixas globalmente (1..N). A IA referencia faixas por este índice
    em vez de repetir título+artista — mantém a resposta pequena e o JSON não trunca."""
    out: dict[int, dict] = {}
    idx = 1
    for pl in collected:
        for t in pl["tracks"]:
            out[idx] = {"title": t.title, "artist": t.artist, "from": pl["name"]}
            idx += 1
    return out


def _build_overview_prompt(collected: list[dict], total_tracks: int, truncated: bool) -> str:
    blocks = []
    idx = 1
    for pl in collected:
        vibe = (pl["vibe"] or "").strip() or "(sem vibe definida)"
        tag = " [GOSTADAS]" if pl["is_favorites"] else ""
        lines = []
        for t in pl["tracks"]:
            lines.append(f"  {idx}. {t.title} — {t.artist}" if t.artist else f"  {idx}. {t.title}")
            idx += 1
        blocks.append(f'Playlist "{pl["name"]}"{tag} — vibe: {vibe} ({len(pl["tracks"])} faixas):\n' + "\n".join(lines))
    listing = "\n\n".join(blocks)
    trunc_note = (
        "\n(NOTA: a lista foi cortada por ser grande — analisa o que tens.)" if truncated else ""
    )
    return f"""És um curador musical exigente que vê a COLEÇÃO TODA de uma vez. Conheces música de todos os géneros (PT e internacional). Cada faixa tem um NÚMERO — usa sempre o número para te referires a uma faixa.

Coleção ({len(collected)} playlists, {total_tracks} faixas no total):{trunc_note}

{listing}

Tarefa (visão global, NÃO playlist a playlist):
1. GROUPS: agrupa as músicas por GÉNERO/MOOD reais (ex: "Treino/Hype", "Triste/Chill", "Rap PT", "Verão"). Para cada grupo dá: "name" (o género, curto), "playlist_name" (um nome giro e curto para a playlist, estilo Spotify — ex: "Sad Hours", "Bangers", "Tuga Bars") e "mood" (uma frase). Cria os grupos que fizerem sentido (tipicamente 4 a 8).
2. ASSIGNMENTS: para CADA faixa, diz a que grupo pertence — um par {{"i": número da faixa, "g": índice do grupo (0-based na lista groups)}}. Classifica todas as faixas.
3. RELOCATIONS: faixas que estão numa playlist mas encaixavam claramente melhor noutra EXISTENTE. Para cada: {{"i": número da faixa, "to": nome da playlist destino, "reason": curta}}. Só as óbvias; se não houver, [].
4. SUMMARY: 2-3 frases sobre o estado da coleção (que géneros dominam, o que está misturado, o que falta).

Não trates de duplicados — isso já é tratado à parte.

Responde APENAS com JSON válido, sem markdown à volta, neste formato exato:
{{"summary": "...", "groups": [{{"name": "...", "playlist_name": "...", "mood": "..."}}], "assignments": [{{"i": 1, "g": 0}}], "relocations": [{{"i": 3, "to": "...", "reason": "..."}}]}}"""


def _normalize_overview(parsed: dict, index_map: dict[int, dict]) -> dict:
    summary = (parsed.get("summary") or "").strip()

    groups = []
    for g in parsed.get("groups") or []:
        if not isinstance(g, dict):
            continue
        name = (g.get("name") or "").strip()
        groups.append({
            "name": name,
            "playlist_name": (g.get("playlist_name") or "").strip(),
            "mood": (g.get("mood") or "").strip(),
            "tracks": [],
            "_seen": set(),
        })

    def _ref(i):
        try:
            return index_map.get(int(i))
        except (TypeError, ValueError):
            return None

    for a in parsed.get("assignments") or []:
        if not isinstance(a, dict):
            continue
        ref = _ref(a.get("i"))
        if ref is None:
            continue
        try:
            g = int(a.get("g"))
        except (TypeError, ValueError):
            continue
        if 0 <= g < len(groups):
            key = (_norm(ref["title"]), _norm(ref["artist"]))   # dedup: a mesma música só uma vez por grupo
            if key in groups[g]["_seen"]:
                continue
            groups[g]["_seen"].add(key)
            groups[g]["tracks"].append({"title": ref["title"], "artist": ref["artist"], "from": ref["from"]})

    groups_out = [{"name": g["name"], "playlist_name": g["playlist_name"], "mood": g["mood"], "tracks": g["tracks"]}
                  for g in groups if g["name"] and g["tracks"]]

    relocations_out = []
    for r in parsed.get("relocations") or []:
        if not isinstance(r, dict):
            continue
        ref = _ref(r.get("i"))
        if ref is None:
            continue
        to = (r.get("to") or "").strip()
        if not to or to == ref["from"]:
            continue
        relocations_out.append({
            "title": ref["title"], "artist": ref["artist"],
            "from": ref["from"], "to": to, "reason": (r.get("reason") or "").strip(),
        })

    return {"summary": summary, "groups": groups_out, "relocations": relocations_out}


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/playlists")
def list_playlists():
    db: Session = SessionLocal()
    try:
        playlists = db.query(SpotifyPlaylist).order_by(SpotifyPlaylist.created_at.desc()).all()
        out = []
        for p in playlists:
            count = db.query(SpotifyTrack).filter(SpotifyTrack.playlist_id == p.id).count()
            out.append(_playlist_out(p, count))
        return out
    finally:
        db.close()


@router.post("/playlists")
def create_playlist(data: PlaylistIn):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome vazio")
    db: Session = SessionLocal()
    try:
        p = SpotifyPlaylist(name=name, vibe=(data.vibe or "").strip(), is_favorites=bool(data.is_favorites))
        db.add(p)
        db.commit()
        db.refresh(p)
        return _playlist_out(p, 0)
    finally:
        db.close()


@router.patch("/playlists/{playlist_id}")
def update_playlist(playlist_id: int, data: PlaylistPatch):
    db: Session = SessionLocal()
    try:
        p = db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id == playlist_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Playlist não encontrada")
        if data.name is not None:
            name = data.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Nome vazio")
            p.name = name
        if data.vibe is not None:
            p.vibe = data.vibe.strip()
        if data.is_favorites is not None:
            if data.is_favorites:
                # só uma playlist é a das gostadas → desmarca as outras
                db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id != p.id).update(
                    {SpotifyPlaylist.is_favorites: False}
                )
            p.is_favorites = data.is_favorites
        db.commit()
        db.refresh(p)
        count = db.query(SpotifyTrack).filter(SpotifyTrack.playlist_id == p.id).count()
        return _playlist_out(p, count)
    finally:
        db.close()


@router.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: int):
    db: Session = SessionLocal()
    try:
        p = db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id == playlist_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Playlist não encontrada")
        db.query(SpotifyTrack).filter(SpotifyTrack.playlist_id == playlist_id).delete()
        db.delete(p)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.get("/playlists/{playlist_id}/tracks")
def list_tracks(playlist_id: int):
    db: Session = SessionLocal()
    try:
        p = db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id == playlist_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Playlist não encontrada")
        tracks = (
            db.query(SpotifyTrack)
            .filter(SpotifyTrack.playlist_id == playlist_id)
            .order_by(SpotifyTrack.position, SpotifyTrack.id)
            .all()
        )
        return [_track_out(t) for t in tracks]
    finally:
        db.close()


@router.post("/playlists/{playlist_id}/import")
async def import_tracks(playlist_id: int, data: ImportIn):
    if _playlist_id_from_link(data.text):
        _, parsed = await _fetch_from_link(data.text)
    else:
        parsed = _parse_import(data.text)
    if not parsed:
        raise HTTPException(status_code=400, detail="Não consegui ler faixas. Cola o link público da playlist, uma lista 'Título - Artista', ou um CSV.")
    db: Session = SessionLocal()
    try:
        p = db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id == playlist_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Playlist não encontrada")
        if data.mode == "replace":
            db.query(SpotifyTrack).filter(SpotifyTrack.playlist_id == playlist_id).delete()
            start = 0
        else:
            start = db.query(SpotifyTrack).filter(SpotifyTrack.playlist_id == playlist_id).count()
        for i, t in enumerate(parsed):
            db.add(SpotifyTrack(
                playlist_id=playlist_id,
                position=start + i,
                title=t["title"][:500],
                artist=t["artist"][:500],
                album=t["album"][:500],
                spotify_url=t["spotify_url"][:1000],
            ))
        # import muda a playlist → análise antiga deixa de valer
        p.last_analysis = ""
        p.analyzed_at = None
        db.commit()
        total = db.query(SpotifyTrack).filter(SpotifyTrack.playlist_id == playlist_id).count()
        return {"imported": len(parsed), "total": total}
    finally:
        db.close()


@router.post("/import-link")
async def import_from_link(data: ImportLinkIn):
    """Cria uma playlist nova a partir de um link público do Spotify (nome + faixas)."""
    name, parsed = await _fetch_from_link(data.url)
    db: Session = SessionLocal()
    try:
        p = SpotifyPlaylist(name=name, vibe="", is_favorites=False)
        db.add(p)
        db.flush()
        for i, t in enumerate(parsed):
            db.add(SpotifyTrack(
                playlist_id=p.id,
                position=i,
                title=t["title"][:500],
                artist=t["artist"][:500],
                album=t["album"][:500],
                spotify_url=t["spotify_url"][:1000],
            ))
        db.commit()
        db.refresh(p)
        return {"playlist": _playlist_out(p, len(parsed)), "imported": len(parsed)}
    finally:
        db.close()


@router.delete("/tracks/{track_id}")
def delete_track(track_id: int):
    db: Session = SessionLocal()
    try:
        t = db.query(SpotifyTrack).filter(SpotifyTrack.id == track_id).first()
        if not t:
            raise HTTPException(status_code=404, detail="Faixa não encontrada")
        db.delete(t)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ── Sugestões de músicas novas (por playlist) ────────────────────

def _suggestion_out(s: SpotifySuggestion) -> dict:
    return {
        "id": s.id,
        "group_name": s.group_name,
        "title": s.title,
        "artist": s.artist,
        "reason": s.reason,
        "accepted": bool(s.accepted),
        "search_url": _search_url(s.title, s.artist),
    }


@router.get("/playlists/{playlist_id}/suggestions")
def list_suggestions(playlist_id: int):
    db: Session = SessionLocal()
    try:
        p = db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id == playlist_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Playlist não encontrada")
        sugs = (
            db.query(SpotifySuggestion)
            .filter(SpotifySuggestion.playlist_id == playlist_id, SpotifySuggestion.group_name.is_(None))
            .order_by(SpotifySuggestion.id)
            .all()
        )
        return [_suggestion_out(s) for s in sugs]
    finally:
        db.close()


@router.get("/overview/group-suggestions")
def group_suggestions():
    """Todas as recomendações dos grupos de género (Visão Geral), indexadas por nome do grupo."""
    db: Session = SessionLocal()
    try:
        sugs = (
            db.query(SpotifySuggestion)
            .filter(SpotifySuggestion.group_name.isnot(None))
            .order_by(SpotifySuggestion.id)
            .all()
        )
        out: dict[str, list] = {}
        for s in sugs:
            out.setdefault(s.group_name, []).append(_suggestion_out(s))
        return out
    finally:
        db.close()


@router.post("/suggestions/{sid}/toggle")
def toggle_suggestion(sid: int):
    db: Session = SessionLocal()
    try:
        s = db.query(SpotifySuggestion).filter(SpotifySuggestion.id == sid).first()
        if not s:
            raise HTTPException(status_code=404, detail="Sugestão não encontrada")
        s.accepted = not bool(s.accepted)
        db.commit()
        db.refresh(s)
        return _suggestion_out(s)
    finally:
        db.close()


@router.get("/playlists/{playlist_id}/analysis")
def get_analysis(playlist_id: int):
    db: Session = SessionLocal()
    try:
        p = db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id == playlist_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Playlist não encontrada")
        if not p.last_analysis:
            return {"summary": "", "intruders": [], "additions": [], "analyzed_at": None}
        try:
            data = json.loads(p.last_analysis)
        except (json.JSONDecodeError, TypeError):
            data = {"summary": "", "intruders": [], "additions": []}
        data["analyzed_at"] = p.analyzed_at
        return data
    finally:
        db.close()


@router.post("/playlists/{playlist_id}/analyze")
async def analyze_playlist(playlist_id: int):
    db: Session = SessionLocal()
    try:
        p = db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id == playlist_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Playlist não encontrada")
        tracks = (
            db.query(SpotifyTrack)
            .filter(SpotifyTrack.playlist_id == playlist_id)
            .order_by(SpotifyTrack.position, SpotifyTrack.id)
            .all()
        )
        if not tracks:
            raise HTTPException(status_code=400, detail="Playlist vazia — importa faixas primeiro.")
        name, vibe, is_fav = p.name, p.vibe, bool(p.is_favorites)
        # tira os objetos da sessão para usar depois do close (só leitura)
        db.expunge_all()
    finally:
        db.close()

    prompt = _build_prompt(name, vibe, is_fav, tracks)
    text = await ask_agent_async(prompt, timeout=180.0)
    if not text:
        raise HTTPException(status_code=502, detail="IA indisponível")
    parsed = extract_json(text)
    if not isinstance(parsed, dict):
        logger.warning("Spotify analyze sem JSON: %s", text[:300])
        raise HTTPException(status_code=502, detail="Resposta da IA inválida")

    result = _normalize_analysis(parsed, tracks)

    db = SessionLocal()
    try:
        p = db.query(SpotifyPlaylist).filter(SpotifyPlaylist.id == playlist_id).first()
        if p:
            p.last_analysis = json.dumps(result, ensure_ascii=False)
            p.analyzed_at = datetime.utcnow()
            db.commit()
            result["analyzed_at"] = p.analyzed_at
    finally:
        db.close()
    return result


# ── Visão Geral (transversal) ────────────────────────────────────

def _empty_overview() -> dict:
    return {"summary": "", "groups": [], "relocations": [], "duplicates": [],
            "playlist_count": 0, "track_count": 0, "truncated": False, "analyzed_at": None}


@router.get("/overview")
def get_overview():
    db: Session = SessionLocal()
    try:
        ov = db.query(SpotifyOverview).filter(SpotifyOverview.id == 1).first()
        if not ov or not ov.last_analysis:
            return _empty_overview()
        try:
            data = json.loads(ov.last_analysis)
        except (json.JSONDecodeError, TypeError):
            return _empty_overview()
        data["analyzed_at"] = ov.analyzed_at
        return data
    finally:
        db.close()


@router.post("/overview/analyze")
async def analyze_overview():
    db: Session = SessionLocal()
    try:
        playlists = db.query(SpotifyPlaylist).order_by(SpotifyPlaylist.created_at).all()
        collected: list[dict] = []
        total_tracks = 0
        truncated = False
        for p in playlists:
            tracks = (
                db.query(SpotifyTrack)
                .filter(SpotifyTrack.playlist_id == p.id)
                .order_by(SpotifyTrack.position, SpotifyTrack.id)
                .all()
            )
            if not tracks:
                continue
            if total_tracks + len(tracks) > _OVERVIEW_TRACK_CAP:
                tracks = tracks[: max(0, _OVERVIEW_TRACK_CAP - total_tracks)]
                truncated = True
            total_tracks += len(tracks)
            collected.append({"name": p.name, "vibe": p.vibe, "is_favorites": bool(p.is_favorites), "tracks": tracks})
            if truncated:
                break
        db.expunge_all()
    finally:
        db.close()

    if total_tracks < 2:
        raise HTTPException(status_code=400, detail="Importa faixas em pelo menos uma playlist primeiro.")

    duplicates = _find_duplicates(collected)
    index_map = _index_map(collected)
    prompt = _build_overview_prompt(collected, total_tracks, truncated)
    text = await ask_agent_async(prompt, timeout=240.0)
    if not text:
        raise HTTPException(status_code=502, detail="IA indisponível")
    parsed = extract_json(text)
    if not isinstance(parsed, dict):
        logger.warning("Spotify overview sem JSON: %s", text[:300])
        raise HTTPException(status_code=502, detail="Resposta da IA inválida")

    result = _normalize_overview(parsed, index_map)
    result["duplicates"] = duplicates
    result["playlist_count"] = len(collected)
    result["track_count"] = total_tracks
    result["truncated"] = truncated

    db = SessionLocal()
    try:
        ov = db.query(SpotifyOverview).filter(SpotifyOverview.id == 1).first()
        if not ov:
            ov = SpotifyOverview(id=1)
            db.add(ov)
        ov.last_analysis = json.dumps(result, ensure_ascii=False)
        ov.analyzed_at = datetime.utcnow()
        db.commit()
        result["analyzed_at"] = ov.analyzed_at
    finally:
        db.close()
    return result
