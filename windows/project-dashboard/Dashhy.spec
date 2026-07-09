# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Windows build. Run via build_app.bat (must run ON
# Windows; PyInstaller does not cross-compile between OSes).
from PyInstaller.utils.hooks import collect_all

datas = [('web', 'web')]
binaries = []
hiddenimports = ['clr', 'webview.platforms.edgechromium', 'webview.platforms.winforms']
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pkg_resources', 'setuptools'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# a.binaries / a.datas passed directly into EXE() (not COLLECT()) is what
# makes this a single-file build — everything gets packed into one Dashhy.exe.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Dashhy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=['AppIcon.ico'],
)
