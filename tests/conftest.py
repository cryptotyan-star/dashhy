"""Point every home-ish variable at a throwaway directory BEFORE the servers load.

Both server modules do real filesystem work at import time: `CONFIG =
_load_config()` reads the config file, and `STORE = Store()` creates the data
dir and copies projects.json over projects.json.bak. Importing them from a test
would therefore rewrite the developer's live registry backup — and, because the
Windows tree falls back to `~/Dashhy` when %LOCALAPPDATA% is unset, would leave
a junk directory in a real macOS home (it did, once).

pytest imports conftest.py before the test modules in its directory, so patching
the environment here lands before any `spec.loader.exec_module()` call.
"""
import atexit
import os
import shutil
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix='dashhy-test-home-')

# HOME covers posixpath.expanduser; USERPROFILE covers ntpath.expanduser;
# LOCALAPPDATA/APPDATA are what the Windows tree builds DATA_DIR from.
for _var in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA'):
    os.environ[_var] = _SANDBOX

# A stray value from the CI job would make run_selftest write into the workspace.
os.environ.pop('DASHHY_SELFTEST_OUT', None)

atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)
