"""Tests for the written-out record of the AI's file edits (Track V, step V2).

The data procedure's final-numbers report shows each AI change to a pipeline
script with its text before and after and the AI's stated reason, and lists
each parameter the AI set in params.yaml (Track V, choices 2 and 3). It reads a
list of entries with an id, a path, a kind, the text before and after, a
rationale, and the session. The sessions are short Claude Code sessions made
up here in the harness's format and captured into an audit store in a
temporary folder. No real session file is read, and nothing here calls a model
or the network. Run from the repository root with python3 -m pytest -q
audit_layer/tests.
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

from audit_layer.capture import capture_file  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.records.file_edits import file_edits, write_file_edits  # noqa: E402
from audit_layer.records.session_index import public_id  # noqa: E402
from audit_layer.store import add_row, open_store  # noqa: E402

FIRST_ID = "7c3e0420-3d4f-4a51-8c6d-e7f8a9b0c123"
SECOND_ID = "8d4f0421-4e50-4b62-9d7e-f8a9b0c1d234"
NO_FOLDERS = {"excluded_folders": []}
FIELDS = ["id", "path", "kind", "before", "after", "rationale", "session", "session_ref"]

OLD_CODE = 'return [r for r in rows if r["income"].strip() != ""]'
NEW_CODE = 'return [r for r in rows if r["age"].strip() != ""]'


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
        record["message"] = {"role": kind, "content": content}
        out.append(record)
    return [json.dumps(record) for record in out]


def text(words):
    return {"type": "text", "text": words}


def use(call_id, name, given):
    return {"type": "tool_use", "id": call_id, "name": name, "input": given}


def result(call_id):
    return ("user", [{"type": "tool_result", "tool_use_id": call_id, "content": "Done."}])


def edit(call_id, path, old, new):
    return use(call_id, "Edit", {"file_path": str(path), "old_string": old, "new_string": new})


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


def test_an_edit_on_a_script_gives_its_text_before_and_after_and_its_stated_reason(
    tmp_path, audit, project
):
    records = [
        ("user", "Please fix the cleaning step."),
        ("assistant", [text("Drop the rows with no age."), edit("t1", project / "s1_clean.py", OLD_CODE, NEW_CODE)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    entries = file_edits(audit, project)
    assert entries == [
        {
            "id": "e01",
            "path": "s1_clean.py",
            "kind": "edit",
            "before": OLD_CODE,
            "after": NEW_CODE,
            "rationale": "Drop the rows with no age.",
            "session": FIRST_ID,
            "session_ref": public_id(FIRST_ID),
        }
    ]
    assert all(list(entry) == FIELDS for entry in entries)


def test_an_edit_with_no_text_before_it_gives_an_empty_rationale(tmp_path, audit, project):
    records = [
        ("user", "Please fix the cleaning step."),
        ("assistant", [edit("t1", project / "s1_clean.py", OLD_CODE, NEW_CODE)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert [entry["rationale"] for entry in file_edits(audit, project)] == [""]


def test_each_edit_of_a_multiedit_gives_its_own_entry(tmp_path, audit, project):
    given = {
        "file_path": str(project / "params.yaml"),
        "edits": [
            {"old_string": "fig_width: 480", "new_string": "fig_width: 520"},
            {"old_string": "alpha: 0.05", "new_string": "alpha: 0.10"},
        ],
    }
    records = [
        ("user", "Please change the settings."),
        ("assistant", [text("Two settings at once."), use("t1", "MultiEdit", given)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    entries = file_edits(audit, project)
    assert [(e["id"], e["path"], e["kind"], e["before"], e["after"], e["rationale"]) for e in entries] == [
        ("e01", "params.yaml", "edit", "fig_width: 480", "fig_width: 520", "Two settings at once."),
        ("e02", "params.yaml", "edit", "alpha: 0.05", "alpha: 0.10", "Two settings at once."),
    ]


def test_a_write_gives_one_entry_of_kind_write_with_the_whole_file_after(tmp_path, audit, project):
    content = "min_age: 18\nalpha: 0.05\n"
    records = [
        ("user", "Please write the settings."),
        ("assistant", [text("Writing the settings."),
                       use("t1", "Write", {"file_path": str(project / "params.yaml"), "content": content})]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    entries = file_edits(audit, project)
    assert [(e["kind"], e["before"], e["after"], e["rationale"]) for e in entries] == [
        ("write", "", content, "Writing the settings.")
    ]


def test_a_relative_path_is_resolved_against_the_session_folder(tmp_path, audit, project):
    records = [
        ("user", "Please fix it."),
        ("assistant", [text("Fixing it."), edit("t1", "s1_clean.py", OLD_CODE, NEW_CODE)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert [entry["path"] for entry in file_edits(audit, project)] == ["s1_clean.py"]


def test_a_file_in_a_subfolder_is_named_with_forward_slashes(tmp_path, audit, project):
    (project / "code").mkdir()
    records = [
        ("user", "Please fix it."),
        ("assistant", [text("Fixing it."), edit("t1", project / "code" / "s1_clean.py", OLD_CODE, NEW_CODE)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    assert [entry["path"] for entry in file_edits(audit, project)] == ["code/s1_clean.py"]


def test_an_edit_outside_the_project_gives_no_entry(tmp_path, audit, project):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    records = [
        ("user", "Please fix it."),
        ("assistant", [text("Fixing it."), edit("t1", elsewhere / "s1_clean.py", OLD_CODE, NEW_CODE)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(elsewhere, records, FIRST_ID))
    assert file_edits(audit, project) == []


def test_a_session_run_elsewhere_that_edits_the_project_is_included(tmp_path, audit, project):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    records = [
        ("user", "Please fix it."),
        ("assistant", [text("Fixing it."), edit("t1", project / "s1_clean.py", OLD_CODE, NEW_CODE)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(elsewhere, records, FIRST_ID))
    assert [entry["path"] for entry in file_edits(audit, project)] == ["s1_clean.py"]


def test_two_sessions_number_their_entries_in_start_order(tmp_path, audit, project):
    def session(session_id, day, reason):
        records = [
            ("user", "Please fix it."),
            ("assistant", [text(reason), edit("t_" + session_id[:8], project / "s1_clean.py", OLD_CODE, NEW_CODE)]),
            result("t_" + session_id[:8]),
        ]
        return records_to_lines(project, records, session_id, day=day)

    capture(audit, tmp_path / "later.jsonl", session(SECOND_ID, "2026-10-24", "Later."))
    capture(audit, tmp_path / "earlier.jsonl", session(FIRST_ID, "2026-10-23", "Earlier."))
    entries = file_edits(audit, project)
    assert [(e["id"], e["session"], e["rationale"]) for e in entries] == [
        ("e01", FIRST_ID, "Earlier."),
        ("e02", SECOND_ID, "Later."),
    ]


def test_a_session_from_a_harness_without_the_ai_flag_is_skipped_and_named(
    tmp_path, audit, project, capsys
):
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
            "object": str(project / "s1_clean.py"),
            "rationale": "",
            "role": "edited",
        },
        provenance,
    )
    assert file_edits(audit, project) == []
    error = capsys.readouterr().err
    assert "other-1" in error and "wrappers" in error


def test_the_written_file_loads_equal_in_field_order_and_keeps_code_exactly(tmp_path, audit, project):
    old = "def f(x):\n    return x  \n"
    new = "def f(x):\n    # tabs\tand trailing spaces stay\n    return 2 * x\n"
    records = [
        ("user", "Please fix it."),
        ("assistant", [text("Double it."), edit("t1", project / "s2.py", old, new)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    entries = file_edits(audit, project)
    out = tmp_path / "file_edits.yaml"
    write_file_edits(entries, out)
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert loaded == entries
    assert all(list(entry) == FIELDS for entry in loaded)
    assert loaded[0]["before"] == old and loaded[0]["after"] == new


def test_a_project_with_no_edits_gives_an_empty_list(tmp_path, audit, project):
    out = tmp_path / "file_edits.yaml"
    entries = file_edits(audit, project)
    assert entries == []
    write_file_edits(entries, out)
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == []


def test_no_entry_names_an_absolute_path(tmp_path, audit, project):
    records = [
        ("user", "Please fix it."),
        ("assistant", [text("Fixing it."), edit("t1", project / "s1_clean.py", OLD_CODE, NEW_CODE)]),
        result("t1"),
    ]
    capture(audit, tmp_path / "s.jsonl", records_to_lines(project, records, FIRST_ID))
    out = tmp_path / "file_edits.yaml"
    write_file_edits(file_edits(audit, project), out)
    assert str(tmp_path) not in out.read_text(encoding="utf-8")


# The command line (Track V, step V4). python3 -m audit_layer write-out file-edits
# --project DIR --out FILE writes the record as the data handoff and procedure read it.


def story_lines(project):
    """A session that edits a script and writes the settings, with a stated reason for each."""
    records = [
        ("user", "Please fix the cleaning step and write the settings."),
        ("assistant", [text("Drop the rows with no age."),
                       edit("t1", project / "s1_clean.py", OLD_CODE, NEW_CODE)]),
        result("t1"),
        ("assistant", [use("t2", "Write", {"file_path": str(project / "params.yaml"),
                                           "content": "min_age: 18\n"})]),
        result("t2"),
    ]
    return records_to_lines(project, records, FIRST_ID)


def test_the_write_out_command_writes_the_record_the_library_gives(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    path = tmp_path / "s.jsonl"
    path.write_bytes("".join(line + "\n" for line in story_lines(project)).encode("utf-8"))
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(path)]) == 0
    capsys.readouterr()
    out = tmp_path / "file_edits.yaml"
    argv = ["write-out", "file-edits", "--home", str(home), "--project", str(project), "--out", str(out)]
    assert main(argv) == 0
    loaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert [(e["id"], e["path"], e["kind"], e["rationale"]) for e in loaded] == [
        ("e01", "s1_clean.py", "edit", "Drop the rows with no age."),
        ("e02", "params.yaml", "write", ""),
    ]
    assert all(list(entry) == FIELDS for entry in loaded)
    store = open_store(home)
    try:
        assert loaded == file_edits(store, project)
    finally:
        store.db.close()
    printed = capsys.readouterr().out
    assert str(out) in printed and "2 file edits" in printed


def test_the_write_out_command_runs_as_a_module_with_the_audit_home_from_the_environment(
    tmp_path, project
):
    home = tmp_path / "audit_home"
    store = open_store(home)
    try:
        capture(store, tmp_path / "s.jsonl", story_lines(project))
    finally:
        store.db.close()
    done = subprocess.run(
        [sys.executable, "-m", "audit_layer", "write-out", "file-edits",
         "--project", "project", "--out", "out.yaml"],
        cwd=str(tmp_path), capture_output=True, text=True,
        env=dict(os.environ, AUDIT_HOME=str(home), PYTHONPATH=str(ROOT)))
    assert done.returncode == 0, done.stderr
    loaded = yaml.safe_load((tmp_path / "out.yaml").read_text(encoding="utf-8"))
    assert [entry["path"] for entry in loaded] == ["s1_clean.py", "params.yaml"]


def test_the_write_out_command_writes_an_empty_list_for_a_project_with_no_ai_edits(
    tmp_path, project, capsys
):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    out = tmp_path / "file_edits.yaml"
    argv = ["write-out", "file-edits", "--home", str(home), "--project", str(project), "--out", str(out)]
    assert main(argv) == 0
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == []
    assert "0 file edits" in capsys.readouterr().out


def test_the_write_out_command_refuses_without_an_audit_store(tmp_path, project, capsys):
    home = tmp_path / "no_home"
    out = tmp_path / "out.yaml"
    argv = ["write-out", "file-edits", "--home", str(home), "--project", str(project), "--out", str(out)]
    assert main(argv) == 1
    assert "there is no audit store" in capsys.readouterr().err
    assert not out.exists() and not home.exists()


def test_the_write_out_command_names_an_out_file_it_cannot_write(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    out = tmp_path / "missing_folder" / "out.yaml"
    argv = ["write-out", "file-edits", "--home", str(home), "--project", str(project), "--out", str(out)]
    assert main(argv) == 1
    assert "could not write out the file edits" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments", [["--out", "x.yaml"], ["--project", "p"]], ids=["no project", "no out file"]
)
def test_the_write_out_command_needs_a_project_and_an_out_file(arguments):
    with pytest.raises(SystemExit) as raised:
        main(["write-out", "file-edits"] + arguments)
    assert raised.value.code == 2
