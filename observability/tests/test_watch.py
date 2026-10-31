"""Tests for live mode (Track E, steps E9 and E13).

Proposal Approach paragraphs 4 and 5 have the scholar observe AI work in real
time, and Status paragraph 3 names a live view of what the harness reads,
calls, and retrieves. Appendix A2.6 paragraph 2 uses the record as it is
written. watch builds the view live, rebuilds it at each interval only when
the record, the kb folders, or the verification runs (step E13) changed, and builds once more with live false
when it stops. Each test runs a set number of cycles with a sleep that
changes the synthetic audit home between them, so nothing waits and nothing
calls a model or the network. Views are built only in temporary folders.
Run from the repository root with python3 -m pytest -q observability/tests.
"""
import json
import shutil
from pathlib import Path

import pytest

from observability import cli
from observability import conventions as cv
from observability import spans as sp
from observability import watch as wt
from observability.tests.audit_fixture import AuditHome

TESTS = Path(__file__).resolve().parent
FIXTURE = TESTS / "fixtures" / "claude_code" / "obs_session.jsonl"
FIXTURE_ID = "7c2e9d10-4b1a-4f3e-9a55-0e6b3c8d2f41"
KB = TESTS / "fixtures" / "kb"
PREFIX = "window.OBS = "

# The fixture's first 12 lines hold four tool calls, and its first 14 a fifth.
FIRST_LINES = 12
GROWN_LINES = 14


def _transcript(project, kb, lines):
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace("{{PROJECT}}", str(project)).replace("{{KB}}", str(kb))
    return "".join(text.splitlines(True)[:lines]).encode("utf-8")


def _data(out):
    text = (Path(out) / "data.js").read_text(encoding="utf-8")
    assert text.startswith(PREFIX)
    body = text[len(PREFIX):].rstrip()
    return json.loads(body[:-1])


def _tool_calls(out):
    trace_id = sp.trace_id_for("claude_code:" + FIXTURE_ID)
    _, spans = sp.read_trace(Path(out) / "traces" / (trace_id + ".json"))
    return [span["attributes"][cv.TOOL_CALL_ID] for span in spans
            if span["attributes"].get(cv.OPERATION_NAME) == cv.EXECUTE_TOOL]


class Live:
    """A synthetic audit home whose one session grows, and the view's options."""

    def __init__(self, tmp_path):
        self.project = tmp_path / "work" / "obs_project"
        self.project.mkdir(parents=True)
        self.kb = tmp_path / "kb"
        shutil.copytree(str(KB), str(self.kb))
        self.audit = AuditHome(tmp_path / "audit_home")
        self.home = self.audit.home
        self.row = self.audit.add_session(FIXTURE_ID, self.project,
                                          started_at="2026-10-22T09:00:01.000Z",
                                          ended_at="2026-10-22T09:00:12.006Z")
        self.audit.add_transcript(self.row, _transcript(self.project, self.kb, FIRST_LINES))
        self.out = tmp_path / "view"
        self.options = {"audit_home": str(self.home), "out": str(self.out),
                        "kb_dirs": (str(self.kb),)}

    def grow(self):
        """Keep a grown copy of the session's transcript as a new row."""
        self.audit.add_transcript(self.row, _transcript(self.project, self.kb, GROWN_LINES))


@pytest.fixture
def live(tmp_path):
    return Live(tmp_path)


class Sleeper:
    """A sleep that runs one action for each call and keeps what it was asked."""

    def __init__(self, *actions):
        self.actions = list(actions)
        self.asked = []

    def __call__(self, seconds):
        self.asked.append(seconds)
        if self.actions:
            action = self.actions.pop(0)
            if action is not None:
                action()


# The fingerprint


def test_the_fingerprint_is_text_and_steady_without_a_change(live):
    first = wt.fingerprint(live.home, [str(live.kb)])
    assert isinstance(first, str) and first
    assert wt.fingerprint(live.home, [str(live.kb)]) == first


def test_the_fingerprint_changes_when_the_record_grows(live):
    before = wt.fingerprint(live.home, [str(live.kb)])
    live.grow()
    assert wt.fingerprint(live.home, [str(live.kb)]) != before


def test_the_fingerprint_changes_with_a_wal_file(live):
    before = wt.fingerprint(live.home, [])
    (live.home / "audit.sqlite-wal").write_bytes(b"x" * 32)
    with_wal = wt.fingerprint(live.home, [])
    assert with_wal != before
    (live.home / "audit.sqlite-wal").write_bytes(b"x" * 64)
    assert wt.fingerprint(live.home, []) != with_wal


def test_the_fingerprint_changes_with_a_markdown_file_in_a_kb_folder(live):
    before = wt.fingerprint(live.home, [str(live.kb)])
    entry = live.kb / "verification" / "verification-references-procedure.md"
    entry.write_text(entry.read_text(encoding="utf-8") + "\nOne more line.\n",
                     encoding="utf-8")
    changed = wt.fingerprint(live.home, [str(live.kb)])
    assert changed != before
    (live.kb / "formats" / "new-entry.md").write_text("---\nid: new-entry\n---\n",
                                                       encoding="utf-8")
    assert wt.fingerprint(live.home, [str(live.kb)]) != changed


def test_the_fingerprint_ignores_other_files_in_a_kb_folder(live):
    before = wt.fingerprint(live.home, [str(live.kb)])
    (live.kb / "formats" / "notes.txt").write_text("not an entry\n", encoding="utf-8")
    assert wt.fingerprint(live.home, [str(live.kb)]) == before


# The watch


def test_the_first_build_is_live(live):
    seen = []
    sleeper = Sleeper(lambda: seen.append(_data(live.out)["live"]))
    wt.watch(live.options, 5, cycles=1, sleep=sleeper)
    assert seen == [True]


def test_each_cycle_sleeps_for_the_interval(live):
    sleeper = Sleeper()
    wt.watch(live.options, 2, cycles=3, sleep=sleeper)
    assert sleeper.asked == [2, 2, 2]


def test_the_page_reloads_at_the_interval(live):
    seen = []
    sleeper = Sleeper(lambda: seen.append(_data(live.out)["refresh_seconds"]))
    wt.watch(live.options, 3, cycles=1, sleep=sleeper)
    assert seen == [3]


def test_a_new_transcript_row_shows_up_in_the_next_cycle(live):
    seen = []

    def look():
        seen.append((_tool_calls(live.out), _data(live.out)["live"]))

    sleeper = Sleeper(look, live.grow, look)
    summaries = wt.watch(live.options, 5, cycles=3, sleep=sleeper)
    before, after = seen
    assert len(before[0]) == 4
    assert after[0] == before[0] + ["toolu_obs_05_bash"]
    assert after[1] is True
    # The first build, the rebuild after the change, and the last build.
    assert len(summaries) == 3
    assert all(summary["traces"] == 1 for summary in summaries)


def test_a_cycle_with_no_change_does_not_rebuild(live):
    stamps = []

    def look():
        data = live.out / "data.js"
        stamps.append((data.stat().st_mtime_ns, _data(live.out)["built_at"]))

    sleeper = Sleeper(look, look, look)
    summaries = wt.watch(live.options, 5, cycles=3, sleep=sleeper)
    assert len(set(stamps)) == 1
    assert len(summaries) == 2


def test_a_kb_change_rebuilds(live):
    def change():
        (live.kb / "formats" / "new-entry.md").write_text(
            "---\nid: new-entry\ntitle: A new entry\ngroup: formats\n---\n",
            encoding="utf-8")

    seen = []
    sleeper = Sleeper(change, lambda: seen.append(
        [entry["id"] for entry in _data(live.out)["kb_entries"]]))
    summaries = wt.watch(live.options, 5, cycles=2, sleep=sleeper)
    assert "new-entry" in seen[0]
    assert len(summaries) == 3


def test_the_last_build_writes_live_false(live):
    summaries = wt.watch(live.options, 5, cycles=2, sleep=Sleeper())
    assert _data(live.out)["live"] is False
    assert summaries[-1]["out"] == str(live.out)


def test_no_cycles_still_build_live_then_not_live(live):
    sleeper = Sleeper()
    summaries = wt.watch(live.options, 5, cycles=0, sleep=sleeper)
    assert sleeper.asked == []
    assert len(summaries) == 2
    assert _data(live.out)["live"] is False


def test_an_interrupt_writes_live_false(live):
    def interrupt():
        raise KeyboardInterrupt

    sleeper = Sleeper(None, interrupt)
    summaries = wt.watch(live.options, 5, sleep=sleeper)
    assert len(sleeper.asked) == 2
    assert len(summaries) == 2
    assert _data(live.out)["live"] is False


def test_the_watch_leaves_the_record_unchanged(live):
    before = live.audit.digest()
    wt.watch(live.options, 5, cycles=2, sleep=Sleeper())
    assert live.audit.digest() == before


# The command


def _interrupted_watch(calls):
    real = wt.watch

    def run(options, interval, cycles=None, sleep=None):
        calls.append((dict(options), interval))

        def stop(seconds):
            raise KeyboardInterrupt

        return real(options, interval, cycles=cycles, sleep=stop)

    return run


def test_the_watch_command_takes_the_build_options_and_an_interval(live, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(wt, "watch", _interrupted_watch(calls))
    code = cli.main(["watch", "--audit-home", str(live.home), "--out", str(live.out),
                     "--kb-dir", str(live.kb), "--kb-server", "pipeline-kb",
                     "--project", str(live.project), "--interval", "2"])
    assert code == 0
    [(options, interval)] = calls
    assert interval == 2
    assert options["audit_home"] == str(live.home)
    assert options["out"] == str(live.out)
    assert tuple(options["kb_dirs"]) == (str(live.kb),)
    assert tuple(options["kb_servers"]) == ("pipeline-kb",)
    assert options["project"] == str(live.project)
    printed = capsys.readouterr().out.splitlines()
    assert printed == ["watching, the view is in %s, checked every 2 seconds" % live.out,
                       "%s, 1 trace" % live.out]
    assert _data(live.out)["live"] is False


def test_the_watch_interval_defaults_to_five_seconds(live, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(wt, "watch", _interrupted_watch(calls))
    assert cli.main(["watch", "--audit-home", str(live.home), "--out", str(live.out)]) == 0
    [(options, interval)] = calls
    assert interval == 5
    assert tuple(options["kb_servers"]) == ("pipeline-kb", "workflow-kb")


def test_a_missing_audit_record_fails_the_watch_command(tmp_path, capsys):
    code = cli.main(["watch", "--audit-home", str(tmp_path / "nothing"),
                     "--out", str(tmp_path / "view")])
    assert code == 1
    assert "there is no audit record" in capsys.readouterr().err
    assert not (tmp_path / "view").exists()


# Verification runs (step E13)

RUN_FIXTURE = TESTS / "fixtures" / "vg_run"


def _add_run(folder, name):
    target = Path(folder) / name
    shutil.copytree(str(RUN_FIXTURE), str(target))
    return target


def _run_ids(out):
    return sorted(row["session_id"] for row in _data(out)["traces"]
                  if row["source"] == "vg.py")


def test_the_fingerprint_changes_when_a_run_is_added(live, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    before = wt.fingerprint(live.home, [], [str(runs)])
    assert wt.fingerprint(live.home, [], [str(runs)]) == before
    _add_run(runs, "run_a")
    assert wt.fingerprint(live.home, [], [str(runs)]) != before


def test_the_fingerprint_changes_when_a_trail_grows(live, tmp_path):
    run = _add_run(tmp_path, "run_a")
    before = wt.fingerprint(live.home, [], [str(run)])
    with open(str(run / "trail.jsonl"), "a", encoding="utf-8") as handle:
        handle.write('{"at": "2026-10-29T03:30:50-07:00", "event": "run_stopped"}\n')
    assert wt.fingerprint(live.home, [], [str(run)]) != before


def test_the_fingerprint_changes_when_a_manifest_changes(live, tmp_path):
    run = _add_run(tmp_path, "run_a")
    before = wt.fingerprint(live.home, [], [str(run)])
    manifest = run / "manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert wt.fingerprint(live.home, [], [str(run)]) != before


def test_the_fingerprint_ignores_other_files_of_a_run(live, tmp_path):
    run = _add_run(tmp_path, "run_a")
    before = wt.fingerprint(live.home, [], [str(run)])
    (run / "notes.txt").write_text("not read\n", encoding="utf-8")
    assert wt.fingerprint(live.home, [], [str(run)]) == before


def test_without_runs_the_fingerprint_is_as_before(live):
    assert wt.fingerprint(live.home, [str(live.kb)], ()) == wt.fingerprint(
        live.home, [str(live.kb)])


def test_a_run_folder_added_between_cycles_appears_in_the_next_cycle(live, tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _add_run(runs, "run_a")
    options = dict(live.options, vg_runs=(str(runs),))
    seen = []

    def look():
        seen.append(_run_ids(live.out))

    sleeper = Sleeper(look, lambda: _add_run(runs, "run_b"), look)
    summaries = wt.watch(options, 5, cycles=3, sleep=sleeper)
    assert seen == [["run_a"], ["run_a", "run_b"]]
    assert len(summaries) == 3
    assert summaries[-1]["traces"] == 3


def test_the_watch_command_takes_vg_runs(live, monkeypatch, capsys, tmp_path):
    calls = []
    monkeypatch.setattr(wt, "watch", _interrupted_watch(calls))
    run = _add_run(tmp_path, "run_a")
    code = cli.main(["watch", "--audit-home", str(live.home), "--out", str(live.out),
                     "--vg-runs", str(run)])
    assert code == 0
    [(options, _)] = calls
    assert tuple(options["vg_runs"]) == (str(run),)
    assert _run_ids(live.out) == ["run_a"]
