"""Step S1, stuck point 2. Without PyYAML, python3 -m features prints the install line.

The child Python is told PyYAML is missing by setting sys.modules["yaml"] to
None before the features run, so the test needs no second Python.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

LINE = 'python3 -m pip install pyyaml "python-docx>=1.2" pytest'

START = ("import sys, runpy; sys.modules['yaml'] = None; sys.argv = ['features'] + sys.argv[1:];"
         " runpy.run_module('features', run_name='__main__', alter_sys=True)")


def private_env(tmp_path):
    """The child's environment, with HOME and the three layer homes inside tmp_path."""
    home = tmp_path / "user_home"
    home.mkdir(exist_ok=True)
    return dict(os.environ, HOME=str(home),
                AUDIT_HOME=str(tmp_path / "audit_home"),
                CONNECTIONS_HOME=str(tmp_path / "connections_home"),
                FEATURES_HOME=str(tmp_path / "features_home"))


def run_without_yaml(tmp_path, *args):
    return subprocess.run([sys.executable, "-c", START] + list(args), cwd=str(ROOT),
                          env=private_env(tmp_path),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=60)


def test_without_pyyaml_the_command_prints_the_install_line_and_no_traceback(tmp_path):
    for args in (["setup", "plan"], ["--version"]):
        done = run_without_yaml(tmp_path, *args)
        assert done.returncode == 1
        assert LINE in done.stderr
        assert "Traceback" not in done.stderr + done.stdout


def test_with_pyyaml_the_command_runs(tmp_path):
    done = subprocess.run([sys.executable, "-m", "features", "--version"], cwd=str(ROOT),
                          env=private_env(tmp_path),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=60)
    assert done.returncode == 0
    assert "features" in done.stdout


def test_the_line_is_detections_own_install_line():
    from features.setup import detect
    assert LINE == detect.PACKAGES_LINE
    text = (ROOT / "features" / "__main__.py").read_text(encoding="utf-8")
    assert "PACKAGES_LINE = %r" % LINE in text
