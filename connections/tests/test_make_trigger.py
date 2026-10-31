"""Tests for the Make trigger (Track D, step D20).

Appendix-only. A3 counts the Make trigger among item 2's acceptance tests,
and A2.2 says AI work in another harness is caught at build time. A stream is
stale unless its results file in <project>/verification lists the checksum
of the input it covers, the source text for prose, citations, and build, and
the numbers file for data (the slice's choice 8). make verify starts each
stale stream's start command in the foreground before the build, logs each
start as a ran action event, and never fails the make (Track D choices 19,
20, and 21).

The registry and triggers.yaml here are synthetic, and each start command
runs this Python to append a line to a file in the project. Every test runs
with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary folder. Run
from the repository root with python3 -m pytest -q connections/tests.
"""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections import home  # noqa: E402
from connections.triggers.make import make_trigger  # noqa: E402

PYTHON = shlex.quote(sys.executable)
VERIFY_MK = ROOT / "connections" / "triggers" / "verify.mk"

REGISTRY = """\
registry_version: 1
procedures:
  - id: prose
    stream: prose
    graph: graphs/prose.yaml
    triggers:
      files: ["*.md"]
  - id: citations
    stream: citations
    graph: graphs/citations.yaml
    triggers:
      files: ["*.md", refs.yaml]
  - id: data
    stream: data
    graph: graphs/data.yaml
    triggers:
      files: ["*.py", numbers.yml]
  - id: build
    stream: build
    graph: graphs/build.yaml
    triggers:
      files: [Makefile, "*.md"]
  - id: notes
    stream: notes
    graph: graphs/notes.yaml
    triggers:
      files: ["*.txt"]
"""


def append_command(name, code=0):
    """A start command that appends name and its working folder to started.log, then exits with code."""
    script = (
        "import os, pathlib, sys; "
        "p = pathlib.Path(sys.argv[1], 'started.log'); "
        "p.open('a').write(%r + ' ' + os.getcwd() + chr(10)); "
        "sys.exit(%d)" % (name, code)
    )
    return f"{PYTHON} -c {shlex.quote(script)} {{project}}"


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
    folder.mkdir()
    (folder / "manuscript.md").write_text("# A paper\n\nThe effect is 0.42.\n", encoding="utf-8")
    (folder / "numbers.yml").write_text("effect: 0.42\n", encoding="utf-8")
    exclude(str(homes / "records"))
    write_settings({})
    return folder


def checksum(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_results(project, stream, covered):
    folder = project / "verification"
    folder.mkdir(exist_ok=True)
    data = {
        "schema": "verification-results",
        "schema_version": 1,
        "run_id": f"run-{stream}",
        "inputs": {"draft.md": checksum(covered)},
        "items": [],
        "decisions": [],
    }
    (folder / f"{stream}.json").write_text(json.dumps(data), encoding="utf-8")


def all_events():
    folder = Path(os.environ["CONNECTIONS_HOME"]) / "events"
    if not folder.exists():
        return []
    events = []
    for path in sorted(folder.glob("*.jsonl")):
        events += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return events


def started(project):
    path = project / "started.log"
    if not path.exists():
        return []
    return [line.split(" ", 1)[0] for line in path.read_text().splitlines()]


def run_cli(*args, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "connections", "trigger", "make", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else str(ROOT),
        env=env,
        timeout=120,
    )


def test_no_results_file_is_stale(project, capsys):
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert lines == [
        "verify prose stale, no start command",
        "verify citations stale, no start command",
        "verify data stale, no start command",
        "verify build stale, no start command",
    ]
    assert capsys.readouterr().out.splitlines() == lines


def test_only_the_four_streams_are_checked(project):
    write_settings({"notes": append_command("notes")})
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert not any("notes" in line for line in lines)
    assert started(project) == []


def test_a_results_file_holding_the_source_checksum_is_current(project):
    write_results(project, "prose", project / "manuscript.md")
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert lines[0] == "verify prose current"
    assert lines[1] == "verify citations stale, no start command"


def test_editing_the_source_makes_the_stream_stale(project):
    write_results(project, "prose", project / "manuscript.md")
    (project / "manuscript.md").write_text("# A paper\n\nThe effect is 0.43.\n", encoding="utf-8")
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert lines[0] == "verify prose stale, no start command"


def test_data_follows_the_numbers_file(project):
    write_results(project, "data", project / "numbers.yml")
    write_results(project, "build", project / "numbers.yml")
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert lines[2] == "verify data current"
    assert lines[3] == "verify build stale, no start command"
    (project / "manuscript.md").write_text("changed\n", encoding="utf-8")
    assert make_trigger(project, "manuscript.md", "numbers.yml")[2] == "verify data current"
    (project / "numbers.yml").write_text("effect: 0.5\n", encoding="utf-8")
    assert make_trigger(project, "manuscript.md", "numbers.yml")[2] == (
        "verify data stale, no start command"
    )


def test_a_results_file_that_does_not_parse_is_stale(project):
    (project / "verification").mkdir()
    (project / "verification" / "prose.json").write_text("{not json", encoding="utf-8")
    (project / "verification" / "citations.json").write_text(
        json.dumps({"inputs": [checksum(project / "manuscript.md")]}), encoding="utf-8"
    )
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert lines[0] == "verify prose stale, no start command"
    assert lines[1] == "verify citations stale, no start command"


def test_other_source_and_numbers_files_are_covered(project):
    (project / "paper.md").write_text("Another text.\n", encoding="utf-8")
    (project / "out").mkdir()
    (project / "out" / "values.yml").write_text("x: 1\n", encoding="utf-8")
    write_results(project, "citations", project / "paper.md")
    write_results(project, "data", project / "out" / "values.yml")
    lines = make_trigger(project, "paper.md", "out/values.yml")
    assert lines[1] == "verify citations current"
    assert lines[2] == "verify data current"


def test_a_missing_covered_input_is_reported_and_skipped(project):
    write_settings({s: append_command(s) for s in ("prose", "citations", "data", "build")})
    (project / "numbers.yml").unlink()
    lines = make_trigger(project, "draft.md", "numbers.yml")
    assert lines == [
        "verify prose skipped, draft.md missing",
        "verify citations skipped, draft.md missing",
        "verify data skipped, numbers.yml missing",
        "verify build skipped, draft.md missing",
    ]
    assert started(project) == []
    assert all_events() == []


def test_each_stale_stream_is_started_in_the_foreground_in_the_project(project):
    write_settings({s: append_command(s) for s in ("prose", "citations", "data", "build")})
    write_results(project, "citations", project / "manuscript.md")
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert lines == [
        "verify prose stale, started, exit 0",
        "verify citations current",
        "verify data stale, started, exit 0",
        "verify build stale, started, exit 0",
    ]
    # The commands have finished by the time the trigger returns, in registry order.
    assert started(project) == ["prose", "data", "build"]
    folders = {line.split(" ", 1)[1] for line in (project / "started.log").read_text().splitlines()}
    assert folders == {os.path.realpath(str(project))}


def test_each_start_is_logged_as_a_ran_action_event(project):
    write_settings({"prose": append_command("prose"), "data": append_command("data")})
    make_trigger(project, "manuscript.md", "numbers.yml")
    events = all_events()
    assert [e["object"] for e in events] == ["prose procedure started", "data procedure started"]
    for event in events:
        assert event["verb"] == "ran"
        assert event["kind"] == "action"
        assert event["program"] == "trigger"
        assert event["harness"] == "wrappers"
        assert event["cwd"] == os.path.abspath(str(project))
    assert "manuscript.md" in events[0]["rationale"]
    assert "numbers.yml" in events[1]["rationale"]


def test_a_failing_start_command_prints_its_exit_code(project):
    write_settings({"prose": append_command("prose", code=3)})
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert lines[0] == "verify prose stale, started, exit 3"
    assert len(all_events()) == 1


def test_recording_off_starts_nothing(project, homes):
    write_settings({s: append_command(s) for s in ("prose", "citations", "data", "build")})
    exclude(str(project))
    assert make_trigger(project, "manuscript.md", "numbers.yml") == [
        "verify skipped, recording is off for this folder"
    ]
    assert started(project) == []
    assert all_events() == []


@pytest.mark.parametrize("ignores, skipped", [(True, True), (False, False)])
def test_a_project_listed_in_another_case_starts_nothing_only_on_a_disk_that_ignores_case(
    project, homes, monkeypatch, ignores, skipped
):
    # Track L, Step L4, decision 51, with a stand-in for the disk check.
    write_settings({"prose": append_command("prose")})
    exclude(str(homes / "MY PROJECT"))
    monkeypatch.setattr(home, "ignores_case", lambda path: ignores)
    lines = make_trigger(project, "manuscript.md", "numbers.yml")
    assert (lines == ["verify skipped, recording is off for this folder"]) is skipped


def test_a_missing_audit_settings_file_starts_nothing(project):
    write_settings({"prose": append_command("prose")})
    (Path(os.environ["AUDIT_HOME"]) / "settings.yaml").unlink()
    assert make_trigger(project, "manuscript.md", "numbers.yml") == [
        "verify skipped, recording is off for this folder"
    ]
    assert started(project) == []


def test_the_command_always_exits_0(project):
    write_settings({"prose": append_command("prose", code=5)})
    done = run_cli("--project", str(project))
    assert done.returncode == 0
    assert done.stdout.splitlines()[0] == "verify prose stale, started, exit 5"
    assert started(project) == ["prose"]


def test_the_command_takes_the_source_and_numbers_files(project):
    (project / "paper.md").write_text("Another text.\n", encoding="utf-8")
    write_results(project, "prose", project / "paper.md")
    done = run_cli("--project", str(project), "--source", "paper.md", "--numbers", "missing.yml")
    assert done.returncode == 0
    assert done.stdout.splitlines() == [
        "verify prose current",
        "verify citations stale, no start command",
        "verify data skipped, missing.yml missing",
        "verify build stale, no start command",
    ]


def test_a_registry_that_cannot_be_read_still_exits_0(project):
    home = Path(os.environ["CONNECTIONS_HOME"])
    (home / "registry.yaml").write_text("procedures: [", encoding="utf-8")
    done = run_cli("--project", str(project))
    assert done.returncode == 0
    assert "registry" in done.stderr


def test_verify_mk_sets_its_variables_and_target():
    text = VERIFY_MK.read_text(encoding="utf-8")
    assert "WORKFLOW_REPO" in text
    assert "$(abspath $(lastword $(MAKEFILE_LIST)))" in text
    assert "VERIFY_SOURCE ?= manuscript.md" in text
    assert "VERIFY_NUMBERS ?= numbers.yml" in text
    assert ".PHONY: verify" in text
    assert "trigger make" in text


def test_verify_mk_recipe_ignores_its_own_errors():
    """The leading '-' keeps the make going when python3 is missing or the import fails."""
    lines = VERIFY_MK.read_text(encoding="utf-8").splitlines()
    recipe = [line for line in lines if "trigger make" in line and not line.startswith("#")]
    assert recipe
    for line in recipe:
        assert line.startswith("\t-"), line


def make_project(project, start_code):
    write_settings({"prose": append_command("verify-prose", code=start_code)})
    paper = (
        "import pathlib; p = pathlib.Path('started.log'); "
        "p.open('a').write('paper ' + str(pathlib.Path.cwd()) + chr(10))"
    )
    makefile = (
        "paper: verify\n"
        f"\t{PYTHON} -c {shlex.quote(paper)}\n"
        "\n"
        f"include {VERIFY_MK}\n"
    )
    (project / "Makefile").write_text(makefile, encoding="utf-8")


def working_make():
    """The command that runs GNU Make from this Python, or None.

    make on the path comes first. On a Mac whose Python runs under Rosetta,
    the /usr/bin/make shim fails from it, and arch -arm64 make works.
    """
    if shutil.which("make") is None:
        return None
    candidates = [["make"]]
    if shutil.which("arch") is not None:
        candidates.append(["arch", "-arm64", "make"])
    for command in candidates:
        try:
            done = subprocess.run(command + ["--version"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and "GNU Make" in done.stdout:
            return command
    return None


MAKE = working_make()
needs_make = pytest.mark.skipif(MAKE is None, reason="no working make on the path")


def run_make(project, *targets):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        MAKE + list(targets),
        capture_output=True,
        text=True,
        cwd=str(project),
        env=env,
        timeout=120,
    )


@needs_make
def test_make_paper_starts_the_stale_streams_before_the_build(project):
    make_project(project, 0)
    done = run_make(project, "paper")
    assert done.returncode == 0, done.stderr
    assert started(project) == ["verify-prose", "paper"]
    assert "verify prose stale, started, exit 0" in done.stdout


@needs_make
def test_make_does_not_stop_when_a_start_command_fails(project):
    make_project(project, 4)
    done = run_make(project, "paper")
    assert done.returncode == 0, done.stderr
    assert started(project) == ["verify-prose", "paper"]
    assert "verify prose stale, started, exit 4" in done.stdout


@needs_make
def test_make_takes_the_scholars_source_name(project):
    (project / "paper.md").write_text("Another text.\n", encoding="utf-8")
    write_results(project, "prose", project / "paper.md")
    make_project(project, 0)
    done = run_make(project, "paper", "VERIFY_SOURCE=paper.md")
    assert done.returncode == 0, done.stderr
    assert "verify prose current" in done.stdout
    assert started(project) == ["paper"]


@needs_make
def test_make_hands_makelevel_to_the_start_command(project):
    """The README's start scripts tell a make start from an end-of-turn start by MAKELEVEL."""
    code = (
        "import os, pathlib, sys; "
        "pathlib.Path(sys.argv[1], 'makelevel.txt').write_text(os.environ.get('MAKELEVEL', 'unset'))"
    )
    make_project(project, 0)
    write_settings({"prose": f"{PYTHON} -c {shlex.quote(code)} {{project}}"})
    done = run_make(project, "paper")
    assert done.returncode == 0, done.stderr
    assert (project / "makelevel.txt").read_text() not in ("", "unset")
