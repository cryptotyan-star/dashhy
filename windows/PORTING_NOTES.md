# Porting notes — macOS → Windows 11

What changed going from the original macOS build to this Windows port, and why.
The frontend (`web/` — HTML/CSS/JS) is **byte-for-byte identical**; everything
below is backend/build/OS-integration only.

| Area | macOS | Windows |
|------|-------|---------|
| Data dir | `~/Library/Application Support/Dashhy` | `%LOCALAPPDATA%\Dashhy` |
| Folder picker | `osascript` (AppleScript `choose folder`) | `powershell` + `System.Windows.Forms.FolderBrowserDialog` |
| Reveal folder | `open <path>` (Finder) | `os.startfile(path)` (File Explorer) |
| Open terminal | `osascript` → `Terminal.app do script` | `wt -d <path>` (Windows Terminal); falls back to a throwaway `.bat` opened via `os.startfile` if `wt` is missing |
| Open in editor | `open -na "Visual Studio Code" --args <path>` / `code <path>` | `code -n <path>` (resolved via `shutil.which`, so it works even when PATH lacks a shell profile) |
| "Создать проект" → open in VS Code | same `open -na` trick | same `code -n` trick |
| VS Code onboarding task | `.vscode/tasks.json` runs `sleep 1 && open 'vscode://...'` | `.vscode/tasks.json` runs `powershell -Command "Start-Sleep -Seconds 1; Start-Process '...'"` (explicit interpreter, not shell-dependent) |
| Native window renderer | pywebview → WKWebView | pywebview → Microsoft Edge WebView2 (ships with Windows 11) |
| App bundling | PyInstaller `--windowed` → `Dashhy.app` (`build_app.sh`) | PyInstaller onefile → `Dashhy.exe` (`build_app.bat` / `Dashhy.spec`) |
| App icon | `AppIcon.icns` | `AppIcon.ico` (converted from the same source art) |
| OS folder-access consent | macOS TCC / Full Disk Access — a system dialog Dashhy detects and surfaces a banner for | No OS-level equivalent for normal user folders; a `PermissionError` (e.g. from an AV lock or NTFS ACL) now falls back to a generic "no access" message instead of a Full-Disk-Access-specific one |
| Credential denylist | `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, `~/.docker`, `~/.netrc`, `~/.password-store`, `~/.config/gh`, `~/.config/gcloud`, `~/Library/Keychains` | `~\.ssh`, `~\.aws`, `~\.gnupg`, `~\.kube`, `~\.docker`, `~\.netrc`, `~\.password-store`, `~\AppData\Roaming\gh`, `~\AppData\Roaming\gcloud`, `~\AppData\Local\gcloud`, `~\AppData\Roaming\Microsoft\Credentials`, `~\AppData\Local\Microsoft\Credentials` |
| Old-install migration | one-time copy from `~/Library/Application Support/ProjectDashboard` (a pre-Dashhy rename) | removed — no prior Windows installs exist to migrate from |

## Unchanged (works identically)

- **Security model** — loopback-only binding, Host/Origin checks, `$HOME`
  confinement, realpath-based path-traversal guards, code-only file reads.
  All of it is OS-agnostic Python and required no changes.
- **Scanning / language detection / line counting** — pure `os.scandir` +
  stdlib, no OS-specific calls.
- **Deep-relocate** (re-finding a moved/renamed project folder) — inode
  identity via `os.stat().st_ino` is meaningful on NTFS too (CPython
  resolves it via `GetFileInformationByHandle` since 3.5), so tiers 1 and 4a
  (exact-inode match) work the same as on APFS/HFS+. Tiers 2–4b (content
  signature) are filesystem-agnostic already.
- **Git snapshot** — shells out to `git`, same command either way (needs
  Git for Windows on `PATH`).

## Known limitations of this port

- **PyInstaller can't cross-compile.** `build_app.bat` must run on Windows —
  there is no way to produce a working `Dashhy.exe` from macOS or Linux.
- **No code-signing.** `Dashhy.exe` is unsigned, so Windows SmartScreen will
  warn on first run (same category of warning any unsigned indie `.exe`
  gets — "More info → Run anyway"). Signing would need a paid code-signing
  certificate, out of scope for a local dev tool.
- **`~/Desktop` isn't redirection-aware.** If OneDrive's "Known Folder Move"
  redirects your Desktop to `...\OneDrive\Desktop`, `os.path.expanduser('~/Desktop')`
  still resolves to the plain profile path. This mirrors the original macOS
  code's own handling of iCloud Desktop sync (also not special-cased) rather
  than being a new gap.
