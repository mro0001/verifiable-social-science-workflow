"""Tests for the working store's snapshots (Track A, Step A16).

Appendix Table A3's Working row keeps snapshots of notes, scripts, and drafts,
with the workspace-relative path and kind of each, and Figure A4 says the
sweep also snapshots working files. Spec 0.11 "Working" says the sweep reads
the workspace and never owns it, and the decision log of 2026-08-05 keeps the
snapshots in the file store with checksum and size. Snapshots are taken of
the files a captured session produced or edited inside its project folder,
with the kind set by a fixed rule (plan choice 18). The reconciliation's
Track A section skips sessions whose adapter lacks the AI flag and adds no
other excluded-folder check.

The sessions are the test story's synthetic Claude Code session and the
subagent fixture, with the folder token replaced by a temporary copy of the
story's project folder, which the tests change. Every harness the sweep
reaches is given its root, so no default root is read. Nothing here calls a
model or the network, and every test runs with its home folder inside a
temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import audit_layer.capture.claude_code as claude_code  # noqa: E402
from audit_layer.capture.sweep import sweep  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import current_session, latest_snapshots, session_events  # noqa: E402
from audit_layer.store import current, open_store  # noqa: E402
from audit_layer.stores.working import kind_of, snapshot_session  # noqa: E402

STORY = ROOT / "examples" / "test_story"
SESSIONS = STORY / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID
ENCODED = "-encoded-project-folder"

# What the story session's Write gives source_notes.md.
SOURCE_NOTES = (
    "# Sources added in this session\n\nTwo findings were added after the sentence on fit in"
    " the Results section.\n\n- Dumont 2014, clear end dates and signing up again\n- Nakamura"
    " 2020, recognition events and exit among long-serving volunteers\n\nCheck both against the"
    " sources before the next build.\n"
)

SPINE = ["id", "created_at", "session", "origin", "method", "reason", "supersedes"]


def lines_of(source, project):
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def tool_call(lines, call_id, name, given, stamp="2026-10-21T15:00:00.000Z"):
    """Two synthetic records the session gains, one tool call and its result.

    Each copies the session's last record's keys, so a subagent's records stay
    sidechain records under its agent id.
    """
    last = json.loads(lines[-1])
    base = {key: last[key] for key in ("isSidechain", "cwd", "sessionId", "agentId") if key in last}
    call = dict(base)
    call.update(
        {
            "parentUuid": last["uuid"],
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "stand-in-model-1",
                "content": [
                    {"type": "text", "text": "One more change."},
                    {"type": "tool_use", "id": call_id, "name": name, "input": given},
                ],
            },
            "uuid": call_id + "-call",
            "timestamp": stamp,
        }
    )
    result = dict(base)
    result.update(
        {
            "parentUuid": call["uuid"],
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"tool_use_id": call_id, "type": "tool_result", "content": "done"}],
            },
            "uuid": call_id + "-result",
            "timestamp": stamp,
        }
    )
    return lines + [json.dumps(call), json.dumps(result)]


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer or a real root."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def project(tmp_path):
    """A copy of the story's project folder, with the notes file the story session wrote."""
    folder = tmp_path / "project"
    shutil.copytree(str(STORY / "project"), str(folder))
    (folder / "source_notes.md").write_text(SOURCE_NOTES, encoding="utf-8")
    return folder


@pytest.fixture
def settings(project):
    return {"excluded_folders": [str(project / "excluded_folder")]}


@pytest.fixture
def audit_home(tmp_path):
    return tmp_path / "audit_home"


@pytest.fixture
def audit(audit_home):
    store = open_store(audit_home)
    yield store
    store.db.close()


@pytest.fixture
def root(tmp_path, project):
    folder = tmp_path / "claude_root"
    write_session(folder / ENCODED / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project))
    return folder


def story_file(root):
    return root / ENCODED / (STORY_ID + ".jsonl")


def run_sweep(audit, settings, audit_home, root):
    return sweep(audit, settings, audit_home, harnesses=["claude_code"], roots={"claude_code": str(root)})


def snapshots(audit):
    return {row["path"]: row for row in current(audit, "snapshots")}


# The kind of each path.


@pytest.mark.parametrize(
    "path,kind",
    [
        ("analysis/s1.py", "script"),
        ("model.R", "script"),
        ("model.r", "script"),
        ("run.sh", "script"),
        ("fit.jl", "script"),
        ("clean.do", "script"),
        ("query.sql", "script"),
        ("report.qmd", "script"),
        ("report.Rmd", "script"),
        ("notes/reading_list.md", "note"),
        ("chapter/notes/ideas.txt", "note"),
        ("notes/outline.tex", "note"),
        ("manuscript.md", "draft"),
        ("source_notes.md", "draft"),
        ("drafts/notes.md", "draft"),
        ("paper.tex", "draft"),
        ("readme.txt", "draft"),
        ("params_record_results.csv", None),
        ("figure.png", None),
        ("Makefile", None),
        ("notes/table.csv", None),
    ],
)
def test_the_kind_of_each_path(path, kind):
    assert kind_of(path) == kind


# Sweeping the story.


def test_sweeping_the_story_snapshots_its_manuscript_and_notes_as_drafts(
    audit, settings, audit_home, root, project
):
    run_sweep(audit, settings, audit_home, root)

    taken = snapshots(audit)
    assert sorted(taken) == ["manuscript.md", "source_notes.md"]
    for path, row in taken.items():
        data = (project / path).read_bytes()
        assert row["kind"] == "draft"
        assert row["project"] == str(project)
        assert row["file_sha256"] == hashlib.sha256(data).hexdigest()
        assert row["byte_size"] == len(data)
        assert (audit.files / row["file_sha256"]).read_bytes() == data
        assert row["session"] == STORY_ID
        assert row["origin"] == "sweep"
        assert row["method"] == "working snapshot 1"
        assert row["reason"] == "snapshot"
        assert row["supersedes"] is None


def test_a_second_sweep_adds_nothing(audit, settings, audit_home, root):
    run_sweep(audit, settings, audit_home, root)
    before = stored_rows(audit.db, "snapshots")
    run_sweep(audit, settings, audit_home, root)
    assert stored_rows(audit.db, "snapshots") == before


def test_a_grown_session_and_a_changed_manuscript_add_one_snapshot_and_keep_the_first(
    audit, settings, audit_home, root, project
):
    run_sweep(audit, settings, audit_home, root)
    (first,) = [row for row in current(audit, "snapshots") if row["path"] == "manuscript.md"]
    first_bytes = (project / "manuscript.md").read_bytes()

    manuscript = project / "manuscript.md"
    manuscript.write_text(manuscript.read_text(encoding="utf-8") + "\nOne more line.\n", encoding="utf-8")
    lines = tool_call(
        lines_of(STORY_SESSION, project),
        "toolu_story_07_edit",
        "Edit",
        {"file_path": str(manuscript), "old_string": "x", "new_string": "y"},
    )
    write_session(story_file(root), lines)
    run_sweep(audit, settings, audit_home, root)

    rows = stored_rows(audit.db, "snapshots")
    assert len(rows) == 3
    assert rows[0] == first
    assert (audit.files / first["file_sha256"]).read_bytes() == first_bytes
    latest = latest_snapshots(audit, str(project))
    assert sorted(latest) == ["manuscript.md", "source_notes.md"]
    assert latest["manuscript.md"]["file_sha256"] == hashlib.sha256(manuscript.read_bytes()).hexdigest()
    assert latest["manuscript.md"]["id"] != first["id"]


def test_a_grown_session_whose_files_are_unchanged_adds_no_snapshot(
    audit, settings, audit_home, root, project
):
    run_sweep(audit, settings, audit_home, root)
    before = stored_rows(audit.db, "snapshots")
    lines = tool_call(
        lines_of(STORY_SESSION, project),
        "toolu_story_07_edit",
        "Edit",
        {"file_path": str(project / "manuscript.md"), "old_string": "x", "new_string": "x"},
    )
    write_session(story_file(root), lines)
    run_sweep(audit, settings, audit_home, root)
    assert stored_rows(audit.db, "snapshots") == before


def test_files_outside_the_project_deleted_read_only_or_of_no_kind_are_not_snapshotted(
    audit, settings, audit_home, root, project, tmp_path
):
    outside = tmp_path / "elsewhere" / "letter.md"
    outside.parent.mkdir()
    outside.write_text("Written outside the project.\n", encoding="utf-8")
    gone = project / "gone.md"
    table = project / "conditions.csv"
    table.write_text("key,n\nnone,60\n", encoding="utf-8")
    lines = lines_of(STORY_SESSION, project)
    lines = tool_call(lines, "toolu_extra_01", "Write", {"file_path": str(outside), "content": "x"})
    lines = tool_call(lines, "toolu_extra_02", "Write", {"file_path": str(gone), "content": "x"})
    lines = tool_call(lines, "toolu_extra_03", "Write", {"file_path": str(table), "content": "x"})
    lines = tool_call(lines, "toolu_extra_04", "Read", {"file_path": str(project / "top_words.md")})
    write_session(story_file(root), lines)

    run_sweep(audit, settings, audit_home, root)

    assert sorted(snapshots(audit)) == ["manuscript.md", "source_notes.md"]


def test_a_file_in_an_excluded_folder_inside_the_project_is_snapshotted_as_the_ruling_says(
    audit, settings, audit_home, root, project
):
    # Excluded folders guard only what runs inside them, and the snapshot adds
    # no check of its own (reconciliation, item 3 and the Track A section).
    inside = project / "excluded_folder" / "memo.md"
    inside.parent.mkdir()
    inside.write_text("A memo.\n", encoding="utf-8")
    lines = tool_call(
        lines_of(STORY_SESSION, project), "toolu_extra_05", "Write", {"file_path": str(inside), "content": "x"}
    )
    write_session(story_file(root), lines)
    run_sweep(audit, settings, audit_home, root)
    assert "excluded_folder/memo.md" in snapshots(audit)


def test_the_subagent_s_note_and_a_synthetic_script_are_snapshotted(
    audit, settings, audit_home, root, project
):
    (project / "notes").mkdir()
    (project / "notes" / "reading_list.md").write_text(
        "# Reading list\n\n- A guide to plain-text social science [@healy2020].\n", encoding="utf-8"
    )
    (project / "analysis").mkdir()
    (project / "analysis" / "s1.py").write_text("print('s1')\n", encoding="utf-8")
    lines = tool_call(
        lines_of(SUBAGENT, project),
        "toolu_agent_09_write",
        "Write",
        {"file_path": str(project / "analysis" / "s1.py"), "content": "print('s1')\n"},
    )
    write_session(root / ENCODED / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"), lines)

    run_sweep(audit, settings, audit_home, root)

    taken = snapshots(audit)
    assert taken["notes/reading_list.md"]["kind"] == "note"
    assert taken["notes/reading_list.md"]["session"] == SUBAGENT_ID
    assert taken["analysis/s1.py"]["kind"] == "script"
    assert taken["analysis/s1.py"]["session"] == SUBAGENT_ID
    assert taken["manuscript.md"]["session"] == STORY_ID


def test_a_session_whose_adapter_lacks_the_ai_flag_is_not_snapshotted(
    audit, settings, audit_home, root, monkeypatch
):
    monkeypatch.setattr(claude_code, "AI", False)
    run_sweep(audit, settings, audit_home, root)
    assert current_session(audit, "claude_code", STORY_ID) is not None
    assert current(audit, "snapshots") == []


def test_snapshot_session_says_what_it_kept(audit, settings, audit_home, root, project):
    run_sweep(audit, settings, audit_home, root)
    row = current_session(audit, "claude_code", STORY_ID)
    summary = snapshot_session(audit, row, session_events(audit, row))
    assert (summary.taken, summary.unchanged) == (0, 2)
    (project / "source_notes.md").write_text(SOURCE_NOTES + "One more.\n", encoding="utf-8")
    summary = snapshot_session(audit, row, session_events(audit, row))
    assert (summary.taken, summary.unchanged) == (1, 1)


def test_a_snapshot_of_the_same_bytes_under_two_paths_keeps_the_file_once(
    audit, settings, audit_home, root, project
):
    (project / "source_notes.md").write_bytes((project / "manuscript.md").read_bytes())
    run_sweep(audit, settings, audit_home, root)
    taken = snapshots(audit)
    assert taken["manuscript.md"]["file_sha256"] == taken["source_notes.md"]["file_sha256"]
    kept = [p for p in audit.files.iterdir() if p.name == taken["manuscript.md"]["file_sha256"]]
    assert len(kept) == 1


def test_the_snapshots_table_has_its_fields_and_refuses_update_and_delete(
    audit, settings, audit_home, root
):
    names = [r[1] for r in audit.db.execute("PRAGMA table_info(snapshots)")]
    assert names == ["id", "project", "path", "kind", "file_sha256", "byte_size"] + SPINE[1:]
    run_sweep(audit, settings, audit_home, root)
    with pytest.raises(sqlite3.DatabaseError, match="never updated"):
        audit.db.execute("UPDATE snapshots SET kind = 'note'")
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        audit.db.execute("DELETE FROM snapshots")


def test_latest_snapshots_of_a_project_with_none_is_empty(audit, project):
    assert latest_snapshots(audit, str(project)) == {}


def test_the_sweep_command_snapshots_too(tmp_path, root, project):
    home = tmp_path / "cli_home"
    assert main(["init", "--home", str(home)]) == 0
    code = main(["sweep", "--home", str(home), "--harness", "claude_code", "--root", f"claude_code={root}"])
    assert code == 0
    db = sqlite3.connect(str(home / "audit.sqlite"))
    rows = stored_rows(db, "snapshots")
    db.close()
    assert sorted(row["path"] for row in rows) == ["manuscript.md", "source_notes.md"]


def test_a_snapshot_that_fails_is_named_by_session_id_and_does_not_stop_the_sweep(
    audit, settings, audit_home, root, project, monkeypatch, tmp_path
):
    import audit_layer.capture.sweep as sweep_module

    def failing(store, row, events):
        raise OSError(f"cannot write {project / 'manuscript.md'}")

    monkeypatch.setattr(sweep_module, "snapshot_session", failing)
    summary = run_sweep(audit, settings, audit_home, root)
    assert summary.captured == 1
    ((name, reason),) = summary.failed
    assert name == STORY_ID
    assert reason == "its working files could not be snapshotted, OSError"
    assert str(tmp_path) not in reason


def test_the_sweep_command_prints_a_failed_snapshot_on_its_own_line_and_counts_the_session_once(
    tmp_path, root, project, monkeypatch, capsys
):
    import audit_layer.capture.sweep as sweep_module

    def failing(store, row, events):
        raise OSError(f"cannot write {project / 'manuscript.md'}")

    monkeypatch.setattr(sweep_module, "snapshot_session", failing)
    home = tmp_path / "cli_home"
    assert main(["init", "--home", str(home)]) == 0
    capsys.readouterr()
    code = main(["sweep", "--home", str(home), "--harness", "claude_code", "--root", f"claude_code={root}"])
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert out == [
        "swept 1 session, 1 captured, 0 unchanged, 0 excluded, 0 working folder unknown, 0 failed",
        f"could not snapshot {STORY_ID}, OSError",
    ]
