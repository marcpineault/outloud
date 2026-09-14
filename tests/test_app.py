import os
import subprocess
import sys


def test_selftest_builds_the_window_offscreen():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run([sys.executable, "-m", "outloud", "--selftest"], capture_output=True, text=True, env=env, timeout=180)
    assert proc.returncode == 0, proc.stderr
    assert "tts=" in proc.stdout and "qt=ok" in proc.stdout
