"""Tests for the AI-edit and end-of-turn triggers (Track D, step D10).

The proposal says events in the harness, such as an AI edit or the end of a
turn, start the verification procedures (Overview paragraph 2). Appendix A2.2
says triggers are designed for one harness's hooks, and Claude Code comes
first by the authors' ruling. An AI edit marks as due the registered procedures
whose file patterns match the edited file, and the end of the turn starts
each due procedure once, in the background, through the scholar's own start
command (Track D choices 18 and 19). Each start is logged as a ran action
event (choice 21). Nothing is marked or started in an excluded folder or
while the audit settings file is missing (choice 3, reconciliation item 3).

The registry and the triggers.yaml here are synthetic, and each start command
runs this Python to write a marker file in the project. Every test runs with
HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary folder. Run from the
repository root with python3 -m pytest -q connections/tests.
"""
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections import home  # noqa: E402
from connections.home import folder_key  # noqa: E402
from connections.triggers.hook import handle_hook  # noqa: E402

PYTHON = shlex.quote(sys.executable)

REGISTRY = """\
registry_version: 1
procedures:
  - id: prose
    graph: graphs/prose.yaml
    triggers:
      files: ["*.md"]
  - id: citations
    graph: graphs/citations.yaml
    triggers:
      files: ["*.md", refs.yaml]
  - id: data
    graph: graphs/data.yaml
    triggers:
      files: ["*.py", numbers.yml]
"""


def marker_command(name, sleep=0.0):
    """A start command that waits, then writes the marker name in the project it is given."""
    code = (
        "import pathlib, sys, time; time.sleep(%r); "
        "pathlib.Path(sys.argv[1], %r).write_text('done')" % (sleep, name)
    )
    return f"{PYTHON} -c {shlex.quote(code)} {{project}}"


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def exclude(*folders):
    path = Path(os.environ["AUDIT_HOME"]) / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"  - {folder}\n" for folder in folders)
    path.write_text("excluded_folders:\n" + lines if folders else "excluded_folders: []\n")


def write_settings(start):
    home = Path(os.environ["CONNECTIONS_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    registry = home / "registry.yaml"
    registry.write_text(REGISTRY, encoding="utf-8")
    settings = {"registry": str(registry), "start": start}
    (home / "triggers.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")


@pytest.fixture
def project(homes):
    folder = homes / "my project"
    (folder / "drafts").mkdir(parents=True)
    exclude(str(homes / "records"))
    write_settings(
        {
            "prose": marker_command("marker_prose"),
            "citations": marker_command("marker_citations"),
            "data": marker_command("marker_data"),
        }
    )
    return folder


def hook(event, project=None, **fields):
    data = {"session_id": "s1", "hook_event_name": event}
    if project is not None:
        data["cwd"] = str(project)
    data.update(fields)
    return json.dumps(data)


def edit(project, path, tool="Edit"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return hook("PostToolUse", project, tool_name=tool, tool_input={key: str(path)})


def stop(project):
    return hook("Stop", project, stop_hook_active=False)


def due_path(project):
    return Path(os.environ["CONNECTIONS_HOME"]) / "triggers" / "due" / f"{folder_key(project)}.json"


def due(project):
    path = due_path(project)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def all_events():
    folder = Path(os.environ["CONNECTIONS_HOME"]) / "events"
    if not folder.exists():
        return []
    events = []
    for path in sorted(folder.glob("*.jsonl")):
        events += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return events


def logs():
    folder = Path(os.environ["CONNECTIONS_HOME"]) / "triggers" / "logs"
    return sorted(folder.glob("*.log")) if folder.exists() else []


def wait_for(path, seconds=15.0):
    end = time.time() + seconds
    while time.time() < end:
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


def run_hook(text, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "connections", "trigger", "hook"],
        input=text.encode("utf-8"),
        capture_output=True,
        cwd=str(cwd) if cwd else str(ROOT),
        env=env,
        timeout=60,
    )


def start_hook():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    process = subprocess.Popen(
        [sys.executable, "-m", "connections", "trigger", "hook"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
        env=env,
    )
    return process


def feed(process, text):
    process.stdin.write(text.encode("utf-8"))
    process.stdin.close()


def test_an_edit_to_the_manuscript_marks_the_matching_procedures(project):
    assert handle_hook(edit(project, project / "manuscript.md")) == ""
    assert due(project) == {"prose": ["manuscript.md"], "citations": ["manuscript.md"]}


def test_an_edit_to_a_data_file_marks_none(project):
    assert handle_hook(edit(project, project / "data.csv")) == ""
    assert due(project) == {}


def test_each_edit_tool_marks(project):
    handle_hook(edit(project, project / "drafts" / "x.md", tool="Write"))
    handle_hook(edit(project, project / "refs.yaml", tool="MultiEdit"))
    handle_hook(edit(project, project / "analysis.py", tool="NotebookEdit"))
    assert due(project) == {
        "prose": ["drafts/x.md"],
        "citations": ["drafts/x.md", "refs.yaml"],
        "data": ["analysis.py"],
    }


def test_other_tools_and_other_hook_events_mark_nothing(project):
    handle_hook(hook("PostToolUse", project, tool_name="Read", tool_input={"file_path": str(project / "a.md")}))
    handle_hook(hook("PostToolUse", project, tool_name="Bash", tool_input={"command": "touch a.md"}))
    handle_hook(hook("PreToolUse", project, tool_name="Edit", tool_input={"file_path": str(project / "a.md")}))
    assert handle_hook(hook("UserPromptSubmit", project, prompt="hello")) == ""
    assert handle_hook(hook("SessionStart", project)) == ""
    assert due(project) == {}
    assert not (project / "marker_prose").exists()


def test_an_edit_outside_the_project_marks_nothing(project, homes):
    handle_hook(edit(project, homes / "elsewhere" / "manuscript.md"))
    assert due(project) == {}


def test_an_edit_given_relative_to_the_project_marks(project):
    handle_hook(edit(project, "drafts/x.md"))
    assert due(project) == {"prose": ["drafts/x.md"], "citations": ["drafts/x.md"]}


def test_repeated_edits_to_one_file_are_named_once(project):
    handle_hook(edit(project, project / "manuscript.md"))
    handle_hook(edit(project, project / "manuscript.md"))
    assert due(project) == {"prose": ["manuscript.md"], "citations": ["manuscript.md"]}


def test_the_project_is_the_working_folder_when_the_input_names_none(project):
    done = run_hook(edit(None, project / "manuscript.md"), cwd=project)
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""
    assert due(project) == {"prose": ["manuscript.md"], "citations": ["manuscript.md"]}


def test_stop_starts_the_due_procedure_in_the_background(project):
    write_settings({"prose": marker_command("marker_prose", sleep=3.0)})
    handle_hook(edit(project, project / "drafts" / "x.md"))
    handle_hook(edit(project, project / "manuscript.md"))
    assert sorted(due(project)) == ["citations", "prose"]

    began = time.time()
    done = run_hook(stop(project))
    took = time.time() - began
    # The command sleeps 3 seconds, so its marker cannot exist yet unless the
    # hook waited for it (choice 18, the turn never waits for a run).
    assert not (project / "marker_prose").exists()
    assert done.returncode == 0
    assert done.stderr == b""
    assert took < 2.0, f"the Stop hook took {took:.2f} seconds"
    assert done.stdout.decode("utf-8") == (
        "Verification started for prose. No start command for citations.\n"
    )
    assert wait_for(project / "marker_prose")
    assert not (project / "marker_citations").exists()

    events = all_events()
    assert len(events) == 1
    event = events[0]
    assert event["harness"] == "wrappers"
    assert event["verb"] == "ran"
    assert event["kind"] == "action"
    assert event["program"] == "trigger"
    assert event["object"] == "prose procedure started"
    assert "drafts/x.md" in event["rationale"] and "manuscript.md" in event["rationale"]
    assert event["cwd"] == str(project)
    assert event["harness_session_id"].endswith("_" + folder_key(project))

    assert due(project) == {}
    assert len(logs()) == 1
    assert logs()[0].name.endswith("_prose.log")

    second = run_hook(stop(project))
    assert second.returncode == 0 and second.stdout == b"" and second.stderr == b""
    assert len(all_events()) == 1


def test_stop_starts_each_due_procedure_once_and_logs_one_event_each(project):
    handle_hook(edit(project, project / "manuscript.md"))
    handle_hook(edit(project, project / "drafts" / "x.md"))
    handle_hook(edit(project, project / "analysis.py"))
    assert handle_hook(stop(project)) == "Verification started for prose, citations, data."
    for name in ("marker_prose", "marker_citations", "marker_data"):
        assert wait_for(project / name)
    objects = [event["object"] for event in all_events()]
    assert objects == [
        "prose procedure started",
        "citations procedure started",
        "data procedure started",
    ]
    assert len(logs()) == 3
    assert handle_hook(stop(project)) == ""


def test_a_due_procedure_with_no_command_is_named_and_not_started(project):
    write_settings({"data": marker_command("marker_data")})
    handle_hook(edit(project, project / "manuscript.md"))
    assert handle_hook(stop(project)) == "No start command for prose, citations."
    time.sleep(0.3)
    assert not (project / "marker_prose").exists()
    assert not (project / "marker_citations").exists()
    assert all_events() == []
    assert logs() == []
    assert due(project) == {}


def test_two_edit_hooks_started_together_both_keep_their_marks(project):
    for _ in range(3):
        if due_path(project).exists():
            due_path(project).unlink()
        # Both start and wait on their input, then both get it at once.
        first = start_hook()
        second = start_hook()
        time.sleep(0.5)
        feed(first, edit(project, project / "manuscript.md"))
        feed(second, edit(project, project / "analysis.py"))
        first.wait(timeout=60)
        second.wait(timeout=60)
        out_first, err_first = first.stdout.read(), first.stderr.read()
        out_second, err_second = second.stdout.read(), second.stderr.read()
        for process in (first, second):
            process.stdout.close()
            process.stderr.close()
        assert first.returncode == 0 and second.returncode == 0
        assert out_first == out_second == b""
        assert err_first == err_second == b""
        assert due(project) == {
            "prose": ["manuscript.md"],
            "citations": ["manuscript.md"],
            "data": ["analysis.py"],
        }



def test_an_edit_hook_waits_for_the_lock_and_keeps_the_marks_written_meanwhile(project):
    """The two hooks above rarely meet inside the lock, so this holds it the way a hook does."""
    import fcntl

    path = due_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        waiting = start_hook()
        feed(waiting, edit(project, project / "analysis.py"))
        time.sleep(1.0)
        assert waiting.poll() is None, "the hook did not wait for the lock"
        os.write(handle, json.dumps({"prose": ["manuscript.md"]}).encode("utf-8"))
    finally:
        os.close(handle)
    waiting.wait(timeout=60)
    waiting.stdout.close()
    waiting.stderr.close()
    assert waiting.returncode == 0
    assert due(project) == {"prose": ["manuscript.md"], "data": ["analysis.py"]}

def test_an_excluded_project_marks_starts_and_prints_nothing(project, homes):
    exclude(str(project))
    done = run_hook(edit(project, project / "manuscript.md"))
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""
    assert due(project) == {}
    assert not due_path(project).exists()


@pytest.mark.parametrize("ignores, marked", [(True, False), (False, True)])
def test_a_project_listed_in_another_case_marks_nothing_only_on_a_disk_that_ignores_case(
    project, homes, monkeypatch, ignores, marked
):
    # Track L, Step L4, decision 51, with a stand-in for the disk check.
    exclude(str(homes / "My Project"))
    monkeypatch.setattr(home, "ignores_case", lambda path: ignores)
    handle_hook(edit(project, project / "manuscript.md"))
    assert due_path(project).exists() is marked


def test_marks_left_before_a_folder_is_excluded_start_nothing(project):
    handle_hook(edit(project, project / "manuscript.md"))
    exclude(str(project))
    done = run_hook(stop(project))
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""
    time.sleep(0.3)
    assert not (project / "marker_prose").exists()
    assert all_events() == []
    assert logs() == []


def test_a_missing_settings_file_marks_starts_and_prints_nothing(project):
    handle_hook(edit(project, project / "manuscript.md"))
    (Path(os.environ["AUDIT_HOME"]) / "settings.yaml").unlink()
    assert handle_hook(edit(project, project / "drafts" / "x.md")) == ""
    assert due(project) == {"prose": ["manuscript.md"], "citations": ["manuscript.md"]}
    done = run_hook(stop(project))
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""
    time.sleep(0.3)
    assert not (project / "marker_prose").exists()
    assert all_events() == []


def test_missing_trigger_settings_start_nothing(project):
    (Path(os.environ["CONNECTIONS_HOME"]) / "triggers.yaml").unlink()
    handle_hook(edit(project, project / "manuscript.md"))
    # With no settings the repository's own registry is read, which marks build too.
    assert handle_hook(stop(project)) == "No start command for prose, citations, build."
    assert all_events() == []


@pytest.mark.parametrize("text", ["", "not json", "{", "[1, 2]", '"Stop"', "null"])
def test_input_that_is_not_a_hook_does_nothing_and_exits_zero(project, text):
    done = run_hook(text)
    assert done.returncode == 0
    assert done.stdout == b""
    assert done.stderr == b""
    assert handle_hook(text) == ""


def test_input_that_is_not_utf8_exits_zero(project):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    done = subprocess.run(
        [sys.executable, "-m", "connections", "trigger", "hook"],
        input=b"\xff\xfe{",
        capture_output=True,
        cwd=str(ROOT),
        env=env,
        timeout=60,
    )
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""


def test_a_start_command_that_fails_still_exits_zero(project):
    write_settings({"prose": "exit 3", "citations": "no_such_program_for_the_trigger_test {project}"})
    handle_hook(edit(project, project / "manuscript.md"))
    done = run_hook(stop(project))
    assert done.returncode == 0
    assert done.stderr == b""
    assert done.stdout.decode("utf-8") == "Verification started for prose, citations.\n"
    assert len(all_events()) == 2


def test_a_hook_whose_registry_cannot_be_read_marks_nothing(project):
    home = Path(os.environ["CONNECTIONS_HOME"])
    (home / "registry.yaml").write_text("a: [unclosed\n", encoding="utf-8")
    done = run_hook(edit(project, project / "manuscript.md"))
    assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""
    assert due(project) == {}


def test_a_due_file_that_cannot_be_read_is_replaced(project):
    path = due_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    handle_hook(edit(project, project / "refs.yaml"))
    assert due(project) == {"citations": ["refs.yaml"]}


def test_the_status_line_never_asks_the_harness_to_block(project):
    handle_hook(edit(project, project / "manuscript.md"))
    text = handle_hook(stop(project))
    with pytest.raises(ValueError):
        json.loads(text)


def test_the_hook_module_imports_no_other_layer():
    for name in ("hook.py", "registry.py", "__init__.py"):
        text = (ROOT / "connections" / "triggers" / name).read_text(encoding="utf-8")
        for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
            assert f"import {layer}" not in text
            assert f"from {layer}" not in text
