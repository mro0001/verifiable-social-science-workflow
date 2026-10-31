"""Tests for the written-out citation log (plan Step 6).

Appendix A2.4 writes a project's records out as files, Table A5 lists the
citation log among the records the procedures read, and Figure A6 follows the
log's entry for one AI-added citation. The sessions are the test story's
synthetic Claude Code session file, whose folder token {{PROJECT}} is replaced
with a temporary folder, and short sessions made up here in the same format.
Each is captured into an audit store in a temporary folder. No real session
file is read, and nothing here calls a model or the network. The references
procedure's own reader runs as a program of its own, so no audit layer code
imports verification code. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
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
from audit_layer.records.citation_log import (  # noqa: E402
    citation_keys,
    citation_log,
    write_citation_log,
)
from audit_layer.records.session_index import public_id  # noqa: E402
from audit_layer.store import add_row, current, open_store, supersede  # noqa: E402

STORY = ROOT / "examples" / "test_story"
STORY_SESSION = STORY / "sessions" / "claude_code" / "story_session.jsonl"
EXPECTED = STORY / "references" / "expected_citation_log.yaml"
# The folder that holds the references procedure's reader, _lib.read_yaml.
IMPLEMENTATIONS = ROOT / "verification_procedures" / "implementations"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"

# Another session made from the story. It ran a day earlier, has its own ids,
# and cites okafor2019 where the story cites nakamura2020.
OTHER_ID = "7c4e0415-3b8e-4c0f-9d72-b1e5f8c3d024"
OTHER = [
    (STORY_ID, OTHER_ID),
    ("5f3c0413-0000", "7c4e0415-0000"),
    ("toolu_story_", "toolu_other_"),
    ("2026-10-21T", "2026-10-20T"),
    ("nakamura2020", "okafor2019"),
]

# The id of the short sessions made up here.
MADE_UP_ID = "2d6a0416-8e1f-4a3b-a5c7-c9e2d4f6b135"

NO_FOLDERS = {"excluded_folders": []}

CORRECTION = {
    "session": STORY_ID,
    "origin": "test_citation_log",
    "method": "corrected by hand",
    "reason": "correction",
}

# Loads one file with the references procedure's reader, which reads the named
# file from the folder given as the program's first argument.
READER = "import json, sys, _lib; print(json.dumps(_lib.read_yaml(sys.argv[2])))"


def entry(session_id):
    """A citation log entry as the references procedure reads it."""
    return {
        "introduced_by": "ai",
        "draft": "",
        "session": session_id,
        "session_ref": public_id(session_id),
    }


# What the audit layer should write out for the story, the two keys the
# session added and none for the scholar's castellanos2017.
STORY_LOG = {"citations": {"dumont2014": entry(STORY_ID), "nakamura2020": entry(STORY_ID)}}


def lines_of(folder, changes=()):
    """The story session's records as lines of text.

    Each change is made first, then the token is replaced by folder.
    """
    text = STORY_SESSION.read_text(encoding="utf-8")
    for old, new in changes:
        text = text.replace(old, new)
    text = text.replace(TOKEN, json.dumps(str(folder))[1:-1])
    return [line for line in text.split("\n") if line]


def made_up_lines(folder, calls, session_id=MADE_UP_ID):
    """A short session in the Claude Code format, run in folder.

    Each call is a tool name and its input, and each has its result.
    """
    records = []

    def add(kind, content):
        number = len(records) + 1
        records.append(
            {
                "parentUuid": records[-1]["uuid"] if records else None,
                "isSidechain": False,
                "cwd": str(folder),
                "sessionId": session_id,
                "type": kind,
                "message": {"role": kind, "content": content},
                "uuid": "{}-0000-4000-8000-{:012d}".format(session_id[:8], number),
                "timestamp": "2026-10-22T09:00:{:02d}.000Z".format(number),
            }
        )

    add("user", "Add the findings to the manuscript.")
    for number, (name, given) in enumerate(calls, start=1):
        call_id = "toolu_{}_{:02d}".format(session_id[:8], number)
        add("assistant", [{"type": "tool_use", "id": call_id, "name": name, "input": given}])
        add("user", [{"type": "tool_result", "tool_use_id": call_id, "content": "Done."}])
    return [json.dumps(record) for record in records]


def capture(store, path, lines):
    """Write the lines as a session file at path and capture it."""
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    summary = capture_file(store, path, NO_FOLDERS)
    assert not summary.excluded
    return path


def read_as_the_references_procedure_does(path):
    """The file as _lib.read_yaml loads it, run as a program of its own."""
    done = subprocess.run(
        [sys.executable, "-c", READER, str(path.parent), path.name],
        cwd=str(IMPLEMENTATIONS),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


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
    """The folder the story session ran in."""
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def audit(tmp_path):
    store = open_store(tmp_path / "audit_home")
    yield store
    store.db.close()


# The story gives entries for the two AI-added keys with the story session's
# id, and none for the scholar's key.


def test_the_story_gives_entries_for_the_two_ai_added_keys_and_none_for_the_scholars_key(
    tmp_path, audit, project
):
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    log = citation_log(audit, project)
    assert log == STORY_LOG
    # The scholar's citation was already in the text the session edited.
    assert "castellanos2017" not in log["citations"]


# The file loads with the references procedure's own reader the same way the
# hand-written expected file does.


def test_the_written_file_loads_with_the_references_procedures_reader_like_the_expected_file(
    tmp_path, audit, project
):
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    out = tmp_path / "citation_log.yaml"
    assert write_citation_log(audit, project, out) == STORY_LOG
    loaded = read_as_the_references_procedure_does(out)
    assert loaded == read_as_the_references_procedure_does(EXPECTED)
    assert loaded == STORY_LOG


def test_a_project_with_no_recorded_session_gives_an_empty_log(tmp_path, audit, project):
    out = tmp_path / "citation_log.yaml"
    assert write_citation_log(audit, project, out) == {"citations": {}}
    assert read_as_the_references_procedure_does(out) == {"citations": {}}


def test_keys_yaml_could_misread_load_back_as_written(tmp_path, audit, project):
    content = "Fit matters [@smith-jones:2020; @2021; @yes; @null].\n"
    calls = [("Write", {"file_path": str(project / "intro.md"), "content": content})]
    capture(audit, tmp_path / "session.jsonl", made_up_lines(project, calls))
    out = tmp_path / "citation_log.yaml"
    write_citation_log(audit, project, out)
    keys = ["2021", "null", "smith-jones:2020", "yes"]
    assert read_as_the_references_procedure_does(out) == {
        "citations": {key: entry(MADE_UP_ID) for key in keys}
    }


# A session counts by the files it edited, not by the folder it ran in
# (Track L, Step L2). A session that edited only another project's files
# contributes nothing.


def beside_the_project(tmp_path):
    folder = tmp_path / "other_project"
    return folder, lines_of(folder, OTHER)


def a_folder_whose_name_starts_with_the_projects(tmp_path):
    folder = tmp_path / "project_old"
    return folder, lines_of(folder, OTHER)


ELSEWHERE = [
    beside_the_project,
    a_folder_whose_name_starts_with_the_projects,
]


@pytest.mark.parametrize("elsewhere", ELSEWHERE, ids=[f.__name__ for f in ELSEWHERE])
def test_a_session_that_edited_another_projects_files_contributes_nothing(
    tmp_path, audit, project, elsewhere
):
    folder, lines = elsewhere(tmp_path)
    folder.mkdir(exist_ok=True)
    capture(audit, tmp_path / "other_session.jsonl", lines)
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    # The other session started a day earlier, so had it counted, it would be
    # named for dumont2014 and okafor2019 would have an entry.
    assert citation_log(audit, project) == STORY_LOG
    # Asked for its own project, the other session counts.
    assert citation_log(audit, folder)["citations"]["okafor2019"] == entry(OTHER_ID)


def test_a_session_run_in_the_folder_that_holds_the_project_counts_for_its_edits(
    tmp_path, audit, project
):
    # The session ran in the folder that holds the project and edited the
    # project's manuscript.
    changes = OTHER + [(TOKEN + "/manuscript.md", TOKEN + "/project/manuscript.md")]
    capture(audit, tmp_path / "other_session.jsonl", lines_of(tmp_path, changes))
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    # The other session started a day earlier, so it is named for dumont2014.
    assert citation_log(audit, project) == {
        "citations": {
            "dumont2014": entry(OTHER_ID),
            "nakamura2020": entry(STORY_ID),
            "okafor2019": entry(OTHER_ID),
        }
    }


@pytest.mark.parametrize(
    "path",
    ["absolute", "relative", "through a link"],
)
def test_a_session_run_in_another_folder_that_edits_a_markdown_file_in_the_project_counts(
    tmp_path, audit, project, path
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "project_link"
    link.symlink_to(project, target_is_directory=True)
    paths = {
        "absolute": str(project / "intro.md"),
        # A relative path is resolved against the folder the session ran in.
        "relative": "../project/intro.md",
        "through a link": str(link / "intro.md"),
    }
    calls = [("Write", {"file_path": paths[path], "content": "Fit matters [@elsewhere2016].\n"})]
    capture(audit, tmp_path / "session.jsonl", made_up_lines(elsewhere, calls))
    assert citation_log(audit, project) == {"citations": {"elsewhere2016": entry(MADE_UP_ID)}}
    # The folder the session ran in holds no file it edited, so it gets nothing.
    assert citation_log(audit, elsewhere) == {"citations": {}}


def test_a_session_run_in_the_project_that_edits_a_file_outside_it_adds_nothing(
    tmp_path, audit, project
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    calls = [
        ("Write", {"file_path": str(elsewhere / "draft.md"), "content": "[@outside2017]\n"}),
        (
            "Edit",
            {
                "file_path": "../elsewhere/manuscript.md",
                "old_string": "A finding.",
                "new_string": "A finding [@upward2018].",
            },
        ),
    ]
    capture(audit, tmp_path / "session.jsonl", made_up_lines(project, calls))
    assert citation_log(audit, project) == {"citations": {}}
    # The files it edited lie in the other folder, so they count there.
    assert citation_log(audit, elsewhere) == {
        "citations": {"outside2017": entry(MADE_UP_ID), "upward2018": entry(MADE_UP_ID)}
    }


def test_the_write_out_command_counts_a_session_run_in_another_folder(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    calls = [("Write", {"file_path": str(project / "intro.md"), "content": "[@elsewhere2016]\n"})]
    session = tmp_path / "session.jsonl"
    session.write_bytes("".join(line + "\n" for line in made_up_lines(elsewhere, calls)).encode("utf-8"))
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(session)]) == 0
    capsys.readouterr()
    out = tmp_path / "citation_log.yaml"
    command = ["write-out", "citation-log", "--home", str(home)]
    assert main(command + ["--project", str(project), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "1 citation from 1 session" in printed
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == {
        "citations": {"elsewhere2016": entry(MADE_UP_ID)}
    }


def test_a_session_in_a_folder_inside_the_project_counts(tmp_path, audit, project):
    folder = project / "chapters"
    folder.mkdir()
    capture(audit, tmp_path / "story_session.jsonl", lines_of(folder))
    assert citation_log(audit, project) == STORY_LOG


@pytest.mark.parametrize(
    "ran_in, asked_for",
    [("link", "project"), ("project", "link")],
    ids=["the session ran through a link", "the project is given as a link"],
)
def test_the_project_is_compared_as_a_real_path(tmp_path, audit, project, ran_in, asked_for):
    link = tmp_path / "project_link"
    link.symlink_to(project, target_is_directory=True)
    folders = {"project": project, "link": link}
    capture(audit, tmp_path / "story_session.jsonl", lines_of(folders[ran_in]))
    assert citation_log(audit, folders[asked_for]) == STORY_LOG


# The first session to introduce a key is the one named.


def test_the_first_session_to_introduce_a_key_is_the_one_named(tmp_path, audit, project):
    # The story is captured first, though the other session started a day earlier.
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    capture(audit, tmp_path / "other_session.jsonl", lines_of(project, OTHER))
    assert citation_log(audit, project) == {
        "citations": {
            "dumont2014": entry(OTHER_ID),
            "nakamura2020": entry(STORY_ID),
            "okafor2019": entry(OTHER_ID),
        }
    }


# Each current session's stored transcript is read.


def test_the_latest_transcript_of_a_grown_session_is_read(tmp_path, audit, project):
    lines = lines_of(project)
    path = tmp_path / "story_session.jsonl"
    # The session so far holds the Read and the first Edit.
    capture(audit, path, lines[:5])
    assert citation_log(audit, project) == {"citations": {"dumont2014": entry(STORY_ID)}}
    capture(audit, path, lines)
    assert len(current(audit, "transcripts")) == 2
    assert citation_log(audit, project) == STORY_LOG


def test_a_superseded_session_row_is_not_read(tmp_path, audit, project):
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    row = current(audit, "sessions")[0]
    # The correction names a harness without the AI flag, so had the
    # superseded row been read, the story's two keys would have entries.
    corrected = {"harness": "wrappers"}
    supersede(audit, "sessions", row["id"], corrected, CORRECTION)
    assert citation_log(audit, project) == {"citations": {}}


def test_a_session_with_no_stored_transcript_is_named(audit, project):
    fields = {
        "harness": "claude_code",
        "harness_session_id": STORY_ID,
        "project": str(project),
        "started_at": "2026-10-21T14:02:05.112Z",
        "ended_at": "2026-10-21T14:02:46.009Z",
        "tools": ["Edit"],
    }
    add_row(audit, "sessions", fields, CORRECTION)
    with pytest.raises(ValueError, match=STORY_ID):
        citation_log(audit, project)


# A session with no stored transcript that ran outside the project is skipped
# and named on standard error, so one broken session elsewhere does not stop
# every project's write-out. One run inside the project still stops it (Track
# L, Step L7).


def lost_session(audit, folder, session_id="lost-1"):
    fields = {
        "harness": "claude_code",
        "harness_session_id": session_id,
        "project": str(folder),
        "started_at": "2026-10-19T09:00:00.000Z",
        "ended_at": "2026-10-19T09:10:00.000Z",
        "tools": ["Edit"],
    }
    add_row(audit, "sessions", fields, dict(CORRECTION, session=session_id))


def test_a_session_outside_the_project_with_no_stored_transcript_is_skipped_and_named(
    tmp_path, audit, project, capsys
):
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    lost_session(audit, elsewhere)
    capsys.readouterr()
    assert citation_log(audit, project) == STORY_LOG
    err = capsys.readouterr().err
    assert "skipped session lost-1 from harness claude_code" in err
    assert "no stored transcript" in err
    assert err.count("lost-1") == 1


def test_a_session_in_a_folder_inside_the_project_with_no_stored_transcript_still_stops_it(
    tmp_path, audit, project
):
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    inner = project / "drafts"
    inner.mkdir()
    lost_session(audit, inner)
    with pytest.raises(ValueError, match="lost-1.*no stored transcript"):
        citation_log(audit, project)


@pytest.mark.parametrize("run_from", ["elsewhere", "project"])
def test_a_session_with_no_project_folder_and_no_stored_transcript_still_stops_it(
    tmp_path, audit, project, monkeypatch, run_from
):
    # An empty project folder is unknown, so the session is not taken to have
    # run outside, wherever the write-out runs.
    capture(audit, tmp_path / "story_session.jsonl", lines_of(project))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    lost_session(audit, "")
    monkeypatch.chdir(elsewhere if run_from == "elsewhere" else project)
    with pytest.raises(ValueError, match="lost-1.*no stored transcript"):
        citation_log(audit, project)


def test_the_write_out_command_names_a_skipped_session_once(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    store = open_store(home)
    try:
        capture(store, tmp_path / "story_session.jsonl", lines_of(project))
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        lost_session(store, elsewhere)
    finally:
        store.db.close()
    capsys.readouterr()
    out = tmp_path / "citation_log.yaml"
    command = ["write-out", "citation-log", "--home", str(home)]
    assert main(command + ["--project", str(project), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert captured.err.count("skipped session lost-1") == 1
    assert "2 citations from 1 session" in captured.out
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == STORY_LOG


# Each Edit or Write on a markdown file in the project, and the keys in the
# new text that the old text did not have.


def test_an_edit_introduces_only_the_keys_its_old_text_did_not_have(tmp_path, audit, project):
    manuscript = str(project / "manuscript.md")
    calls = [
        (
            "Edit",
            {
                "file_path": manuscript,
                "old_string": "Fit matters [@kept2001].",
                "new_string": "Fit matters [@kept2001], and so does timing [@added2002].",
            },
        ),
        (
            "Edit",
            {
                "file_path": manuscript,
                "old_string": "Exit is rare [@gone2003].",
                "new_string": "Exit is rare.",
            },
        ),
        (
            "Edit",
            {
                "file_path": manuscript,
                "old_string": "[@moved2004] found the same.",
                "new_string": "The same was found [@moved2004].",
            },
        ),
    ]
    capture(audit, tmp_path / "session.jsonl", made_up_lines(project, calls))
    assert citation_log(audit, project) == {"citations": {"added2002": entry(MADE_UP_ID)}}


def test_every_key_in_a_written_file_counts(tmp_path, audit, project):
    content = "# Intro\n\nTiming matters [@first2005]. Others agree [@second2006; @third2007].\n"
    calls = [("Write", {"file_path": str(project / "intro.md"), "content": content})]
    capture(audit, tmp_path / "session.jsonl", made_up_lines(project, calls))
    keys = ["first2005", "second2006", "third2007"]
    assert citation_log(audit, project) == {"citations": {key: entry(MADE_UP_ID) for key in keys}}


def test_only_edits_and_writes_on_markdown_files_in_the_project_count(tmp_path, audit, project):
    elsewhere = tmp_path / "elsewhere"
    calls = [
        # A relative path is resolved against the folder the session ran in.
        (
            "Edit",
            {
                "file_path": "chapters/methods.md",
                "old_string": "We asked.",
                "new_string": "We asked [@relative2011].",
            },
        ),
        ("Write", {"file_path": str(project / "README.MD"), "content": "See [@capitals2014].\n"}),
        # Files that are not markdown.
        (
            "Edit",
            {
                "file_path": str(project / "refs.bib"),
                "old_string": "}\n",
                "new_string": "}\n@article{bibonly2008,\n  title = {T},\n}\n",
            },
        ),
        ("Write", {"file_path": str(project / "notes.txt"), "content": "[@textfile2009]\n"}),
        # Markdown files outside the project.
        (
            "Edit",
            {
                "file_path": str(elsewhere / "manuscript.md"),
                "old_string": "A finding.",
                "new_string": "A finding [@outside2010].",
            },
        ),
        ("Write", {"file_path": "../elsewhere/draft.md", "content": "[@upward2015]\n"}),
        # Tools that do not change a file.
        ("Read", {"file_path": str(project / "manuscript.md")}),
        ("Grep", {"pattern": "[@grep2013]", "path": str(project)}),
    ]
    capture(audit, tmp_path / "session.jsonl", made_up_lines(project, calls))
    assert citation_log(audit, project) == {
        "citations": {"capitals2014": entry(MADE_UP_ID), "relative2011": entry(MADE_UP_ID)}
    }


# The pandoc forms, [@key], [@key, p. 5], [@a; @b], and @key after a space or
# at a line start.


@pytest.mark.parametrize(
    "text, keys",
    [
        ("Fit matters [@key].", ["key"]),
        ("Fit matters [@key, p. 5].", ["key"]),
        ("Fit matters [@a; @b].", ["a", "b"]),
        ("Fit matters [@a;@b].", ["a", "b"]),
        ("@key finds that fit matters.", ["key"]),
        ("As @key finds, fit matters.", ["key"]),
        ("Fit matters.\n@key finds the same.", ["key"]),
        ("Fit matters [see @doe99, pp. 33-35; also @smith04, chap. 1].", ["doe99", "smith04"]),
        ("As @smith2020's study shows.", ["smith2020"]),
        ("Fit matters [@smith-jones:2020].", ["smith-jones:2020"]),
        ("Fit matters [@a], as before [@a].", ["a"]),
        ("Write to jo@example.org for the data.", []),
        ("No citation here.", []),
    ],
    ids=[
        "bracketed",
        "with a locator",
        "two in brackets",
        "two in brackets with no space",
        "at the start",
        "after a space",
        "at a line start",
        "with words around them",
        "followed by punctuation",
        "with a hyphen and a colon",
        "cited twice",
        "an email address",
        "none",
    ],
)
def test_citation_keys_reads_the_pandoc_forms(text, keys):
    assert citation_keys(text) == keys


# What pandoc prints as text is not a citation (Track L, Step L3). That is an @
# a backslash escapes and anything inside inline code or a fenced code block, as
# the references procedure's extractor reads them. An unclosed fence is text,
# as in pandoc 3.9.


@pytest.mark.parametrize(
    "text, keys",
    [
        ("The appendix writes \\@nakamura2020 as text.", []),
        ("The appendix writes [\\@nakamura2020] as text.", []),
        ("The syntax is `@nakamura2020` in the source.", []),
        ("The syntax is `[@nakamura2020]` in the source.", []),
        ("The syntax is ``a ` then @nakamura2020`` in the source.", []),
        ("The syntax is `@nakamura2020\nacross a line` in the source.", []),
        ("Before.\n\n```\n[@nakamura2020]\n\n@okafor2019\n```\n\nAfter.", []),
        ("Before.\n\n~~~ {.markdown}\nAs @nakamura2020 finds.\n~~~\n", []),
        ("Before.\n```\n@nakamura2020\n```\n", []),
        ("Write `@key` or \\@key, as Lee found [@lee2019, p. 4; \\@not2020].", ["lee2019"]),
        ("First [@a2001].\n\n```\n[@code2002]\n```\n\nSecond [@b2003].", ["a2001", "b2003"]),
        ("Before.\n\n```\n@inside2001\n\nStill open, as @open2002 says.", ["inside2001", "open2002"]),
        ("Use `code` and then cite [@after2004].", ["after2004"]),
    ],
    ids=[
        "escaped",
        "escaped in brackets",
        "inline code",
        "inline code in brackets",
        "double backticks around a backtick",
        "inline code across a line",
        "fenced block with a blank line",
        "tilde fence with a class",
        "fence with no blank line before",
        "a real citation beside an escaped one and code",
        "citations around a fenced block",
        "an unclosed fence is text",
        "a citation after inline code",
    ],
)
def test_citation_keys_skips_what_pandoc_prints_as_text(text, keys):
    assert citation_keys(text) == keys


def test_a_citation_written_inside_code_gets_no_entry(tmp_path, audit, project):
    content = (
        "# Methods\n\nCite a work as `[@key]`, as Lee did [@lee2019].\n\n"
        "```markdown\nAs @example2020 shows [@example2021].\n```\n"
    )
    calls = [("Write", {"file_path": str(project / "methods.md"), "content": content})]
    capture(audit, tmp_path / "session.jsonl", made_up_lines(project, calls))
    assert citation_log(audit, project) == {"citations": {"lee2019": entry(MADE_UP_ID)}}


# The write-out command.


def test_the_write_out_command_writes_the_citation_log(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    story = tmp_path / "story_session.jsonl"
    story.write_bytes("".join(line + "\n" for line in lines_of(project)).encode("utf-8"))
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(story)]) == 0
    capsys.readouterr()

    out = project / "citation_log.yaml"
    command = [
        "write-out",
        "citation-log",
        "--home",
        str(home),
        "--project",
        str(project),
        "--out",
        str(out),
    ]
    assert main(command) == 0
    printed = capsys.readouterr().out
    assert str(out) in printed and "2 citations" in printed and "1 session" in printed
    written = out.read_bytes()
    assert yaml.safe_load(written.decode("utf-8")) == STORY_LOG

    # Writing out again gives the same file.
    assert main(command) == 0
    assert out.read_bytes() == written


def test_write_out_runs_as_a_module_and_takes_a_relative_project_folder(tmp_path, project):
    home = tmp_path / "audit_home"
    store = open_store(home)
    try:
        capture(store, tmp_path / "story_session.jsonl", lines_of(project))
    finally:
        store.db.close()
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "audit_layer",
            "write-out",
            "citation-log",
            "--home",
            str(home),
            "--project",
            "project",
            "--out",
            "citation_log.yaml",
        ],
        cwd=str(tmp_path),
        env=dict(os.environ, PYTHONPATH=str(ROOT)),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    written = (tmp_path / "citation_log.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load(written) == STORY_LOG


def test_write_out_refuses_without_an_audit_store(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    out = tmp_path / "citation_log.yaml"
    command = ["write-out", "citation-log", "--home", str(home)]
    code = main(command + ["--project", str(project), "--out", str(out)])
    assert code == 1
    err = capsys.readouterr().err
    assert "no audit store" in err and "init" in err
    assert not home.exists()
    assert not out.exists()


def test_write_out_names_a_transcript_missing_from_the_file_store(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    store = open_store(home)
    try:
        capture(store, tmp_path / "story_session.jsonl", lines_of(project))
        for kept in store.files.iterdir():
            kept.unlink()
    finally:
        store.db.close()
    capsys.readouterr()
    out = tmp_path / "citation_log.yaml"
    command = ["write-out", "citation-log", "--home", str(home)]
    assert main(command + ["--project", str(project), "--out", str(out)]) == 1
    assert "could not write out" in capsys.readouterr().err
    assert not out.exists()


def test_write_out_names_an_out_file_it_cannot_write(tmp_path, project, capsys):
    home = tmp_path / "audit_home"
    assert main(["init", "--home", str(home)]) == 0
    capsys.readouterr()
    out = tmp_path / "missing_folder" / "citation_log.yaml"
    command = ["write-out", "citation-log", "--home", str(home)]
    assert main(command + ["--project", str(project), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "could not write out" in err and str(out) in err
    assert not out.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["write-out"],
        ["write-out", "citation-log", "--out", "citation_log.yaml"],
        ["write-out", "citation-log", "--project", "project"],
    ],
    ids=["no record", "no project", "no out file"],
)
def test_write_out_needs_a_record_a_project_and_an_out_file(arguments):
    with pytest.raises(SystemExit) as stop:
        main(arguments)
    assert stop.value.code == 2
