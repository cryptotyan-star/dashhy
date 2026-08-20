# Security

Dashhy is a **single-user, local-only** Windows tool. The backend serves a UI to
*you*, on *your* machine, and never to the network. This document describes the
threat model, the protections in place, and the result of a pre-release audit.

## Threat model

- **In scope:** a malicious web page open in your browser trying to reach the
  local API (CSRF / DNS-rebinding); a crafted/added project folder trying to
  exfiltrate files outside itself (path traversal, symlinks); accidental
  exposure of secrets (SSH keys, tokens) through the file viewer.
- **Out of scope:** another local process running as your user. Anything running
  as you can already read your files directly; a localhost developer tool can't
  defend against that, and trying to would be security theatre.

## Protections

| Area | Protection |
|------|------------|
| **Network** | Server binds `127.0.0.1` only, ports `7777`–`7796`. Not reachable off-host. |
| **CSRF / DNS-rebinding** | Every request's `Host` must be loopback, and any `Origin` must be loopback — blocks cross-site `fetch` and rebinding. |
| **Path traversal** | File reads are confined with `realpath` + separator-aware prefix checks; `..` escapes are rejected. |
| **Home confinement** | Folders you add must resolve under `$HOME`. |
| **Credential denylist** | `~\.ssh`, `~\.aws`, `~\.gnupg`, `~\.gpg`, `~\.kube`, `~\.docker`, `~\.netrc`, `~\.password-store`, `~\.config\gh`, `~\.config\gcloud`, `~\AppData\Roaming\GitHub CLI`, `~\AppData\Roaming\gcloud`, `~\AppData\Local\gcloud`, `~\AppData\Roaming\Microsoft\Credentials`, `~\AppData\Local\Microsoft\Credentials` are refused for add/discover. |
| **Code-only reads** | The file viewer serves only recognised code/text extensions — never raw secrets like `id_rsa` or `.env`. |
| **Symlink safety** | The scanner never follows symlinks out of the tree; manifest/README reads are confined to the project root. |
| **No network / telemetry** | Backend is the Python standard library only. The one external command is local, read-only `git`. |
| **Private registry** | `%LOCALAPPDATA%\Dashhy\projects.json` is written atomically; `chmod`-equivalent applied (clears the read-only attribute — Windows has no POSIX-mode owner-only ACL via `os.chmod`). |
| **Command execution** | "Run" and "Open Terminal" launch *your own* command in *your own* terminal (Windows Terminal, or a throwaway `.bat`); `subprocess` is called with argument lists and never `shell=True`. The one exception is VS Code / Cursor, whose CLI ships as a `.cmd` batch launcher that `CreateProcess` cannot start: those go through `cmd /v:off /s /c` with every token quoted by us. `/S` makes cmd take the quoted line verbatim instead of re-parsing it, and `/V:OFF` pins delayed expansion off so `!` in a folder name stays literal; paths containing `"` or `%` cannot be quoted safely and are refused rather than passed on. |

## Pre-release audit

Before open-sourcing, the code was put through a multi-agent security review
(seven dimensions: filesystem/path, network/CSRF, command execution, data &
disclosure, build/supply-chain, frontend/XSS, and an architecture sweep), with
every candidate finding adversarially re-checked.

**Result:** 2 real issues found and **fixed**, 27 candidate findings dismissed
as by-design or unreachable in the local-only threat model.

Fixed:
1. **Home was not a real boundary.** `add()`/`discover()` confined paths to
   `$HOME`, but credential directories live under `$HOME`. Added an explicit
   credential-directory denylist and restricted the file viewer to code/text
   extensions, so an added folder can no longer be used to read `~/.ssh/id_rsa`
   or similar.
2. **Tooltip could follow a symlink out of the project.** `project_info()` read
   `README`/manifest files without confinement; a `README.md` symlinked to an
   outside file could leak an excerpt via the hover popover. Reads are now
   `realpath`-confined to the project root.

This Windows port carries forward every fix above — but it is a separate copy
of the code, not shared code, so "identical" is a claim that has to be kept true
rather than assumed. Where the two builds necessarily differ:

| Area | macOS | Windows |
|------|-------|---------|
| Credential paths | `~/.config/gh`, `~/.config/gcloud`, `~/Library/Keychains`, … | the same `.config` entries plus `%APPDATA%\GitHub CLI`, `%APPDATA%\Microsoft\Credentials`, … |
| Editor launch | `open -na` with an argv list | `cmd /v:off /s /c` with tokens quoted by us (see the table above) |
| Terminal | Terminal.app / iTerm | Windows Terminal / cmd / PowerShell |
| Autostart | per-user LaunchAgent plist | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` |
| Data dir | `~/Library/Application Support/Dashhy` | `%LOCALAPPDATA%\Dashhy` |

Everything else that matters is **shared, not merely similar**: `_within()`,
`_within_exact()`, `_samefile_path()` and `_is_sensitive_path()` are
byte-identical in both trees (`os.path.normcase(...).casefold()`, correct on
both filesystems), as are the read-path denylist check and the refusal to enable
autostart from a non-frozen run.

`tests/test_parity.py` is what keeps that true rather than aspirational. It
compares the four helpers' source byte for byte, asserts the credential denylist
rejects mixed-case paths and keeps its platform-neutral entries, asserts both
builds expose the same HTTP routes per verb and the same config keys, and checks
that a credential path inside an added project is refused on the read path. CI
runs it on macOS and Windows; `tests/test_windows_launcher.py` additionally
exercises the cmd quoting against a real `cmd.exe`.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Instead, use
GitHub's **"Report a vulnerability"** (Security → Advisories) on the repository,
or open a private security advisory. Include steps to reproduce and the impact.
You'll get a response as soon as possible.
