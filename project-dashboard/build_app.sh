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
APP_NAME="Dashhy"
DEST="$HOME/Applications/$APP_NAME.app"
SITE="$HOME/Library/Python/3.9/lib/python/site-packages"
PB=/usr/libexec/PlistBuddy

export PYTHONPATH="$SITE"

echo "→ PyInstaller сборка…"
rm -rf build dist "$APP_NAME.spec"
/usr/bin/python3 -m PyInstaller \
  --noconfirm --windowed \
  --name "$APP_NAME" \
  --icon AppIcon.icns \
  --osx-bundle-identifier com.dashhy.app \
  --add-data "web:web" \
  --collect-all webview \
  --hidden-import WebKit --hidden-import Foundation \
  --hidden-import AppKit --hidden-import objc --hidden-import Quartz \
  app.py >/tmp/pd-build.log 2>&1 || { echo "Сборка упала — см. /tmp/pd-build.log"; tail -20 /tmp/pd-build.log; exit 1; }

BUILT="dist/$APP_NAME.app"
PL="$BUILT/Contents/Info.plist"

echo "→ ATS-исключение для localhost (иначе белое окно)…"
$PB -c "Add :NSAppTransportSecurity dict" "$PL" 2>/dev/null || true
$PB -c "Add :NSAppTransportSecurity:NSAllowsLocalNetworking bool true" "$PL" 2>/dev/null || true
$PB -c "Add :NSAppTransportSecurity:NSAllowsArbitraryLoads bool true" "$PL" 2>/dev/null || true

echo "→ Подпись (ad-hoc)…"
codesign --force --deep --sign - "$BUILT" >/dev/null 2>&1 || echo "  (codesign пропущен)"

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
