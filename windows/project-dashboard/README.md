# Dashhy — application folder

This folder contains the Dashhy app itself. For the project overview, features,
screenshots and full install guide, see the repository root:

- **[../README.md](../README.md)** — what Dashhy is + all features (EN / RU)
- **[../INSTALL.md](../INSTALL.md)** — step-by-step install for everyone
- **[../SECURITY.md](../SECURITY.md)** — security model & audit
- **[../PORTING_NOTES.md](../PORTING_NOTES.md)** — what changed vs. the macOS original

## Run it

```bat
:: native window (needs pywebview — see ../INSTALL.md)
python app.py

:: OR browser fallback — zero dependencies, pure standard library
python server.py        :: → http://127.0.0.1:7777/
```

Change the port for browser mode with `set DASH_PORT=8080 && python server.py`.

## Files

| File | Role |
|------|------|
| `app.py` | Default entry point — native window (pywebview / WebView2) |
| `server.py` | HTTP server + JSON API; also the standalone browser mode |
| `build_app.bat` | Build a self-contained `Dashhy.exe` with PyInstaller (must run on Windows) |
| `Dashhy.spec` | PyInstaller spec used by the build |
| `AppIcon.ico` | App icon used by the build |
| `requirements.txt` | `pywebview` (only needed for the native window) |
| `web/` | The dashboard UI — `index.html`, `mi.css`, `golos.css`, `app.js`, `fonts/` |

## Data

Your project registry lives at
`%LOCALAPPDATA%\Dashhy\projects.json` — written atomically (`tmp` + rename).
One UUID per project.
