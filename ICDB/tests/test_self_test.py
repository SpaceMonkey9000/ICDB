"""The build runs `ICDB.exe --self-test`; it must start the window on throw-away DATA."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent


def test_self_test_starts_main_window(tmp_path):
    pytest.importorskip('PySide6')
    report = tmp_path / 'report.json'
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    result = subprocess.run([sys.executable, str(APP / 'icdb_qt.py'), '--self-test', '--report', str(report)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text('utf-8'))
    assert data['ok'] and data['screens'] == 3
