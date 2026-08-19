"""Editor launch on Windows goes through cmd.exe — prove it can't be injected.

`&`, `^`, `(`, `)` and `!` are all legal in NTFS names but mean something to
cmd, so an unquoted project path could run a second command or arrive mangled.
The cmd.exe tests only run on Windows; the refusal and fixture tests run
everywhere so that a revert of the fix goes red on any runner.
"""
import importlib.util
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WIN = _load('win_server_launcher', ROOT / 'windows' / 'project-dashboard' / 'server.py')

# Names that are legal on NTFS and hostile to cmd. `&` chains a command,
# `^` escapes, `( )` group, `!` expands under delayed expansion.
HOSTILE = ['proj&marker.cmd', 'proj^x', 'proj(a)b', 'proj!TEMP!x', 'my project']

on_windows = pytest.mark.skipif(sys.platform != 'win32', reason='needs a real cmd.exe')


@pytest.mark.parametrize('bad', ['C:\\dev\\a%TEMP%b', 'C:\\dev\\a"b'])
def test_unquotable_paths_are_refused(bad):
    """%VAR% expands even inside quotes, and " cannot occur in an NTFS name."""
    r = WIN._run_launcher('code.cmd', ['-n', bad])
    assert r.returncode == 1


@pytest.mark.parametrize('name', HOSTILE)
def test_fixtures_are_actually_adversarial(name):
    """Guard the guard.

    If subprocess.list2cmdline() would have quoted these names anyway, the
    cmd.exe tests below would pass against the pre-fix code too and prove
    nothing. Everything except the deliberate 'my project' case must come out
    of the naive construction unquoted.
    """
    naive = subprocess.list2cmdline(['cmd', '/c', 'code.cmd', '-n', 'C:\\dev\\' + name])
    assert ('"' in naive) is (' ' in name), f'naive quoting for {name!r}: {naive}'


@on_windows
@pytest.mark.parametrize('name', HOSTILE)
def test_hostile_path_arrives_intact(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    probe = tmp_path / 'probe.cmd'
    probe.write_bytes(b'@echo off\r\n> "%~dp0got.txt" echo %*\r\n')
    victim = tmp_path / name
    victim.mkdir()

    r = WIN._run_launcher(str(probe), ['-n', str(victim)])

    assert r.returncode == 0, r.stderr
    got = (tmp_path / 'got.txt').read_text(encoding='ascii', errors='replace')
    assert name in got, f'path was mangled on the way to the editor: {got!r}'


@on_windows
def test_ampersand_does_not_chain_a_second_command(tmp_path, monkeypatch):
    """The classic injection: cmd would run `marker.cmd` after the folder path."""
    monkeypatch.chdir(tmp_path)
    probe = tmp_path / 'probe.cmd'
    probe.write_bytes(b'@echo off\r\n> "%~dp0got.txt" echo %*\r\n')
    # `marker.cmd` sits in the cwd, so an injected bare `marker.cmd` resolves.
    (tmp_path / 'marker.cmd').write_bytes(b'@echo off\r\n> "%~dp0pwned.txt" echo x\r\n')
    victim = tmp_path / 'proj&marker.cmd'
    victim.mkdir()

    r = WIN._run_launcher(str(probe), ['-n', str(victim)])

    assert r.returncode == 0, r.stderr
    assert not (tmp_path / 'pwned.txt').exists(), 'cmd executed the tail of the path'
