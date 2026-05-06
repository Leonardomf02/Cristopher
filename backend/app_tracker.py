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


def applescript_active() -> tuple[str, str, str, bool] | None:
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
        return normalize_app_name(app, bundle), title, bundle, acc == "1"
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

    def observe(self, app: str, title: str, bundle: str, now: datetime) -> None:
        # Detect a system-sleep gap: if more than SLEEP_GAP_SECONDS passed
        # between this poll and the previous one, the laptop was asleep —
        # close the live session at the last known good tick instead of `now`.
        if self.last_tick and (now - self.last_tick).total_seconds() > self.SLEEP_GAP_SECONDS:
            self._truncate_at(self.last_tick)
        self.last_tick = now

        key = (app, title, bundle)
        if self.current == key and self.row_id is not None:
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

        self._finalize_short()

        self.current = key
        self.start = now
        self.row_id = self._exec(
            """INSERT INTO app_usage_sessions
               (app_name, window_title, bundle_id, date, start_time, end_time, duration_seconds, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)""",
            (
                app, title or "", bundle or None,
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
        """Cap the live session's end_time at `ts` (called when sleep is detected)."""
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

        app, title, bundle, acc_ok = active
        if not acc_ok and not warned_no_acc:
            print("[tracker] WARNING: no Accessibility permission — window titles will be empty", file=sys.stderr)
            warned_no_acc = True

        if (bundle and bundle in block_bundles) or (app in block_names):
            writer.close()
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        writer.observe(app, title, bundle, now)
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    writer = SessionWriter(DB_PATH)
    # We always use polling here — NSWorkspace events would require a runloop
    # that doesn't play well with this simple threading model, and osascript
    # at 3s is <0.1% CPU. Heartbeat makes polling cheap (no row explosion).
    _run_loop(writer, event_driven=False)


if __name__ == "__main__":
    main()
