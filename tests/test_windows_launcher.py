"""Editor launch on Windows goes through cmd.exe — prove it can't be injected.

`&`, `^`, `(` and `)` are legal in NTFS names but are operators to cmd, so an
unquoted project path could run a second command. The cmd.exe test below only
runs on Windows; the refusal test runs everywhere.
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WIN = _load('win_server_launcher', ROOT / 'windows' / 'project-dashboard' / 'server.py')


@pytest.mark.parametrize('bad', ['C:\\dev\\a%TEMP%b', 'C:\\dev\\a!x!b', 'C:\\dev\\a"b'])
def test_unquotable_paths_are_refused(bad):
    """% and ! expand even inside quotes; " can't be quoted at all."""
    r = WIN._run_launcher('code.cmd', ['-n', bad])
    assert r.returncode == 1


@pytest.mark.skipif(sys.platform != 'win32', reason='needs a real cmd.exe')
def test_cmd_metacharacters_in_path_are_not_executed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    probe = tmp_path / 'probe.cmd'
    probe.write_text('@echo off\r\n> "%~dp0got.txt" echo %*\r\n', encoding='ascii')

    # every one of these is a legal directory name on NTFS
    victim = tmp_path / 'proj&mkdir pwned'
    victim.mkdir()

    r = WIN._run_launcher(str(probe), ['-n', str(victim)])

    assert r.returncode == 0, r.stderr
    assert not (tmp_path / 'pwned').exists(), 'cmd executed the tail of the path'
    got = (tmp_path / 'got.txt').read_text(encoding='ascii', errors='replace')
    assert 'proj&mkdir pwned' in got, f'path did not arrive intact: {got!r}'


@pytest.mark.skipif(sys.platform != 'win32', reason='needs a real cmd.exe')
def test_ordinary_path_with_spaces_still_launches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    probe = tmp_path / 'probe.cmd'
    probe.write_text('@echo off\r\n> "%~dp0got.txt" echo %*\r\n', encoding='ascii')
    victim = tmp_path / 'my project'
    victim.mkdir()

    r = WIN._run_launcher(str(probe), ['-n', str(victim)])

    assert r.returncode == 0, r.stderr
    assert 'my project' in (tmp_path / 'got.txt').read_text(encoding='ascii', errors='replace')
