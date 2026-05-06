"""VS Code activity tracker.

Reads VS Code's Local History (the per-file save snapshots VS Code keeps under
~/Library/Application Support/Code/User/History/) and turns it into a daily
summary of which files were edited in which projects.

No git required — VS Code stores a snapshot on every save automatically."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import date as date_type, datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict
from urllib.parse import unquote
import difflib
import httpx
import json
import os
import re
import uuid
import logging

from database import get_db
from models import CodeProjectTodo, CodeProjectNote, CodeFileSnapshot
from ai_config import AI_API_URL, AI_API_KEY, AI_CHANNEL_ID
import hashlib

router = APIRouter(prefix="/api/code-activity", tags=["CodeActivity"])
logger = logging.getLogger(__name__)


HOME = Path.home()
VSCODE_HISTORY_DIRS = [
    HOME / "Library" / "Application Support" / "Code" / "User" / "History",
    HOME / "Library" / "Application Support" / "Code - Insiders" / "User" / "History",
    HOME / ".vscode-server" / "data" / "User" / "History",  # remote / linux fallback
]

# Roots scanned for direct filesystem mtime changes (catches edits made outside the
# VS Code UI — e.g. via Claude Code, terminal editors, AI assistants — which never
# touch VS Code's Local History).
FS_SCAN_ROOTS = [
    HOME / "Documents" / "Projects",
    HOME / "Documents" / "Uni",
    HOME / "IdeaProjects",
]
FS_SCAN_IGNORE_DIR_NAMES = {
    "node_modules", "venv", ".venv", "env", ".env", "__pycache__",
    ".git", ".hg", ".svn", ".idea", ".vscode", ".next", ".nuxt", ".cache",
    "dist", "build", "out", "target", "bin", "obj", ".gradle", ".mvn",
    "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "DerivedData", ".DS_Store",
}
FS_SCAN_CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".java", ".kt", ".scala", ".groovy",
    ".rs", ".go", ".rb", ".php", ".cs", ".swift", ".m", ".mm",
    ".c", ".cc", ".cpp", ".h", ".hpp",
    ".html", ".css", ".scss", ".sass", ".less",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".env",
    ".md", ".sql", ".sh", ".zsh", ".bash", ".dockerfile",
}

# Strong markers (real "project" boundary). Prefer these.
STRONG_MARKERS = {".git", ".gitignore", ".hg", ".svn"}
# Weak markers (build target — could be a sub-component of a larger project).
WEAK_MARKERS = {"package.json", "pom.xml", "Cargo.toml", "go.mod",
                "pyproject.toml", "build.gradle", "build.gradle.kts",
                "requirements.txt", "Gemfile", "composer.json"}

# Cache: directory path → project root path (or "" if not in any project)
_project_cache: dict[str, str] = {}


def _find_project_root(file_path: Path) -> Optional[Path]:
    """Walk up from file_path to HOME, picking the deepest STRONG-marker dir if any,
    otherwise the deepest WEAK-marker dir. Cached per directory."""
    d = file_path.parent
    home_str = str(HOME)
    visited: list[Path] = []
    strong_hit: Optional[Path] = None
    weak_hit: Optional[Path] = None
    while True:
        s = str(d)
        if s in _project_cache:
            cached = _project_cache[s]
            for v in visited:
                _project_cache[str(v)] = cached
            return Path(cached) if cached else None
        if not s.startswith(home_str) or s == home_str:
            chosen = strong_hit or weak_hit
            if chosen:
                chosen_s = str(chosen)
                chosen_prefix = chosen_s + os.sep
                for v in visited + [d]:
                    v_s = str(v)
                    if v_s == chosen_s or v_s.startswith(chosen_prefix):
                        _project_cache[v_s] = chosen_s
            return chosen
        try:
            entries = {p.name for p in d.iterdir()}
        except (PermissionError, FileNotFoundError):
            entries = set()
        if entries & STRONG_MARKERS:
            strong_hit = d  # remember deepest strong; keep walking to find shallower? no — we want deepest, which we hit first walking up
            # Actually walking up, the FIRST strong hit is the DEEPEST. Stop here.
            for v in visited + [d]:
                _project_cache[str(v)] = str(d)
            return d
        if entries & WEAK_MARKERS and weak_hit is None:
            # Monorepo heuristic: if a sibling also carries a marker, prefer the parent.
            parent = d.parent
            has_sibling_marker = False
            if str(parent).startswith(home_str) and parent != HOME:
                try:
                    for sib in parent.iterdir():
                        if sib == d or not sib.is_dir():
                            continue
                        try:
                            sib_entries = {p.name for p in sib.iterdir()}
                        except (PermissionError, FileNotFoundError):
                            continue
                        if sib_entries & (WEAK_MARKERS | STRONG_MARKERS):
                            has_sibling_marker = True
                            break
                except (PermissionError, FileNotFoundError):
                    pass
            weak_hit = parent if has_sibling_marker else d
        visited.append(d)
        d = d.parent


def _project_label(root: Optional[Path], file_path: Path) -> tuple[str, str]:
    """Return (project_name, project_path_relative_to_home)."""
    if root is None:
        return ("Outros", "")
    try:
        rel = root.relative_to(HOME)
        return (root.name, str(rel))
    except ValueError:
        return (root.name, str(root))


def _scan_history_for_date(target: date_type) -> dict:
    """Walk VS Code History and collect entries with timestamps on `target` (local date)."""
    day_start = datetime.combine(target, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    start_ms = int(day_start.timestamp() * 1000)
    end_ms = int(day_end.timestamp() * 1000)

    # project_path → { name, files: { abs_path → { saves, sources, last_ts } } }
    projects: dict[str, dict] = {}
    total_saves = 0
    files_seen: set[str] = set()
    sample_dir_used: Optional[str] = None

    for hdir in VSCODE_HISTORY_DIRS:
        if not hdir.exists():
            continue
        sample_dir_used = str(hdir)
        for entry_dir in hdir.iterdir():
            if not entry_dir.is_dir():
                continue
            entries_json = entry_dir / "entries.json"
            if not entries_json.exists():
                continue
            try:
                data = json.loads(entries_json.read_text())
            except (OSError, json.JSONDecodeError):
                continue

            resource = data.get("resource", "")
            if not resource.startswith("file://"):
                continue
            abs_path = unquote(resource[len("file://"):])
            file_p = Path(abs_path)

            day_entries = [
                e for e in data.get("entries", [])
                if start_ms <= e.get("timestamp", 0) < end_ms
            ]
            if not day_entries:
                continue

            root = _find_project_root(file_p)
            name, key = _project_label(root, file_p)
            key = key or "_outros"
            if key not in projects:
                projects[key] = {"name": name, "path": key, "files": {}}
            files = projects[key]["files"]
            if abs_path not in files:
                rel_path = file_p.name
                if root:
                    try:
                        rel_path = str(file_p.relative_to(root))
                    except ValueError:
                        pass
                files[abs_path] = {
                    "abs_path": abs_path,
                    "rel_path": rel_path,
                    "filename": file_p.name,
                    "saves": 0,
                    "sources": [],
                    "last_ts": 0,
                    "entry_dir": str(entry_dir),
                }
            f = files[abs_path]
            f["saves"] += len(day_entries)
            f["last_ts"] = max(f["last_ts"], max(e["timestamp"] for e in day_entries))
            for e in day_entries:
                src = e.get("source") or ""
                if src and src not in f["sources"]:
                    f["sources"].append(src)
            total_saves += len(day_entries)
            files_seen.add(abs_path)

    # Augment with direct filesystem mtime scan (catches edits done outside VS Code,
    # e.g. via Claude Code / terminal editors). For files VS Code already tracked
    # we just refresh last_ts; for new ones we register a synthetic save.
    fs_total_added = 0
    for root_dir in FS_SCAN_ROOTS:
        if not root_dir.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in FS_SCAN_IGNORE_DIR_NAMES and not d.startswith(".")]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in FS_SCAN_CODE_EXTS:
                    continue
                abs_path = os.path.join(dirpath, fname)
                try:
                    mtime = os.path.getmtime(abs_path)
                except OSError:
                    continue
                ts_ms = int(mtime * 1000)
                if not (start_ms <= ts_ms < end_ms):
                    continue
                file_p = Path(abs_path)
                root = _find_project_root(file_p)
                name, key = _project_label(root, file_p)
                key = key or "_outros"
                if key not in projects:
                    projects[key] = {"name": name, "path": key, "files": {}}
                files = projects[key]["files"]
                if abs_path in files:
                    f = files[abs_path]
                    f["last_ts"] = max(f["last_ts"], ts_ms)
                    if "fs" not in f["sources"]:
                        f["sources"].insert(0, "fs")
                else:
                    rel_path = file_p.name
                    if root:
                        try:
                            rel_path = str(file_p.relative_to(root))
                        except ValueError:
                            pass
                    files[abs_path] = {
                        "abs_path": abs_path,
                        "rel_path": rel_path,
                        "filename": file_p.name,
                        "saves": 1,
                        "sources": ["fs"],
                        "last_ts": ts_ms,
                    }
                    total_saves += 1
                    fs_total_added += 1
                    files_seen.add(abs_path)

    # Convert dict-of-dicts to sorted lists
    project_list = []
    for p in projects.values():
        files_list = sorted(p["files"].values(), key=lambda f: -f["saves"])
        # Trim noisy source list per file
        for f in files_list:
            f["sources"] = f["sources"][:5]
        total = sum(f["saves"] for f in files_list)
        project_list.append({
            "name": p["name"],
            "path": p["path"],
            "saves": total,
            "files_count": len(files_list),
            "files": files_list,
            "last_ts": max((f["last_ts"] for f in files_list), default=0),
        })
    project_list.sort(key=lambda p: -p["saves"])

    return {
        "date": target.isoformat(),
        "total_saves": total_saves,
        "total_files": len(files_seen),
        "projects": project_list,
        "history_dir": sample_dir_used,
        "fs_added": fs_total_added,
    }


def _snapshot_today_files(db: Session, summary: dict) -> int:
    """For each file detected in today's scan, capture a snapshot if content changed.
    This builds up baselines over time so future days have reliable diffs."""
    inserted = 0
    for project in summary.get("projects", []):
        for f in project.get("files", []):
            try:
                if take_snapshot(db, project["path"], f["abs_path"]):
                    inserted += 1
            except Exception as e:
                logger.warning(f"snapshot failed for {f.get('abs_path')}: {e}")
    if inserted:
        try:
            db.commit()
        except Exception:
            db.rollback()
    return inserted


@router.get("/")
def get_activity(target_date: Optional[str] = Query(None, alias="date"), db: Session = Depends(get_db)):
    """Return code activity summary for a given date (defaults to today).
    As a side effect, snapshots today's modified files so future notes have baselines."""
    if target_date:
        try:
            d = date_type.fromisoformat(target_date)
        except ValueError:
            d = date_type.today()
    else:
        d = date_type.today()
    summary = _scan_history_for_date(d)
    if d == date_type.today():
        _snapshot_today_files(db, summary)
    return summary


@router.get("/range")
def get_activity_range(days: int = Query(7, ge=1, le=60)):
    """Return per-day totals for the last `days` days (oldest → newest)."""
    today = date_type.today()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        summary = _scan_history_for_date(d)
        out.append({
            "date": d.isoformat(),
            "total_saves": summary["total_saves"],
            "total_files": summary["total_files"],
            "project_count": len(summary["projects"]),
        })
    return {"days": out}


# ── TODOs / Notes per project ───────────────────────────────────

class TodoIn(BaseModel):
    content: str

class TodoPatch(BaseModel):
    content: Optional[str] = None
    done: Optional[bool] = None

class NoteIn(BaseModel):
    content: str
    note_date: Optional[date_type] = None

class NoteOut(BaseModel):
    id: int
    project_path: str
    content: str
    source: str
    note_date: Optional[date_type]
    created_at: datetime
    class Config:
        from_attributes = True

class TodoOut(BaseModel):
    id: int
    project_path: str
    content: str
    done: bool
    created_at: datetime
    done_at: Optional[datetime]
    class Config:
        from_attributes = True


def _decode_path(project_path: str) -> str:
    """Project paths can contain '/' so frontend URL-encodes them."""
    return unquote(project_path)


@router.get("/projects/{project_path:path}/todos", response_model=list[TodoOut])
def list_todos(project_path: str, db: Session = Depends(get_db)):
    pp = _decode_path(project_path)
    return (
        db.query(CodeProjectTodo)
        .filter(CodeProjectTodo.project_path == pp)
        .order_by(CodeProjectTodo.done.asc(), CodeProjectTodo.created_at.desc())
        .all()
    )


@router.post("/projects/{project_path:path}/todos", response_model=TodoOut)
def create_todo(project_path: str, data: TodoIn, db: Session = Depends(get_db)):
    pp = _decode_path(project_path)
    content = (data.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Conteúdo vazio")
    todo = CodeProjectTodo(project_path=pp, content=content, done=False)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


@router.patch("/todos/{todo_id}", response_model=TodoOut)
def update_todo(todo_id: int, data: TodoPatch, db: Session = Depends(get_db)):
    todo = db.query(CodeProjectTodo).filter(CodeProjectTodo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404)
    if data.content is not None:
        c = data.content.strip()
        if not c:
            raise HTTPException(status_code=400, detail="Conteúdo vazio")
        todo.content = c
    if data.done is not None:
        todo.done = data.done
        todo.done_at = datetime.utcnow() if data.done else None
    db.commit()
    db.refresh(todo)
    return todo


@router.delete("/todos/{todo_id}")
def delete_todo(todo_id: int, db: Session = Depends(get_db)):
    n = db.query(CodeProjectTodo).filter(CodeProjectTodo.id == todo_id).delete()
    db.commit()
    return {"deleted": n}


@router.get("/projects/{project_path:path}/notes", response_model=list[NoteOut])
def list_notes(project_path: str, db: Session = Depends(get_db)):
    pp = _decode_path(project_path)
    return (
        db.query(CodeProjectNote)
        .filter(CodeProjectNote.project_path == pp)
        .order_by(CodeProjectNote.created_at.desc())
        .all()
    )


@router.post("/projects/{project_path:path}/notes", response_model=NoteOut)
def create_note(project_path: str, data: NoteIn, db: Session = Depends(get_db)):
    pp = _decode_path(project_path)
    content = (data.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Conteúdo vazio")
    note = CodeProjectNote(
        project_path=pp,
        content=content,
        source="manual",
        note_date=data.note_date,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    n = db.query(CodeProjectNote).filter(CodeProjectNote.id == note_id).delete()
    db.commit()
    return {"deleted": n}


def _vscode_diff_for_file(file_info: dict, day_start_ms: int, day_end_ms: int, max_diff_lines: int) -> Optional[str]:
    """Diff using VS Code's Local History snapshots. Returns None when unavailable."""
    entry_dir_str = file_info.get("entry_dir")
    if not entry_dir_str:
        return None
    entry_dir = Path(entry_dir_str)
    entries_json = entry_dir / "entries.json"
    if not entries_json.exists():
        return None
    try:
        data = json.loads(entries_json.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    entries = sorted(data.get("entries", []), key=lambda e: e.get("timestamp", 0))
    baseline = None
    target = None
    for e in entries:
        ts = e.get("timestamp", 0)
        if ts < day_start_ms:
            baseline = e
        elif day_start_ms <= ts < day_end_ms:
            target = e
    if not target:
        return None

    target_path = entry_dir / target["id"]
    if not target_path.exists():
        return None
    try:
        target_text = target_path.read_text(errors="replace")
    except OSError:
        return None

    if baseline is None:
        head = "\n".join(target_text.splitlines()[:max_diff_lines])
        return f"NEW FILE (sem baseline anterior)\n{head}"

    baseline_path = entry_dir / baseline["id"]
    try:
        baseline_text = baseline_path.read_text(errors="replace")
    except OSError:
        return None

    diff_lines = list(difflib.unified_diff(
        baseline_text.splitlines(),
        target_text.splitlines(),
        lineterm="",
        n=2,
    ))
    if not diff_lines:
        return None
    if len(diff_lines) > max_diff_lines:
        diff_lines = diff_lines[:max_diff_lines] + [f"... (+{len(diff_lines) - max_diff_lines} linhas)"]
    return "\n".join(diff_lines)


def _git_diff_for_file(abs_path: str, project_root: str, day_start_ms: int, max_diff_lines: int) -> Optional[str]:
    """Fallback diff using git: file content at the last commit before day_start vs. current working tree."""
    import subprocess
    if not project_root or not Path(project_root, ".git").exists():
        return None
    try:
        rel = str(Path(abs_path).resolve().relative_to(Path(project_root).resolve()))
    except ValueError:
        return None
    iso_before = datetime.fromtimestamp(day_start_ms / 1000).isoformat()
    try:
        sha = subprocess.run(
            ["git", "-C", project_root, "log", f"--before={iso_before}", "-1", "--pretty=format:%H", "--", rel],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if not sha:
        return None
    try:
        baseline_text = subprocess.run(
            ["git", "-C", project_root, "show", f"{sha}:{rel}"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    try:
        with open(abs_path, "r", errors="replace") as f:
            current_text = f.read()
    except OSError:
        return None
    diff_lines = list(difflib.unified_diff(
        baseline_text.splitlines(),
        current_text.splitlines(),
        lineterm="",
        n=2,
    ))
    if not diff_lines:
        return None
    if len(diff_lines) > max_diff_lines:
        diff_lines = diff_lines[:max_diff_lines] + [f"... (+{len(diff_lines) - max_diff_lines} linhas)"]
    return "\n".join(diff_lines)


def _read_file_text(abs_path: str) -> Optional[str]:
    try:
        with open(abs_path, "r", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()


def take_snapshot(db: Session, project_path: str, abs_path: str) -> bool:
    """Snapshot the current file content if it changed since the last stored snapshot.
    Returns True if a new snapshot was inserted."""
    text = _read_file_text(abs_path)
    if text is None:
        return False
    h = _hash_text(text)
    latest = (
        db.query(CodeFileSnapshot)
        .filter(CodeFileSnapshot.abs_path == abs_path)
        .order_by(CodeFileSnapshot.captured_at.desc())
        .first()
    )
    if latest and latest.content_hash == h:
        return False
    db.add(CodeFileSnapshot(
        project_path=project_path,
        abs_path=abs_path,
        captured_at=datetime.now(),
        content_hash=h,
        content=text,
    ))
    return True


def _snapshot_diff_for_file(db: Session, abs_path: str, day_start_ms: int, max_diff_lines: int) -> Optional[str]:
    """Diff using our own snapshot table: latest snapshot captured before the day vs. current content.
    Only works for days >= the first day we ever snapshotted this file."""
    day_start = datetime.fromtimestamp(day_start_ms / 1000)
    baseline = (
        db.query(CodeFileSnapshot)
        .filter(CodeFileSnapshot.abs_path == abs_path, CodeFileSnapshot.captured_at < day_start)
        .order_by(CodeFileSnapshot.captured_at.desc())
        .first()
    )
    if not baseline:
        return None
    current = _read_file_text(abs_path)
    if current is None:
        return None
    if _hash_text(current) == baseline.content_hash:
        return None  # nothing actually changed
    diff_lines = list(difflib.unified_diff(
        baseline.content.splitlines(),
        current.splitlines(),
        lineterm="",
        n=2,
    ))
    if not diff_lines:
        return None
    if len(diff_lines) > max_diff_lines:
        diff_lines = diff_lines[:max_diff_lines] + [f"... (+{len(diff_lines) - max_diff_lines} linhas)"]
    return "\n".join(diff_lines)


def _diff_for_file(
    db: Session,
    file_info: dict,
    project_root: Optional[str],
    day_start_ms: int,
    day_end_ms: int,
    max_diff_lines: int = 80,
) -> tuple[Optional[str], str]:
    """Try real-diff sources only. Returns (text, source_label) or (None, 'none').
    NEVER returns the file's current content as a fake "diff" — we don't lie to the AI."""
    text = _vscode_diff_for_file(file_info, day_start_ms, day_end_ms, max_diff_lines)
    if text:
        return text, "vscode-history"
    text = _git_diff_for_file(file_info["abs_path"], project_root or "", day_start_ms, max_diff_lines)
    if text:
        return text, "git"
    text = _snapshot_diff_for_file(db, file_info["abs_path"], day_start_ms, max_diff_lines)
    if text:
        return text, "snapshot"
    return None, "none"


@router.post("/projects/{project_path:path}/notes/generate", response_model=NoteOut)
async def generate_note(
    project_path: str,
    target_date: str = Query(..., alias="date"),
    db: Session = Depends(get_db),
):
    """Generate a changelog-style note for the project for the given date,
    based on the actual diffs of files saved that day. Stored as source='ai'."""
    pp = _decode_path(project_path)
    try:
        d = date_type.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Data inválida (YYYY-MM-DD)")

    summary = _scan_history_for_date(d)
    project = next((p for p in summary["projects"] if p["path"] == pp), None)
    if not project or not project["files"]:
        raise HTTPException(status_code=400, detail="Sem actividade no projecto neste dia")

    day_start_ms = int(datetime.combine(d, datetime.min.time()).timestamp() * 1000)
    day_end_ms = day_start_ms + 24 * 60 * 60 * 1000

    diff_blocks = []
    files_without_diff = []
    source_counts: dict[str, int] = {}
    chars_used = 0
    CHAR_BUDGET = 14000  # keep prompt compact
    for f in project["files"][:12]:
        diff, src = _diff_for_file(db, f, pp, day_start_ms, day_end_ms)
        source_counts[src] = source_counts.get(src, 0) + 1
        if not diff:
            files_without_diff.append(f["rel_path"])
            continue
        block = f"### {f['rel_path']}  [fonte: {src}]\n{diff}"
        if chars_used + len(block) > CHAR_BUDGET:
            files_without_diff.append(f["rel_path"])
            continue
        diff_blocks.append(block)
        chars_used += len(block)

    logger.info(f"Note generation for {pp} on {d}: sources={source_counts}, blocks={len(diff_blocks)}")

    if not diff_blocks:
        raise HTTPException(
            status_code=422,
            detail=(
                "Sem diffs reais para este dia: nem VS Code Local History, nem git, nem snapshots próprios. "
                "Os snapshots começam a ser tirados a partir de agora — vai poder gerar notas a partir do "
                "próximo dia em que mexeres em ficheiros deste projecto. Para já, tens de escrever a nota à mão."
            ),
        )

    diffs_section = "\n\n".join(diff_blocks)
    extra_files = ""
    if files_without_diff:
        extra_files = "\n\nFicheiros mexidos sem diff disponível (ignora):\n" + "\n".join(
            f"- {p}" for p in files_without_diff[:30]
        )

    prompt = f"""Estou a escrever, em poucas linhas, o que foi feito hoje neste projecto pessoal — em português PT, no tom de alguém a contar a um amigo. Tu vais escrever isso por mim.

Projecto: {project['name']}
Data: {d.isoformat()}

Vou-te dar o DIFF REAL do que mudou hoje em cada ficheiro. As linhas '+' são adições, as '-' são remoções. Não inventes fora disto. A fonte (vscode-history / git / snapshot) é só meta-info; o que importa são as linhas + e -.

Conteúdo:
{diffs_section}{extra_files}

REGRAS DURAS — ler com atenção:

1) Cada bullet descreve UMA funcionalidade visível ao utilizador, não um ficheiro. Pensa "o que é que ficou diferente para quem usa a app?".

2) PROIBIDO:
   - Listar ficheiros como sujeito ("Adicionados componentes em frontend/src/App.tsx").
   - Frases tipo "Implementada API para...", "Trabalho em páginas: X, Y, Z", "Alterações no modelo de dados", "Criadas interfaces para tipagem".
   - Listar várias páginas/ficheiros separados por vírgulas — agrupa por funcionalidade.
   - Mencionar caminhos tipo "frontend/src/pages/...". Se mencionares um ficheiro, usa o nome curto, e só se ajudar mesmo.
   - "Ajustes em X", "melhorias em Y", "refactor de Z" — diz concretamente o quê.

3) ESCREVE COMO O DONO DO PROJECTO falaria. Vê estes exemplos do tom certo (são o objectivo!):
   - mudei "Os teus sítios" para "Sítios a visitar" e adicionei botão que sugere sítios do país
   - quando adiciono uma viagem, os dias passam a ficar marcados como Férias no calendário
   - na Atividade VS Code, os TODOs e as Notas IA passam a estar lado a lado na mesma janela
   - timeline do uso de aplicações ficou agrupada por categoria (produtividade, gaming…)
   - corrigido o valor errado de investimentos no dashboard (estava a somar snapshots duplicados)

4) Tamanho:
   - 3 a 6 bullets, NUNCA mais.
   - Cada um numa linha, máx ~20 palavras.
   - Começam por "- " (sem números, sem markdown extra).
   - Verbo concreto à cabeça ("adicionei", "mudei", "corrigi", "tirei", "substituí") OU descrição da feature.

5) Se um diff é pequeno ou trivial (whitespace, imports), ignora-o. Não escrevas bullets só por ter de escrever.

6) Sem introduções, sem conclusões. Só os bullets.

Responde."""

    thread_id = uuid.uuid4().hex[:20]
    full_text = ""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                AI_API_URL,
                headers={"x-api-key": AI_API_KEY},
                data={
                    "channel_id": AI_CHANNEL_ID,
                    "thread_id": thread_id,
                    "user_info": "{}",
                    "message": prompt,
                },
            )
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="AI indisponível")
            token_text = ""
            for line in response.text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("type") == "message":
                        content = event.get("content", {})
                        full_text = content.get("content", "") if isinstance(content, dict) else str(content)
                        break
                    elif event.get("type") == "token":
                        token_text += event.get("content", "")
                except json.JSONDecodeError:
                    continue
            if not full_text:
                full_text = token_text
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="AI indisponível")

    full_text = full_text.strip().strip('"').strip()
    full_text = re.sub(r"^```.*?\n|\n```$", "", full_text, flags=re.DOTALL).strip()
    if not full_text:
        raise HTTPException(status_code=502, detail="Resposta da IA vazia")

    note = CodeProjectNote(
        project_path=pp,
        content=full_text,
        source="ai",
        note_date=d,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/totals")
def get_totals(db: Session = Depends(get_db)):
    """Open TODO count + total notes count, for the summary tiles."""
    open_todos = db.query(CodeProjectTodo).filter(CodeProjectTodo.done == False).count()
    notes = db.query(CodeProjectNote).count()
    return {"open_todos": open_todos, "total_notes": notes}


@router.get("/projects-with-todos")
def list_projects_with_todos(db: Session = Depends(get_db)):
    """Project paths that have at least one open TODO, regardless of activity."""
    rows = (
        db.query(CodeProjectTodo.project_path)
        .filter(CodeProjectTodo.done == False)
        .distinct()
        .all()
    )
    out = []
    for (pp,) in rows:
        if not pp:
            continue
        name = pp.rstrip("/").split("/")[-1] or pp
        out.append({"path": pp, "name": name})
    out.sort(key=lambda x: x["name"].lower())
    return out


class BulletsNoteIn(BaseModel):
    bullets: list[str]
    note_date: Optional[date_type] = None


@router.post("/projects/{project_path:path}/notes/from-bullets", response_model=NoteOut)
def create_ai_note_from_bullets(
    project_path: str,
    data: BulletsNoteIn,
    db: Session = Depends(get_db),
):
    """Create an AI Note directly from a list of bullets (no LLM call).
    Designed to be called by the assistant at task end with the summary it
    already showed the user — bypasses the diff pipeline entirely."""
    pp = _decode_path(project_path)
    cleaned = [b.strip() for b in (data.bullets or []) if b and b.strip()]
    if not cleaned:
        raise HTTPException(status_code=400, detail="Sem bullets")
    body = "\n".join(f"- {b.lstrip('- ').strip()}" for b in cleaned)
    note = CodeProjectNote(
        project_path=pp,
        content=body,
        source="ai",
        note_date=data.note_date or date_type.today(),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.post("/snapshot")
def snapshot_file(path: str = Query(...), db: Session = Depends(get_db)):
    """Capture a baseline snapshot of `path` before an external edit.

    Designed to be called by a Claude Code PreToolUse hook so that the AI Notes
    pipeline has a baseline to diff against — Claude writes via FS directly,
    bypassing VS Code Local History."""
    abs_path = os.path.abspath(os.path.expanduser(unquote(path)))
    if not os.path.isfile(abs_path):
        return {"snapshot": False, "reason": "not_a_file"}
    file_p = Path(abs_path)
    project_root = _find_project_root(file_p)
    _, project_path = _project_label(project_root, file_p)
    project_path = project_path or "_outros"
    try:
        inserted = take_snapshot(db, project_path, abs_path)
        if inserted:
            db.commit()
        return {"snapshot": bool(inserted), "project_path": project_path}
    except Exception as e:
        logger.warning(f"snapshot endpoint failed for {abs_path}: {e}")
        db.rollback()
        return {"snapshot": False, "reason": "error"}
