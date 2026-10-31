"""The view built from the real layers, through their commands (Track E, step E14).

Proposal Status paragraph 3 names a live view of what the harness reads,
calls, and retrieves, with the same events written to the logs, and appendix
A2.6 paragraph 2 and Table A7 have the layer read the record as it is
written. Only files and command lines cross a layer edge, so this test
imports no other layer's code. It runs each layer's own command as a
subprocess on the test story, with AUDIT_HOME set to a temporary audit home.

In a temporary folder it copies the test story's project and session files
with {{PROJECT}} replaced and makes the excluded session's folder. From the
repository root it runs python3 -m audit_layer init, then capture on both
story sessions while no folder is excluded, so the excluded session is
recorded, and then lists that session's folder in the audit home's
settings.yaml. From verification_procedures/ it runs the self-test graph
with its recorded answers. Last it runs python3 -m observability build. The
reconciliation file drops the view's filtering by excluded folder (item 3),
so the session captured before its folder was listed is still shown. A
failing command is named in the failure message, so a changed interface
after another track merges shows at once. Nothing here calls a model or the
network, and the view is built only in a temporary folder. Run from the
repository root with python3 -m pytest -q observability/tests.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from observability import conventions as cv
from observability import spans as sp

ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "examples" / "test_story"
VERIFICATION = ROOT / "verification_procedures"
STORY_SESSION_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
EXCLUDED_SESSION_ID = "9b1e0414-6c3a-4f2d-b8e5-71d2a9c4f086"
PLACEHOLDER = "{{PROJECT}}"
PREFIX = "window.OBS = "


def run_command(command, cwd, env):
    """Run one layer's command, and fail naming it when it does not succeed."""
    done = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True)
    if done.returncode != 0:
        pytest.fail("the command %s, run in %s, exited %d\nstdout:\n%s\nstderr:\n%s" % (
            " ".join(str(part) for part in command), cwd, done.returncode,
            done.stdout, done.stderr))
    return done


def _copy_with_project(source, target, project):
    """Copy a folder, with {{PROJECT}} replaced in every file that reads as text."""
    for path in sorted(Path(source).rglob("*")):
        if "__pycache__" in path.parts:
            continue
        place = Path(target) / path.relative_to(source)
        if path.is_dir():
            place.mkdir(parents=True, exist_ok=True)
            continue
        place.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            place.write_bytes(data)
            continue
        place.write_bytes(text.replace(PLACEHOLDER, str(project)).encode("utf-8"))


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _data(out):
    text = (Path(out) / "data.js").read_text(encoding="utf-8")
    assert text.startswith(PREFIX)
    return json.loads(text[len(PREFIX):].rstrip()[:-1])


class Layers:
    """The test story taken through each layer's command, and what they left."""

    def __init__(self, tmp):
        tmp = Path(tmp)
        self.project = tmp / "story_project"
        _copy_with_project(STORY / "project", self.project, self.project)
        self.excluded = self.project / "excluded_folder"
        self.excluded.mkdir(parents=True, exist_ok=True)
        sessions = tmp / "sessions"
        _copy_with_project(STORY / "sessions" / "claude_code", sessions, self.project)
        self.home = tmp / "audit_home"
        self.run = tmp / "run"
        self.out = tmp / "view"
        env = dict(os.environ)
        env["AUDIT_HOME"] = str(self.home)
        env.pop("PYTHONPATH", None)

        run_command([sys.executable, "-m", "audit_layer", "init"], ROOT, env)
        self.capture = run_command(
            [sys.executable, "-m", "audit_layer", "capture", "--harness", "claude_code",
             str(sessions / "story_session.jsonl"), str(sessions / "excluded_session.jsonl")],
            ROOT, env)
        # The excluded session was recorded while no folder was listed.
        (self.home / "settings.yaml").write_text(
            "excluded_folders:\n  - %s\n" % self.excluded, encoding="utf-8")
        run_command(
            [sys.executable, "vg.py", "run", "graphs/selftest.yaml", "--run", str(self.run),
             "--inputs", "fixtures/selftest",
             "--judge", "recorded:fixtures/selftest/recorded_judge.json"],
            VERIFICATION, env)
        self.database = self.home / "audit.sqlite"
        self.before = _digest(self.database)
        self.build = run_command(
            [sys.executable, "-m", "observability", "build", "--audit-home", str(self.home),
             "--vg-runs", str(self.run), "--out", str(self.out)],
            ROOT, env)
        self.after = _digest(self.database)

    def trace(self, key):
        return sp.read_trace(self.out / "traces" / (sp.trace_id_for(key) + ".json"))


@pytest.fixture(scope="module")
def layers(tmp_path_factory):
    return Layers(tmp_path_factory.mktemp("with_layers"))


def _operation(span):
    return span["attributes"].get(cv.OPERATION_NAME)


def test_capture_recorded_both_story_sessions(layers):
    printed = layers.capture.stdout
    assert STORY_SESSION_ID in printed
    assert EXCLUDED_SESSION_ID in printed
    assert "skipped" not in printed


def test_the_build_names_its_folder_and_three_traces(layers):
    assert str(layers.out) in layers.build.stdout
    assert "3 traces" in layers.build.stdout


def test_the_story_trace_has_its_six_tool_spans_with_paths_and_roles(layers):
    resource, spans = layers.trace("claude_code:" + STORY_SESSION_ID)
    assert resource[cv.SERVICE_NAME] == "claude_code"
    tools = sorted((span for span in spans if _operation(span) == cv.EXECUTE_TOOL),
                   key=lambda span: span["start_ns"])
    assert [span["attributes"][cv.TOOL_NAME] for span in tools] == [
        "Read", "Edit", "Edit", "Write", "Bash", "Bash"]
    manuscript = str(layers.project / "manuscript.md")
    notes = str(layers.project / "source_notes.md")
    files = [(span["attributes"].get(cv.FILE_PATH), span["attributes"].get(cv.AUDIT_ROLE))
             for span in tools]
    assert files[:4] == [(manuscript, "read"), (manuscript, "edited"),
                         (manuscript, "edited"), (notes, "produced")]
    assert [path for path, _ in files[4:]] == [None, None]
    for span in spans:
        assert sp.problems(span) == []
        assert cv.convention_problems(span) == []


def test_the_story_trace_has_its_seven_model_turns(layers):
    _, spans = layers.trace("claude_code:" + STORY_SESSION_ID)
    chats = [span for span in spans if _operation(span) == cv.CHAT]
    assert len(chats) == 7
    for span in chats:
        assert span["attributes"][cv.PROVIDER_NAME] == "anthropic"


def test_the_run_trace_has_its_four_recorded_items(layers):
    key = "vg:" + os.path.realpath(str(layers.run))
    resource, spans = layers.trace(key)
    assert resource[cv.SERVICE_NAME] == "vg.py"
    [root] = [span for span in spans if not span["parent_span_id"]]
    assert root["name"] == "invoke_workflow selftest"
    recorded = [span for span in spans
                if str(span["attributes"].get(cv.VG_EXECUTOR, "")).startswith("recorded:")]
    assert len(recorded) == 4
    assert all(not _operation(span) for span in recorded)
    assert all(cv.INPUT_MESSAGES in span["attributes"] for span in recorded)
    assert all(cv.OUTPUT_MESSAGES in span["attributes"] for span in recorded)
    assert [span for span in spans if _operation(span) == cv.CHAT] == []
    for span in spans:
        assert sp.problems(span) == []
        assert cv.convention_problems(span) == []


def test_the_view_data_holds_the_session_and_the_run(layers):
    data = _data(layers.out)
    rows = {row["session_id"]: row for row in data["traces"]}
    assert rows[STORY_SESSION_ID]["model_calls"] == 7
    assert rows[STORY_SESSION_ID]["tool_calls"] == 6
    assert rows["run"]["source"] == "vg.py"
    assert rows["run"]["model_calls"] == 0
    assert rows["run"]["errors"] == 0
    assert data["sources"]["vg_runs"] == [str(layers.run)]


def test_the_session_captured_before_its_folder_was_listed_is_still_shown(layers):
    """The reconciliation drops the view's filtering by excluded folder (item 3)."""
    rows = {row["session_id"]: row for row in _data(layers.out)["traces"]}
    assert rows[EXCLUDED_SESSION_ID]["project"] == str(layers.excluded)
    _, spans = layers.trace("claude_code:" + EXCLUDED_SESSION_ID)
    assert spans


def test_the_build_leaves_the_audit_database_bytes_unchanged(layers):
    assert layers.after == layers.before


def test_a_failing_command_is_named_in_the_failure_message(tmp_path):
    command = [sys.executable, "-m", "audit_layer", "no-such-command"]
    with pytest.raises(pytest.fail.Exception) as failure:
        run_command(command, ROOT, dict(os.environ, AUDIT_HOME=str(tmp_path / "home")))
    message = str(failure.value)
    assert "audit_layer no-such-command" in message
    assert str(ROOT) in message
