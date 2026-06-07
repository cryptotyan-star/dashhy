#!/usr/bin/env python3
"""Dashhy — нативное окно (pywebview / WKWebView).

Точка входа по умолчанию. Поднимает локальный HTTP-сервер (server.py) и
показывает дашборд в нативном окне macOS. Окно запоминает размер и позицию
между запусками.
"""

import json
import os
import sys
import threading

import webview

import server

STATE_FILE = os.path.join(server.DATA_DIR, "window.json")


def _load_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
        return {k: s[k] for k in ('x', 'y', 'width', 'height') if k in s}
    except Exception:
        return {}


def _save_state(state):
    try:
        os.makedirs(server.DATA_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def main():
    try:
        httpd, port = server.start_server()
    except RuntimeError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    saved = _load_state()
    state = {'width': saved.get('width', 1400), 'height': saved.get('height', 900)}
    if 'x' in saved and 'y' in saved:
        state['x'], state['y'] = saved['x'], saved['y']

    win = webview.create_window(
        title="Dashhy",
        url=f"http://127.0.0.1:{port}/",
        width=state['width'],
        height=state['height'],
        x=state.get('x'),
        y=state.get('y'),
        min_size=(960, 600),
        background_color="#f3f5f8",
    )

    # persist geometry on resize / move (pywebview 4+ events API)
    def _on_resized(w, h):
        state['width'], state['height'] = int(w), int(h)
        _save_state(state)

    def _on_moved(x, y):
        state['x'], state['y'] = int(x), int(y)
        _save_state(state)

    try:
        win.events.resized += _on_resized
        win.events.moved += _on_moved
    except Exception as e:
        print(f"window-state events unavailable: {e}", file=sys.stderr)

    webview.start()  # blocks until the window is closed
    _save_state(state)

    try:
        httpd.shutdown()
    except Exception:
        pass


if __name__ == "__main__":
    main()
