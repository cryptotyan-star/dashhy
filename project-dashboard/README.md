# Dashhy — application folder

This folder contains the Dashhy app itself. For the project overview, features,
screenshots and full install guide, see the repository root:

- **[../README.md](../README.md)** — what Dashhy is + all features (EN / RU)
- **[../INSTALL.md](../INSTALL.md)** — step-by-step install for everyone
- **[../SECURITY.md](../SECURITY.md)** — security model & audit

## Run it

```bash
# native macOS window (needs pywebview — see ../INSTALL.md)
python3 app.py

# OR browser fallback — zero dependencies, pure standard library
python3 server.py        # → http://127.0.0.1:7777/
```

Change the port for browser mode with `DASH_PORT=8080 python3 server.py`.

## Files

| File | Role |
|------|------|
| `app.py` | Default entry point — native window (pywebview / WKWebView) |
| `server.py` | HTTP server + JSON API; also the standalone browser mode |
| `build_app.sh` | Build a self-contained `Dashhy.app` with PyInstaller |
| `Dashhy.spec` | PyInstaller spec used by the build |
| `requirements.txt` | `pywebview` (only needed for the native window) |
| `web/` | The dashboard UI — `index.html`, `mi.css`, `golos.css`, `app.js`, `fonts/` |

## Data

Your project registry lives at
`~/Library/Application Support/Dashhy/projects.json` — written atomically
(`tmp` + rename) and `chmod 600`. One UUID per project. Records from older
versions migrate automatically on first launch.
