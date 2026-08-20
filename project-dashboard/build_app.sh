#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  build_app.sh — собирает самодостаточный  Dashhy.app  (PyInstaller)
#
#  ЗАЧЕМ self-contained:
#  Приложение сканирует папки проектов в ~/Desktop / ~/Documents — это TCC-зона.
#  Чтобы доступ через «Системные настройки → Конфиденциальность → Доступ к диску»
#  реально работал, ЧИТАЮЩИЙ диск процесс должен иметь нашу подпись
#  (com.dashhy.app), а не системного Python. PyInstaller вшивает Python
#  внутрь бандла → читающий бинарь = наш → тумблер FDA «Dashhy»
#  применяется к нему.
#
#  Плюс:
#   • NSAppTransportSecurity — иначе WKWebView блокирует http://127.0.0.1 (белое окно)
#   • ad-hoc подпись — стабильная identity для TCC
#   • установка в ~/Applications (вне TCC) + симлинк на Рабочем столе
#
#  Запусти заново после правок кода. Требует: pip install --user pyinstaller pywebview
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SRC"

# --no-install: build and sign into dist/ but skip installing to ~/Applications
# and skip lsregister. CI uses this to prove the bundle builds and its server
# answers, without writing into a home directory it does not own.
NO_INSTALL=0
[ "${1:-}" = "--no-install" ] && NO_INSTALL=1
APP_NAME="Dashhy"
DEST="$HOME/Applications/$APP_NAME.app"
SITE="$HOME/Library/Python/3.9/lib/python/site-packages"
PY_BIN="${PYTHON:-/usr/bin/python3}"          # CI sets PYTHON to the runner's interpreter
PB=/usr/libexec/PlistBuddy

export PYTHONPATH="$SITE"

echo "→ PyInstaller сборка…"
rm -rf build dist "$APP_NAME.spec"
"$PY_BIN" -m PyInstaller \
  --noconfirm --windowed \
  --name "$APP_NAME" \
  --icon AppIcon.icns \
  --osx-bundle-identifier com.dashhy.app \
  --add-data "web:web" \
  --collect-all webview \
  --hidden-import WebKit --hidden-import Foundation \
  --hidden-import AppKit --hidden-import objc --hidden-import Quartz \
  `# setuptools 82 ломает PyInstaller-хук pyi_rth_pkgres (appdirs / InvalidVersion`\
  `#  на путях Frameworks) → app не стартует. Наш код их не юзает — исключаем.` \
  --exclude-module pkg_resources --exclude-module setuptools \
  app.py >/tmp/pd-build.log 2>&1 || { echo "Сборка упала — см. /tmp/pd-build.log"; tail -20 /tmp/pd-build.log; exit 1; }

BUILT="dist/$APP_NAME.app"
PL="$BUILT/Contents/Info.plist"

echo "→ ATS-исключение для localhost (иначе белое окно)…"
$PB -c "Add :NSAppTransportSecurity dict" "$PL" 2>/dev/null || true
$PB -c "Add :NSAppTransportSecurity:NSAllowsLocalNetworking bool true" "$PL" 2>/dev/null || true
$PB -c "Add :NSAppTransportSecurity:NSAllowsArbitraryLoads bool true" "$PL" 2>/dev/null || true

echo "→ Подпись (ad-hoc)…"
codesign --force --deep --sign - "$BUILT" >/dev/null 2>&1 || echo "  (codesign пропущен)"

if [ "$NO_INSTALL" = "1" ]; then
  echo "✓ Собрано: $BUILT  (--no-install: пропускаю ~/Applications и lsregister)"
  exit 0
fi

echo "→ Установка в ~/Applications…"
rm -rf "$DEST"
cp -R "$BUILT" "$DEST"
# регистрируем в LaunchServices → появляется в Launchpad с иконкой
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$DEST" 2>/dev/null || true

echo "✓ Готово."
echo "  Приложение:  $DEST"
echo "  Запуск:      Launchpad → «Dashhy» (или из ~/Applications)"
echo "  Identity:    com.dashhy.app  (FDA-тумблер «Dashhy» к нему применяется)"
