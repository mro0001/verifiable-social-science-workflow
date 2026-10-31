"""Tests for the command wrapper (Track D, step D3).

Appendix A2.2 says wrappers are small programs that log each action in the
scholar's external software for the audit layer, and Figure A2 says they log
each action and never interrupt the call. A wrapped call leaves one event for
the call and one wrote event, role produced, for each file it created or
changed under its working folder (Track D choice 4). Its verb follows the
rules the reconciliation fixes for wrapper events (item 7), the same as Track
G's git wrapper graph for git, and the slice's mechanical pass for any other
program. Nothing is recorded in an excluded folder or while the audit
settings file is missing (choice 3, reconciliation item 3).

Every test runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a
temporary folder, and the stand-in programs are small scripts the tests
write. Run from the repository root with python3 -m pytest -q
connections/tests.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections import home, wrap  # noqa: E402
from connections.wrap import call_verb, run_wrapped, snapshot  # noqa: E402

PYTHON = sys.executable


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


@pytest.fixture
def project(homes):
    folder = homes / "project"
    folder.mkdir()
    exclude(str(homes / "records"), str(folder / "private"))
    return folder


@pytest.fixture
def stand_ins(homes, monkeypatch):
    """A folder of stand-in programs put first on the path."""
    folder = homes / "bin"
    folder.mkdir()
    monkeypatch.setenv("PATH", str(folder) + os.pathsep + os.environ.get("PATH", ""))
    return folder


def stand_in(folder, name, body):
    path = folder / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


def all_events():
    folder = Path(os.environ["CONNECTIONS_HOME"]) / "events"
    if not folder.exists():
        return []
    found = []
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            found.append(json.loads(line))
    return found


def cli(args, cwd, stdin=b""):
    """Run python3 -m connections with args in cwd, with the tests' homes."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [PYTHON, "-m", "connections"] + list(args),
        cwd=str(cwd),
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=60,
    )


# The exit code and the program's own streams


def test_exit_code_comes_back(project):
    assert run_wrapped([PYTHON, "-c", "import sys; sys.exit(3)"], cwd=str(project)) == 3


def test_exit_code_comes_back_through_the_command(project):
    done = cli(["wrap", "--", PYTHON, "-c", "import sys; sys.exit(3)"], project)
    assert done.returncode == 3


def test_input_reaches_the_program_and_its_streams_come_back_byte_for_byte(project):
    code = (
        "import sys; data = sys.stdin.buffer.read(); "
        "sys.stdout.buffer.write(data[::-1] + b'\\x00\\xff out\\r\\n'); "
        "sys.stderr.buffer.write(b'err \\xe2\\x80\\x94 line\\n')"
    )
    done = cli(["wrap", "--", PYTHON, "-c", code], project, stdin=b"abc\n\x01")
    assert done.returncode == 0
    assert done.stdout == b"\x01\ncba" + b"\x00\xff out\r\n"
    assert done.stderr == "err \u2014 line\n".encode("utf-8")


def test_options_after_the_program_belong_to_the_program(project):
    done = cli(["wrap", "--", PYTHON, "-c", "import sys; print(sys.argv[1:])", "-v", "--help"], project)
    assert done.returncode == 0
    assert done.stdout.decode().strip() == "['-v', '--help']"


def test_wrap_with_no_program_prints_the_usage_and_exits_2(project):
    done = cli(["wrap", "--"], project)
    assert done.returncode == 2
    assert b"usage" in done.stderr
    assert all_events() == []


def test_a_signal_that_ends_the_program_gives_128_plus_its_number(project):
    code = "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
    assert run_wrapped([PYTHON, "-c", code], cwd=str(project)) == 143


def test_a_signal_through_the_command_gives_143(project):
    code = "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
    assert cli(["wrap", "--", PYTHON, "-c", code], project).returncode == 143


def test_ctrl_c_is_left_to_the_program(project, tmp_path):
    """The wrapper keeps waiting on Ctrl-C, so a program that handles it decides how to stop."""
    ready = tmp_path / "ready"
    code = (
        "import signal, sys, time, pathlib\n"
        "signal.signal(signal.SIGINT, lambda *a: (print('stopping cleanly', flush=True), sys.exit(5)))\n"
        f"pathlib.Path({str(ready)!r}).write_text('ok')\n"
        "time.sleep(30)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    process = subprocess.Popen(
        [PYTHON, "-m", "connections", "wrap", "--", PYTHON, "-c", code],
        cwd=str(project),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        for _ in range(300):
            if ready.exists():
                break
            time.sleep(0.05)
        assert ready.exists()
        # Ctrl-C at a terminal sends SIGINT to every process in the group.
        os.killpg(process.pid, 2)
        out, err = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 5
    assert out == b"stopping cleanly\n"
    assert err == b""


# A missing program


def test_a_missing_program_returns_127_and_writes_no_event(project, capfd):
    assert run_wrapped(["no-such-program-d3"], cwd=str(project)) == 127
    assert capfd.readouterr().err == "no-such-program-d3: command not found\n"
    assert all_events() == []


def test_a_missing_program_through_the_command(project):
    done = cli(["wrap", "--", "no-such-program-d3", "x"], project)
    assert done.returncode == 127
    assert done.stdout == b""
    assert done.stderr == b"no-such-program-d3: command not found\n"
    assert all_events() == []


# What a wrapped call records


def test_a_call_that_writes_a_file_gives_a_ran_event_and_a_wrote_event(project):
    code = "open('out.txt', 'w').write('hello')"
    assert run_wrapped([PYTHON, "-c", code], cwd=str(project)) == 0
    found = all_events()
    assert len(found) == 2
    call, wrote = found
    command = f"{PYTHON} -c {code}"
    assert call["verb"] == "ran"
    assert call["kind"] == "action"
    assert call["object"] == command
    assert call["role"] == ""
    assert call["harness"] == "wrappers"
    assert call["program"] == os.path.basename(PYTHON)
    assert call["cwd"] == str(project)
    assert call["exit_code"] == 0
    assert isinstance(call["duration_s"], (int, float)) and call["duration_s"] >= 0
    assert call["files_scanned"] == 1
    assert wrote["verb"] == "wrote"
    assert wrote["kind"] == "action"
    assert wrote["role"] == "produced"
    assert wrote["object"] == os.path.realpath(str(project / "out.txt"))
    assert wrote["by"] == command
    assert wrote["harness_session_id"] == call["harness_session_id"]
    assert wrote["source_id"] != call["source_id"]


def test_a_changed_file_gives_a_wrote_event_and_an_untouched_one_does_not(project):
    (project / "kept.txt").write_text("same")
    (project / "changed.txt").write_text("before")
    old = 1_000_000_000
    os.utime(str(project / "changed.txt"), (old, old))
    code = "open('changed.txt', 'w').write('after!')"
    run_wrapped([PYTHON, "-c", code], cwd=str(project))
    wrote = [event["object"] for event in all_events() if event["verb"] == "wrote"]
    assert wrote == [os.path.realpath(str(project / "changed.txt"))]


def test_a_file_in_a_subfolder_is_found(project):
    code = "import os; os.makedirs('out/figures'); open('out/figures/f1.png', 'wb').write(b'x')"
    run_wrapped([PYTHON, "-c", code], cwd=str(project))
    wrote = [event["object"] for event in all_events() if event["verb"] == "wrote"]
    assert wrote == [os.path.realpath(str(project / "out" / "figures" / "f1.png"))]


def test_files_in_skipped_folders_give_no_wrote_event(project):
    code = (
        "import os\n"
        "for folder in ('.git', '.cache', '__pycache__', 'node_modules', 'a/.hidden'):\n"
        "    os.makedirs(folder)\n"
        "    open(os.path.join(folder, 'f'), 'w').write('x')\n"
        "open('.Rhistory', 'w').write('x')\n"
    )
    run_wrapped([PYTHON, "-c", code], cwd=str(project))
    wrote = [event["object"] for event in all_events() if event["verb"] == "wrote"]
    assert wrote == [os.path.realpath(str(project / ".Rhistory"))]


def test_a_file_changed_in_an_excluded_subfolder_gives_no_event(project):
    code = "import os; os.makedirs('private'); open('private/grades.csv', 'w').write('x')"
    run_wrapped([PYTHON, "-c", code], cwd=str(project))
    found = all_events()
    assert [event["verb"] for event in found] == ["ran"]
    assert found[0]["files_scanned"] == 0


def test_the_snapshot_skips_folders_and_stops_at_its_limit(project, monkeypatch):
    for name in ("a.txt", "b.txt", "c.txt"):
        (project / name).write_text(name)
    (project / ".git").mkdir()
    (project / ".git" / "HEAD").write_text("x")
    (project / "private").mkdir()
    (project / "private" / "p.txt").write_text("x")
    seen = snapshot(str(project))
    assert sorted(os.path.basename(path) for path in seen) == ["a.txt", "b.txt", "c.txt"]
    monkeypatch.setattr(wrap, "SNAPSHOT_LIMIT", 2)
    assert len(snapshot(str(project))) == 2


def test_two_calls_from_one_folder_land_in_one_file_in_order(project):
    run_wrapped([PYTHON, "-c", "print(1)"], cwd=str(project))
    run_wrapped([PYTHON, "-c", "print(2)"], cwd=str(project))
    files = list((Path(os.environ["CONNECTIONS_HOME"]) / "events").glob("*.jsonl"))
    assert len(files) == 1
    assert [event["object"].split()[-1] for event in all_events()] == ["print(1)", "print(2)"]


def test_the_object_is_cut_at_200_characters(project):
    long_text = "x" * 400
    run_wrapped([PYTHON, "-c", "pass", long_text], cwd=str(project))
    (call,) = all_events()
    assert call["object"] == (f"{PYTHON} -c pass " + long_text)[:200]


def test_the_command_records_in_the_folder_it_runs_in(project):
    done = cli(["wrap", "--", PYTHON, "-c", "open('o.txt', 'w')"], project)
    assert done.returncode == 0
    assert [event["verb"] for event in all_events()] == ["ran", "wrote"]
    assert all_events()[0]["cwd"] == str(project)


def test_a_failed_program_keeps_its_verb(project):
    run_wrapped([PYTHON, "-c", "import sys; sys.exit(4)"], cwd=str(project))
    (call,) = all_events()
    assert call["verb"] == "ran"
    assert call["exit_code"] == 4


# The verb for git, test programs, and others


def test_a_git_commit_gives_committed_with_its_message(project, stand_ins):
    stand_in(stand_ins, "git", "exit 0")
    assert run_wrapped(["git", "commit", "-m", "Add the results paragraph"], cwd=str(project)) == 0
    (call,) = all_events()
    assert call["verb"] == "committed"
    assert call["kind"] == "action"
    assert call["rationale"] == "Add the results paragraph"
    assert call["program"] == "git"
    assert call["object"] == "git commit -m Add the results paragraph"


def test_pytest_gives_verified_with_kind_observation(project, stand_ins):
    stand_in(stand_ins, "pytest", "exit 0")
    assert run_wrapped(["pytest", "-q"], cwd=str(project)) == 0
    (call,) = all_events()
    assert call["verb"] == "verified"
    assert call["kind"] == "observation"
    assert call["program"] == "pytest"


# The five calls of Track G's clean git fixture (reconciliation item 7), each
# with the verb, kind, and rationale both wrappers give it.
PROJECT_STAND_IN = "/synthetic/test_story/project"
FIVE_GIT_CALLS = [
    (["git", "status"], 0, "searched", "observation", ""),
    (["git", "add", "manuscript.md", "refs.bib"], 0, "ran", "action", ""),
    (
        ["git", "commit", "-m", "Add the results paragraph"],
        0,
        "committed",
        "action",
        "Add the results paragraph",
    ),
    (["git", "-C", PROJECT_STAND_IN, "log", "--oneline"], 0, "searched", "observation", ""),
    (["git", "push"], 128, "ran", "blocker", "exit 128"),
]


@pytest.mark.parametrize("argv, code, verb, kind, rationale", FIVE_GIT_CALLS)
def test_call_verb_on_the_five_git_calls(argv, code, verb, kind, rationale):
    expected_kind = "action" if kind == "blocker" else kind
    assert call_verb(argv) == (verb, expected_kind)


def test_the_five_git_calls_through_a_stand_in_git(project, stand_ins):
    stand_in(stand_ins, "git", 'if [ "$1" = push ]; then exit 128; fi\nexit 0')
    codes = [run_wrapped(list(argv), cwd=str(project)) for argv, *_ in FIVE_GIT_CALLS]
    assert codes == [code for _, code, *_ in FIVE_GIT_CALLS]
    found = all_events()
    assert [(event["verb"], event["kind"], event["rationale"]) for event in found] == [
        (verb, kind, rationale) for _, _, verb, kind, rationale in FIVE_GIT_CALLS
    ]
    assert [event["object"] for event in found] == [" ".join(argv) for argv, *_ in FIVE_GIT_CALLS]
    assert found[4]["exit_code"] == 128


def test_a_failed_commit_starts_its_rationale_with_the_exit_code(project, stand_ins):
    stand_in(stand_ins, "git", "exit 1")
    run_wrapped(["git", "commit", "-m", "Fix a typo"], cwd=str(project))
    (call,) = all_events()
    assert call["verb"] == "committed"
    assert call["kind"] == "blocker"
    assert call["rationale"].startswith("exit 1")
    assert "Fix a typo" in call["rationale"]


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["git", "log"], ("searched", "observation")),
        (["git", "diff", "HEAD~1"], ("searched", "observation")),
        (["git", "show"], ("searched", "observation")),
        (["git", "blame", "a.py"], ("searched", "observation")),
        (["git", "grep", "commit"], ("searched", "observation")),
        (["git", "ls-files"], ("searched", "observation")),
        (["git", "-c", "user.name=x", "commit", "-m", "m"], ("committed", "action")),
        (["git", "--no-pager", "log"], ("searched", "observation")),
        (["git", "push", "origin", "main"], ("ran", "action")),
        (["git"], ("ran", "action")),
        (["/usr/bin/git", "status"], ("searched", "observation")),
        (["git", "add", "commit"], ("ran", "action")),
        (["pytest", "-q"], ("verified", "observation")),
        (["python3", "-m", "pytest", "tests"], ("verified", "observation")),
        (["python3", "vg.py", "check", "graphs/x.yaml"], ("verified", "observation")),
        (["python3", "-m", "ospipe", "check"], ("verified", "observation")),
        (["ospipe", "check", "manuscript.md"], ("verified", "observation")),
        (["sh", "-c", "git commit -m x"], ("committed", "action")),
        (["Rscript", "analysis.R"], ("ran", "action")),
        (["make", "legit"], ("ran", "action")),
    ],
)
def test_call_verb(argv, expected):
    assert call_verb(argv) == expected


@pytest.mark.parametrize(
    "argv, message",
    [
        (["git", "commit", "--message", "Long form"], "Long form"),
        (["git", "commit", "--message=Equals form"], "Equals form"),
        (["git", "commit", "-mJoined"], "Joined"),
        (["git", "commit", "-am", "All tracked"], "All tracked"),
        (["git", "commit", "-m", "One", "-m", "Two"], "One\n\nTwo"),
        (["git", "commit"], ""),
    ],
)
def test_a_commit_message_becomes_the_rationale(project, stand_ins, argv, message):
    stand_in(stand_ins, "git", "exit 0")
    run_wrapped(argv, cwd=str(project))
    (call,) = all_events()
    assert call["rationale"] == message


# Where nothing is recorded


def test_an_excluded_folder_gives_no_event(project, homes):
    records = homes / "records" / "course"
    records.mkdir(parents=True)
    code = "open('roster.csv', 'w').write('x')"
    assert run_wrapped([PYTHON, "-c", code], cwd=str(records)) == 0
    assert (records / "roster.csv").exists()
    assert all_events() == []


def test_a_missing_settings_file_gives_no_event(homes):
    folder = homes / "project"
    folder.mkdir()
    assert run_wrapped([PYTHON, "-c", "open('o.txt', 'w')"], cwd=str(folder)) == 0
    assert all_events() == []
    assert not Path(os.environ["CONNECTIONS_HOME"]).exists()


# Letter case in a listed folder (Track L, Step L4, decision 51), with a
# stand-in for the check of whether the disk ignores case.


@pytest.mark.parametrize("ignores, recorded", [(True, False), (False, True)])
def test_a_folder_listed_in_another_case_gives_no_event_only_on_a_disk_that_ignores_case(
    homes, monkeypatch, ignores, recorded
):
    records = homes / "records" / "course"
    records.mkdir(parents=True)
    exclude(str(homes / "Records"))
    monkeypatch.setattr(home, "ignores_case", lambda path: ignores)
    assert run_wrapped([PYTHON, "-c", "pass"], cwd=str(records)) == 0
    assert bool(all_events()) is recorded


@pytest.mark.parametrize("ignores, walked", [(True, []), (False, ["p.txt"])])
def test_the_snapshot_skips_a_subfolder_listed_in_another_case_only_on_a_disk_that_ignores_case(
    project, homes, monkeypatch, ignores, walked
):
    exclude(str(homes / "records"), str(project / "PRIVATE"))
    (project / "private").mkdir()
    (project / "private" / "p.txt").write_text("x")
    monkeypatch.setattr(home, "ignores_case", lambda path: ignores)
    assert [os.path.basename(path) for path in snapshot(str(project))] == walked


def test_a_folder_that_is_not_walked_when_recording_is_off(homes, monkeypatch):
    folder = homes / "project"
    folder.mkdir()
    walked = []
    monkeypatch.setattr(wrap, "snapshot", lambda path: walked.append(path) or {})
    run_wrapped([PYTHON, "-c", "pass"], cwd=str(folder))
    assert walked == []


def test_a_home_that_cannot_be_written_changes_nothing_the_scholar_sees(project, homes, monkeypatch):
    blocker = homes / "home_is_a_file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("CONNECTIONS_HOME", str(blocker))
    code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(6)"
    done = cli(["wrap", "--", PYTHON, "-c", code], project)
    assert done.returncode == 6
    assert done.stdout == b"out\n"
    assert done.stderr == b"err\n"
    assert blocker.read_text() == "not a folder"


def test_a_failing_snapshot_never_reaches_the_caller(project, monkeypatch, capfd):
    def broken(path):
        raise RuntimeError("walk failed")

    monkeypatch.setattr(wrap, "snapshot", broken)
    assert run_wrapped([PYTHON, "-c", "import sys; sys.exit(2)"], cwd=str(project)) == 2
    assert capfd.readouterr().err == ""
