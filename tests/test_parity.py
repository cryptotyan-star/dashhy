"""The parity checks that would have caught the defects the July audit found.

Both trees ship a module called `server`, so a plain import would let whichever
loads first shadow the other. Each is loaded under its own module name instead,
which also means this file runs on macOS *and* Windows: `winreg` is imported
lazily inside the Windows functions, never at module scope.
"""
import importlib.util
import os
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAC_SRC = ROOT / 'project-dashboard' / 'server.py'
WIN_SRC = ROOT / 'windows' / 'project-dashboard' / 'server.py'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MAC = _load('mac_server', MAC_SRC)
WIN = _load('win_server', WIN_SRC)
BOTH = pytest.mark.parametrize('mod', [MAC, WIN], ids=['mac', 'win'])


# ── 1. the credential denylist must not be defeated by casing ──────────────
# APFS and NTFS are both case-insensitive by default, so ~/.ssh and ~/.SSH are
# the same directory. macOS compared paths byte-exactly until Aug 2026 and let
# ~/.SSH through; Windows had already been fixed in 7ba9a11. Neither may regress.
@BOTH
@pytest.mark.parametrize('sub', ['.ssh', '.SSH', '.Ssh',
                                 '.aws', '.AWS',
                                 '.gnupg', '.GnuPG',
                                 '.config/gh', '.CONFIG/gh',
                                 '.config/gcloud'])
def test_denylist_is_case_insensitive(mod, sub):
    home = os.path.realpath(os.path.expanduser('~'))
    target = os.path.join(home, *sub.split('/'))
    assert mod._is_sensitive_path(target, home) is True


@BOTH
@pytest.mark.parametrize('sub', ['Desktop', 'Documents', 'src', 'dev'])
def test_denylist_does_not_overreach(mod, sub):
    home = os.path.realpath(os.path.expanduser('~'))
    assert mod._is_sensitive_path(os.path.join(home, sub), home) is False


@BOTH
def test_within_is_a_prefix_check_not_a_string_prefix(mod):
    """/a/proj-evil must not pass for being inside /a/proj."""
    sep = os.sep
    assert mod._within(f'{sep}a{sep}proj', f'{sep}a{sep}proj') is True
    assert mod._within(f'{sep}a{sep}proj{sep}x', f'{sep}a{sep}proj') is True
    assert mod._within(f'{sep}a{sep}proj-evil', f'{sep}a{sep}proj') is False


# ── 2. both builds must expose the same HTTP surface ───────────────────────
def _routes(path):
    return set(re.findall(r"p == '(/api/[a-z0-9-]+)'", path.read_text(encoding='utf-8')))


def test_route_parity():
    mac, win = _routes(MAC_SRC), _routes(WIN_SRC)
    assert mac, 'route regex matched nothing — did the dispatch style change?'
    assert mac == win, f'only mac: {mac - win} | only win: {win - mac}'


# ── 3. both builds must accept the same config shape ───────────────────────
def _keys(cfg, prefix=''):
    out = set()
    for k, v in cfg.items():
        out.add(prefix + k)
        if isinstance(v, dict):
            out |= _keys(v, prefix + k + '.')
    return out


def test_config_key_parity():
    mac, win = _keys(MAC.DEFAULT_CONFIG), _keys(WIN.DEFAULT_CONFIG)
    assert mac == win, f'only mac: {mac - win} | only win: {win - mac}'


@BOTH
def test_editor_choices_are_shared(mod):
    """Terminals are legitimately platform-specific; editors are not."""
    assert mod._EDITORS == {'auto', 'code', 'cursor', 'system'}
