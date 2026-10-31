"""The git wrapper written as a procedural graph (graphs/wrap_git.yaml).

The wrapper's own program appends one line to calls.jsonl after each git
command returns. The graph turns those lines into events in the audit layer's
event schema. The clean fixture holds five calls made in the test story's
project, under a synthetic working folder, and the seeded fixture adds three
bad lines named in its truth.yaml.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
FIX = ROOT / "fixtures" / "wrap_git"
GRAPH = "graphs/wrap_git.yaml"
FOLDER = "/scholar/test_story/project"
# The slice's event fields, in the slice's order.
FIELDS = ("harness", "harness_session_id", "source_id", "verb", "kind", "object", "rationale", "role")


def vg(*args):
    return subprocess.run(VG + list(args), cwd=ROOT, capture_output=True, text=True)


def run_on(tmp_path, inputs):
    run = tmp_path / "run"
    p = vg("run", GRAPH, "--run", str(run), "--inputs", str(inputs))
    assert p.returncode == 0, p.stdout + p.stderr
    return run


def run_lines(tmp_path, lines):
    """Run the graph on a calls.jsonl made of the given lines (objects or text)."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    text = "".join((line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines)
    (inputs / "calls.jsonl").write_text(text, encoding="utf-8")
    return run_on(tmp_path, inputs)


def read(run, name):
    return json.loads((run / "files" / name).read_text(encoding="utf-8"))


def problems(run):
    return [f for f in read(run, "findings.json") if f["severity"] in ("blocking", "warning")]


def session_id(date, folder):
    key = hashlib.sha256(os.path.realpath(folder).encode("utf-8")).hexdigest()[:12]
    return "{}_{}".format(date, key)


def call(n, argv, exit_code=0, cwd=FOLDER, started="2026-10-20T09:00:00-07:00"):
    return {"id": "call-{:04d}".format(n), "argv": argv, "cwd": cwd, "started_at": started,
            "ended_at": started, "exit_code": exit_code}


# ---------------------------------------------------------------- the graph

def test_graph_passes_check():
    p = vg("check", GRAPH)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.startswith("OK: 3 nodes")


def test_graph_names_its_stream_title_trigger_and_steps():
    import yaml
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert graph["stream"] == "wrap_git"
    assert graph["version"] == 0.1
    assert graph["title"] == "The git wrapper, written as a procedural graph"
    assert len(graph["triggers"]) == 1 and graph["triggers"][0].endswith(".")
    assert (graph["entry"], graph["exit"]) == ("read_calls", "report")
    assert [n["id"] for n in graph["nodes"]] == ["read_calls", "to_events", "report"]
    assert all(n["kind"] == "tool" for n in graph["nodes"])
    assert [(e["from"], e["rel"], e["to"]) for e in graph["edges"]] == [
        ("read_calls", "LEADS_TO", "to_events"), ("to_events", "CONVERGES_TO", "report")]
    pitfalls = " ".join(p for e in graph["edges"] for p in e["pitfalls"]).lower()
    for words in ("failed command", "blocker", "file contents", "rerun", "excluded folder"):
        assert words in pitfalls, words


# ---------------------------------------------------------------- the clean calls

def test_clean_calls_give_five_events_in_order(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    events = read(run, "events.json")
    sid = session_id("2026-10-20", FOLDER)
    assert events == [
        {"harness": "wrappers", "harness_session_id": sid, "source_id": "call-0001",
         "verb": "searched", "kind": "observation", "object": "git status", "rationale": "", "role": ""},
        {"harness": "wrappers", "harness_session_id": sid, "source_id": "call-0002",
         "verb": "ran", "kind": "action", "object": "git add manuscript.md refs.bib", "rationale": "",
         "role": ""},
        {"harness": "wrappers", "harness_session_id": sid, "source_id": "call-0003",
         "verb": "committed", "kind": "action", "object": "git commit -m Add the results paragraph",
         "rationale": "Add the results paragraph", "role": ""},
        {"harness": "wrappers", "harness_session_id": sid, "source_id": "call-0004",
         "verb": "searched", "kind": "observation",
         "object": "git -C /scholar/test_story/project log --oneline", "rationale": "", "role": ""},
        {"harness": "wrappers", "harness_session_id": sid, "source_id": "call-0005",
         "verb": "ran", "kind": "blocker", "object": "git push", "rationale": "exit 128", "role": ""},
    ]
    for event in events:
        assert tuple(sorted(event)) == tuple(sorted(FIELDS))
    assert problems(run) == []


def test_session_id_is_the_date_and_the_folder_key(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    sid = read(run, "events.json")[0]["harness_session_id"]
    assert re.fullmatch(r"2026-10-20_[0-9a-f]{12}", sid)
    expected = hashlib.sha256(os.path.realpath(FOLDER).encode("utf-8")).hexdigest()[:12]
    assert sid.endswith("_" + expected)


def test_clean_calls_are_read_whole(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    calls = read(run, "calls.json")
    assert [c["id"] for c in calls] == ["call-0001", "call-0002", "call-0003", "call-0004", "call-0005"]
    assert calls[4] == {"id": "call-0005", "argv": ["git", "push"], "cwd": FOLDER,
                        "started_at": "2026-10-20T09:04:00-07:00",
                        "ended_at": "2026-10-20T09:04:03-07:00", "exit_code": 128}
    assert read(run, "findings_read_calls.json") == []


def test_report_counts_and_lists_the_events(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    notes = [f for f in read(run, "findings.json") if f["severity"] == "info"]
    assert len(notes) == 1
    message = notes[0]["message"]
    assert notes[0]["check"] == "report"
    assert "5 calls" in message and "5 events" in message
    for words in ("committed 1", "ran 2", "searched 2", "action 2", "observation 2", "blocker 1"):
        assert words in message, words
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    for heading in ("## Summary", "## Problems", "## Events"):
        assert heading in report
    assert "| Source id | Verb | Kind | Object |" in report
    assert "| call-0005 | ran | blocker | git push |" in report


# ---------------------------------------------------------------- the seeded calls

def test_seeded_calls_score_recall_one(tmp_path):
    run = run_on(tmp_path, FIX / "seeded")
    p = vg("score", "--run", str(run), "--truth", str(FIX / "seeded" / "truth.yaml"))
    assert p.returncode == 0, p.stdout + p.stderr
    score = json.loads((run / "score.json").read_text(encoding="utf-8"))
    assert score["recall"] == 1.0
    assert score["extra_findings"] == []


def test_seeded_bad_lines_give_no_event(tmp_path):
    run = run_on(tmp_path, FIX / "seeded")
    events = read(run, "events.json")
    assert [e["source_id"] for e in events] == ["call-0001", "call-0002", "call-0003", "call-0004",
                                               "call-0005"]
    # The first call-0002 is kept, and the repeat (a reset) gives no event.
    assert events[1]["object"] == "git add manuscript.md refs.bib"
    assert not any("stash" in e["object"] or "reset" in e["object"] or e["object"].startswith("ls")
                   for e in events)
    found = problems(run)
    assert sorted(f["item"] for f in found) == ["call-0002", "line 3", "line 7"]
    assert all(f["severity"] == "warning" and f["check"] == "read_calls" for f in found)


def test_empty_call_file_gives_no_event_and_no_problem(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "calls.jsonl").write_text("", encoding="utf-8")
    run = run_on(tmp_path, inputs)
    assert read(run, "calls.json") == []
    assert read(run, "events.json") == []
    assert problems(run) == []


# ---------------------------------------------------------------- reading calls

def test_calls_are_sorted_by_start_then_id(tmp_path):
    run = run_lines(tmp_path, [
        call(3, ["git", "status"], started="2026-10-20T10:00:00-07:00"),
        call(2, ["git", "status"], started="2026-10-20T09:00:00-07:00"),
        call(1, ["git", "status"], started="2026-10-20T10:00:00-07:00"),
    ])
    assert [e["source_id"] for e in read(run, "events.json")] == ["call-0002", "call-0001", "call-0003"]


def test_each_malformed_field_is_a_warning_on_its_line(tmp_path):
    good = call(1, ["git", "status"])
    lines = [
        "[1, 2]",                                  # not an object
        dict(good, id=""),                         # empty id
        dict(good, id=7),                          # id not text
        dict(good, argv="git status"),             # argv not a list
        dict(good, argv=["git", 3]),               # argv holds a number
        dict(good, argv=[]),                       # argv empty
        dict(good, cwd=None),                      # cwd not text
        {k: v for k, v in good.items() if k != "started_at"},
        dict(good, ended_at=5),                    # ended_at not text
        dict(good, exit_code="0"),                 # exit code not a whole number
        dict(good, exit_code=True),                # a true or false is not a whole number
        dict(good, exit_code=1.5),
        good,
    ]
    run = run_lines(tmp_path, lines)
    assert [e["source_id"] for e in read(run, "events.json")] == ["call-0001"]
    found = problems(run)
    assert sorted(f["item"] for f in found) == sorted("line {}".format(n) for n in range(1, 13))
    assert all(f["severity"] == "warning" for f in found)


# ---------------------------------------------------------------- turning calls into events

def test_subcommand_skips_options_and_the_values_of_C_and_c(tmp_path):
    run = run_lines(tmp_path, [
        call(1, ["git", "-c", "core.pager=cat", "-C", "/elsewhere", "--no-pager", "diff"]),
        call(2, ["git", "--version"]),
        call(3, ["git", "-C", "status", "commit", "-m", "x"]),
        call(4, ["git", "blame", "manuscript.md"]),
        call(5, ["git", "grep", "slope"]),
        call(6, ["git", "ls-files"]),
        call(7, ["git", "show", "HEAD"]),
        call(8, ["git", "checkout", "status"]),
    ])
    pairs = [(e["verb"], e["kind"]) for e in read(run, "events.json")]
    assert pairs == [("searched", "observation"), ("ran", "action"), ("committed", "action"),
                     ("searched", "observation"), ("searched", "observation"),
                     ("searched", "observation"), ("searched", "observation"), ("ran", "action")]


def test_commit_message_forms(tmp_path):
    run = run_lines(tmp_path, [
        call(1, ["git", "commit", "--message", "Long form"]),
        call(2, ["git", "commit", "--message=Joined form"]),
        call(3, ["git", "commit", "-mShort joined"]),
        call(4, ["git", "commit"]),
        call(5, ["git", "commit", "-m", "Nothing to commit"], exit_code=1),
    ])
    events = read(run, "events.json")
    assert [e["rationale"] for e in events] == [
        "Long form", "Joined form", "Short joined", "", "exit 1, Nothing to commit"]
    assert [e["kind"] for e in events] == ["action", "action", "action", "action", "blocker"]
    assert all(e["verb"] == "committed" for e in events)


def test_failed_search_keeps_its_verb(tmp_path):
    run = run_lines(tmp_path, [call(1, ["git", "log"], exit_code=128)])
    event = read(run, "events.json")[0]
    assert (event["verb"], event["kind"], event["rationale"]) == ("searched", "blocker", "exit 128")


def test_object_is_cut_at_200_characters(tmp_path):
    long_name = "x" * 300
    run = run_lines(tmp_path, [call(1, ["git", "add", long_name])])
    event = read(run, "events.json")[0]
    assert event["object"] == ("git add " + long_name)[:200]
    assert len(event["object"]) == 200


def test_session_id_follows_each_calls_day_and_folder(tmp_path):
    run = run_lines(tmp_path, [
        call(1, ["git", "status"], started="2026-10-20T09:00:00-07:00"),
        call(2, ["git", "status"], started="2026-10-21T09:00:00-07:00"),
        call(3, ["git", "status"], cwd="/scholar/other_project", started="2026-10-21T10:00:00-07:00"),
    ])
    ids = [e["harness_session_id"] for e in read(run, "events.json")]
    assert ids == [session_id("2026-10-20", FOLDER), session_id("2026-10-21", FOLDER),
                   session_id("2026-10-21", "/scholar/other_project")]
    assert len(set(ids)) == 3


def test_the_graph_reads_only_the_call_file(tmp_path):
    """A call names files, and the graph never opens them, so a missing file changes nothing."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    shutil.copy2(FIX / "clean" / "calls.jsonl", inputs / "calls.jsonl")
    run = run_on(tmp_path, inputs)
    assert sorted(os.listdir(run / "files")) == sorted([
        "calls.jsonl", "calls.json", "findings_read_calls.json", "events.json", "findings.json",
        "report.md"])


# ---------------------------------------------------------------- replay and layers

def test_verify_reports_replay_matches(tmp_path):
    for name in ("clean", "seeded"):
        sub = tmp_path / name
        sub.mkdir()
        run = run_on(sub, FIX / name)
        p = vg("verify", "--run", str(run))
        assert p.returncode == 0, p.stdout + p.stderr
        lines = p.stdout.strip().splitlines()
        assert len(lines) == 3
        assert all(line.endswith("replay matches") for line in lines), p.stdout


def test_no_code_imports_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(audit_layer|ospipe|vg)\b")
    files = sorted((ROOT / "implementations" / "wrap_git").glob("*.py"))
    assert [f.name for f in files] == ["read_calls.py", "report.py", "to_events.py"]
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)
