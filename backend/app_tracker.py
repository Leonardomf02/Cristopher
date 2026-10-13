"""
macOS active-window tracker.

Architecture
------------
- Event-driven when pyobjc is available: NSWorkspace posts a notification
  on active app change; we update the in-memory session immediately.
- Falls back to polling (osascript) when pyobjc is missing.
- Window title is refreshed by a timer (osascript, cheap).
- Writes directly to the SQLite DB — the backend does not need to be up.
- Uses the heartbeat pattern: one DB row per (app, window) session,
  UPDATE'd on every tick; a new row is inserted only when the active
  app/window changes. No 60-second chunking, no row explosion.
- Blocklist + idle detection applied before any write.
"""
from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

POLL_INTERVAL_SECONDS = int(os.environ.get("TRACKER_POLL", "3"))
MIN_SESSION_SECONDS = int(os.environ.get("TRACKER_MIN", "10"))
# Rede de segurança: mesmo que a detecção de inactividade falhe (o `ioreg` pode
# rebentar e devolver "0s inactivo"), nenhuma sessão passa daqui sem ser cortada.
MAX_SESSION_SECONDS = int(os.environ.get("TRACKER_MAX_SESSION", str(90 * 60)))
# Música: perguntar ao Spotify de 15 em 15s chega para não perder faixas curtas
# sem encher o Mac de chamadas AppleScript.
MUSIC_TRACKING = os.environ.get("TRACKER_MUSIC", "1") == "1"
MUSIC_POLL_SECONDS = int(os.environ.get("TRACKER_MUSIC_POLL", "15"))
# Paragens abaixo disto não são ir dormir (bloquear o ecrã para ir almoçar, por
# exemplo); acima disto vale a pena guardar como candidato a noite.
PARAGEM_MINIMA_MIN = int(os.environ.get("TRACKER_MIN_PARAGEM", "25"))
IDLE_THRESHOLD_SECONDS = int(os.environ.get("TRACKER_IDLE", "180"))

DB_PATH = os.environ.get(
    "TRACKER_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "cristopher.db"),
)

APPLESCRIPT_FULL = '''
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set bundleID to bundle identifier of frontApp
    set accOk to "1"
    try
        set windowTitle to name of front window of frontApp
        if windowTitle is missing value then set windowTitle to ""
    on error
        set windowTitle to ""
        set accOk to "0"
    end try
end tell
return appName & "|||" & windowTitle & "|||" & bundleID & "|||" & accOk
'''

BUNDLE_NAME_OVERRIDES = {
    "com.microsoft.VSCode": "Visual Studio Code",
    "org.mozilla.firefox": "Firefox",
    "com.google.Chrome": "Google Chrome",
    "com.apple.Safari": "Safari",
    "com.tinyspeck.slackmacgap": "Slack",
    "com.riotgames.LeagueofLegends.GameClient": "League of Legends",
    "com.riotgames.LeagueofLegends.LeagueClient": "League Client",
    "com.hnc.Discord": "Discord",
    "com.spotify.client": "Spotify",
    "com.apple.Terminal": "Terminal",
    "com.apple.finder": "Finder",
    "com.apple.systempreferences": "System Settings",
}


def normalize_app_name(app: str, bundle: str) -> str:
    if bundle and bundle in BUNDLE_NAME_OVERRIDES:
        return BUNDLE_NAME_OVERRIDES[bundle]
    if app and app.islower() and " " not in app:
        return app.capitalize()
    return app


def get_idle_seconds() -> float:
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True, text=True, timeout=3,
        )
        for line in out.stdout.splitlines():
            if '"HIDIdleTime"' in line:
                ns = int(line.split("=")[-1].strip())
                return ns / 1_000_000_000
    except Exception:
        pass
    return 0.0


# Em ecrã inteiro (vídeo, por exemplo) o System Events não consegue ler o nome da
# janela e o título vinha vazio — eram 85h/mês de browser sem se saber o que era.
# Os browsers expõem o tab activo por AppleScript próprio, que funciona sempre e
# ainda dá o URL (melhor pista que o título).
BROWSER_TAB_SCRIPTS = {
    "com.brave.Browser": 'tell application "Brave Browser" to return (title of active tab of front window) & "|||" & (URL of active tab of front window)',
    "com.google.Chrome": 'tell application "Google Chrome" to return (title of active tab of front window) & "|||" & (URL of active tab of front window)',
    "com.microsoft.edgemac": 'tell application "Microsoft Edge" to return (title of active tab of front window) & "|||" & (URL of active tab of front window)',
    "com.apple.Safari": 'tell application "Safari" to return (name of front document) & "|||" & (URL of front document)',
}


SPOTIFY_SCRIPT = (
    'tell application "System Events" to set aberto to (name of processes) contains "Spotify"\n'
    'if not aberto then return ""\n'
    'tell application "Spotify"\n'
    '  if player state is not playing then return ""\n'
    '  return (name of current track) & "|||" & (artist of current track) & "|||" & '
    '(album of current track) & "|||" & (id of current track) & "|||" & (duration of current track)\n'
    'end tell'
)


def spotify_now() -> tuple[str, str, str, str, int] | None:
    """O que o Spotify está a tocar AGORA, mesmo em segundo plano.

    A janela activa só conta a música quando o Spotify está à frente — que é
    quase nunca. Perguntando à aplicação apanha-se o que toca enquanto ele
    programa ou joga, que é o interessante."""
    try:
        out = subprocess.run(["osascript", "-e", SPOTIFY_SCRIPT],
                             capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return None
        linha = out.stdout.strip()
        if not linha:
            return None
        partes = linha.split("|||")
        if len(partes) < 5 or not partes[0].strip():
            return None
        # A conta grátis mete anúncios no meio, e o Spotify apresenta-os como se
        # fossem faixas: "Curta músicas sem anúncios." aparecia no histórico como
        # a música mais ouvida do mês. O id trai-os (spotify:ad:…).
        if partes[3].strip().startswith("spotify:ad:"):
            return None
        try:
            dur_ms = int(float(partes[4]))
        except ValueError:
            dur_ms = 0
        return partes[0].strip(), partes[1].strip(), partes[2].strip(), partes[3].strip(), dur_ms // 1000
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return None


class MusicWriter:
    """Grava uma linha por música ouvida, esticando enquanto a mesma continua."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.row_id: int | None = None
        self.atual: str | None = None
        self.inicio: datetime | None = None

    def close(self) -> None:
        self.row_id = None
        self.atual = None
        self.inicio = None

    def observe(self, now: datetime) -> None:
        info = spotify_now()
        if not info:
            self.close()          # em pausa ou fechado: a música actual acabou
            return
        nome, artista, album, sid, dur = info
        chave = sid or f"{nome}|{artista}"
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            if chave == self.atual and self.row_id is not None:
                segundos = int((now - self.inicio).total_seconds()) if self.inicio else 0
                conn.execute(
                    "UPDATE spotify_plays SET ended_at=?, seconds=? WHERE id=?",
                    (now.isoformat(sep=" ", timespec="seconds"), segundos, self.row_id),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO spotify_plays
                       (track, artist, album, spotify_id, date, started_at, ended_at,
                        seconds, track_seconds, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, CURRENT_TIMESTAMP)""",
                    (nome[:200], artista[:120], album[:160], sid[:80] or None,
                     now.date().isoformat(), now.isoformat(sep=" ", timespec="seconds"),
                     now.isoformat(sep=" ", timespec="seconds"), dur or None),
                )
                self.row_id = cur.lastrowid
                self.atual = chave
                self.inicio = now
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"[tracker] spotify write error: {e}", file=sys.stderr)


def dominio_do_url(url: str) -> str:
    """youtube.com a partir de https://www.youtube.com/watch?v=… ('' se não der).

    Só o domínio: o caminho e os parâmetros ficam de fora de propósito — dizem
    pouco sobre a categoria e trazem tokens de sessão para dentro da base."""
    from urllib.parse import urlparse

    try:
        rede = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    rede = rede.split("@")[-1].split(":")[0]
    if rede.startswith("www."):
        rede = rede[4:]
    return rede[:120]


def browser_tab_info(bundle: str) -> tuple[str, str]:
    """(título, domínio) do tab activo. ('', '') se não der.

    O domínio é a melhor pista que existe sobre o que se está a fazer — muito
    melhor que o título, que muda a cada vídeo e que em ecrã inteiro nem sequer
    aparece. Era lido e deitado fora: 258h de browser ficaram reduzidas a 1970
    títulos soltos quando são umas dezenas de sites."""
    script = BROWSER_TAB_SCRIPTS.get(bundle or "")
    if not script:
        return "", ""
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
        if out.returncode != 0:
            return "", ""
        partes = out.stdout.strip().split("|||")
        titulo = partes[0].strip() if partes else ""
        url = partes[1].strip() if len(partes) > 1 else ""
        dominio = dominio_do_url(url) if url else ""
        return (titulo or dominio), dominio
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "", ""


def applescript_active() -> tuple[str, str, str, str, bool] | None:
    """(app, título, bundle, domínio, permissão de acessibilidade)."""
    try:
        out = subprocess.run(
            ["osascript", "-e", APPLESCRIPT_FULL],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode != 0:
            return None
        parts = out.stdout.strip().split("|||")
        if len(parts) < 4:
            return None
        app, title, bundle, acc = parts
        if not app:
            return None
        dominio = ""
        if bundle in BROWSER_TAB_SCRIPTS:
            # Sempre, não só quando o título falta: é o domínio que interessa
            # guardar, e vem da mesma chamada.
            do_tab, dominio = browser_tab_info(bundle)
            if not title.strip():
                title = do_tab
        return normalize_app_name(app, bundle), title, bundle, dominio, acc == "1"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


# ── DB helpers ────────────────────────────────────────────────────

def load_blocklist() -> tuple[set[str], set[str]]:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        rows = conn.execute("SELECT bundle_id, app_name FROM app_usage_blocklist").fetchall()
        conn.close()
        bundles = {r[0] for r in rows if r[0]}
        names = {r[1] for r in rows if r[1]}
        return bundles, names
    except sqlite3.Error:
        return set(), set()


def grava_paragem(db_path: str, adormeceu: datetime, acordou: datetime,
                  origem: str = "tracker", detalhe: str = "") -> None:
    """Guarda um intervalo em que a máquina esteve parada. Só interessam as
    paragens longas — as curtas são o ecrã a bloquear, não ir dormir."""
    minutos = int((acordou - adormeceu).total_seconds() / 60)
    if minutos < PARAGEM_MINIMA_MIN:
        return
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute(
            """INSERT OR IGNORE INTO power_events
               (slept_at, woke_at, minutes, source, detail, created_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (adormeceu.isoformat(sep=" ", timespec="seconds"),
             acordou.isoformat(sep=" ", timespec="seconds"), minutos, origem, detalhe[:120]),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[tracker] power event error: {e}", file=sys.stderr)


def importa_pmset(db_path: str) -> int:
    """Traz do registo de energia do macOS as paragens dos últimos dias.

    O `pmset` só guarda poucos dias, mas chega para preencher o que aconteceu
    enquanto o tracker esteve desligado."""
    import re
    try:
        out = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return 0
    eventos: list[tuple[datetime, str, str]] = []
    padrao = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+[+-]\d{4}\s+(Sleep|Wake)\s+(.*)")
    for linha in out.splitlines():
        m = padrao.match(linha)
        if not m:
            continue
        quando = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        tipo, desc = m.group(2), m.group(3)
        # DarkWake é manutenção do sistema, não é a pessoa a mexer no Mac
        if tipo == "Wake" and "UserActivity" not in desc:
            continue
        eventos.append((quando, tipo, desc))
    eventos.sort()
    n = 0
    for (t1, k1, _), (t2, k2, d2) in zip(eventos, eventos[1:]):
        if k1 == "Sleep" and k2 == "Wake":
            antes = n
            grava_paragem(db_path, t1, t2, "pmset", d2.split("due to")[-1].strip()[:60])
            n += 1 if antes == n else 0
    return n


class SessionWriter:
    """Heartbeat writer — one row per (app, window) session, updated in place."""

    SLEEP_GAP_SECONDS = 60  # gap larger than this → assume system was asleep

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.row_id: int | None = None
        self.current: tuple[str, str, str] | None = None  # (app, title, bundle)
        self.start: datetime | None = None
        self.last_tick: datetime | None = None

    def _exec(self, sql: str, params: tuple) -> int:
        conn = sqlite3.connect(self.db_path, timeout=5)
        cur = conn.execute(sql, params)
        rowid = cur.lastrowid
        conn.commit()
        conn.close()
        return rowid or 0

    def _delete(self, row_id: int) -> None:
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.execute("DELETE FROM app_usage_sessions WHERE id=?", (row_id,))
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass

    def observe(self, app: str, title: str, bundle: str, now: datetime, domain: str = "") -> None:
        # Detect a system-sleep gap: if more than SLEEP_GAP_SECONDS passed
        # between this poll and the previous one, the laptop was asleep —
        # close the live session at the last known good tick instead of `now`.
        if self.last_tick and (now - self.last_tick).total_seconds() > self.SLEEP_GAP_SECONDS:
            grava_paragem(self.db_path, self.last_tick, now, "tracker")
            self._truncate_at(self.last_tick)
        self.last_tick = now

        key = (app, title, bundle, domain)
        muito_longa = bool(self.start and (now - self.start).total_seconds() > MAX_SESSION_SECONDS)
        if self.current == key and self.row_id is not None and not muito_longa:
            duration = int((now - self.start).total_seconds()) if self.start else 0
            try:
                conn = sqlite3.connect(self.db_path, timeout=5)
                conn.execute(
                    "UPDATE app_usage_sessions SET end_time=?, duration_seconds=? WHERE id=?",
                    (now.isoformat(sep=" ", timespec="seconds"), duration, self.row_id),
                )
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                print(f"[tracker] update error: {e}", file=sys.stderr)
            return

        if muito_longa:
            self._truncate_at(now)      # parte em duas em vez de crescer sem fim

        self._finalize_short()

        self.current = key
        self.start = now
        self.row_id = self._exec(
            """INSERT INTO app_usage_sessions
               (app_name, window_title, bundle_id, domain, date, start_time, end_time, duration_seconds, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)""",
            (
                app, title or "", bundle or None, domain or None,
                now.date().isoformat(),
                now.isoformat(sep=" ", timespec="seconds"),
                now.isoformat(sep=" ", timespec="seconds"),
            ),
        )

    def _finalize_short(self) -> None:
        """Drop the just-ended session if it was shorter than MIN_SESSION_SECONDS."""
        if self.row_id is None or self.start is None:
            return
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            row = conn.execute(
                "SELECT duration_seconds FROM app_usage_sessions WHERE id=?", (self.row_id,)
            ).fetchone()
            conn.close()
            if row and row[0] < MIN_SESSION_SECONDS:
                self._delete(self.row_id)
        except sqlite3.Error:
            pass

    def _truncate_at(self, ts: datetime) -> None:
        """Fecha a sessão viva em `ts` (Mac adormecido ou parado).

        O estado é limpo no fim: sem isso, o próximo `observe` da MESMA janela
        reconhecia a sessão como "a mesma" e voltava a esticá-la até ao presente,
        desfazendo o corte. Era assim que o tracker registava 9h de "Brave" durante
        a noite inteira em que ele estava a dormir."""
        if self.row_id is None or self.start is None:
            self.current = None
            self.row_id = None
            self.start = None
            return
        duration = max(0, int((ts - self.start).total_seconds()))
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.execute(
                "UPDATE app_usage_sessions SET end_time=?, duration_seconds=? WHERE id=?",
                (ts.isoformat(sep=" ", timespec="seconds"), duration, self.row_id),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"[tracker] truncate error: {e}", file=sys.stderr)
        self._finalize_short()
        self.current = None
        self.row_id = None
        self.start = None
        self.current = None
        self.row_id = None
        self.start = None

    def close(self) -> None:
        self._finalize_short()
        self.current = None
        self.row_id = None
        self.start = None
        self.last_tick = None


# ── Main loop ─────────────────────────────────────────────────────

def _run_loop(writer: SessionWriter, event_driven: bool) -> None:
    print(f"[tracker] started (mode={'event-driven' if event_driven else 'polling'}, poll={POLL_INTERVAL_SECONDS}s)")
    warned_no_acc = False
    was_idle = False
    try:
        importa_pmset(writer.db_path)
    except Exception as e:      # noqa: BLE001 — o tracker não pode morrer por isto
        print(f"[tracker] pmset import falhou: {e}", file=sys.stderr)
    musica = MusicWriter(writer.db_path) if MUSIC_TRACKING else None
    ultima_musica = 0.0
    block_bundles, block_names = load_blocklist()
    last_blocklist_refresh = time.time()

    def flush_and_exit(*_):
        writer.close()
        print("[tracker] stopped")
        sys.exit(0)

    signal.signal(signal.SIGTERM, flush_and_exit)
    signal.signal(signal.SIGINT, flush_and_exit)

    while True:
        now = datetime.now()

        # Refresh blocklist every 30s (cheap)
        if time.time() - last_blocklist_refresh > 30:
            block_bundles, block_names = load_blocklist()
            last_blocklist_refresh = time.time()

        # A música continua a tocar mesmo com ele longe do Mac, por isso é lida
        # antes da verificação de inactividade.
        if musica and time.time() - ultima_musica >= MUSIC_POLL_SECONDS:
            ultima_musica = time.time()
            musica.observe(now)

        if get_idle_seconds() >= IDLE_THRESHOLD_SECONDS:
            if not was_idle:
                writer.close()
                print("[tracker] idle — paused")
                was_idle = True
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        if was_idle:
            print("[tracker] active again")
            was_idle = False
            writer.last_tick = None  # don't trigger sleep-gap detection on resume

        active = applescript_active()
        if active is None:
            writer.close()
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        app, title, bundle, dominio, acc_ok = active
        if not acc_ok and not warned_no_acc:
            print("[tracker] WARNING: no Accessibility permission — window titles will be empty", file=sys.stderr)
            warned_no_acc = True

        if (bundle and bundle in block_bundles) or (app in block_names):
            writer.close()
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        writer.observe(app, title, bundle, now, dominio)
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    writer = SessionWriter(DB_PATH)
    # We always use polling here — NSWorkspace events would require a runloop
    # that doesn't play well with this simple threading model, and osascript
    # at 3s is <0.1% CPU. Heartbeat makes polling cheap (no row explosion).
    _run_loop(writer, event_driven=False)


if __name__ == "__main__":
    main()
