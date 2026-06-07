# Third-party notices

Dashhy's own code is licensed under the [MIT License](LICENSE). It also includes
or relies on the following third-party components.

## Bundled in this repository

### Golos Text (font)
- **Files:** `project-dashboard/web/fonts/golos-1.woff2` … `golos-4.woff2`
- **License:** SIL Open Font License, Version 1.1 — full text in
  [`project-dashboard/web/fonts/OFL.txt`](project-dashboard/web/fonts/OFL.txt)
- **Copyright:** © 2021 The Golos Text Project Authors
  (https://github.com/googlefonts/golos-text), designed by Alexandra Korolkova.
- **Reserved Font Name:** "Golos Text".

The OFL permits redistribution and embedding. The font is used unmodified (as a
web-subset `woff2`). If you modify the font files, you must rename them so they
do not use the reserved name "Golos Text".

## Installed at runtime (not bundled in this repo)

The **native window** mode installs these into your user environment via `pip`
(see `project-dashboard/requirements.txt`); they are **not** redistributed here:

- **pywebview** — BSD 3-Clause License — https://github.com/r0x0r/pywebview
- **pyobjc** (pulled in by pywebview) — MIT License — https://github.com/ronaldoussoren/pyobjc

The **browser** mode (`server.py`) uses only the Python standard library and has
no third-party dependencies.
