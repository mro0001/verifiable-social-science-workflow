"""Tests for the hook script and the schedule entry (Track A, Step A6).

Appendix A2.4 "Capture" sweeps a harness's session files while a session runs,
when it ends, and on a schedule. The Claude Code hook script runs at the end
of each turn (Stop), when a subagent finishes (SubagentStop), and when a
session ends (SessionEnd), and starts the sweep of that one file as a separate
process, so a turn never waits on capture (plan choice 7). The schedule entry
runs the sweep every 30 minutes.

Nothing here installs anything. No test writes to ~/.claude, a crontab, or
~/Library/LaunchAgents. The hook's spawn is a recording stand-in, except in
one test that starts a short Python process of its own, and every audit home
is a temporary folder. No real session file is read, and nothing here calls a
model or the network. Run from the repository root with python3 -m pytest -q
audit_layer/tests.
"""
import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.hooks import claude_code_hook as hook  # noqa: E402

HOOKS = ROOT / "audit_layer" / "hooks"
SCRIPT = HOOKS / "claude_code_hook.py"
PLIST = HOOKS / "schedule" / "audit_layer.sweep.plist"
INSTALL = HOOKS / "INSTALL.md"

EVENTS = ("Stop", "SubagentStop", "SessionEnd")


class Recording:
    """A spawn that records what it is asked to start and starts nothing."""

    def __init__(self):
        self.calls = []

    def __call__(self, command, log):
        self.calls.append((list(command), Path(log)))


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches ~/.claude or the real ~/.audit_layer."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def audit_home(tmp_path):
    folder = tmp_path / "audit_home"
    folder.mkdir()
    return folder


@pytest.fixture
def transcript(tmp_path):
    folder = tmp_path / "claude_root" / "-encoded-project-folder"
    folder.mkdir(parents=True)
    path = folder / "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    return path


def sweep_of(path):
    return [sys.executable, "-m", "audit_layer", "sweep", "--harness", "claude_code", "--file", str(path)]


def log_lines(audit_home):
    log = audit_home / "hook.log"
    if not log.exists():
        return []
    return log.read_text(encoding="utf-8").splitlines()


# handle starts the sweep of the transcript the hook names.


def test_a_stop_payload_asks_for_the_sweep_of_its_transcript(audit_home, transcript):
    spawn = Recording()
    payload = {
        "session_id": "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913",
        "transcript_path": str(transcript),
        "cwd": str(transcript.parent),
        "hook_event_name": "Stop",
    }
    hook.handle(payload, audit_home, spawn)
    assert spawn.calls == [(sweep_of(transcript), audit_home / "hook.log")]


def test_a_subagent_stop_payload_names_the_subagent_file(audit_home, transcript, tmp_path):
    spawn = Recording()
    agent = tmp_path / "agent-a7c41e2b9d0f3856.jsonl"
    payload = {
        "transcript_path": str(transcript),
        "agent_transcript_path": str(agent),
        "hook_event_name": "SubagentStop",
    }
    hook.handle(payload, audit_home, spawn)
    assert spawn.calls == [(sweep_of(agent), audit_home / "hook.log")]


def test_a_session_end_payload_asks_for_the_sweep(audit_home, transcript):
    spawn = Recording()
    hook.handle(
        {"transcript_path": str(transcript), "hook_event_name": "SessionEnd", "reason": "exit"},
        audit_home,
        spawn,
    )
    assert spawn.calls == [(sweep_of(transcript), audit_home / "hook.log")]


@pytest.mark.parametrize(
    "payload",
    [
        {"hook_event_name": "Stop"},
        {"hook_event_name": "Stop", "transcript_path": ""},
        {"hook_event_name": "Stop", "transcript_path": 7},
        {"hook_event_name": "SubagentStop", "agent_transcript_path": None},
        None,
        ["not", "an", "object"],
    ],
)
def test_a_payload_with_no_transcript_path_spawns_nothing_and_logs_one_line(
    audit_home, payload
):
    spawn = Recording()
    hook.handle(payload, audit_home, spawn)
    assert spawn.calls == []
    lines = log_lines(audit_home)
    assert len(lines) == 1
    assert "/" not in lines[0].split(" ", 1)[1]


def test_the_logged_line_holds_the_time_the_event_and_the_outcome(audit_home, tmp_path):
    hook.handle({"hook_event_name": "Stop", "cwd": str(tmp_path)}, audit_home, Recording())
    (line,) = log_lines(audit_home)
    stamp, event, outcome = line.split(" ", 2)
    assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", stamp)
    assert event == "Stop"
    assert outcome
    assert str(tmp_path) not in line


def test_an_event_name_that_is_not_a_plain_name_is_not_logged(audit_home, tmp_path):
    hook.handle({"hook_event_name": str(tmp_path / "secret")}, audit_home, Recording())
    (line,) = log_lines(audit_home)
    assert str(tmp_path) not in line
    assert "secret" not in line


# The script, run as Claude Code runs it.


def run_script(stdin, audit_home):
    env = dict(os.environ, AUDIT_HOME=str(audit_home))
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(audit_home.parent),
        timeout=60,
    )


@pytest.mark.parametrize("stdin", ["", "this is not JSON", "[1, 2", '"a string"', "{}"])
def test_the_script_exits_0_with_empty_output_on_input_it_cannot_use(audit_home, stdin):
    done = run_script(stdin, audit_home)
    assert done.returncode == 0
    assert done.stdout == ""
    lines = log_lines(audit_home)
    assert len(lines) == 1
    assert "/" not in lines[0].split(" ", 1)[1]


def test_the_script_exits_0_when_the_audit_home_does_not_exist(tmp_path):
    missing = tmp_path / "no_audit_home"
    done = run_script("this is not JSON", missing)
    assert done.returncode == 0
    assert done.stdout == ""
    assert not missing.exists()


@pytest.mark.parametrize("stdin", ["this is not JSON", '{"hook_event_name": "Stop"}'])
def test_the_script_exits_0_with_empty_output_when_its_package_cannot_be_imported(
    audit_home, tmp_path, transcript, stdin
):
    # A python3 without PyYAML, such as a system python3, cannot import the
    # settings module. The stand-in yaml found first on PYTHONPATH fails the
    # same way, and the script must still exit 0 and print nothing.
    stand_in = tmp_path / "no_yaml"
    stand_in.mkdir()
    (stand_in / "yaml.py").write_text("raise ImportError('no yaml here')\n", encoding="utf-8")
    payload = stdin if "Stop" not in stdin else json.dumps(
        {"hook_event_name": "Stop", "transcript_path": str(transcript)}
    )
    env = dict(os.environ, AUDIT_HOME=str(audit_home), PYTHONPATH=str(stand_in))
    done = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(audit_home.parent),
        timeout=60,
    )
    assert done.returncode == 0
    assert done.stdout == ""
    assert done.stderr == ""


def test_the_default_spawn_starts_a_detached_process_writing_to_the_log(audit_home):
    probe = (
        "import os, sys; print(os.getsid(0), os.environ.get('AUDIT_HOME'), os.getcwd()); "
        "sys.stdout.flush()"
    )
    log = audit_home / "hook.log"
    process = hook.detached([sys.executable, "-c", probe], log)
    assert process.wait(timeout=60) == 0
    sid, home, cwd = log.read_text(encoding="utf-8").split()
    assert int(sid) != os.getsid(0)
    assert home == str(audit_home)
    assert os.path.realpath(cwd) == os.path.realpath(str(ROOT))


# INSTALL.md and the schedule entry.


def install_text():
    return INSTALL.read_text(encoding="utf-8")


def hooks_block():
    found = re.findall(r"```json\n(.*?)```", install_text(), re.S)
    assert found, "INSTALL.md holds no json block"
    return json.loads(found[0])


def test_the_install_notes_hooks_block_runs_the_script_on_the_three_events():
    block = hooks_block()
    assert sorted(block["hooks"]) == sorted(EVENTS)
    for event in EVENTS:
        commands = [
            entry["command"]
            for matcher in block["hooks"][event]
            for entry in matcher["hooks"]
            if entry["type"] == "command"
        ]
        assert len(commands) == 1
        command = commands[0]
        assert command.startswith("python3 ")
        script = command.split(" ", 1)[1].replace("REPO_PATH", str(ROOT))
        assert Path(script) == SCRIPT


def test_the_install_notes_say_what_the_documents_ask():
    text = install_text()
    assert "audit_layer init" in text
    assert "excluded_folders" in text
    assert "launchctl load" in text
    assert "launchctl unload" in text
    assert "crontab" in text
    assert "*/30 * * * *" in text
    assert "ForgeCode" in text
    assert "never replace" in text.lower()
    assert "installs nothing" in text
    assert "\u2014" not in text


def test_the_plist_runs_the_sweep_every_1800_seconds():
    with PLIST.open("rb") as handle:
        entry = plistlib.load(handle)
    assert entry["ProgramArguments"] == ["PYTHON_PATH", "-m", "audit_layer", "sweep"]
    assert entry["WorkingDirectory"] == "REPO_PATH"
    assert entry["StartInterval"] == 1800
    assert entry["Label"] == "audit_layer.sweep"


def test_nothing_in_the_hooks_folder_names_a_real_home():
    for path in HOOKS.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            text = path.read_text(encoding="utf-8")
            assert "/Users/" not in text, path
