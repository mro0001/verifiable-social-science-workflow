"""Step F1. The layer command runner and the package's command line.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from features import layers

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples" / "sample_project"


def _first_on_path(env_add):
    return env_add["PYTHONPATH"].split(os.pathsep)[0]


def test_default_root_is_the_folder_holding_features():
    root = Path(layers.default_root())
    assert root == ROOT
    assert (root / "features" / "layers.py").is_file()


def test_ospipe_command_puts_its_folder_first_on_the_path():
    argv, env_add, cwd = layers.layer_command(
        "ospipe", ["check", "--manuscript", "m.md"], str(ROOT), python="py3")
    assert argv == ["py3", "-m", "ospipe", "check", "--manuscript", "m.md"]
    assert _first_on_path(env_add) == str(ROOT / "ospipe")
    assert set(env_add) == {"PYTHONPATH"}
    assert cwd is None


def test_audit_layer_command_puts_the_root_first_on_the_path():
    argv, env_add, cwd = layers.layer_command("audit_layer", ["init"], str(ROOT), python="py3")
    assert argv == ["py3", "-m", "audit_layer", "init"]
    assert _first_on_path(env_add) == str(ROOT)
    assert set(env_add) == {"PYTHONPATH"}
    assert cwd is None


def test_vg_command_runs_the_script_in_its_own_folder():
    argv, env_add, cwd = layers.layer_command(
        "vg", ["check", "graphs/selftest.yaml"], str(ROOT), python="py3")
    assert argv == ["py3", str(ROOT / "verification_procedures" / "vg.py"),
                    "check", "graphs/selftest.yaml"]
    assert env_add == {}
    assert cwd == str(ROOT / "verification_procedures")


def test_connections_command_puts_the_root_first_on_the_path():
    argv, env_add, cwd = layers.layer_command(
        "connections", ["provider", "show"], str(ROOT), python="py3")
    assert argv == ["py3", "-m", "connections", "provider", "show"]
    assert _first_on_path(env_add) == str(ROOT)
    assert cwd is None


def test_connections_is_run_but_not_among_the_layers_setup_checks():
    assert layers.LAYERS == ("ospipe", "audit_layer", "vg")
    assert "connections" in layers.RUNNABLE


def test_connections_provider_set_runs_in_a_home_inside_tmp(tmp_path):
    home = tmp_path / "connections_home"
    done = layers.run_layer(
        "connections", ["provider", "set", "--base-url", "https://models.example.edu/v1",
                        "--model", "open-model-70b", "--home", str(home)],
        env={"HOME": str(tmp_path), "CONNECTIONS_HOME": str(home),
             "AUDIT_HOME": str(tmp_path / "audit_home")})
    assert done.returncode == 0, done.stderr
    assert (home / "provider.yaml").is_file()


def test_the_running_interpreter_is_the_default_python():
    argv, _, _ = layers.layer_command("audit_layer", ["init"], str(ROOT))
    assert argv[0] == sys.executable


def test_an_existing_python_path_follows_the_layer_folder(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/elsewhere")
    _, env_add, _ = layers.layer_command("ospipe", [], str(ROOT))
    assert env_add["PYTHONPATH"].split(os.pathsep) == [str(ROOT / "ospipe"), "/elsewhere"]


def test_an_unknown_layer_is_refused():
    with pytest.raises(ValueError) as caught:
        layers.layer_command("observability", ["build"], str(ROOT))
    assert "observability" in str(caught.value)


def test_ospipe_check_fills_the_sample_project(tmp_path):
    project = tmp_path / "sample_project"
    shutil.copytree(str(SAMPLE), str(project))
    result = layers.run_layer(
        "ospipe",
        ["check", "--manuscript", "manuscript.md", "--manifest", "numbers.yml",
         "--tables-dir", "."],
        cwd=str(project))
    assert result.returncode == 0, result.stderr
    assert result.argv[1:3] == ["-m", "ospipe"]
    assert "mistral-small:22b" in result.stdout
    assert "{{num:" not in result.stdout


def test_audit_layer_init_writes_the_audit_home(tmp_path):
    home = tmp_path / "audit_home"
    result = layers.run_layer("audit_layer", ["init"], env={"AUDIT_HOME": str(home)})
    assert result.returncode == 0, result.stderr
    assert (home / "settings.yaml").is_file()
    assert (home / "audit.sqlite").is_file()


def test_vg_checks_the_selftest_graph():
    result = layers.run_layer("vg", ["check", "graphs/selftest.yaml"])
    assert result.returncode == 0, result.stderr


def test_a_nonzero_exit_is_returned_not_raised():
    result = layers.run_layer("vg", ["check", "graphs/no_such_graph.yaml"])
    assert result.returncode != 0


def _partial_root(tmp_path, leave_out):
    root = tmp_path / "root"
    (root / "ospipe" / "ospipe").mkdir(parents=True)
    (root / "audit_layer").mkdir()
    (root / "connections").mkdir()
    (root / "verification_procedures").mkdir()
    (root / "verification_procedures" / "vg.py").write_text("", encoding="utf-8")
    target = root / leave_out
    if target.is_dir():
        shutil.rmtree(str(target))
    else:
        target.unlink()
    return root, target


@pytest.mark.parametrize("layer, leave_out", [
    ("ospipe", "ospipe/ospipe"),
    ("audit_layer", "audit_layer"),
    ("vg", "verification_procedures/vg.py"),
    ("connections", "connections"),
])
def test_a_missing_layer_is_named(tmp_path, layer, leave_out):
    root, target = _partial_root(tmp_path, leave_out)
    with pytest.raises(layers.LayerMissing) as caught:
        layers.run_layer(layer, ["--help"], root=str(root))
    assert str(target) in str(caught.value)


def _features(*args):
    return subprocess.run(
        [sys.executable, "-m", "features"] + list(args),
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True)


def test_version_prints_the_package_version():
    result = _features("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "features 0.1"


@pytest.mark.parametrize("group", ["setup", "organize", "portal"])
def test_a_group_with_no_command_prints_its_help(group):
    result = _features(group)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: features " + group)
