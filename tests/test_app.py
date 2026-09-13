import os
import subprocess
import sys

import pytest


def test_selftest_builds_the_window_hidden():
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, "-m", "outloud", "--selftest"], capture_output=True, text=True, env=env, timeout=120)
    if proc.returncode != 0 and ("no display" in proc.stderr.lower() or "couldn't connect to display" in proc.stderr.lower()):
        pytest.skip("no display available")
    assert proc.returncode == 0, proc.stderr
    assert "tts=" in proc.stdout
