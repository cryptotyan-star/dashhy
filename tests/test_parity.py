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
@pytest.mark.parametrize('fn', ['_within', '_within_exact'])
def test_containment_is_a_path_check_not_a_string_prefix(mod, fn):
    """/a/proj-evil must not pass for being inside /a/proj."""
    within, sep = getattr(mod, fn), os.sep
    assert within(f'{sep}a{sep}proj', f'{sep}a{sep}proj') is True
    assert within(f'{sep}a{sep}proj{sep}x', f'{sep}a{sep}proj') is True
    assert within(f'{sep}a{sep}proj-evil', f'{sep}a{sep}proj') is False


@BOTH
def test_within_exact_does_not_fold_case(mod):
    """Project-root reads must not widen containment by casing."""
    sep = os.sep
    assert mod._within_exact(f'{sep}a{sep}PROJ{sep}x', f'{sep}a{sep}proj') is False
    assert mod._within(f'{sep}a{sep}PROJ{sep}x', f'{sep}a{sep}proj') is True


# ── 2. both builds must expose the same HTTP surface, per method ───────────
# Per method, not per file: a route that moved from POST to DELETE, or exists
# under only one verb, is real drift that a whole-file set comparison hides.
_ROUTE = re.compile(r"""p\s*(?:==|\.startswith\()\s*['"](/api/[^'"]+)""")


def _routes_by_method(path):
    src = path.read_text(encoding='utf-8')
    marks = [(m.group(1), m.start()) for m in re.finditer(r'def (do_[A-Z]+)\(self\)', src)]
    assert marks, f'no do_* handlers found in {path}'
    out = {}
    for i, (method, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(src)
        out[method] = set(_ROUTE.findall(src[start:end]))
    return out


def test_route_parity():
    mac, win = _routes_by_method(MAC_SRC), _routes_by_method(WIN_SRC)
    assert set(mac) == set(win), f'handler methods differ: {set(mac) ^ set(win)}'
    for method in sorted(mac):
        assert mac[method], f'{method} matched no routes — did the dispatch style change?'
        assert mac[method] == win[method], (
            f'{method}: only mac {mac[method] - win[method]} | '
            f'only win {win[method] - mac[method]}')


# ── 2b. the credential denylist itself must not lose entries in a port ─────
# `.config/gh` and `.config/gcloud` existed on macOS and were dropped when the
# Windows tree was created; a casing test cannot catch a missing entry.
PLATFORM_NEUTRAL = {
    '.ssh', '.aws', '.gnupg', '.gpg', '.kube', '.docker', '.netrc',
    '.password-store', '.config/gh', '.config/gcloud',
}


@BOTH
def test_denylist_keeps_the_platform_neutral_entries(mod):
    have = {s.replace(os.sep, '/') for s in mod.SENSITIVE_SUBPATHS}
    assert PLATFORM_NEUTRAL <= have, f'dropped: {PLATFORM_NEUTRAL - have}'


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
