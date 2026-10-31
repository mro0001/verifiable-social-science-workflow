"""Tests for the session index write-out (Track P, step P3).

the authors asked on 2026-10-30 for a public, searchable index of a project's AI
sessions. python3 -m audit_layer write-out session-index writes it into a new
or empty folder as sessions.csv, README.md, one <public id>.md per session,
and index.html (Track P choice 6). It lists every AI session that touched the
project (choice 2), publishes no transcript text (choice 3), publishes the
model-written fields unless the scholar opts out (choice 4), and names each
session's AI contributions in the final reports by the results files given
(choice 5).

The sessions are the test story's synthetic Claude Code sessions, the
synthetic subagent conversation in fixtures/claude_code, and two synthetic
sessions written here that ran in another folder, with the folder token
{{PROJECT}} replaced with a temporary folder. The model pass answers from a
recorded book written here, the results files are written here, and every
test runs with its home folder inside a temporary folder. No real session
file is read, and nothing here calls a model or the network. Run from the
repository root with python3 -m pytest -q audit_layer/tests.
"""
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_session  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import current_session  # noqa: E402
from audit_layer.records.session_index import (  # noqa: E402
    COLUMNS,
    REVIEWED,
    UNREVIEWED,
    WITHHELD,
    public_id,
)
from audit_layer.store import open_store  # noqa: E402
from audit_layer.tagging.answers import open_answers  # noqa: E402
from audit_layer.tagging.model_pass import tag_session  # noqa: E402
from audit_layer.tagging.review import review  # noqa: E402

SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
TOUCH_SESSION = SESSIONS / "build_touch_session.jsonl"
SUBAGENT = Path(__file__).parent / "fixtures" / "claude_code" / "subagent.jsonl"
BOOK = Path(__file__).parent / "fixtures" / "model_pass" / "recorded_tags.json"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
TOUCH_ID = "8b21d6e4-9c3a-4f57-a2e0-3d6c1f84b705"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID
# Two synthetic sessions run in another folder. The first reads a project
# file, so it touched the project, and the second does not.
READER_ID = "d4c3b2a1-0f9e-4d8c-b7a6-152433425160"
ELSEWHERE_ID = "e5d4c3b2-1a0f-4e9d-8c7b-261534435261"

STORY_REF = "S55ac19fb97b9"
TOUCH_REF = "Sadbdcaecef34"

# A word the reader session's model-written title holds, for the scrub.
SECRET = "Quillfeather"


def lines_of(source, project):
    text = source.read_text(encoding="utf-8")
    text = text.replace(TOKEN, json.dumps(str(project))[1:-1])
    return [line for line in text.split("\n") if line]


def write_session(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return path


def synthetic(session_id, cwd, start, reads):
    """A Claude Code session run in cwd, reading each file of reads, with one model and a version."""
    records = []
    previous = None

    def add(record):
        nonlocal previous
        record.update(
            {
                "sessionId": session_id,
                "cwd": str(cwd),
                "uuid": "u%02d-%s" % (len(records), session_id[:8]),
                "parentUuid": previous,
                "isSidechain": False,
                "version": "9.9.9",
            }
        )
        previous = record["uuid"]
        records.append(json.dumps(record))

    add(
        {
            "type": "user",
            "timestamp": start + ":00.000Z",
            "message": {"role": "user", "content": "Please look over the notes for me."},
        }
    )
    for number, path in enumerate(reads):
        call = "toolu_%s_%d" % (session_id[:8], number)
        add(
            {
                "type": "assistant",
                "timestamp": start + ":%02d.000Z" % (10 + 2 * number),
                "message": {
                    "role": "assistant",
                    "model": "claude-synthetic-2",
                    "content": [
                        {"type": "tool_use", "id": call, "name": "Read", "input": {"file_path": str(path)}}
                    ],
                },
            }
        )
        add(
            {
                "type": "user",
                "timestamp": start + ":%02d.500Z" % (10 + 2 * number),
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": call, "content": "notes"}],
                },
            }
        )
    add(
        {
            "type": "assistant",
            "timestamp": start + ":59.000Z",
            "message": {"role": "assistant", "model": "claude-synthetic-2", "content": "Done."},
        }
    )
    return records


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def project(home_folder):
    # The project sits in the home folder, as a scholar's would.
    folder = home_folder / "projects" / "story"
    folder.mkdir(parents=True)
    return Path(str(folder))


@pytest.fixture
def elsewhere(home_folder):
    folder = home_folder / "elsewhere"
    folder.mkdir()
    return folder


@pytest.fixture
def audit_home(tmp_path):
    return tmp_path / "audit_home"


@pytest.fixture
def book(tmp_path, home_folder):
    """A recorded book for the story, its subagent, and the reader session."""
    answers = json.loads(BOOK.read_text(encoding="utf-8"))
    kept = {STORY_ID: answers[STORY_ID], SUBAGENT_ID: answers[SUBAGENT_ID]}
    kept[READER_ID] = {
        "title": "Look over the %s notes" % SECRET,
        "gist": "The AI read notes kept in %s/elsewhere and the manuscript." % home_folder,
        "summary": "The scholar asked for a look at the notes. The AI read them and the manuscript.",
        "keywords": ["notes", SECRET.lower(), "manuscript"],
        "decisions": [],
    }
    path = tmp_path / "book.json"
    path.write_text(json.dumps(kept), encoding="utf-8")
    return path


@pytest.fixture
def files(tmp_path, project, elsewhere):
    """The session files written, by session id."""
    root = tmp_path / "root" / "-encoded-project-folder"
    written = {
        STORY_ID: write_session(root / (STORY_ID + ".jsonl"), lines_of(STORY_SESSION, project)),
        TOUCH_ID: write_session(root / (TOUCH_ID + ".jsonl"), lines_of(TOUCH_SESSION, project)),
    }
    written[SUBAGENT_ID] = write_session(
        root / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"), lines_of(SUBAGENT, project)
    )
    other = tmp_path / "root" / "-encoded-elsewhere"
    written[READER_ID] = write_session(
        other / (READER_ID + ".jsonl"),
        synthetic(READER_ID, elsewhere, "2026-10-21T15:00", [elsewhere / "notes.md", project / "manuscript.md"]),
    )
    written[ELSEWHERE_ID] = write_session(
        other / (ELSEWHERE_ID + ".jsonl"),
        synthetic(ELSEWHERE_ID, elsewhere, "2026-10-21T16:00", [elsewhere / "notes.md"]),
    )
    return written


@pytest.fixture
def captured(audit_home, files, book):
    """The store once every session is captured and the story, subagent, and reader tagged."""
    store = open_store(audit_home)
    settings = {"excluded_folders": []}
    for session_id in (STORY_ID, TOUCH_ID, READER_ID, ELSEWHERE_ID):
        capture_session(store, "claude_code", files[session_id], settings)
    source = open_answers("recorded:%s" % book)
    for session_id in (STORY_ID, SUBAGENT_ID, READER_ID):
        outcome = tag_session(store, current_session(store, "claude_code", session_id), source)
        assert outcome.status == "tagged", outcome
    yield store
    store.db.close()


def results_file(path, stream, run_id, items, decisions=()):
    """Write a results file in the form vg.py writes, with the items and decisions given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": "verification-results",
        "schema_version": 1,
        "stream": stream,
        "run_id": run_id,
        "procedure_version": 1,
        "inputs": {},
        "items": items,
        "decisions": [
            {"item": item, "decision": word, "by": "story scholar", "at": "2026-10-23T10:00:00Z", "run_id": run_id}
            for item, word in decisions
        ],
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def citations(tmp_path):
    """A citations results file in which the story session added r02 and r03, and r02 is approved."""
    items = [
        {"id": "r01", "needs_decision": True, "citekey": "castellanos2017"},
        {"id": "r02", "needs_decision": True, "citekey": "dumont2014", "sessions": [STORY_REF]},
        {"id": "r03", "needs_decision": True, "citekey": "nakamura2020", "sessions": [STORY_REF]},
    ]
    return results_file(
        tmp_path / "runs" / "story_citations" / "results.json",
        "citations",
        "story_citations",
        items,
        [("r02", "held"), ("r02", "approved")],
    )


def write_index(audit_home, project, out, *extra):
    args = ["write-out", "session-index", "--home", str(audit_home), "--project", str(project), "--out", str(out)]
    return main(args + [str(part) for part in extra])


@pytest.fixture
def index(tmp_path, captured, audit_home, project, citations):
    """The index written with the citations results file."""
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", citations) == 0
    return out


def rows_of(out):
    with open(str(out / "sessions.csv"), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def html_data(out):
    """The rows embedded in index.html, read as JSON."""
    page = (out / "index.html").read_text(encoding="utf-8")
    found = re.search(r'<script id="session-data" type="application/json">(.*?)</script>', page, re.S)
    assert found, "index.html holds no embedded data"
    return json.loads(found.group(1))


def every_text(out):
    """Each file of the index, by its path relative to the index, as text."""
    return {
        path.relative_to(out).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(out.rglob("*"))
        if path.is_file()
    }


def by_id(out):
    return {row["public_id"]: row for row in rows_of(out)}


# ------------------------------------------------------------------ the files


def test_the_index_is_the_csv_the_readme_a_page_per_session_and_the_html_page(index):
    names = sorted(path.name for path in index.iterdir())
    pages = sorted(row["public_id"] + ".md" for row in rows_of(index))
    assert names == sorted(["README.md", "index.html", "sessions.csv"] + pages)


def test_the_csv_has_one_column_for_each_field_in_order(index):
    with open(str(index / "sessions.csv"), encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    assert tuple(header) == COLUMNS


def test_the_output_must_be_a_new_or_empty_folder(tmp_path, captured, audit_home, project, capsys):
    out = tmp_path / "busy"
    out.mkdir()
    (out / "kept.txt").write_text("kept", encoding="utf-8")
    assert write_index(audit_home, project, out) == 1
    assert "not empty" in capsys.readouterr().err
    assert sorted(path.name for path in out.iterdir()) == ["kept.txt"]


def test_a_home_with_no_store_is_refused_and_not_made(tmp_path, project, capsys):
    home = tmp_path / "no_store"
    assert write_index(home, project, tmp_path / "index") == 1
    assert "no audit store" in capsys.readouterr().err
    assert not home.exists()
    assert not (tmp_path / "index").exists()


def test_the_command_says_what_it_wrote(tmp_path, captured, audit_home, project, citations, capsys):
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", citations) == 0
    said = capsys.readouterr().out
    assert "wrote %s" % out in said
    assert "4 sessions" in said


# ------------------------------------------------------------------ which sessions


def test_every_session_that_touched_the_project_is_listed_in_the_order_they_started(index):
    ids = [row["public_id"] for row in rows_of(index)]
    assert ids == [STORY_REF, public_id(SUBAGENT_ID), public_id(READER_ID), TOUCH_REF]


def test_a_session_elsewhere_that_touched_no_project_file_is_not_listed(index):
    assert public_id(ELSEWHERE_ID) not in "".join(every_text(index).values())


def test_a_session_elsewhere_that_a_contribution_names_is_listed(tmp_path, captured, audit_home, project, capsys):
    # A citation an AI found in a session run elsewhere still links to that session.
    path = results_file(
        tmp_path / "runs" / "elsewhere_citations" / "results.json", "citations", "elsewhere_citations",
        [{"id": "r01", "needs_decision": True, "citekey": "osei2015", "sessions": [public_id(ELSEWHERE_ID)]}],
    )
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", path) == 0
    rows = by_id(out)
    assert public_id(ELSEWHERE_ID) in rows
    assert rows[public_id(ELSEWHERE_ID)]["contributions"] == "1"
    assert "which the index does not list" not in capsys.readouterr().out


def test_a_link_to_the_project_counts_as_the_project(tmp_path, captured, audit_home, project, citations):
    link = tmp_path / "linked"
    link.symlink_to(project)
    out = tmp_path / "index"
    assert write_index(audit_home, link, out, "--results", citations) == 0
    assert [row["public_id"] for row in rows_of(out)] == [
        STORY_REF,
        public_id(SUBAGENT_ID),
        public_id(READER_ID),
        TOUCH_REF,
    ]


def test_a_folder_the_project_was_worked_in_before_counts_as_the_projects(
    tmp_path, captured, audit_home, project, elsewhere, citations
):
    # A project that moved, such as a demonstration built from a proposal
    # written in another folder, names its earlier folder too.
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", citations, "--also-folder", elsewhere) == 0
    rows = by_id(out)
    # The session elsewhere started at 16:00, before the touch session.
    assert list(rows) == [STORY_REF, public_id(SUBAGENT_ID), public_id(READER_ID), public_id(ELSEWHERE_ID), TOUCH_REF]
    # A file in the earlier folder is named by that folder's name and its path inside it.
    assert rows[public_id(ELSEWHERE_ID)]["files_read"] == "elsewhere/notes.md"
    assert rows[public_id(ELSEWHERE_ID)]["other_files"] == "0"
    assert rows[public_id(READER_ID)]["files_read"] == "elsewhere/notes.md; manuscript.md"
    assert rows[public_id(READER_ID)]["other_files"] == "0"


def test_an_earlier_folder_that_is_not_there_is_refused(tmp_path, captured, audit_home, project, capsys):
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--also-folder", tmp_path / "gone") == 1
    assert "is not a folder" in capsys.readouterr().err
    assert not out.exists()


def test_a_project_no_session_touched_gives_an_index_with_no_rows(tmp_path, captured, audit_home):
    empty = tmp_path / "empty_project"
    empty.mkdir()
    out = tmp_path / "index"
    assert write_index(audit_home, empty, out) == 0
    assert rows_of(out) == []
    assert html_data(out) == []


# ------------------------------------------------------------------ a row's fields


def test_a_row_holds_the_sessions_metadata(index, files):
    story = by_id(index)[STORY_REF]
    assert story["started_at"] == "2026-10-21T14:02:05.112Z"
    assert story["minutes"] == "0.7"
    assert story["harness"] == "claude_code"
    assert story["parent"] == ""
    assert story["tool_calls"] == "wrote 1; edited 2; searched 1; verified 1; committed 1"
    assert story["files_read"] == "manuscript.md"
    assert story["files_edited"] == "manuscript.md"
    assert story["files_written"] == "source_notes.md"
    assert story["other_files"] == "0"
    data = files[STORY_ID].read_bytes()
    assert story["transcript_sha256"] == hashlib.sha256(data).hexdigest()
    assert story["transcript_bytes"] == str(len(data))


def test_a_subagent_names_its_parents_public_id_and_its_models(index):
    agent = by_id(index)[public_id(SUBAGENT_ID)]
    assert agent["parent"] == STORY_REF
    assert agent["models"] == "claude-synthetic-1"
    assert agent["files_read"] == "refs.bib"
    assert agent["files_written"] == "notes/reading_list.md"
    assert agent["tool_calls"] == "wrote 1; searched 2"


def test_a_session_elsewhere_counts_its_other_files_and_never_names_them(index):
    reader = by_id(index)[public_id(READER_ID)]
    assert reader["harness_version"] == "9.9.9"
    assert reader["models"] == "claude-synthetic-2"
    assert reader["files_read"] == "manuscript.md"
    assert reader["other_files"] == "1"
    assert reader["minutes"] == "1.0"
    for text in every_text(index).values():
        assert "elsewhere/notes.md" not in text
        assert "notes.md" not in text.replace("source_notes.md", "")


def test_no_file_of_the_index_names_a_full_path(index, project, home_folder):
    for path, text in every_text(index).items():
        assert str(project) not in text, path


# ------------------------------------------------------------------ contributions


def test_the_ai_added_citations_appear_under_the_story_session_with_their_reference_ids(index):
    story = by_id(index)[STORY_REF]
    assert story["contributions"] == "2"
    assert story["references"] == (
        "citations/r02 (approved, run story_citations); citations/r03 (not yet decided, run story_citations)"
    )
    entry = [row for row in html_data(index) if row["public_id"] == STORY_REF][0]
    assert entry["references"] == [
        {"reference": "citations/r02", "run": "story_citations", "decision": "approved"},
        {"reference": "citations/r03", "run": "story_citations", "decision": "not yet decided"},
    ]
    page = (index / (STORY_REF + ".md")).read_text(encoding="utf-8")
    assert "citations/r02" in page and "citations/r03" in page


def test_a_session_with_no_contribution_is_listed_with_zero(index):
    rows = by_id(index)
    for ref in (TOUCH_REF, public_id(SUBAGENT_ID), public_id(READER_ID)):
        assert rows[ref]["contributions"] == "0"
        assert rows[ref]["references"] == ""


def test_with_no_results_file_every_session_has_zero(tmp_path, captured, audit_home, project):
    out = tmp_path / "index"
    assert write_index(audit_home, project, out) == 0
    assert {row["contributions"] for row in rows_of(out)} == {"0"}


def test_the_latest_results_file_given_for_a_stream_counts(tmp_path, captured, audit_home, project, citations):
    later = results_file(
        tmp_path / "runs" / "story_citations_2" / "results.json",
        "citations",
        "story_citations_2",
        [{"id": "r05", "needs_decision": True, "sessions": [STORY_REF]}],
        [("r05", "held")],
    )
    build = results_file(
        tmp_path / "runs" / "story_build" / "results.json",
        "build",
        "story_build",
        [{"id": "b01", "needs_decision": False, "sessions": [TOUCH_REF]}],
    )
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", citations, build, "--results", later) == 0
    rows = by_id(out)
    assert rows[STORY_REF]["references"] == "citations/r05 (held, run story_citations_2)"
    assert rows[TOUCH_REF]["references"] == "build/b01 (needs no decision, run story_build)"


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", json.dumps({"stream": "citations", "items": []}), json.dumps({"stream": 3, "run_id": "r", "items": []})],
)
def test_a_results_file_that_is_not_one_is_refused(tmp_path, captured, audit_home, project, text, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(text, encoding="utf-8")
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", bad) == 1
    assert "bad.json" in capsys.readouterr().err
    assert not out.exists()


# ------------------------------------------------------------------ Q2, several products
#
# A project with two research products keeps each product's results in
# verification/<product>/<stream>.json (Track Q, step Q1). The index reads
# every product's files, and a reference id names the product as well, as
# <product>/<stream>/<item id>, when the file sits in a product's folder or is
# given as PRODUCT=FILE.


@pytest.fixture
def two_products(project):
    """The prose and citations results of the proposal and the appendix, in their product folders."""
    verification = project / "verification"
    proposal = results_file(
        verification / "proposal" / "prose.json",
        "prose",
        "proposal_prose",
        [{"id": "c01", "needs_decision": True, "sessions": [STORY_REF]}],
        [("c01", "approved")],
    )
    appendix = results_file(
        verification / "appendix" / "prose.json",
        "prose",
        "appendix_prose",
        [
            {"id": "c01", "needs_decision": True, "sessions": [STORY_REF]},
            {"id": "c02", "needs_decision": True, "sessions": [TOUCH_REF]},
        ],
    )
    citations = results_file(
        verification / "appendix" / "citations.json",
        "citations",
        "appendix_citations",
        [{"id": "r02", "needs_decision": True, "sessions": [STORY_REF]}],
        [("r02", "held")],
    )
    return proposal, appendix, citations


def test_a_two_product_project_lists_both_products_contributions_with_ids_that_name_the_product(
    tmp_path, captured, audit_home, project, two_products, capsys
):
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", *two_products) == 0
    assert "set aside" not in capsys.readouterr().out
    rows = by_id(out)
    assert rows[STORY_REF]["contributions"] == "3"
    assert rows[STORY_REF]["references"] == (
        "proposal/prose/c01 (approved, run proposal_prose); "
        "appendix/prose/c01 (not yet decided, run appendix_prose); "
        "appendix/citations/r02 (held, run appendix_citations)"
    )
    assert rows[TOUCH_REF]["references"] == "appendix/prose/c02 (not yet decided, run appendix_prose)"
    entry = [row for row in html_data(out) if row["public_id"] == STORY_REF][0]
    assert [item["reference"] for item in entry["references"]] == [
        "proposal/prose/c01",
        "appendix/prose/c01",
        "appendix/citations/r02",
    ]
    page = (out / (STORY_REF + ".md")).read_text(encoding="utf-8")
    assert "proposal/prose/c01" in page and "appendix/prose/c01" in page


def test_results_given_as_product_equals_file_name_the_product(
    tmp_path, captured, audit_home, project, citations
):
    proposal = results_file(
        tmp_path / "runs" / "proposal_prose" / "results.json",
        "prose",
        "proposal_prose",
        [{"id": "c01", "needs_decision": True, "sessions": [STORY_REF]}],
    )
    out = tmp_path / "index"
    given = ["--results", "proposal=%s" % proposal, "appendix=%s" % citations]
    assert write_index(audit_home, project, out, *given) == 0
    assert by_id(out)[STORY_REF]["references"] == (
        "proposal/prose/c01 (not yet decided, run proposal_prose); "
        "appendix/citations/r02 (approved, run story_citations); "
        "appendix/citations/r03 (not yet decided, run story_citations)"
    )


def test_the_product_given_with_the_file_names_the_product_over_its_folder(
    tmp_path, captured, audit_home, project, two_products
):
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", "draft=%s" % two_products[0]) == 0
    assert by_id(out)[STORY_REF]["references"] == "draft/prose/c01 (approved, run proposal_prose)"


def test_a_later_file_of_a_products_stream_sets_aside_only_that_products_earlier_one(
    tmp_path, captured, audit_home, project, two_products, capsys
):
    proposal, appendix, _ = two_products
    rerun = results_file(
        tmp_path / "runs" / "proposal_prose_2" / "results.json",
        "prose",
        "proposal_prose_2",
        [{"id": "c05", "needs_decision": True, "sessions": [STORY_REF]}],
    )
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", proposal, appendix, "proposal=%s" % rerun) == 0
    said = capsys.readouterr().out
    assert "set aside %s" % proposal in said
    assert "set aside %s" % appendix not in said
    assert by_id(out)[STORY_REF]["references"] == (
        "proposal/prose/c05 (not yet decided, run proposal_prose_2); "
        "appendix/prose/c01 (not yet decided, run appendix_prose)"
    )


def test_a_file_in_a_product_folder_not_named_for_its_stream_keeps_the_one_product_id(
    tmp_path, captured, audit_home, project
):
    other = results_file(
        project / "verification" / "appendix" / "prose_old.json",
        "prose",
        "appendix_prose",
        [{"id": "c01", "needs_decision": True, "sessions": [STORY_REF]}],
    )
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--results", other) == 0
    assert by_id(out)[STORY_REF]["references"] == "prose/c01 (not yet decided, run appendix_prose)"


def test_a_one_product_projects_index_is_unchanged(tmp_path, captured, audit_home, project, citations):
    """The results file copied to verification/<stream>.json gives the same index as the run's own."""
    copied = project / "verification" / "citations.json"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(citations.read_bytes())
    from_run, from_project = tmp_path / "from_run", tmp_path / "from_project"
    assert write_index(audit_home, project, from_run, "--results", citations) == 0
    assert write_index(audit_home, project, from_project, "--results", copied) == 0
    assert every_text(from_run) == every_text(from_project)
    assert by_id(from_project)[STORY_REF]["references"] == (
        "citations/r02 (approved, run story_citations); citations/r03 (not yet decided, run story_citations)"
    )


# ------------------------------------------------------------------ index.html


def test_index_html_embeds_every_row_and_the_checkbox_keeps_sessions_with_a_contribution(index):
    page = (index / "index.html").read_text(encoding="utf-8")
    data = html_data(index)
    assert [row["public_id"] for row in data] == [row["public_id"] for row in rows_of(index)]
    # The checkbox and the rule the script filters by.
    assert re.search(r'<input type="checkbox" id="only-contributions"', page)
    assert "Only sessions with an AI contribution in the final reports" in page
    assert "if (onlyContributions && row.contributions === 0) { return false; }" in page
    kept = [row["public_id"] for row in data if row["contributions"] != 0]
    assert kept == [STORY_REF]


def test_index_html_has_a_search_box_and_puts_no_text_into_the_page_as_markup(index):
    page = (index / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<input type="search" id="search"', page)
    assert "innerHTML" not in page
    assert "<script src" not in page


def test_embedded_text_cannot_close_the_script(tmp_path, captured, audit_home, project):
    review(captured, STORY_ID, "story scholar", {"title": "Ends </script><b>here</b>"}, {})
    out = tmp_path / "index"
    assert write_index(audit_home, project, out) == 0
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "</script><b>" not in page
    titles = {row["public_id"]: row["title"] for row in html_data(out)}
    assert titles[STORY_REF] == "Ends </script><b>here</b>"


# ------------------------------------------------------------------ the model's fields


def test_model_fields_are_published_and_labeled_unreviewed(index):
    story = by_id(index)[STORY_REF]
    answers = json.loads(BOOK.read_text(encoding="utf-8"))[STORY_ID]
    assert story["title"] == answers["title"]
    assert story["gist"] == answers["gist"]
    assert story["summary"] == answers["summary"]
    assert story["keywords"] == "; ".join(answers["keywords"])
    assert story["model_fields"] == UNREVIEWED
    # A session the pass has not tagged has no fields and no label.
    touch = by_id(index)[TOUCH_REF]
    assert (touch["title"], touch["model_fields"]) == ("", "")


def test_a_reviewed_session_is_labeled_reviewed(tmp_path, captured, audit_home, project):
    review(captured, STORY_ID, "story scholar", {}, {})
    out = tmp_path / "index"
    assert write_index(audit_home, project, out) == 0
    assert by_id(out)[STORY_REF]["model_fields"] == REVIEWED
    assert by_id(out)[public_id(SUBAGENT_ID)]["model_fields"] == UNREVIEWED


def model_texts(store):
    """Each text the model pass wrote for the three tagged sessions."""
    texts = []
    for session_id in (STORY_ID, SUBAGENT_ID, READER_ID):
        row = current_session(store, "claude_code", session_id)
        texts += [row["title"], row["gist"], row["summary"]] + list(row["keywords"])
    return texts


def test_no_summaries_removes_every_model_field(tmp_path, captured, audit_home, project):
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--no-summaries") == 0
    # Short keywords such as citations are common words, so the longer texts are searched for.
    texts = [field for field in model_texts(captured) if len(field) >= 20]
    assert len(texts) >= 9
    for path, text in every_text(out).items():
        for field in texts:
            assert field not in text, (path, field)
    for row in rows_of(out):
        assert (row["title"], row["gist"], row["summary"], row["keywords"]) == ("", "", "", "")
        assert row["model_fields"] == WITHHELD


def test_withhold_removes_the_model_fields_of_the_named_sessions_only(tmp_path, captured, audit_home, project):
    listing = tmp_path / "withhold.txt"
    listing.write_text("\n%s\n\n" % STORY_REF, encoding="utf-8")
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--withhold", listing) == 0
    rows = by_id(out)
    assert (rows[STORY_REF]["title"], rows[STORY_REF]["model_fields"]) == ("", WITHHELD)
    story_title = json.loads(BOOK.read_text(encoding="utf-8"))[STORY_ID]["title"]
    for text in every_text(out).values():
        assert story_title not in text
    assert rows[public_id(SUBAGENT_ID)]["title"] != ""
    assert rows[public_id(SUBAGENT_ID)]["model_fields"] == UNREVIEWED


@pytest.mark.parametrize("line", ["not-an-id", "S000000000000"])
def test_withhold_refuses_a_line_that_names_no_listed_session(tmp_path, captured, audit_home, project, line, capsys):
    listing = tmp_path / "withhold.txt"
    listing.write_text(line + "\n", encoding="utf-8")
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--withhold", listing) == 1
    assert line in capsys.readouterr().err
    assert not out.exists()


def test_the_scrub_replaces_the_home_path_and_each_listed_term(tmp_path, captured, audit_home, project, home_folder):
    terms = tmp_path / "scrub.txt"
    terms.write_text(SECRET + "\n\n", encoding="utf-8")
    out = tmp_path / "index"
    assert write_index(audit_home, project, out, "--scrub", terms) == 0
    reader = by_id(out)[public_id(READER_ID)]
    assert reader["title"] == "Look over the [withheld] notes"
    assert reader["gist"] == "The AI read notes kept in ~/elsewhere and the manuscript."
    assert reader["keywords"] == "notes; [withheld]; manuscript"
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert (
        "In them only the home folder's path is written as ~, and each term on the author's list"
        " as [withheld], so they may name other files and full paths." in readme
    )
    for path, text in every_text(out).items():
        assert SECRET.lower() not in text.lower(), path
        assert str(home_folder) not in text, path


def test_without_a_scrub_list_the_home_path_is_still_replaced(index, home_folder):
    reader = by_id(index)[public_id(READER_ID)]
    assert reader["gist"] == "The AI read notes kept in ~/elsewhere and the manuscript."
    assert SECRET in reader["title"]


# ------------------------------------------------------------------ no transcript text


def transcript_lines(path):
    """The story transcript's distinctive lines, each text a record holds, by line."""
    found = set()

    def walk(value):
        if isinstance(value, str):
            for line in value.splitlines():
                if len(line.strip()) >= 20:
                    found.add(line.strip())
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        walk(record.get("message"))
        walk(record.get("content"))
    return found


def test_no_file_of_the_index_holds_transcript_text(index, files):
    lines = set()
    for session_id in (STORY_ID, SUBAGENT_ID, READER_ID, TOUCH_ID):
        lines |= transcript_lines(files[session_id])
    assert len(lines) > 10
    for path, text in every_text(index).items():
        for line in lines:
            assert line not in text, (path, line)


# ------------------------------------------------------------------ the README and the pages


def test_the_readme_says_what_the_index_holds_and_how_to_check_and_search_it(index):
    readme = (index / "README.md").read_text(encoding="utf-8")
    for heading in (
        "## What the index holds",
        "## What the index does not hold",
        "## Checking a transcript against its checksum",
        "## Searching the index",
        "## Sessions",
    ):
        assert heading in readme
    assert "shasum -a 256" in readme
    assert "[index.html](index.html)" in readme
    assert "GitHub Pages" in readme
    for row in rows_of(index):
        assert "[%s](%s.md)" % (row["public_id"], row["public_id"]) in readme
    assert "—" not in readme


def test_each_session_page_names_its_fields_and_its_contributions(index):
    page = (index / (STORY_REF + ".md")).read_text(encoding="utf-8")
    assert page.startswith("# Session %s\n" % STORY_REF)
    assert "| Transcript sha256 |" in page
    assert UNREVIEWED in page
    assert "—" not in page
    agent = (index / (public_id(SUBAGENT_ID) + ".md")).read_text(encoding="utf-8")
    assert "[%s](%s.md)" % (STORY_REF, STORY_REF) in agent


def test_a_subagent_whose_parent_is_not_listed_names_the_parent_without_a_link(tmp_path, captured, audit_home, project):
    # Only the subagent touched the notes folder, and its parent ran in the project above it.
    notes = project / "notes"
    notes.mkdir(exist_ok=True)
    out = tmp_path / "index"
    assert write_index(audit_home, notes, out) == 0
    agent_ref = public_id(SUBAGENT_ID)
    assert [row["public_id"] for row in rows_of(out)] == [agent_ref]
    assert not (out / (STORY_REF + ".md")).exists()
    page = (out / (agent_ref + ".md")).read_text(encoding="utf-8")
    assert "| Started by session | %s |" % STORY_REF in page
    assert "(%s.md)" % STORY_REF not in page


def test_the_readme_says_the_model_fields_may_name_other_files_and_paths(index):
    readme = (index / "README.md").read_text(encoding="utf-8")
    section = readme.split("## What the index does not hold", 1)[1].split("\n## ", 1)[0]
    assert "No path of a file outside the project." not in section
    assert "No full path of any file." not in section
    assert (
        "No file outside the project named in the file fields, the project files read, edited, and"
        " written. Such files are counted and never named." in section
    )
    assert "No full path in the file fields." in section
    assert (
        "The title, gist, summary, and keywords a model wrote are not held to this. They may name"
        " other files and full paths, and in them only the home folder's path and the terms on the"
        " author's list are replaced." in section
    )
    assert (
        "In them only the home folder's path is written as ~, so they may name other files and"
        " full paths." in readme
    )
    assert "approved, held, not yet decided, or needs no decision" in readme
    assert "—" not in readme


def test_line_and_paragraph_separators_are_escaped_in_index_html(tmp_path, captured, audit_home, project):
    review(captured, STORY_ID, "story scholar", {"title": "One two three"}, {})
    out = tmp_path / "index"
    assert write_index(audit_home, project, out) == 0
    page = (out / "index.html").read_text(encoding="utf-8")
    assert " " not in page and " " not in page
    assert "\\u2028" in page and "\\u2029" in page
    titles = {row["public_id"]: row["title"] for row in html_data(out)}
    assert titles[STORY_REF] == "One two three"


def test_the_session_index_source_holds_no_invisible_line_separators():
    source = (ROOT / "audit_layer" / "records" / "session_index.py").read_text(encoding="utf-8")
    assert " " not in source and " " not in source


# P4. The write-out help names the handoff that copies the index into the project.


def test_the_session_index_help_names_the_handoff_into_the_project(capsys):
    with pytest.raises(SystemExit) as done:
        main(["write-out", "session-index", "--help"])
    assert done.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert ("python3 handoffs/session_index_to_project.py --from DIR --project DIR" in text)
    assert "sessions/" in text
