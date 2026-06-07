# Installing Dashhy · Установка Dashhy

Dashhy runs on **macOS** with **Python 3** (which already ships with macOS).
Pick the path that suits you. The first one needs nothing but Python.

> 🇷🇺 Русская версия — [ниже](#-установка-на-русском).

---

## English

### Before you start

Open the **Terminal** app (press `⌘ + Space`, type `Terminal`, Enter) and check
Python is present:

```bash
python3 --version          # should print Python 3.x.x
```

Get the code:

```bash
git clone https://github.com/<your-username>/dashhy.git
cd dashhy
```

(or download the ZIP from GitHub, unzip it, and `cd` into the folder).

---

### Option A — One-command installer (recommended)

From the repo root:

```bash
./install.sh
```

The script will:
1. check that Python 3 is available,
2. install **pywebview** into your user packages (only needed for the native window),
3. launch Dashhy.

If pywebview can't be installed for any reason, the script automatically falls
back to **browser mode** — Dashhy still works.

> If you get `permission denied`, run `chmod +x install.sh` once, then retry.

---

### Option B — Browser mode (zero dependencies)

Nothing to install. Pure Python standard library:

```bash
cd project-dashboard
python3 server.py
```

Your browser opens at **http://127.0.0.1:7777/**.
Change the port if needed: `DASH_PORT=8080 python3 server.py`.
Stop it with `Ctrl + C` in the Terminal.

---

### Option C — Native macOS window

A real app window (no tabs, no address bar). Needs **pywebview** once:

```bash
/usr/bin/python3 -m pip install --user --upgrade pip
/usr/bin/python3 -m pip install --user pywebview
```

Then:

```bash
cd project-dashboard
python3 app.py
```

The window remembers its size and position between launches.

---

### Option D — Build a self-contained app (Dashhy.app)

This produces a double-clickable `Dashhy.app` in `~/Applications`, with its own
icon in Launchpad, that bundles Python so **Full Disk Access works reliably**
(see the note below). Needs `pyinstaller` + `pywebview`:

```bash
/usr/bin/python3 -m pip install --user pyinstaller pywebview
cd project-dashboard
./build_app.sh
```

When it finishes, launch **Dashhy** from Launchpad or `~/Applications`.

---

### macOS Full Disk Access (important)

macOS protects `~/Desktop`, `~/Documents` and `~/Downloads`. To let Dashhy scan
projects living there, grant access **once**:

1. Open **System Settings → Privacy & Security → Full Disk Access**.
2. Click **+**, and add:
   - the **Dashhy** app (Option D), **or**
   - your terminal app (e.g. **Terminal**) if you run `python3` yourself (Options A–C).
3. Toggle it **on** and relaunch Dashhy.

Dashhy shows a banner and a **"Grant access"** button whenever it hits a folder
it can't read — clicking it opens the native folder picker, which is enough to
unlock that folder without changing system settings.

---

### Updating

```bash
cd dashhy
git pull
# if you built the app (Option D), rebuild it:
cd project-dashboard && ./build_app.sh
```

### Uninstalling

- Delete the repo folder.
- Delete the app: `rm -rf ~/Applications/Dashhy.app`
- Delete your project registry: `rm -rf ~/Library/Application\ Support/Dashhy`
- Remove Dashhy/Terminal from Full Disk Access in System Settings.

Dashhy never modifies the project folders it lists — removing a project from the
dashboard only forgets it; nothing on disk is touched.

---
---

<a name="-установка-на-русском"></a>
## Установка на русском

Dashhy работает на **macOS** с **Python 3** (он уже встроен в macOS).
Выбери удобный способ. Первый не требует вообще ничего, кроме Python.

### Перед стартом

Открой приложение **Терминал** (`⌘ + Пробел`, набери `Terminal`, Enter) и
проверь Python:

```bash
python3 --version          # должно показать Python 3.x.x
```

Скачай код:

```bash
git clone https://github.com/<твой-логин>/dashhy.git
cd dashhy
```

(или скачай ZIP с GitHub, распакуй и зайди в папку через `cd`).

---

### Способ A — Установщик одной командой (рекомендуется)

Из корня репозитория:

```bash
./install.sh
```

Скрипт:
1. проверит, что есть Python 3,
2. поставит **pywebview** в пользовательские пакеты (нужно только для нативного окна),
3. запустит Dashhy.

Если pywebview поставить не удалось — скрипт сам откроет **браузерный режим**,
Dashhy всё равно заработает.

> Если видишь `permission denied` — выполни один раз `chmod +x install.sh` и повтори.

---

### Способ B — Браузерный режим (без зависимостей)

Ставить нечего. Только стандартная библиотека Python:

```bash
cd project-dashboard
python3 server.py
```

Браузер откроется на **http://127.0.0.1:7777/**.
Сменить порт: `DASH_PORT=8080 python3 server.py`.
Остановить — `Ctrl + C` в Терминале.

---

### Способ C — Нативное окно macOS

Настоящее окно приложения (без вкладок и адресной строки). Нужен **pywebview** один раз:

```bash
/usr/bin/python3 -m pip install --user --upgrade pip
/usr/bin/python3 -m pip install --user pywebview
```

Затем:

```bash
cd project-dashboard
python3 app.py
```

Окно запоминает размер и позицию между запусками.

---

### Способ D — Собрать самостоятельное приложение (Dashhy.app)

Создаёт `Dashhy.app` в `~/Applications` с иконкой в Launchpad. Внутрь вшивается
Python, поэтому **Full Disk Access работает надёжно** (см. ниже). Нужны
`pyinstaller` + `pywebview`:

```bash
/usr/bin/python3 -m pip install --user pyinstaller pywebview
cd project-dashboard
./build_app.sh
```

После сборки запускай **Dashhy** из Launchpad или `~/Applications`.

---

### Full Disk Access на macOS (важно)

macOS защищает `~/Desktop`, `~/Documents`, `~/Downloads`. Чтобы Dashhy мог
сканировать проекты оттуда, выдай доступ **один раз**:

1. **Системные настройки → Конфиденциальность и безопасность → Полный доступ к диску**.
2. Нажми **+** и добавь:
   - приложение **Dashhy** (способ D), **или**
   - твой терминал (например **Terminal**), если запускаешь `python3` вручную (способы A–C).
3. Включи тумблер и перезапусти Dashhy.

Dashhy сам показывает баннер и кнопку **«Дать доступ»**, когда упирается в папку
без доступа — нажатие открывает нативный диалог выбора папки, и этого достаточно,
чтобы разблокировать конкретную папку без захода в системные настройки.

---

### Обновление

```bash
cd dashhy
git pull
# если собирал приложение (способ D) — пересобери:
cd project-dashboard && ./build_app.sh
```

### Удаление

- Удали папку репозитория.
- Удали приложение: `rm -rf ~/Applications/Dashhy.app`
- Удали реестр проектов: `rm -rf ~/Library/Application\ Support/Dashhy`
- Убери Dashhy/Terminal из «Полного доступа к диску» в системных настройках.

Dashhy никогда не меняет сами папки проектов — удаление проекта из дашборда лишь
«забывает» его, на диске ничего не трогается.
