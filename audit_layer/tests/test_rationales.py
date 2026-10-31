"""Tests for the written-out AI rationales record (Track W, step W15).

Appendix A2.5 "Prose" asks that each AI edit come with a stated reason, and
Table A5 lists the AI rationales among the records the procedures read, which
nothing wrote before. The prose procedure's rationale_coverage reads a list of
entries with an id, an anchor, a kind, and a rationale. The sessions are the
test story's synthetic Claude Code session file, whose folder token
{{PROJECT}} is replaced with a temporary folder, and short sessions made up
here in the same format. Each is captured into an audit store in a temporary
folder. No real session file is read, and nothing here calls a model or the
network. Run from the repository root with python3 -m pytest -q audit_layer/tests.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_file, claude_code  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.records.rationales import (  # noqa: E402
    rationales,
    sentence_changes,
    stated_reasons,
    write_rationales,
)
from audit_layer.records.session_index import public_id  # noqa: E402
from audit_layer.store import add_row, open_store  # noqa: E402

STORY = ROOT / "examples" / "test_story"
STORY_SESSION = STORY / "sessions" / "claude_code" / "story_session.jsonl"
EXPECTED = STORY / "prose" / "expected_rationales.yaml"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
FIRST_ID = "4a1c0418-1b2d-4e3f-8a4b-c5d6e7f8a901"
SECOND_ID = "6b2d0419-2c3e-4f40-9b5c-d6e7f8a9b012"

NO_FOLDERS = {"excluded_folders": []}
FIELDS = ["id", "anchor", "kind", "rationale", "session", "session_ref"]

OLD = "Retention is a matter of fit. Volunteers stay when the tasks suit them."


def expected():
    return yaml.safe_load(EXPECTED.read_text(encoding="utf-8"))


def lines_of(folder, cut=None):
    """The story session's records as lines of text, run in folder.

    cut keeps only that many records, for a session that has not yet grown.
    """
    text = STORY_SESSION.read_text(encoding="utf-8").replace(TOKEN, json.dumps(str(folder))[1:-1])
    lines = [line for line in text.split("\n") if line]
    return lines if cut is None else lines[:cut]


def records_to_lines(folder, records, session_id, day="2026-10-23"):
    """Records given as (type, content) in the Claude Code format, run in folder."""
    out = []
    for number, (kind, content) in enumerate(records, start=1):
        record = {
            "parentUuid": out[-1]["uuid"] if out else None,
            "isSidechain": False,
            "cwd": str(folder),
            "sessionId": session_id,
            "type": kind,
            "uuid": "{}-0000-4000-8000-{:012d}".format(session_id[:8], number),
            "timestamp": "{}T09:00:{:02d}.000Z".format(day, number),
        }
        if kind == "system":
            record["content"] = content
        else:
            record["message"] = {"role": kind, "content": content}
        out.append(record)
    return [json.dumps(record) for record in out]


def text(words):
    return {"type": "text", "text": words}


def thinking(words):
    return {"type": "thinking", "thinking": words, "signature": "sig"}


def use(call_id, name="Edit", given=None):
    return {"type": "tool_use", "id": call_id, "name": name, "input": given or {}}


def result(call_id):
    return ("user", [{"type": "tool_result", "tool_use_id": call_id, "content": "Done."}])


def edit(call_id, path, old, new):
    return use(call_id, "Edit", {"file_path": str(path), "old_string": old, "new_string": new})


def transcript(records, session_id=FIRST_ID, folder="/tmp/p"):
    return "".join(line + "\n" for line in records_to_lines(folder, records, session_id)).encode()


def parts_of(data):
    """The ordered parts the Claude Code adapter reads from a transcript's bytes (Step A4)."""
    return claude_code.parse_transcript(data).parts


def capture(store, path, lines):
    """Write the lines as a session file at path and capture it."""
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    summary = capture_file(store, path, NO_FOLDERS)
    assert not summary.excluded
    return summary


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


# The story.


def test_the_story_session_gives_the_expected_entries(tmp_path, audit, project):
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    entries = rationales(audit, project / "manuscript.md")
    assert entries == expected()
    assert all(list(entry) == FIELDS for entry in entries)


def test_the_written_file_loads_equal_to_the_expected_file_in_field_order(
    tmp_path, audit, project
):
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    out = tmp_path / "rationales.yaml"
    write_rationales(rationales(audit, project / "manuscript.md"), out)
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert loaded == expected()
    assert all(list(entry) == FIELDS for entry in loaded)


def test_capturing_a_grown_session_again_gives_the_same_entries(tmp_path, audit, project):
    path = tmp_path / "story_session.jsonl"
    # The session as it stood after its first edit, then the whole session.
    capture(audit, path, lines_of(project, cut=5))
    first = rationales(audit, project / "manuscript.md")
    assert [entry["id"] for entry in first] == ["r01"]
    capture(audit, path, lines_of(project))
    assert rationales(audit, project / "manuscript.md") == expected()
    capture(audit, path, lines_of(project))
    assert rationales(audit, project / "manuscript.md") == expected()


def test_a_project_with_no_edits_gives_an_empty_list(tmp_path, audit, project):
    out = tmp_path / "rationales.yaml"
    entries = rationales(audit, project / "manuscript.md")
    assert entries == []
    write_rationales(entries, out)
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == []


# The stated reason, read from the transcript.


def test_text_in_the_same_record_before_an_edit_counts():
    data = transcript(
        [("user", "Please edit."), ("assistant", [text("First part."), text("Second part."), use("t1")])]
    )
    assert stated_reasons(parts_of(data)) == {"t1": "First part. Second part."}


def test_text_in_its_own_record_before_an_edit_counts():
    data = transcript(
        [("user", "Please edit."), ("assistant", [text("I will edit it.")]), ("assistant", [use("t1")])]
    )
    assert stated_reasons(parts_of(data)) == {"t1": "I will edit it."}


def test_text_before_an_earlier_tool_call_does_not_carry_over():
    data = transcript(
        [
            ("user", "Please edit."),
            ("assistant", [text("I'll read it first."), use("t1", "Read")]),
            result("t1"),
            ("assistant", [use("t2")]),
        ]
    )
    assert stated_reasons(parts_of(data)) == {"t1": "I'll read it first.", "t2": ""}


def test_a_thinking_part_is_left_out():
    data = transcript(
        [("user", "Please edit."), ("assistant", [thinking("Private."), text("Adding it."), use("t1")])]
    )
    assert stated_reasons(parts_of(data)) == {"t1": "Adding it."}


def test_a_typed_prompt_clears_the_pending_text_and_results_and_system_records_do_not():
    data = transcript(
        [
            ("assistant", [text("Dropped by the prompt.")]),
            ("user", "Now add the finding."),
            ("assistant", [text("Adding the finding.")]),
            ("system", "A note from the harness."),
            result("t0"),
            ("assistant", [use("t1")]),
        ]
    )
    assert stated_reasons(parts_of(data)) == {"t1": "Adding the finding."}


def test_text_the_harness_put_in_a_user_record_clears_the_pending_text_as_a_prompt_does():
    data = transcript(
        [
            ("assistant", [text("Waiting for the report.")]),
            ("user", "<task-notification>\nThe report is done.</task-notification>"),
            ("assistant", [use("t1")]),
        ]
    )
    parts = parts_of(data)
    assert [part.role for part in parts if part.text is not None] == ["assistant", "meta"]
    assert stated_reasons(parts) == {"t1": ""}


# Which edits give entries.


def test_an_edit_with_no_text_before_it_gives_an_entry_with_an_empty_rationale(tmp_path, audit, project):
    # The record names every AI edit, so the prose procedure (version 0.3) can tell the
    # AI's change with no stated reason from the scholar's own change (Track V, step V1).
    source = project / "manuscript.md"
    records = [
        ("user", "Please edit."),
        ("assistant", [edit("t1", source, OLD, OLD + " Training helps too.")]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert rationales(audit, source) == [
        {
            "id": "r01",
            "anchor": "Training helps too.",
            "kind": "insert",
            "rationale": "",
            "session": FIRST_ID,
            "session_ref": public_id(FIRST_ID),
        }
    ]


def test_an_edit_on_another_file_gives_no_entry(tmp_path, audit, project):
    source = project / "manuscript.md"
    records = [
        ("user", "Please edit."),
        ("assistant", [text("Editing the notes."), edit("t1", project / "notes.md", OLD, OLD + " More.")]),
        result("t1"),
        ("assistant", [text("Now the manuscript."), edit("t2", source, OLD, OLD + " Training helps too.")]),
        result("t2"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert rationales(audit, source) == [
        {
            "id": "r01",
            "anchor": "Training helps too.",
            "kind": "insert",
            "rationale": "Now the manuscript.",
            "session": FIRST_ID,
            "session_ref": public_id(FIRST_ID),
        }
    ]


def test_a_write_on_the_source_gives_one_entry_of_kind_write_with_no_anchor(tmp_path, audit, project):
    # A Write gives the whole file and not what it replaced, so its changes cannot be
    # split into sentences. One entry of kind write tells the prose procedure that an AI
    # tool call rewrote the file (Track V, step V1, choice 2).
    source = project / "manuscript.md"
    records = [
        ("user", "Please write it."),
        ("assistant", [text("Writing the draft."), use("t1", "Write", {"file_path": str(source), "content": OLD})]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert rationales(audit, source) == [
        {
            "id": "r01",
            "anchor": "",
            "kind": "write",
            "rationale": "Writing the draft.",
            "session": FIRST_ID,
            "session_ref": public_id(FIRST_ID),
        }
    ]


def test_a_write_on_another_file_gives_no_entry(tmp_path, audit, project):
    source = project / "manuscript.md"
    records = [
        ("user", "Please write the notes."),
        ("assistant", [text("Writing notes."), use("t1", "Write", {"file_path": str(project / "notes.md"), "content": OLD})]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert rationales(audit, source) == []


def test_each_edit_of_a_multiedit_on_the_source_gives_its_entries(tmp_path, audit, project):
    source = project / "manuscript.md"
    given = {
        "file_path": str(source),
        "edits": [
            {"old_string": OLD, "new_string": OLD + " Training helps too."},
            {"old_string": "Pay matters less. Hours matter more.", "new_string": "Pay matters less."},
        ],
    }
    records = [
        ("user", "Please edit."),
        ("assistant", [text("Two changes at once."), use("t1", "MultiEdit", given)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    entries = rationales(audit, source)
    assert [(e["id"], e["kind"], e["anchor"], e["rationale"]) for e in entries] == [
        ("r01", "insert", "Training helps too.", "Two changes at once."),
        ("r02", "delete", "Hours matter more.", "Two changes at once."),
    ]


def test_a_multiedit_on_another_file_gives_no_entry(tmp_path, audit, project):
    source = project / "manuscript.md"
    given = {"file_path": str(project / "notes.md"),
             "edits": [{"old_string": OLD, "new_string": OLD + " More."}]}
    records = [
        ("user", "Please edit."),
        ("assistant", [text("Editing the notes."), use("t1", "MultiEdit", given)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert rationales(audit, source) == []


def test_a_relative_path_is_resolved_against_the_session_folder(tmp_path, audit, project):
    source = project / "manuscript.md"
    records = [
        ("user", "Please edit."),
        ("assistant", [text("Adding it."), edit("t1", "manuscript.md", OLD, OLD + " Training helps too.")]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert [entry["anchor"] for entry in rationales(audit, source)] == ["Training helps too."]


def test_a_word_change_inside_a_sentence_gives_an_edit_on_the_new_sentence(
    tmp_path, audit, project
):
    source = project / "manuscript.md"
    new = "Retention is a matter of fit. Volunteers stay when the tasks really suit them."
    records = [
        ("user", "Please edit."),
        ("assistant", [text("Sharpening the claim."), edit("t1", source, OLD, new)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    entries = rationales(audit, source)
    assert [(entry["kind"], entry["anchor"]) for entry in entries] == [
        ("edit", "Volunteers stay when the tasks really suit them.")
    ]


def test_a_removed_sentence_gives_a_delete_on_the_old_sentence(tmp_path, audit, project):
    source = project / "manuscript.md"
    records = [
        ("user", "Please edit."),
        ("assistant", [text("Cutting the second sentence."), edit("t1", source, OLD, "Retention is a matter of fit.")]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    entries = rationales(audit, source)
    assert [(entry["kind"], entry["anchor"]) for entry in entries] == [
        ("delete", "Volunteers stay when the tasks suit them.")
    ]
    assert entries[0]["rationale"] == "Cutting the second sentence."


def test_two_sessions_number_their_entries_in_start_order(tmp_path, audit, project):
    source = project / "manuscript.md"

    def session(session_id, day, reason, added):
        records = [
            ("user", "Please edit."),
            ("assistant", [text(reason), edit("t_" + session_id[:8], source, OLD, OLD + " " + added)]),
            result("t_" + session_id[:8]),
        ]
        return records_to_lines(project, records, session_id, day=day)

    # The later session is captured first, so the order comes from the starts.
    capture(audit, tmp_path / "later.jsonl", session(SECOND_ID, "2026-10-24", "Later.", "Training helps too."))
    capture(audit, tmp_path / "earlier.jsonl", session(FIRST_ID, "2026-10-23", "Earlier.", "Pay matters less."))
    entries = rationales(audit, source)
    assert [(entry["id"], entry["session"], entry["rationale"]) for entry in entries] == [
        ("r01", FIRST_ID, "Earlier."),
        ("r02", SECOND_ID, "Later."),
    ]


def test_a_session_from_a_harness_with_no_adapter_is_skipped_and_named(tmp_path, audit, project, capsys):
    source = project / "manuscript.md"
    provenance = {"session": "other-1", "origin": "test", "method": "by hand", "reason": "test"}
    row = add_row(
        audit,
        "sessions",
        {
            "harness": "wrappers",
            "harness_session_id": "other-1",
            "project": str(project),
            "started_at": "2026-10-20T09:00:00.000Z",
            "ended_at": "2026-10-20T09:10:00.000Z",
            "tools": ["Edit"],
        },
        provenance,
    )
    add_row(
        audit,
        "events",
        {
            "session_row_id": row,
            "ordinal": 1,
            "verb": "edited",
            "kind": "action",
            "object": str(source),
            "rationale": "",
            "role": "edited",
        },
        provenance,
    )
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    assert rationales(audit, source) == expected()
    error = capsys.readouterr().err
    assert "other-1" in error and "wrappers" in error


# The sentence changes.


def test_sentence_changes_follow_the_new_order_then_the_deletes():
    old = "Alpha one two three. Beta stays here today. Gamma goes away now."
    new = "Delta is new here. Beta stays here today. Alpha one two three four."
    assert sentence_changes(old, new) == [
        ("insert", "Delta is new here."),
        ("edit", "Alpha one two three four."),
        ("delete", "Gamma goes away now."),
    ]


def test_sentence_changes_skip_headings_and_front_matter_and_compare_normalized():
    old = "---\ntitle: x\n---\n## Results\n\nIt’s “fit”  that matters."
    new = "# Findings\n\nit's \"fit\" that matters."
    assert sentence_changes(old, new) == []


def test_a_sentence_ending_inside_a_closing_quote_ends_there():
    old = 'They said "stay." Then they left.'
    new = 'They said "stay." Then they returned. Few left.'
    assert sentence_changes(old, new) == [
        ("edit", "Then they returned."),
        ("insert", "Few left."),
    ]


# The command line.


def test_the_write_out_command_writes_the_record(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    path = tmp_path / "story_session.jsonl"
    path.write_bytes("".join(line + "\n" for line in lines_of(project)).encode("utf-8"))
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(path)]) == 0
    capsys.readouterr()
    out = tmp_path / "rationales.yaml"
    argv = ["write-out", "rationales", "--home", str(home), "--project", str(project)]
    assert main(argv + ["--source", "manuscript.md", "--out", str(out)]) == 0
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == expected()
    printed = capsys.readouterr().out
    assert str(out) in printed and "2 rationales" in printed


def test_write_out_runs_as_a_module_with_the_audit_home_from_the_environment(tmp_path, project):
    home = tmp_path / "audit_home"
    store = open_store(home)
    try:
        capture(store, tmp_path / "story_session.jsonl", lines_of(project))
    finally:
        store.db.close()
    done = subprocess.run(
        [sys.executable, "-m", "audit_layer", "write-out", "rationales",
         "--project", "project", "--source", "manuscript.md", "--out", "out.yaml"],
        cwd=str(tmp_path), capture_output=True, text=True,
        env=dict(os.environ, AUDIT_HOME=str(home), PYTHONPATH=str(ROOT)))
    assert done.returncode == 0, done.stderr
    assert yaml.safe_load((tmp_path / "out.yaml").read_text(encoding="utf-8")) == expected()


def test_write_out_refuses_without_an_audit_store(tmp_path, project, capsys):
    home = tmp_path / "no_home"
    out = tmp_path / "out.yaml"
    argv = ["write-out", "rationales", "--home", str(home), "--project", str(project)]
    assert main(argv + ["--source", "manuscript.md", "--out", str(out)]) == 1
    assert "there is no audit store" in capsys.readouterr().err
    assert not out.exists() and not home.exists()


def test_write_out_names_an_out_file_it_cannot_write(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    out = tmp_path / "missing_folder" / "out.yaml"
    argv = ["write-out", "rationales", "--home", str(home), "--project", str(project)]
    assert main(argv + ["--source", "manuscript.md", "--out", str(out)]) == 1
    assert "could not write out the rationales" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--source", "m.md", "--out", "x.yaml"],
        ["--project", "p", "--out", "x.yaml"],
        ["--project", "p", "--source", "m.md"],
    ],
    ids=["no project", "no source", "no out file"],
)
def test_write_out_needs_a_project_a_source_and_an_out_file(arguments):
    with pytest.raises(SystemExit) as raised:
        main(["write-out", "rationales"] + arguments)
    assert raised.value.code == 2
