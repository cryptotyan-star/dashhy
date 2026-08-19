# Installing Dashhy on Windows 11 · Установка Dashhy на Windows 11

**Fastest path — no Python needed:** download `dashhy-windows-ready.zip` from
the [Releases page](https://github.com/cryptotyan-star/dashhy/releases/tag/windows),
unzip it, double-click **`Install Dashhy.bat`**. It copies `Dashhy.exe`
somewhere permanent, drops a shortcut on your Desktop, and launches it.

> 🇷🇺 **Самый быстрый способ — без Python:** скачай `dashhy-windows-ready.zip`
> со [страницы релизов](https://github.com/cryptotyan-star/dashhy/releases/tag/windows),
> распакуй, дважды кликни **`Install Dashhy.bat`**. Появится ярлык на рабочем
> столе, Dashhy запустится сам.

**The binary is not code-signed**, so Windows will show a *"Windows protected
your PC"* (SmartScreen) popup — click **"More info" → "Run anyway"**. Because it
is unsigned, check what you downloaded against `SHA256SUMS.txt` from the same
release before running it:

```powershell
Get-FileHash .\dashhy-windows-ready.zip -Algorithm SHA256
```

Every release also names the exact commit it was built from and links its build
log, so you can see what went into the binary.

> 🇷🇺 **Бинарь не подписан** — Windows покажет SmartScreen («Windows protected
> your PC»), жми **"More info" → "Run anyway"**. Именно поэтому сверь скачанное
> с `SHA256SUMS.txt` из того же релиза командой выше. В описании релиза указан
> коммит сборки и ссылка на лог — видно, из чего собран бинарь.

Everything below is for building/running from **source** instead (useful if
you want to modify the code, or the prebuilt `.exe` doesn't work for you).
Dashhy runs on **Windows 11** (Windows 10 works too, see the requirements
note) with **Python 3**. Pick the path that suits you. The first one needs
nothing but Python.

> The screenshots below show the Dashhy **web UI** — the same HTML/CSS/JS
> that renders identically whether it's sitting inside a browser tab, the
> native window on Windows, or the native window on macOS. They're carried
> over from the original macOS build rather than re-shot on Windows, because
> the interface itself is pixel-identical; only the window chrome around it
> differs by OS.

> 🇷🇺 Русская версия — [ниже](#-установка-на-русском).

---

## English

### Before you start

**1. Install Python 3**, if you don't already have it:

- Go to <https://www.python.org/downloads/> and download the latest Python 3 installer.
- Run it. **Check the box "Add python.exe to PATH"** at the bottom of the first screen — this is the step people miss, and without it none of the scripts below will find Python.
- Click "Install Now".

**2. Get the code** — unzip the `dashhy-windows.zip` you downloaded anywhere you like, e.g. `C:\Users\<you>\dashhy-windows\`.

**3. Open a terminal in that folder** — in File Explorer, open the `dashhy-windows` folder, click the address bar, type `cmd`, press Enter (or right-click inside the folder → "Open in Terminal" on Windows 11).

Check Python is on PATH:

```bat
python --version          :: should print Python 3.x.x
```

If that fails, try `py --version` instead — the installer script tries both automatically, but for this manual check use whichever one works.

---

### Option A — One-click installer (recommended)

Double-click **`install.bat`** in the `dashhy-windows` folder (or run it from the terminal you just opened):

```bat
install.bat
```

The script will:
1. check that Python 3 is available,
2. install **pywebview** for the current user (only needed for the native window),
3. launch Dashhy.

If Windows shows a **"Windows protected your PC" (SmartScreen)** popup (this happens for any unsigned `.bat`/`.exe` you download), click **"More info" → "Run anyway"**.

If pywebview can't be installed for any reason, the script automatically falls back to **browser mode** — Dashhy still works.

---

### Option B — Browser mode (zero dependencies)

Nothing to install. Pure Python standard library:

```bat
cd project-dashboard
python server.py
```

Your browser opens at **http://127.0.0.1:7777/**.
Change the port if needed: `set DASH_PORT=8080 && python server.py`.
Stop it with `Ctrl+C` in the terminal window.

---

### Option C — Native window

A real app window (no tabs, no address bar), rendered via Microsoft Edge
WebView2 — the runtime **ships preinstalled on Windows 11**, so there's
nothing extra to install for the rendering engine itself. Needs
**pywebview** once:

```bat
python -m pip install --user --upgrade pip
python -m pip install --user pywebview
```

Then:

```bat
cd project-dashboard
python app.py
```

The window remembers its size and position between launches.

> **Windows 10 only:** if the window stays blank, install the
> [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
> — it's optional on Windows 10 (Windows 11 already has it).

---

### Option D — Build a self-contained Dashhy.exe

This produces a double-clickable `Dashhy.exe` that bundles Python — you (or
anyone else) can then run it without installing Python at all. **This step
must run on Windows** — PyInstaller packages for whatever OS it's running
on, it cannot cross-build a Windows `.exe` from macOS or Linux.

```bat
cd project-dashboard
build_app.bat
```

This installs `pyinstaller` + `pywebview` for you, then builds. When it
finishes:

```
project-dashboard\dist\Dashhy.exe
```

Double-click it to run, or right-click → **Show more options → Send to →
Desktop (create shortcut)** to pin it somewhere convenient. Re-run
`build_app.bat` after any code change.

> The first launch may take a few seconds longer while Windows Defender
> scans the new, unsigned executable — normal for any freshly built `.exe`.

---

### A note on Windows Terminal & the editor buttons

- **"Open Terminal here"** uses **Windows Terminal** (`wt`), the Windows 11
  default — it's preinstalled and needs no setup. If it's ever missing,
  Dashhy falls back to a plain `cmd` window automatically.
- **"Open in editor"** looks for VS Code's `code` command, then Cursor's
  `cursor` command, on your `PATH`. Both editors add themselves to PATH
  automatically during a normal install — if the button falls back to
  Explorer instead, reinstall the editor and make sure "Add to PATH" was
  checked, or add its `bin` folder to PATH manually.

---

### Updating

Download the new ZIP, unzip it over (or beside) the old folder. If you built
`Dashhy.exe` (Option D), rebuild it:

```bat
cd project-dashboard
build_app.bat
```

### Uninstalling

- Delete the `dashhy-windows` folder.
- Delete your project registry: delete the `%LOCALAPPDATA%\Dashhy` folder
  (open File Explorer, paste `%LOCALAPPDATA%` into the address bar, Enter,
  then delete the `Dashhy` folder inside).
- If you made a desktop shortcut to `Dashhy.exe`, delete that too.

Dashhy never modifies the project folders it lists — removing a project from
the dashboard only forgets it; nothing on disk is touched.

---
---

<a name="-установка-на-русском"></a>
## Установка на русском

Dashhy работает на **Windows 11** (Windows 10 тоже подойдёт, см. примечание
в требованиях) с **Python 3**. Выбери удобный способ. Первый не требует
вообще ничего, кроме Python.

### Перед стартом

**1. Установи Python 3**, если его ещё нет:

- Зайди на <https://www.python.org/downloads/> и скачай последний установщик Python 3.
- Запусти его. **Обязательно поставь галочку «Add python.exe to PATH»** внизу первого экрана — это тот самый шаг, который все забывают, без него ни один скрипт ниже не найдёт Python.
- Нажми «Install Now».

**2. Скачай код** — распакуй `dashhy-windows.zip` куда угодно, например в `C:\Users\<имя>\dashhy-windows\`.

**3. Открой терминал в этой папке** — в Проводнике открой папку `dashhy-windows`, кликни в адресную строку, введи `cmd`, нажми Enter (или ПКМ внутри папки → «Открыть в терминале» на Windows 11).

Проверь, что Python виден системе:

```bat
python --version          :: должно показать Python 3.x.x
```

Если не работает — попробуй `py --version`. Установочный скрипт пробует оба варианта сам, но для этой ручной проверки используй тот, что сработал.

---

### Способ A — Установщик в один клик (рекомендуется)

Дважды кликни **`install.bat`** в папке `dashhy-windows` (или запусти его из уже открытого терминала):

```bat
install.bat
```

Скрипт:
1. проверит, что есть Python 3,
2. поставит **pywebview** для текущего пользователя (нужно только для нативного окна),
3. запустит Dashhy.

Если Windows покажет окно **«Windows защитила ваш компьютер» (SmartScreen)** — это стандартная реакция на любой неподписанный `.bat`/`.exe`, — нажми **«Подробнее» → «Выполнить в любом случае»**.

Если pywebview поставить не удалось — скрипт сам откроет **браузерный режим**, Dashhy всё равно заработает.

---

### Способ B — Браузерный режим (без зависимостей)

Ставить нечего. Только стандартная библиотека Python:

```bat
cd project-dashboard
python server.py
```

Браузер откроется на **http://127.0.0.1:7777/**.
Сменить порт: `set DASH_PORT=8080 && python server.py`.
Остановить — `Ctrl+C` в окне терминала.

---

### Способ C — Нативное окно

Настоящее окно приложения (без вкладок и адресной строки) на движке
Microsoft Edge WebView2 — рантайм **уже встроен в Windows 11**, отдельно
ставить сам движок не нужно. Нужен **pywebview** один раз:

```bat
python -m pip install --user --upgrade pip
python -m pip install --user pywebview
```

Затем:

```bat
cd project-dashboard
python app.py
```

Окно запоминает размер и позицию между запусками.

> **Только для Windows 10:** если окно остаётся пустым — поставь
> [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
> (на Windows 11 он уже есть).

---

### Способ D — Собрать самостоятельный Dashhy.exe

Создаёт `Dashhy.exe`, внутрь которого вшит Python — его (или его копию)
можно запускать на любом Windows 11 без установки Python вообще. **Этот шаг
обязательно выполнять на Windows** — PyInstaller всегда собирает под ту ОС,
на которой запущен, собрать Windows-`.exe` с macOS или Linux нельзя.

```bat
cd project-dashboard
build_app.bat
```

Скрипт сам поставит `pyinstaller` и `pywebview`, затем соберёт. После сборки:

```
project-dashboard\dist\Dashhy.exe
```

Дважды кликни, чтобы запустить, или ПКМ → **Дополнительные параметры →
Отправить → Рабочий стол (создать ярлык)**, чтобы закрепить удобнее.
Пересобирай `build_app.bat` после каждой правки кода.

> Первый запуск может быть на пару секунд дольше — Защитник Windows
> сканирует свежесобранный неподписанный `.exe`, это нормально для любого
> нового исполняемого файла.

---

### О Windows Terminal и кнопках редактора

- **«Открыть терминал здесь»** использует **Windows Terminal** (`wt`) —
  стандартное приложение Windows 11, уже установлено, ничего настраивать не
  нужно. Если его вдруг нет — Dashhy автоматически откроет обычное окно
  `cmd`.
- **«Открыть в редакторе»** ищет команду `code` (VS Code), затем `cursor`
  (Cursor) в `PATH`. Оба редактора добавляют себя в PATH сами при обычной
  установке — если кнопка вместо этого открывает Проводник, переустанови
  редактор и убедись, что галочка «Add to PATH» была отмечена, либо добавь
  его папку `bin` в PATH вручную.

---

### Обновление

Скачай новый ZIP, распакуй поверх (или рядом со) старой папкой. Если собирал
`Dashhy.exe` (способ D) — пересобери:

```bat
cd project-dashboard
build_app.bat
```

### Удаление

- Удали папку `dashhy-windows`.
- Удали реестр проектов: удали папку `%LOCALAPPDATA%\Dashhy` (открой
  Проводник, вставь `%LOCALAPPDATA%` в адресную строку, Enter, удали папку
  `Dashhy` внутри).
- Если делал ярлык `Dashhy.exe` на рабочем столе — удали и его.

Dashhy никогда не меняет сами папки проектов — удаление проекта из дашборда
лишь «забывает» его, на диске ничего не трогается.
