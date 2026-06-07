#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  install.sh — set up and launch Dashhy.
#
#  What it does / Что делает:
#    1. checks Python 3 is available          / проверяет наличие Python 3
#    2. installs pywebview (for native window)/ ставит pywebview (нативное окно)
#    3. launches Dashhy                        / запускает Dashhy
#
#  If pywebview can't be installed, it falls back to browser mode (no deps).
#  Если pywebview поставить нельзя — открывается браузерный режим (без зависимостей).
#
#  Usage:  ./install.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Resolve the directory this script lives in, then the app folder.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT/project-dashboard"

say()  { printf '\033[1;34m→ %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$1"; }

# ── 1. Python 3 ──────────────────────────────────────────────────────────────
if command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
elif [ -x /usr/bin/python3 ]; then
  PY=/usr/bin/python3
else
  warn "Python 3 not found / Python 3 не найден."
  echo "  Install it from https://www.python.org/downloads/ or via Xcode tools:"
  echo "    xcode-select --install"
  exit 1
fi
ok "Python 3: $PY ($("$PY" --version 2>&1))"

if [ ! -d "$APP_DIR" ]; then
  warn "Can't find project-dashboard/ next to this script."
  exit 1
fi

# ── 2. pywebview (best effort — only needed for the native window) ───────────
say "Installing pywebview (native window) / ставлю pywebview…"
NATIVE=1
if "$PY" -c "import webview" >/dev/null 2>&1; then
  ok "pywebview already installed / уже установлен."
else
  "$PY" -m pip install --user --upgrade pip >/dev/null 2>&1 || true
  if "$PY" -m pip install --user pywebview >/dev/null 2>&1 \
       && "$PY" -c "import webview" >/dev/null 2>&1; then
    ok "pywebview installed / установлен."
  else
    NATIVE=0
    warn "Couldn't install pywebview — falling back to browser mode."
    warn "Не удалось поставить pywebview — открою браузерный режим."
  fi
fi

# ── 3. Launch ────────────────────────────────────────────────────────────────
cd "$APP_DIR"
if [ "$NATIVE" -eq 1 ]; then
  say "Launching Dashhy (native window) / запускаю Dashhy (нативное окно)…"
  exec "$PY" app.py
else
  say "Launching Dashhy (browser) → http://127.0.0.1:7777/"
  exec "$PY" server.py
fi
