#!/usr/bin/env python3
"""
Dashhy — local backend (Windows port).

Serves the Dashhy (Mi · Deep-Blue) web dashboard and exposes a tiny JSON API for
real filesystem access: list / add / scan / open projects on this PC, read
file contents, pick a folder via the native Windows dialog.

Pure standard library — no pip installs. Run:  python server.py
"""

import http.server
import socketserver
import json
import os
import re
import shutil
import sys
import uuid
import subprocess
import threading
import time
import webbrowser
import urllib.request
from datetime import datetime
from urllib.parse import urlparse, parse_qs, quote

# ── Paths / config ────────────────────────────────────────────
# When frozen by PyInstaller the bundled data lives in sys._MEIPASS, not next
# to this source file.
if getattr(sys, "frozen", False):
    HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR   = os.path.join(HERE, "web")
DATA_DIR  = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'Dashhy')
DATA_FILE = os.path.join(DATA_DIR, "projects.json")
PORT      = int(os.environ.get("DASH_PORT", "7777"))
# A GUI-subsystem .exe (console=False) pops a fresh console window every time
# it spawns a console app (git, powershell, cmd) unless we suppress it.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

CODE_EXT = {
    '.ts', '.tsx', '.js', '.jsx', '.py', '.go', '.rs', '.java', '.c', '.cpp',
    '.h', '.hpp', '.rb', '.php', '.swift', '.kt', '.css', '.scss', '.html',
    '.vue', '.svelte', '.md', '.json', '.yaml', '.yml', '.toml', '.sql',
    '.sh', '.bash', '.zsh', '.ps1', '.bat', '.cmd',
}
SKIP_DIRS = {'node_modules', '.git', 'dist', 'build', '.next', '__pycache__',
             '.venv', 'venv', '.idea', '.vscode', 'Pods', '.cache'}
# lock/vendored files that explode file & line counts without being "your code"
SKIP_FILES = {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock',
              'Cargo.lock', 'composer.lock', 'Gemfile.lock'}
MAX_SCAN_ENTRIES = 50000   # hard cap so a giant tree can't hang/crash the scan
# Last-resort relocate: when the cheap 1-level scan misses, walk the whole $HOME
# tree to re-find a folder moved to an entirely new location. Bounded so a giant
# home can't hang; cached briefly so one "Обновить" pass walks the tree once even
# when many projects moved at the same time.
DEEP_SCAN_MAX_DIRS = 200000
_HOME_INDEX_TTL = 8.0      # seconds

VALID_STATUS = {'idle', 'analyzing', 'running', 'stopped', 'complete'}

# ── "Создать проект" — clone the project-starter template ──────
# A green button in the UI copies this template to a fresh ~/Desktop/new project,
# drops a VS Code folderOpen task that auto-launches `claude /onboard`, and opens
# the folder in VS Code. Override the template via $DASH_STARTER if it ever moves.
STARTER_DIR   = os.environ.get('DASH_STARTER', os.path.expanduser('~/Desktop/project-starter'))
NEW_PROJ_BASE = os.path.expanduser('~/Desktop')   # where new projects land
NEW_PROJ_NAME = 'new project'
# heavy / per-clone junk we never want copied into a fresh project
COPY_IGNORE = shutil.ignore_patterns(
    '.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '.next',
    '__pycache__', '.cache', '.DS_Store', 'Thumbs.db',
)

# Credential / secret directories we refuse to index even though they live under
# $HOME. The $HOME confinement alone is NOT a real boundary — ~/.ssh etc. are
# under $HOME — so we explicitly deny these (and never read non-code files).
# Defined with '/' and normalized to the native separator below, so the
# startswith() checks in _is_sensitive_path line up with realpath()'d strings
# on both POSIX and Windows.
SENSITIVE_SUBPATHS = tuple(p.replace('/', os.sep) for p in (
    '.ssh', '.aws', '.gnupg', '.gpg', '.kube', '.docker', '.netrc',
    '.password-store', '.config/gh', '.config/gcloud',
    'AppData/Roaming/GitHub CLI', 'AppData/Roaming/gcloud', 'AppData/Local/gcloud',
    'AppData/Roaming/Microsoft/Credentials', 'AppData/Local/Microsoft/Credentials',
    'AppData/Local/Dashhy',
))


def _within(child, parent):
    """True if realpath `child` is, or is inside, realpath `parent`.

    Case-insensitive on purpose, because both platforms' default filesystems
    are: on APFS/HFS+ ~/.ssh and ~/.SSH are the same directory, and NTFS is
    case-insensitive (though case-preserving). A byte-exact comparison here
    would let ~/.SSH walk straight past the credential denylist below, and
    would also reject a perfectly valid folder whose casing came back from the
    OS folder picker differently from $HOME / %USERPROFILE%.

    normcase() alone is not enough: it case-folds on Windows but is a no-op on
    POSIX, so it would silently do nothing on macOS — and would make this
    module behave differently when imported on a POSIX CI runner. casefold()
    alone is not enough either: only normcase() normalises Windows' mixed
    slashes. Both, in that order, are correct on both platforms.

    Kept byte-identical between the macOS and Windows trees on purpose; see
    tests/test_parity.py.
    """
    c = os.path.normcase(child).casefold()
    p = os.path.normcase(parent).casefold()
    return c == p or c.startswith(p + os.path.normcase(os.sep))


def _within_exact(child, parent):
    """Like _within(), but case-SENSITIVE.

    Used where `parent` is a directory name the user chose rather than $HOME:
    both paths are already realpath()'d and `child` is built by joining onto
    `parent`, so their casing always agrees on a legitimate read. Folding there
    would only ever widen containment — on a case-sensitive volume it would let
    a sibling that differs from the project root by casing alone read as inside
    it. Kept identical between the two trees; see tests/test_parity.py.
    """
    return child == parent or child.startswith(parent + os.sep)


def _is_sensitive_path(rp, home):
    """True if realpath `rp` is, or is inside, a known credential/secret dir."""
    for sub in SENSITIVE_SUBPATHS:
        if _within(rp, os.path.join(home, sub)):
            return True
    return False


def _dir_inode(path):
    """Filesystem identity of a dir: "st_dev:st_ino", or None if unreadable.

    NTFS keeps this pair stable across an in-place rename/move, so it lets us
    re-find a project folder after the user renames it (CPython's os.stat
    resolves st_ino on Windows via GetFileInformationByHandle since 3.5+).
    None for old records that predate this field — they get one on their
    next successful scan.
    """
    try:
        st = os.stat(path)
        return f"{st.st_dev}:{st.st_ino}"
    except OSError:
        return None


# ── App config (settings screen) ──────────────────────────────
# Single JSON file next to projects.json in %LOCALAPPDATA%\Dashhy. Everything
# the settings screen edits lives here.
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

DEFAULT_CONFIG = {
    "new_project": {
        "base_dir":    os.path.expanduser("~/Desktop"),          # where new folders land
        "name":        NEW_PROJ_NAME,                            # base name for new folders
        "starter_dir": os.path.expanduser("~/Desktop/project-starter"),
        "onboard":     "/onboard",                               # prompt injected into VS Code task
    },
    "launch": {
        "editor":          "auto",       # auto | code | cursor | system
        "terminal":        "wt",         # wt | cmd | powershell
        "default_run_cmd": "",           # applied when a project has no run_cmd of its own
    },
    "scan": {
        "auto_on_focus": True,
        "interval_sec":  45,             # 0 = never rescan on focus
        "watched": [],                   # folders auto-discovered on load
    },
    "storage": {
        "data_dir": DATA_DIR,            # where projects.json lives (movable)
    },
    "startup": {
        "launch_at_login": False,        # reflected from the HKCU Run key on read
    },
}

_EDITORS     = {"auto", "code", "cursor", "system"}
_TERMINALS   = {"wt", "cmd", "powershell"}
_config_lock = threading.Lock()


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, encoding='utf-8') as f:
                return _deep_merge(DEFAULT_CONFIG, json.load(f) or {})
    except Exception as e:
        print(f"[config] load failed: {e}", file=sys.stderr)
    return _deep_merge(DEFAULT_CONFIG, {})


def _save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_FILE)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


CONFIG = _load_config()


def _validate_dir(path):
    """Real, existing dir under $HOME and not a credential dir → realpath, else None."""
    if not path:
        return None
    rp = os.path.realpath(os.path.expanduser(str(path)))
    home = os.path.realpath(os.path.expanduser('~'))
    if not os.path.isdir(rp):
        return None
    if not _within(rp, home):
        return None
    if _is_sensitive_path(rp, home):
        return None
    return rp


def _need_dir(path):
    d = _validate_dir(path)
    if not d:
        raise ValueError(f"Недопустимая папка: {path}")
    return d


def _clean_name(name):
    n = re.sub(r'[/\\:*?"<>|]', '', str(name)).strip() or NEW_PROJ_NAME
    return n[:80]


# ── "Запускать при старте компьютера" — HKCU Run key ──────────
_RUN_KEY   = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "Dashhy"


def _login_command():
    """The command string stored in the Run key.

    Frozen .exe: run the executable directly (it IS the app). Run-from-source:
    launch the native window via pythonw.exe (no console flash) + app.py.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    appdir = os.path.dirname(os.path.abspath(__file__))
    apppy = os.path.join(appdir, "app.py")
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    py = pyw if os.path.exists(pyw) else sys.executable
    return f'"{py}" "{apppy}"'


def login_item_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _RUN_VALUE)
        return True
    except Exception:
        return False


def set_login_item(enabled):
    """Add/remove the HKCU\\...\\Run value so Dashhy starts at login."""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            if enabled:
                winreg.SetValueEx(k, _RUN_VALUE, 0, winreg.REG_SZ, _login_command())
            else:
                try:
                    winreg.DeleteValue(k, _RUN_VALUE)
                except FileNotFoundError:
                    pass
    except Exception as e:
        print(f"[login-item] {e}", file=sys.stderr)
    return login_item_enabled()


# ── Data store ────────────────────────────────────────────────
class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.projects = {}
        self._home_index = None        # cached deep-relocate candidate list
        self._home_index_at = 0.0
        # registry location is configurable (settings ▸ storage); default = DATA_DIR
        self.data_dir = CONFIG.get('storage', {}).get('data_dir') or DATA_DIR
        self.data_file = os.path.join(self.data_dir, 'projects.json')
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            if os.path.exists(self.data_file):
                with open(self.data_file) as f:
                    for item in json.load(f):
                        self.projects[item['id']] = self._migrate(item)
                # one-time safety snapshot per launch — recover a clobbered registry
                try:
                    shutil.copy2(self.data_file, self.data_file + ".bak")
                except Exception:
                    pass
        except Exception as e:
            print(f"[Store] load failed: {e}", file=sys.stderr)

    @staticmethod
    def _migrate(item):
        """Normalize old-schema (tkinter app) records to the new shape."""
        files = item.get('files')
        if isinstance(files, list):                 # old: files was a path list
            item['file_list'] = sorted(files)[:1000]
            item['files'] = len(files)
        item.setdefault('files', 0)
        item.setdefault('lines', 0)
        item.setdefault('langs', {})
        item.setdefault('last_stage', item.get('last_stage', 'Added'))
        item.setdefault('scanned_at', None)
        now = datetime.now().isoformat()
        item.setdefault('created_at', now)
        item.setdefault('updated_at', now)
        item.pop('editor_positions', None)
        return item

    def save(self):
        os.makedirs(self.data_dir, exist_ok=True)
        tmp = self.data_file + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(list(self.projects.values()), f, indent=2)
        os.replace(tmp, self.data_file)
        try:
            # best-effort: on POSIX this restricts to owner-only; on Windows
            # os.chmod only maps to the read-only attribute, which this clears.
            os.chmod(self.data_file, 0o600)
        except OSError:
            pass

    def set_data_dir(self, new_dir):
        """Move the projects registry to a new folder (settings ▸ storage).

        Copies projects.json to the new dir (leaving the old copy as a backup),
        rebinds this store, and persists the choice into CONFIG.
        """
        rp = _need_dir(new_dir)
        new_file = os.path.join(rp, 'projects.json')
        with self.lock:
            if os.path.normcase(os.path.realpath(new_file)) != os.path.normcase(os.path.realpath(self.data_file)):
                try:
                    if os.path.exists(self.data_file):
                        shutil.copy2(self.data_file, new_file)
                except Exception as e:
                    raise ValueError(f"Не удалось перенести данные: {e}")
            self.data_dir = rp
            self.data_file = new_file
        self.save()
        CONFIG['storage']['data_dir'] = rp
        _save_config(CONFIG)
        return rp

    def discover_watched(self):
        """Run discover() over every watched folder (settings ▸ scan)."""
        added = []
        for folder in (CONFIG.get('scan', {}).get('watched') or []):
            try:
                added += self.discover(folder)
            except Exception as e:
                print(f"[watched] {folder}: {e}", file=sys.stderr)
        return added

    def list(self):
        return list(self.projects.values())

    def add(self, name, path):
        now = datetime.now().isoformat()
        p = {
            'id': f"proj_{uuid.uuid4().hex[:12]}",
            'name': name, 'path': path,
            'status': 'idle', 'last_stage': 'Added',
            'files': 0, 'lines': 0, 'langs': {},
            'inode': _dir_inode(os.path.realpath(path)),
            'created_at': now, 'updated_at': now, 'scanned_at': None,
        }
        with self.lock:
            self.projects[p['id']] = p
            self.save()
        return p

    def remove(self, pid):
        with self.lock:
            self.projects.pop(pid, None)
            self.save()

    def set_status(self, pid, status):
        with self.lock:
            if pid in self.projects and status in VALID_STATUS:
                self.projects[pid]['status'] = status
                self.projects[pid]['updated_at'] = datetime.now().isoformat()
                self.save()
                return self.projects[pid]
        return None

    def _home_candidates(self, taken):
        """Every plausible project dir anywhere under $HOME — last-resort relocate.

        The cheap 1-level scan in `_relocate` only sees folders moved/renamed
        *inside* a known parent. This deep-walks the whole home tree so a folder
        moved to an entirely new place can still be re-found by inode or content.

        Returns [(realpath, name, inode), ...]. Excludes hidden dirs, SKIP_DIRS,
        credential/secret dirs, and any dir already claimed by a tracked project
        (`taken`). Never leaves $HOME (no symlink-follow). Bounded by
        DEEP_SCAN_MAX_DIRS. The raw tree (minus `taken`) is cached for
        _HOME_INDEX_TTL so one scan_all pass that relocates many projects walks
        the disk once, not once per project.
        """
        now = time.time()
        if self._home_index is not None and (now - self._home_index_at) < _HOME_INDEX_TTL:
            cached = self._home_index
        else:
            home = os.path.realpath(os.path.expanduser('~'))
            cached, seen = [], set()
            stack = [home]
            count = 0
            while stack:
                d = stack.pop()
                try:
                    with os.scandir(d) as it:
                        for e in it:
                            try:
                                if not e.is_dir(follow_symlinks=False):
                                    continue
                                if e.name.startswith('.') or e.name in SKIP_DIRS:
                                    continue
                                rp = os.path.realpath(e.path)
                            except OSError:
                                continue
                            if rp in seen or _is_sensitive_path(rp, home):
                                continue
                            seen.add(rp)
                            count += 1
                            if count > DEEP_SCAN_MAX_DIRS:
                                stack = []
                                break
                            cached.append((rp, e.name, _dir_inode(rp)))
                            stack.append(rp)
                except OSError:
                    continue
            self._home_index = cached
            self._home_index_at = now
        # `taken` differs per project, so filter the shared cache on every call
        return [(rp, nm, ino) for (rp, nm, ino) in cached if rp not in taken]

    def _relocate(self, pid):
        """Re-find a project folder the user renamed/moved, then update the path.

        When proj['path'] no longer exists we look through the parents of every
        tracked project (and the old parent) for the folder, matching by three
        tiers, strongest first:

          1. inode    — (st_dev, st_ino) is stable across an in-place rename on
                        NTFS. Exact; only set on records scanned by this build.
          2. contents — enough of the last-known file_list still lives in the
                        candidate. Survives a record that has no inode yet.
          3. name     — a single untracked sibling whose name still relates to
                        the old folder name (rename like  сайт → сайт_Borners).
                        Used only when exactly one candidate matches, so it
                        can't grab the wrong folder.

        Tiers 1-3 only look one level deep inside the parents of tracked
        projects. If they all miss — the folder moved somewhere brand new — we
        fall back to a deep walk of the whole $HOME tree (tier 4), matching only
        by inode or content signature (never by name, which is too ambiguous
        across the entire home dir).

        On a hit we update path (and name, if it still mirrored the folder name),
        stamp a fresh inode, and persist. Returns the new realpath, or None.
        Caller must NOT hold self.lock.
        """
        with self.lock:
            proj = self.projects.get(pid)
            if not proj:
                return None
            target = proj.get('inode')
            sig = [r for r in (proj.get('file_list') or []) if r][:40]
            old = os.path.realpath(proj['path'])
            old_base = os.path.basename(old.rstrip(os.sep))
            cur_name = proj.get('name')
            # never claim a folder another project already tracks
            taken = {os.path.realpath(p['path'])
                     for p in self.projects.values() if p['id'] != pid}
            roots = {os.path.dirname(os.path.realpath(p['path']))
                     for p in self.projects.values()}
        roots.add(os.path.dirname(old))
        home = os.path.realpath(os.path.expanduser('~'))

        # collect untracked candidate dirs across all searched roots (deduped)
        cands, seen = [], set()
        for root in roots:
            if not root or not _within(root, home):
                continue
            try:
                with os.scandir(root) as it:
                    for e in it:
                        try:
                            if not e.is_dir(follow_symlinks=False):
                                continue
                            if e.name.startswith('.') or e.name in SKIP_DIRS:
                                continue
                            rp = os.path.realpath(e.path)
                        except OSError:
                            continue
                        if rp in seen or rp in taken or _is_sensitive_path(rp, home):
                            continue
                        seen.add(rp)
                        cands.append((rp, e.name))
            except OSError:
                continue

        match = None
        # tier 1 — exact inode
        if target:
            for rp, nm in cands:
                if _dir_inode(rp) == target:
                    match = (rp, nm)
                    break
        # tier 2 — content signature (≥60% of known files still present)
        if not match and sig:
            best = None
            for rp, nm in cands:
                hit = sum(1 for rel in sig if os.path.exists(os.path.join(rp, rel)))
                frac = hit / len(sig)
                if frac >= 0.6 and (best is None or frac > best[0]):
                    best = (frac, rp, nm)
            if best:
                match = (best[1], best[2])
        # tier 3 — unique name relative (only one untracked candidate matches)
        if not match and len(old_base) >= 3:
            ob = old_base.lower()
            hits = [(rp, nm) for rp, nm in cands
                    if (lambda n: n.startswith(ob) or ob.startswith(n) or ob in n)
                       (nm.lower())]
            if len(hits) == 1:
                match = hits[0]

        # tier 4 — LAST RESORT: deep walk of the whole $HOME tree. Covers a
        # folder moved to an entirely new location (e.g. Desktop → Documents).
        # Only inode + content signature: both are real identity signals, so a
        # match anywhere in $HOME is trustworthy. Name matching is omitted here —
        # across the whole tree it would collide constantly.
        if not match and (target or sig):
            deep = self._home_candidates(taken)
            if target:                       # tier 4a — exact inode (move keeps it)
                for rp, nm, ino in deep:
                    if ino == target:
                        match = (rp, nm)
                        break
            if not match and sig:            # tier 4b — ≥60% of known files present
                best = None
                for rp, nm, ino in deep:
                    hit = sum(1 for rel in sig if os.path.exists(os.path.join(rp, rel)))
                    frac = hit / len(sig)
                    if frac >= 0.6 and (best is None or frac > best[0]):
                        best = (frac, rp, nm)
                if best:
                    match = (best[1], best[2])

        if not match:
            return None
        rp, nm = match
        with self.lock:
            p = self.projects.get(pid)
            if not p:
                return None
            p['path'] = rp
            if cur_name == old_base:          # name wasn't customized
                p['name'] = nm
            p['inode'] = _dir_inode(rp)       # stamp so future renames hit tier 1
            p['relocated_at'] = datetime.now().isoformat()
            p['updated_at'] = p['relocated_at']
            self.save()
        return rp

    def scan(self, pid, save=True):
        with self.lock:
            proj = self.projects.get(pid)
        if not proj:
            return None
        # realpath the base so relpaths match read_file (which also realpaths)
        base = os.path.realpath(proj['path'])
        # Folder renamed/moved? Re-find it by inode before giving up (else the
        # scan would silently report 0 files for the now-missing old path).
        if not os.path.isdir(base):
            new_base = self._relocate(pid)
            if new_base:
                base = new_base
            else:
                with self.lock:
                    proj = self.projects.get(pid)
                    if not proj:
                        return None
                    proj['scan_error'] = 'missing'
                    proj['last_stage'] = 'Папка не найдена — переименована или удалена?'
                    proj['updated_at'] = datetime.now().isoformat()
                    if save:
                        self.save()
                    return proj
        files, langs, lines = [], {}, 0
        last_mod = 0.0
        access_denied = False
        truncated = False
        seen = set()
        stack = [(base, True)]      # (dir, is_root)
        count = 0

        # iterative, bounded walk — no recursion limit, no symlink loops
        while stack:
            d, is_root = stack.pop()
            try:
                rp = os.path.realpath(d)
                if rp in seen:
                    continue
                seen.add(rp)
                with os.scandir(d) as it:
                    for e in it:
                        count += 1
                        if count > MAX_SCAN_ENTRIES:
                            truncated = True
                            break
                        try:
                            if e.is_symlink():
                                continue          # never follow symlinks out of tree
                            if e.is_dir(follow_symlinks=False):
                                if e.name not in SKIP_DIRS and not e.name.startswith('.'):
                                    stack.append((e.path, False))
                            elif e.is_file(follow_symlinks=False):
                                ext = os.path.splitext(e.name)[1].lower()
                                if (ext in CODE_EXT and e.name not in SKIP_FILES
                                        and '.min.' not in e.name):
                                    files.append(os.path.relpath(e.path, base))
                                    langs[ext] = langs.get(ext, 0) + 1
                                    try:
                                        m = e.stat(follow_symlinks=False).st_mtime
                                        if m > last_mod:
                                            last_mod = m
                                    except OSError:
                                        pass
                        except OSError:
                            continue
            except PermissionError:
                if is_root:
                    access_denied = True
            except (FileNotFoundError, OSError):
                pass
            if truncated:
                break

        # Some folder can't be read (locked by another process, blocked by an
        # antivirus, or an NTFS ACL that excludes this user). Don't overwrite
        # prior file/line counts with zeros — keep them, surface the error.
        if access_denied:
            with self.lock:
                proj = self.projects.get(pid)
                if not proj:
                    return None
                # status is user-controlled only — scan must never change it
                proj['scan_error'] = 'no_access'
                proj['last_stage'] = 'Нет доступа к папке — проверь права NTFS/антивирус'
                proj['updated_at'] = datetime.now().isoformat()
                if save:
                    self.save()
                return proj

        # honest line count: binary \n over ALL code files (skip huge data files)
        for rel in files:
            fp = os.path.join(base, rel)
            try:
                if os.path.getsize(fp) > 5_000_000:
                    continue
                with open(fp, 'rb') as fh:
                    while True:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            break
                        lines += chunk.count(b'\n')
            except OSError:
                pass

        git = self._git_status(base)

        with self.lock:
            proj = self.projects.get(pid)
            if not proj:
                return None
            proj['files'] = len(files)
            proj['lines'] = lines
            proj['lines_partial'] = truncated
            proj['langs'] = dict(sorted(langs.items(), key=lambda kv: -kv[1])[:8])
            proj['file_list'] = sorted(files)[:1000]
            proj['last_modified'] = last_mod or None
            proj['git'] = git
            proj['inode'] = _dir_inode(base)   # keep fresh — enables rename re-find
            proj['last_stage'] = (
                f"{len(files)} файлов · {lines:,} строк".replace(',', ' ')
            )
            # status is user-controlled only — scan must never change it
            proj.pop('scan_error', None)
            proj['scanned_at'] = datetime.now().isoformat()
            proj['updated_at'] = proj['scanned_at']
            if save:
                self.save()
            return proj

    @staticmethod
    def _git_status(base):
        """Local-only git snapshot (no network): branch, dirty, ahead/behind.

        Returns None if not a git repo or git is unavailable. Uses only local
        refs — instant and offline. Requires Git for Windows (or any git.exe)
        on PATH.
        """
        if not os.path.exists(os.path.join(base, '.git')):
            return None
        try:
            out = subprocess.run(
                ['git', '-C', base, 'status', '--porcelain=2', '--branch'],
                capture_output=True, text=True, timeout=5,
                creationflags=_NO_WINDOW,
            )
            if out.returncode != 0:
                return None
        except Exception:
            return None
        branch, ahead, behind, dirty = None, 0, 0, False
        for line in out.stdout.splitlines():
            if line.startswith('# branch.head'):
                branch = line.split(' ', 2)[-1].strip()
            elif line.startswith('# branch.ab'):
                for tok in line.split():
                    if tok.startswith('+'):
                        ahead = int(tok[1:] or 0)
                    elif tok.startswith('-'):
                        behind = int(tok[1:] or 0)
            elif line[:1] in ('1', '2', 'u', '?'):
                dirty = True
        # last commit: subject + relative date (empty repo → none)
        msg, rel = None, None
        try:
            lg = subprocess.run(
                ['git', '-C', base, 'log', '-1', '--format=%s%x1f%cr'],
                capture_output=True, text=True, timeout=5,
                creationflags=_NO_WINDOW)
            if lg.returncode == 0 and '\x1f' in lg.stdout:
                msg, rel = lg.stdout.strip().split('\x1f', 1)
        except Exception:
            pass
        return {'branch': branch or 'detached', 'dirty': dirty,
                'ahead': ahead, 'behind': behind, 'msg': msg, 'rel': rel}

    def set_notes(self, pid, text):
        with self.lock:
            if pid in self.projects:
                self.projects[pid]['notes'] = (text or '')[:5000]
                self.projects[pid]['updated_at'] = datetime.now().isoformat()
                self.save()
                return self.projects[pid]
        return None

    def set_run_cmd(self, pid, cmd):
        with self.lock:
            if pid in self.projects:
                self.projects[pid]['run_cmd'] = (cmd or '').strip()[:500]
                self.save()
                return self.projects[pid]
        return None

    def discover(self, root):
        """Auto-add project-like immediate subdirs of `root` (onboarding helper).

        A child counts as a project if it holds a .git / package.json /
        pyproject.toml / requirements.txt / Cargo.toml / go.mod. Skips dirs
        already tracked. Returns the list of newly added projects.
        """
        root = os.path.realpath(root or '')
        home = os.path.realpath(os.path.expanduser('~'))
        if not root or not _within(root, home) or _is_sensitive_path(root, home):
            return []
        markers = ('.git', 'package.json', 'pyproject.toml', 'requirements.txt',
                   'Cargo.toml', 'go.mod', 'composer.json')
        existing = {os.path.realpath(p['path']) for p in self.list()}
        added = []
        try:
            with os.scandir(root) as it:
                for e in it:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    if e.name.startswith('.') or e.name in SKIP_DIRS:
                        continue
                    if os.path.realpath(e.path) in existing:
                        continue
                    if _is_sensitive_path(os.path.realpath(e.path), home):
                        continue
                    if any(os.path.exists(os.path.join(e.path, m)) for m in markers):
                        added.append(self.add(e.name, e.path))
        except OSError:
            pass
        return added

    @staticmethod
    def _write_vscode_task(dest):
        """Drop .vscode/tasks.json so opening `dest` in VS Code opens the Claude
        Code *extension panel* (not a terminal) pre-filled with `/onboard`.

        Mechanism: a folderOpen task fires the extension's deep link
        `vscode://anthropic.claude-code/open?prompt=%2Fonboard`. The extension's
        URI handler routes that to `primaryEditor.open(session, prompt)`, and the
        webview calls `setInputText("/onboard")` — so the panel opens with
        `/onboard` typed in, ready to send with Enter. `Start-Sleep` lets the
        extension finish activating (it registers the URI handler on startup)
        before the link fires. The task spawns `powershell` directly (rather
        than relying on `sleep`/`open` being valid in whatever default shell
        VS Code is configured with) so it runs the same regardless of the
        user's default terminal profile (cmd or PowerShell).

        Note: VS Code only auto-runs this if automatic tasks are allowed
        (`task.allowAutomaticTasks: on`) and the folder is trusted (in Restricted
        Mode the task is blocked and the extension itself is disabled — click
        "Trust" on the banner first). The template already ships a
        .vscode/settings.json — we add tasks.json beside it.
        """
        vs = os.path.join(dest, '.vscode')
        os.makedirs(vs, exist_ok=True)
        prompt = CONFIG.get('new_project', {}).get('onboard') or '/onboard'
        link = "vscode://anthropic.claude-code/open?prompt=" + quote(prompt, safe='')
        task = {
            "version": "2.0.0",
            "tasks": [{
                "label": "Dashhy ▸ Claude onboard",
                "type": "shell",
                "command": "powershell",
                "args": ["-NoProfile", "-Command",
                         f"Start-Sleep -Seconds 1; Start-Process '{link}'"],
                "presentation": {"echo": False, "reveal": "silent", "focus": False,
                                 "panel": "shared", "close": True},
                "runOptions": {"runOn": "folderOpen"},
                "problemMatcher": [],
            }],
        }
        with open(os.path.join(vs, 'tasks.json'), 'w') as f:
            json.dump(task, f, indent=2, ensure_ascii=False)

    def create_from_starter(self):
        """Clone the project-starter template into a fresh ~/Desktop/new project.

        Full copy (minus .git / node_modules / build junk), a VS Code folderOpen
        task that auto-launches `claude /onboard`, then registers it so it shows
        up in the grid. Returns (project, dest_path). Raises ValueError with a
        user-facing (Russian) message on any expected failure.
        """
        np = CONFIG.get('new_project', {})
        starter = os.path.expanduser(np.get('starter_dir') or STARTER_DIR)
        src = os.path.realpath(starter)
        if not os.path.isdir(src):
            raise ValueError(f"Болванка не найдена: {starter}")
        home = os.path.realpath(os.path.expanduser('~'))
        parent = os.path.realpath(os.path.expanduser(np.get('base_dir') or NEW_PROJ_BASE))
        base_name = np.get('name') or NEW_PROJ_NAME
        # never overwrite an existing folder — "new project", "new project 2", …
        dest = os.path.join(parent, base_name)
        n = 2
        while os.path.exists(dest):
            dest = os.path.join(parent, f"{base_name} {n}")
            n += 1
        rp = os.path.realpath(dest)
        if not _within(rp, home) or _is_sensitive_path(rp, home):
            raise ValueError("Недопустимый путь назначения")
        # guard against cloning the template into itself
        if _within(rp, src):
            raise ValueError("Нельзя создать проект внутри болванки")
        shutil.copytree(src, dest, ignore=COPY_IGNORE, symlinks=False)
        self._write_vscode_task(dest)
        return self.add(os.path.basename(dest), dest), dest

    def scan_all(self):
        """Re-scan all projects sequentially, saving ONCE at the end."""
        results = []
        with self.lock:
            pids = list(self.projects.keys())
        for pid in pids:
            try:
                proj = self.scan(pid, save=False)
            except Exception as e:
                print(f"[scan_all] {pid} failed: {e}", file=sys.stderr)
                proj = None
            if proj:
                ok = not proj.get('scan_error')      # no_access counts as failure
                results.append({'id': pid, 'name': proj['name'], 'ok': ok})
            else:
                results.append({'id': pid, 'name': 'unknown', 'ok': False})
        with self.lock:
            self.save()
        return results

    def file_tree(self, pid):
        with self.lock:
            proj = self.projects.get(pid)
        if not proj:
            return []
        return proj.get('file_list', [])

    def read_file(self, pid, rel):
        with self.lock:
            proj = self.projects.get(pid)
        if not proj:
            return None
        # prevent path escape — use a separator-aware prefix check so that a
        # sibling like  /a/proj-evil  can't pass for being inside  /a/proj
        base = os.path.realpath(proj['path'])
        full = os.path.realpath(os.path.join(base, rel))
        if not _within_exact(full, base):
            return None
        # only ever serve the code/text files we actually index — never raw
        # secrets like id_rsa / .env that might sit inside an added folder
        if os.path.splitext(full)[1].lower() not in CODE_EXT:
            return None
        try:
            with open(full, errors='ignore') as f:
                return f.read(500_000)  # cap 500 KB
        except Exception as e:
            print(f"[read_file] {e}", file=sys.stderr)   # detail to log, not body
            return "# Не удалось прочитать файл"

    # ── short auto-summary for the hover popover ──────────────────
    def project_info(self, pid):
        """Build a short, heuristic description of a project (no network/LLM).

        Reads the top-level dir for a manifest (package.json / pyproject /
        Cargo.toml / …) and a README, infers the kind, and returns a compact
        dict for the tooltip. Cheap: no recursive walk — reuses stored stats.
        """
        with self.lock:
            proj = self.projects.get(pid)
        if not proj:
            return None
        base = os.path.realpath(proj['path'])

        def read(name, cap=8000):
            # confine to the project root — realpath blocks a manifest/README
            # symlink that points outside the project (or outside $HOME)
            full = os.path.realpath(os.path.join(base, name))
            if not _within_exact(full, base):
                return None
            try:
                with open(full, errors='ignore') as fh:
                    return fh.read(cap)
            except Exception:
                return None

        # case-insensitive top-level listing
        try:
            entries = {e.lower(): e for e in os.listdir(base)}
        except PermissionError:
            return {'name': proj['name'], 'kind': 'Нет доступа',
                    'desc': 'Нет прав на чтение этой папки (NTFS-права или антивирус).',
                    'stats': '', 'langs': []}
        except Exception:
            entries = {}

        EXT_LANG = {'.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript',
                    '.js': 'JavaScript', '.jsx': 'JavaScript', '.go': 'Go',
                    '.rs': 'Rust', '.java': 'Java', '.rb': 'Ruby', '.php': 'PHP',
                    '.swift': 'Swift', '.kt': 'Kotlin', '.c': 'C', '.cpp': 'C++',
                    '.html': 'HTML', '.css': 'CSS', '.vue': 'Vue', '.svelte': 'Svelte'}

        kind, desc = None, ''

        # 1) manifests
        if 'package.json' in entries:
            try:
                pkg = json.loads(read(entries['package.json']) or '{}')
            except Exception:
                pkg = {}
            deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
            fw = ('Next.js' if 'next' in deps else 'React' if 'react' in deps
                  else 'Vue' if 'vue' in deps else 'Svelte' if 'svelte' in deps
                  else 'Express' if 'express' in deps else None)
            kind = f"Node.js · {fw}" if fw else 'Node.js'
            desc = pkg.get('description', '') or ''
        elif 'pyproject.toml' in entries:
            kind = 'Python'
            txt = read(entries['pyproject.toml']) or ''
            m = re.search(r'(?m)^\s*description\s*=\s*["\'](.+?)["\']', txt)
            desc = m.group(1) if m else ''
        elif 'setup.py' in entries or 'requirements.txt' in entries:
            kind = 'Python'
        elif 'cargo.toml' in entries:
            kind = 'Rust'
            m = re.search(r'(?m)^\s*description\s*=\s*["\'](.+?)["\']',
                          read(entries['cargo.toml']) or '')
            desc = m.group(1) if m else ''
        elif 'go.mod' in entries:
            kind = 'Go'
        elif 'composer.json' in entries:
            kind = 'PHP'
        elif 'gemfile' in entries:
            kind = 'Ruby'
        elif 'pom.xml' in entries or 'build.gradle' in entries:
            kind = 'Java'

        # 2) README description (if manifest gave none)
        if not desc:
            for key in ('readme.md', 'readme.txt', 'readme', 'readme.rst'):
                if key in entries:
                    desc = self._readme_excerpt(read(entries[key]) or '')
                    break

        # 3) fall back to dominant language
        langs = proj.get('langs', {})
        if not kind:
            if langs:
                top = max(langs.items(), key=lambda kv: kv[1])[0]
                kind = EXT_LANG.get(top, top.lstrip('.').upper() or 'Папка')
            elif 'index.html' in entries:
                kind = 'Статический сайт'
            else:
                kind = 'Папка'

        files, lines = proj.get('files', 0), proj.get('lines', 0)
        stats = (f"{files} файлов · {lines:,} строк".replace(',', ' ')
                 if files else 'Ещё не сканировано')
        lang_list = [[k.lstrip('.'), v] for k, v in
                     sorted(langs.items(), key=lambda kv: -kv[1])[:5]]

        return {'name': proj['name'], 'kind': kind,
                'desc': (desc or '').strip()[:280],
                'stats': stats, 'langs': lang_list}

    @staticmethod
    def _readme_excerpt(text):
        """First meaningful prose paragraph from a README — skip headings,
        badges, HTML, code fences."""
        out = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                if out:
                    break
                continue
            if line[0] in '#!<[|=-`' or line.startswith('```'):
                continue
            out.append(line)
            if sum(len(x) for x in out) > 240:
                break
        text = ' '.join(out)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)   # [label](url) → label
        text = re.sub(r'[*_`]+', '', text)                     # **bold** `code` _em_
        return text.strip()[:280]


STORE = Store()


# ── Windows helpers ───────────────────────────────────────────
def pick_folder():
    """Native folder picker via a PowerShell + WinForms dialog.

    Returns the selected path, or None. Uses the same "shell out to a
    scripting host" approach as the macOS build (which shells out to
    osascript) — Windows ships PowerShell + .NET WinForms out of the box, so
    this stays dependency-free.
    """
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
        "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$f.Description = 'Select a project folder'; "
        "$f.ShowNewFolderButton = $false; "
        "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "Write-Output $f.SelectedPath }"
    )
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
            capture_output=True, text=True, timeout=120,
            creationflags=_NO_WINDOW,
        )
        path = out.stdout.strip()
        return path if path else None
    except Exception:
        return None


def reveal_in_explorer(path):
    """Open `path` in File Explorer."""
    try:
        os.startfile(path)  # Windows-only stdlib function
        return True
    except Exception:
        return False


def open_terminal(path, cmd=None, app="wt"):
    """Open a new terminal at `path`; optionally run `cmd` there (user's own
    command). `app` (settings ▸ launch) picks Windows Terminal / PowerShell /
    cmd.

    Windows Terminal (`wt`, the Windows 11 default, on PATH via an App
    Execution Alias) opens at `path`. PowerShell opens a persistent window at
    `path`. Any other case — or a failure of the above — falls back to a
    throwaway .bat opened with os.startfile: letting Explorer's own .bat
    association spawn the console sidesteps cmd.exe's finicky inline quoting.
    """
    if app == "powershell":
        try:
            ps = f"Set-Location -LiteralPath '{path}'"
            if cmd:
                ps += f"; {cmd}"
            subprocess.Popen(['powershell', '-NoExit', '-NoProfile', '-Command', ps])
            return True
        except Exception:
            pass
    elif app == "wt":
        wt = shutil.which('wt')
        if wt:
            args = [wt, '-d', path]
            if cmd:
                args += ['cmd', '/k', cmd]
            try:
                subprocess.Popen(args)
                return True
            except Exception:
                pass
    # app == "cmd", or any of the above was unavailable/failed
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        bat = os.path.join(DATA_DIR, f"_run_{uuid.uuid4().hex[:8]}.bat")
        with open(bat, 'w') as f:
            f.write('@echo off\r\n')
            f.write(f'cd /d "{path}"\r\n')
            if cmd:
                f.write(cmd + '\r\n')
        os.startfile(bat)
        return True
    except Exception:
        return False


def _run_launcher(exe, extra_args):
    """Run an editor CLI resolved via shutil.which().

    VS Code / Cursor install their `code`/`cursor` command as a `.cmd` batch
    launcher, not a real PE executable. Windows' CreateProcess (what
    subprocess uses under shell=False) only auto-appends `.exe` to an
    extension-less command — it can't launch a `.cmd`/`.bat` file directly
    (that's cmd.exe's job via PATHEXT), so calling it straight fails with
    WinError 193. Routing through `cmd /c` — which does know how to run
    batch files — fixes that; a real `.exe` just runs as-is.
    """
    if not exe.lower().endswith(('.cmd', '.bat')):
        return subprocess.run([exe, *extra_args], capture_output=True,
                              check=False, creationflags=_NO_WINDOW)

    # cmd.exe re-parses its own command line, and & | ^ < > ( ) are operators
    # to it while being perfectly legal in NTFS names — an unquoted project path
    # like  C:\dev\my&calc  would run the tail as a second command. Quote every
    # token ourselves and hand cmd a STRING: passing a list would let
    # subprocess.list2cmdline() re-join it, and that only quotes arguments
    # containing spaces (and backslash-escapes any quotes we added), which
    # reopens the same hole for exactly the paths that need it most.
    # Anything inside double quotes is literal to cmd. The leading `call` also
    # keeps cmd's "/C strips the outer pair of quotes" rule from firing.
    parts = [exe, *extra_args]
    if any(ch in a for a in parts for ch in '"%'):
        # `"` can't occur in an NTFS name, and %VAR% is expanded even inside
        # quotes. Report failure so the caller falls back to Explorer.
        return subprocess.CompletedProcess(parts, 1)
    # /S: take everything between the outermost pair of quotes verbatim, which
    # is the only documented way to pass several quoted arguments through cmd
    # without its "strip the first and last quote on the line" rule mangling
    # them. `call` would work for that too but re-parses its remainder and
    # doubles carets that a quoted argument never un-doubles, so a project at
    # C:\dev\a^b would silently open C:\dev\a^^b and still report success.
    # /V:OFF pins delayed expansion off, so `!` in a folder name stays literal
    # even under a machine that turns it on via the Command Processor AutoRun.
    line = 'cmd /v:off /s /c "' + ' '.join(f'"{a}"' for a in parts) + '"'
    return subprocess.run(line, capture_output=True, check=False,
                          creationflags=_NO_WINDOW)


def open_in_vscode(path):
    """Open `path` as its own folder/window in VS Code.

    `-n`/`--new-window` forces a fresh window at `path` instead of VS Code's
    default of reusing whatever window is already open — the Windows
    analogue of the macOS `open -na ... --args` fix (see server.py history:
    without it, an already-running VS Code just adds `path` to the current
    window instead of opening it as its own project).
    """
    code = shutil.which('code')
    if code:
        try:
            r = _run_launcher(code, ['-n', path])
            if r.returncode == 0:
                return True
        except Exception:
            pass
    return reveal_in_explorer(path)


def open_in_editor(path, pref="auto"):
    """Open `path` in the preferred editor (settings ▸ launch).

    pref: "code" | "cursor" | "system" (Explorer) | "auto" (VS Code → Cursor).
    """
    if pref == "system":
        return reveal_in_explorer(path)
    order = {"code": ["code"], "cursor": ["cursor"]}.get(pref, ["code", "cursor"])
    for name in order:
        exe = shutil.which(name)
        if not exe:
            continue
        try:
            r = _run_launcher(exe, ['-n', path])
            if r.returncode == 0:
                return True
        except Exception:
            continue
    return reveal_in_explorer(path)


def open_url(url):
    """Open an external https URL — allowlisted to github.com (settings ▸ GitHub)."""
    try:
        u = urlparse(url)
        if u.scheme not in ('http', 'https'):
            return False
        if (u.hostname or '').lower() not in ('github.com', 'www.github.com'):
            return False
        os.startfile(url)
        return True
    except Exception:
        return False


def _config_payload():
    """Full current config for the UI — with live-computed fields folded in."""
    cfg = json.loads(json.dumps(_deep_merge(DEFAULT_CONFIG, CONFIG)))
    cfg['startup']['launch_at_login'] = login_item_enabled()
    cfg['storage']['data_dir'] = STORE.data_dir
    return cfg


def apply_config_patch(patch):
    """Validate + merge a partial config from the settings screen; run side effects."""
    global CONFIG
    if not isinstance(patch, dict):
        raise ValueError("bad config")
    with _config_lock:
        new = _deep_merge(CONFIG, {})

        np = patch.get('new_project') or {}
        if 'base_dir' in np:    new['new_project']['base_dir'] = _need_dir(np['base_dir'])
        if 'starter_dir' in np: new['new_project']['starter_dir'] = _need_dir(np['starter_dir'])
        if 'name' in np:        new['new_project']['name'] = _clean_name(np['name'])
        if 'onboard' in np:     new['new_project']['onboard'] = str(np['onboard'])[:200]

        lc = patch.get('launch') or {}
        if 'editor' in lc:
            new['launch']['editor'] = lc['editor'] if lc['editor'] in _EDITORS else 'auto'
        if 'terminal' in lc:
            new['launch']['terminal'] = lc['terminal'] if lc['terminal'] in _TERMINALS else 'wt'
        if 'default_run_cmd' in lc:
            new['launch']['default_run_cmd'] = str(lc['default_run_cmd'])[:300]

        sc = patch.get('scan') or {}
        if 'auto_on_focus' in sc:
            new['scan']['auto_on_focus'] = bool(sc['auto_on_focus'])
        if 'interval_sec' in sc:
            try:
                iv = int(sc['interval_sec'])
            except (TypeError, ValueError):
                iv = 45
            new['scan']['interval_sec'] = min(3600, max(0, iv))
        if 'watched' in sc:
            folders = []
            for f in (sc['watched'] or [])[:50]:
                d = _validate_dir(f)
                if d and d not in folders:
                    folders.append(d)
            new['scan']['watched'] = folders

        CONFIG = new
        _save_config(CONFIG)

    st = patch.get('storage') or {}
    if st.get('data_dir'):
        STORE.set_data_dir(st['data_dir'])
    su = patch.get('startup') or {}
    if 'launch_at_login' in su:
        set_login_item(bool(su['launch_at_login']))
    return _config_payload()


# ── HTTP handler ──────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # quiet

    # -- security --
    LOOPBACK = ('127.0.0.1', 'localhost', '::1')

    def _host_ok(self):
        """Block DNS-rebinding + cross-site (CSRF) calls.

        DNS-rebinding: a malicious page points a hostname at 127.0.0.1 and calls
        this local API — its Host header is the attacker domain, not loopback.
        CSRF: a cross-origin page's fetch carries an Origin header that isn't
        loopback. Reject both; allow same-origin (no/loopback Origin) loopback Host.
        """
        host = (self.headers.get('Host') or '').strip()
        hostname = host.rsplit(':', 1)[0] if host.count(':') == 1 else host
        hostname = hostname.strip('[]')  # IPv6 literal
        if hostname not in self.LOOPBACK:
            self._json({'error': 'forbidden host'}, 403)
            return False
        origin = self.headers.get('Origin')
        if origin:
            oh = urlparse(origin).hostname
            if oh not in self.LOOPBACK:
                self._json({'error': 'forbidden origin'}, 403)
                return False
        return True

    # -- helpers --
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('X-Dashhy', '1')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return {}

    def _static(self, path):
        if path in ('/', ''):
            path = '/index.html'
        fp = os.path.normpath(os.path.join(WEB_DIR, path.lstrip('/')))
        if (fp != WEB_DIR and not fp.startswith(WEB_DIR + os.sep)) \
                or not os.path.isfile(fp):
            self.send_error(404, "Not found")
            return
        ctype = {
            '.html': 'text/html; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.svg': 'image/svg+xml',
            '.woff2': 'font/woff2',
            '.woff': 'font/woff',
        }.get(os.path.splitext(fp)[1], 'application/octet-stream')
        with open(fp, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('X-Dashhy', '1')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    # -- routes --
    def do_GET(self):
        if not self._host_ok():
            return
        u = urlparse(self.path)
        p = u.path
        if p == '/api/projects':
            return self._json({'projects': STORE.list()})
        if p == '/api/config':
            return self._json({'config': _config_payload()})
        if p == '/api/files':
            q = parse_qs(u.query)
            return self._json({'files': STORE.file_tree(q.get('id', [''])[0])})
        if p == '/api/file':
            q = parse_qs(u.query)
            txt = STORE.read_file(q.get('id', [''])[0], q.get('path', [''])[0])
            if txt is None:
                return self._json({'error': 'not found'}, 404)
            return self._json({'content': txt})
        if p == '/api/info':
            q = parse_qs(u.query)
            info = STORE.project_info(q.get('id', [''])[0])
            if info is None:
                return self._json({'error': 'not found'}, 404)
            return self._json({'info': info})
        return self._static(p)

    def do_POST(self):
        if not self._host_ok():
            return
        p = urlparse(self.path).path
        body = self._body()
        if p == '/api/pick':
            return self._json({'path': pick_folder()})
        if p == '/api/projects':
            path = (body.get('path') or '').rstrip('/\\')
            name = body.get('name') or (os.path.basename(path) or path)
            # Folder must be a real dir under $HOME and NOT a credential dir.
            # ($HOME alone isn't a boundary — ~/.ssh is under $HOME — so we also
            #  deny known secret dirs and refuse to read non-code files.)
            rp = os.path.realpath(path) if path else ''
            home = os.path.realpath(os.path.expanduser('~'))
            inside_home = bool(rp) and _within(rp, home)
            if not path or not os.path.isdir(rp) or not inside_home \
                    or _is_sensitive_path(rp, home):
                return self._json({'error': 'invalid path'}, 400)
            return self._json({'project': STORE.add(name, path)})
        if p == '/api/scan':
            proj = STORE.scan(body.get('id'))
            return self._json({'project': proj} if proj else {'error': 'not found'},
                              200 if proj else 404)
        if p == '/api/scan-all':
            results = STORE.scan_all()
            return self._json({'results': results})
        if p == '/api/status':
            proj = STORE.set_status(body.get('id'), body.get('status'))
            return self._json({'project': proj} if proj else {'error': 'bad'},
                              200 if proj else 400)
        if p == '/api/open':
            proj = next((x for x in STORE.list() if x['id'] == body.get('id')), None)
            if not proj:
                return self._json({'error': 'not found'}, 404)
            if body.get('editor'):
                ok = open_in_editor(proj['path'], CONFIG.get('launch', {}).get('editor', 'auto'))
            else:
                ok = reveal_in_explorer(proj['path'])
            return self._json({'ok': ok})
        if p == '/api/notes':
            proj = STORE.set_notes(body.get('id'), body.get('notes'))
            return self._json({'project': proj} if proj else {'error': 'not found'},
                              200 if proj else 404)
        if p == '/api/run-cmd':
            proj = STORE.set_run_cmd(body.get('id'), body.get('cmd'))
            return self._json({'project': proj} if proj else {'error': 'not found'},
                              200 if proj else 404)
        if p == '/api/launch':
            proj = next((x for x in STORE.list() if x['id'] == body.get('id')), None)
            if not proj:
                return self._json({'error': 'not found'}, 404)
            lc = CONFIG.get('launch', {})
            cmd = (proj.get('run_cmd') or lc.get('default_run_cmd')) if body.get('run') else None
            ok = open_terminal(proj['path'], cmd, lc.get('terminal', 'wt'))
            return self._json({'ok': ok})
        if p == '/api/discover':
            added = STORE.discover(body.get('path'))
            return self._json({'added': added})
        if p == '/api/create-project':
            try:
                proj, dest = STORE.create_from_starter()
            except ValueError as e:
                return self._json({'error': str(e)}, 400)
            except Exception as e:
                print(f"[create-project] {e}", file=sys.stderr)
                return self._json({'error': 'Не удалось создать проект'}, 500)
            opened = open_in_vscode(dest)
            return self._json({'project': proj, 'path': dest, 'opened': opened})
        if p == '/api/config':
            try:
                cfg = apply_config_patch(body)
            except ValueError as e:
                return self._json({'error': str(e)}, 400)
            except Exception as e:
                print(f"[config] {e}", file=sys.stderr)
                return self._json({'error': 'Не удалось сохранить настройки'}, 500)
            return self._json({'config': cfg})
        if p == '/api/discover-watched':
            return self._json({'added': STORE.discover_watched()})
        if p == '/api/open-url':
            return self._json({'ok': open_url(body.get('url', ''))})
        return self._json({'error': 'unknown route'}, 404)

    def do_DELETE(self):
        if not self._host_ok():
            return
        p = urlparse(self.path).path
        if p.startswith('/api/projects/'):
            STORE.remove(p.rsplit('/', 1)[-1])
            return self._json({'ok': True})
        return self._json({'error': 'unknown route'}, 404)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _is_our_dashboard(port):
    """True if a Dashhy server already answers on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.6) as r:
            return r.headers.get('X-Dashhy') == '1'
    except Exception:
        return False


def start_server(host="127.0.0.1", port=PORT):
    """Start the HTTP server on a free port.

    Reuses the existing port-selection logic (cycles through PORT..PORT+19).
    Does NOT call serve_forever() or open a browser — caller is responsible
    for both.

    Returns:
        (httpd, actual_port): the Server instance and the port it bound to.
    """
    os.chdir(HERE)
    httpd, actual_port = None, port
    for p in range(port, port + 20):
        try:
            httpd = Server((host, p), Handler)
            actual_port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise RuntimeError(
            f"Не нашёл свободный порт в диапазоне {port}–{port + 19}."
        )
    return httpd, actual_port


def run_selftest(port):
    """Headless check that this build actually serves the dashboard.

    Used by CI (`server.py --selftest`) and by the packaged binary
    (`Dashhy --selftest`), where there is no desktop session to show a window
    in. Writes its report to $DASHHY_SELFTEST_OUT when set — the release binary
    is built for the GUI subsystem, so its stdout goes nowhere.
    """
    import urllib.request

    lines, ok = [], True
    checks = (('/', '<title>Dashhy</title>'),
              ('/api/projects', '"projects"'),
              ('/api/config', '"launch"'))
    for path, needle in checks:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=15) as r:
                body = r.read(8192).decode('utf-8', 'replace')
            good = r.status == 200 and needle in body
            detail = f"status={r.status}"
        except Exception as e:
            good, detail = False, repr(e)
        ok = ok and good
        lines.append(f"[selftest] {path:15} {'OK' if good else 'FAIL'}  {detail}")

    lines.append(f"[selftest] port={port} result={'PASS' if ok else 'FAIL'}")
    report = "\n".join(lines)
    print(report, file=sys.stderr)
    out = os.environ.get('DASHHY_SELFTEST_OUT')
    if out:
        try:
            with open(out, 'w', encoding='utf-8') as f:
                f.write(report + "\n")
        except Exception:
            pass
    return ok


def main():
    os.chdir(HERE)

    if '--selftest' in sys.argv:
        httpd, port = start_server()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        ok = run_selftest(port)
        try:
            httpd.shutdown()
        except Exception:
            pass
        sys.exit(0 if ok else 1)

    # Already running? Just open the browser to it — no second server, no error.
    if _is_our_dashboard(PORT):
        url = f"http://127.0.0.1:{PORT}/"
        print(f"\n  Dashhy уже запущен на {url} — открываю браузер.\n")
        webbrowser.open(url)
        return

    try:
        httpd, port = start_server()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    url = f"http://127.0.0.1:{port}/"
    print("\n  Dashhy")
    print(f"  Открыто:  {url}")
    print("  Это окно держит сервер. Закрой его (или Ctrl+C), чтобы остановить.\n")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")


if __name__ == "__main__":
    main()
