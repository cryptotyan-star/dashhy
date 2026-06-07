#!/usr/bin/env python3
"""
Dashhy — local backend.

Serves the Dashhy (Mi · Deep-Blue) web dashboard and exposes a tiny JSON API for
real filesystem access: list / add / scan / open projects on this Mac, read
file contents, pick a folder via the native macOS dialog.

Pure standard library — no pip installs. Run:  python3 server.py
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
import webbrowser
import urllib.request
from datetime import datetime
from urllib.parse import urlparse, parse_qs

# ── Paths / config ────────────────────────────────────────────
# When frozen by PyInstaller the bundled data lives in sys._MEIPASS, not next
# to this source file.
if getattr(sys, "frozen", False):
    HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR   = os.path.join(HERE, "web")
DATA_DIR  = os.path.expanduser("~/Library/Application Support/Dashhy")
DATA_FILE = os.path.join(DATA_DIR, "projects.json")
_OLD_DATA_DIR = os.path.expanduser("~/Library/Application Support/ProjectDashboard")


def _migrate_data_dir():
    """One-time move of the registry from the old ProjectDashboard dir to Dashhy."""
    try:
        if not os.path.exists(DATA_FILE) and os.path.exists(os.path.join(_OLD_DATA_DIR, "projects.json")):
            os.makedirs(DATA_DIR, exist_ok=True)
            shutil.copy2(os.path.join(_OLD_DATA_DIR, "projects.json"), DATA_FILE)
    except Exception as e:
        print(f"[migrate] {e}", file=sys.stderr)
PORT      = int(os.environ.get("DASH_PORT", "7777"))

CODE_EXT = {
    '.ts', '.tsx', '.js', '.jsx', '.py', '.go', '.rs', '.java', '.c', '.cpp',
    '.h', '.hpp', '.rb', '.php', '.swift', '.kt', '.css', '.scss', '.html',
    '.vue', '.svelte', '.md', '.json', '.yaml', '.yml', '.toml', '.sql',
    '.sh', '.bash', '.zsh',
}
SKIP_DIRS = {'node_modules', '.git', 'dist', 'build', '.next', '__pycache__',
             '.venv', 'venv', '.idea', '.vscode', 'Pods', '.cache'}
# lock/vendored files that explode file & line counts without being "your code"
SKIP_FILES = {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock',
              'Cargo.lock', 'composer.lock', 'Gemfile.lock'}
MAX_SCAN_ENTRIES = 50000   # hard cap so a giant tree can't hang/crash the scan

VALID_STATUS = {'idle', 'analyzing', 'running', 'stopped', 'complete'}

# Credential / secret directories we refuse to index even though they live under
# $HOME. The $HOME confinement alone is NOT a real boundary — ~/.ssh etc. are
# under $HOME — so we explicitly deny these (and never read non-code files).
SENSITIVE_SUBPATHS = (
    '.ssh', '.aws', '.gnupg', '.gpg', '.kube', '.docker', '.netrc',
    '.password-store', '.config/gh', '.config/gcloud',
    'Library/Keychains', 'Library/Application Support/Dashhy',
)


def _is_sensitive_path(rp, home):
    """True if realpath `rp` is, or is inside, a known credential/secret dir."""
    for sub in SENSITIVE_SUBPATHS:
        b = os.path.join(home, sub)
        if rp == b or rp.startswith(b + os.sep):
            return True
    return False


# ── Data store ────────────────────────────────────────────────
class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.projects = {}
        _migrate_data_dir()
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE) as f:
                    for item in json.load(f):
                        self.projects[item['id']] = self._migrate(item)
                # one-time safety snapshot per launch — recover a clobbered registry
                try:
                    shutil.copy2(DATA_FILE, DATA_FILE + ".bak")
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
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(list(self.projects.values()), f, indent=2)
        os.replace(tmp, DATA_FILE)
        try:
            os.chmod(DATA_FILE, 0o600)   # registry holds local paths — keep private
        except OSError:
            pass

    def list(self):
        return list(self.projects.values())

    def add(self, name, path):
        now = datetime.now().isoformat()
        p = {
            'id': f"proj_{uuid.uuid4().hex[:12]}",
            'name': name, 'path': path,
            'status': 'idle', 'last_stage': 'Added',
            'files': 0, 'lines': 0, 'langs': {},
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

    def scan(self, pid, save=True):
        with self.lock:
            proj = self.projects.get(pid)
        if not proj:
            return None
        # realpath the base so relpaths match read_file (which also realpaths)
        base = os.path.realpath(proj['path'])
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

        # macOS TCC: app launched by double-click can't read ~/Desktop, ~/Documents,
        # ~/Downloads without Full Disk Access. If the project root is denied, DON'T
        # overwrite prior file/line counts with zeros — keep them, surface the error.
        if access_denied:
            with self.lock:
                proj = self.projects.get(pid)
                if not proj:
                    return None
                # status is user-controlled only — scan must never change it
                proj['scan_error'] = 'no_access'
                proj['last_stage'] = 'Нет доступа к папке — дай Full Disk Access'
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
        refs — instant and offline.
        """
        if not os.path.exists(os.path.join(base, '.git')):
            return None
        try:
            out = subprocess.run(
                ['git', '-C', base, 'status', '--porcelain=2', '--branch'],
                capture_output=True, text=True, timeout=5,
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
                capture_output=True, text=True, timeout=5)
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
        if not root or not (root == home or root.startswith(home + os.sep)) \
                or _is_sensitive_path(root, home):
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
        if full != base and not full.startswith(base + os.sep):
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
            if full != base and not full.startswith(base + os.sep):
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
                    'desc': 'Дай Full Disk Access, чтобы собрать информацию.',
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


# ── macOS helpers ─────────────────────────────────────────────
def pick_folder():
    """Native folder picker via osascript. Returns POSIX path or None."""
    script = (
        'try\n'
        '  set f to choose folder with prompt "Select a project folder" '
        'default location (path to home folder)\n'
        '  return POSIX path of f\n'
        'on error\n'
        '  return ""\n'
        'end try'
    )
    try:
        out = subprocess.run(['osascript', '-e', script],
                             capture_output=True, text=True, timeout=120)
        path = out.stdout.strip()
        return path.rstrip('/') if path else None
    except Exception:
        return None


def reveal_in_finder(path):
    try:
        subprocess.run(['open', path], check=False)
        return True
    except Exception:
        return False


def open_terminal(path, cmd=None):
    """Open Terminal.app at `path`; optionally run `cmd` there (user's own command)."""
    p = path.replace('\\', '\\\\').replace('"', '\\"')
    if cmd:
        c = cmd.replace('\\', '\\\\').replace('"', '\\"')
        do = f'cd \\"{p}\\" && {c}'
    else:
        do = f'cd \\"{p}\\"'
    script = f'tell application "Terminal"\n activate\n do script "{do}"\nend tell'
    try:
        subprocess.run(['osascript', '-e', script], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def open_in_editor(path):
    """Try VS Code, then Cursor, then default `open`."""
    for cmd in (['code', path], ['open', '-a', 'Cursor', path],
                ['open', '-a', 'Visual Studio Code', path]):
        try:
            r = subprocess.run(cmd, capture_output=True, check=False)
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return reveal_in_finder(path)


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
            path = (body.get('path') or '').rstrip('/')
            name = body.get('name') or (os.path.basename(path) or path)
            # Folder must be a real dir under $HOME and NOT a credential dir.
            # ($HOME alone isn't a boundary — ~/.ssh is under $HOME — so we also
            #  deny known secret dirs and refuse to read non-code files.)
            rp = os.path.realpath(path) if path else ''
            home = os.path.realpath(os.path.expanduser('~'))
            inside_home = bool(rp) and (rp == home or rp.startswith(home + os.sep))
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
            ok = (open_in_editor if body.get('editor') else reveal_in_finder)(proj['path'])
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
            cmd = proj.get('run_cmd') if body.get('run') else None
            ok = open_terminal(proj['path'], cmd)
            return self._json({'ok': ok})
        if p == '/api/discover':
            added = STORE.discover(body.get('path'))
            return self._json({'added': added})
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


def main():
    os.chdir(HERE)

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
