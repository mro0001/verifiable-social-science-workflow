"""Tests for the citation provenance record (Track C2, step C1).

the authors' second step for citations asks which citations originated in some
way from an AI, and the fourth asks that the session transcripts, logs, and
artifacts be used as much as possible. The provenance record reads, for each
work in the reference list, every place the record names it, in time order,
and says whether an AI or the scholar named it first (plan choices 2 and 4).

Every session here is a short synthetic Claude Code session or a synthetic
wrappers events file, made up in the test and captured into an audit store
in a temporary folder. No real session file is read, and nothing here calls a
model or the network. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_file, capture_session  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.records.citation_provenance import (  # noqa: E402
    EXCERPT_LIMIT,
    citation_provenance,
    read_references,
    write_citation_provenance,
)
from audit_layer.records.session_index import public_id  # noqa: E402
from audit_layer.store import open_store  # noqa: E402

NO_FOLDERS = {"excluded_folders": []}

AI_ID = "8a1b0417-1c2d-4e3f-9a4b-c5d6e7f80911"
LATER_ID = "8a1b0417-2c2d-4e3f-9a4b-c5d6e7f80922"

# A synthetic reference list in the references procedure's form.
REFERENCES = {
    "references": [
        {
            "id": "whitlock2020",
            "type": "article-journal",
            "author": [{"family": "Whitlock", "given": "Grace"}],
            "issued": 2020,
            "title": "Named contacts and volunteer tenure in three cities",
            "DOI": "10.5555/uan.2020.0230",
        },
        {
            "id": "castellanos2017",
            "type": "article-journal",
            "author": [{"family": "Castellanos", "given": "Rosa"}, {"family": "Ibe", "given": "Kelechi"}],
            "issued": 2017,
            "title": "Fit and retention in local volunteering",
            "DOI": "10.5555/vss.2017.0021",
        },
        {
            "id": "tanaka2016",
            "type": "article-journal",
            "author": [{"family": "Tanaka", "given": "Hiroshi"}],
            "issued": 2016,
            "title": "Training length and volunteer retention",
            "DOI": "10.5555/psq.2016.0071",
        },
        {
            "id": "devries2021",
            "type": "article-journal",
            "author": [{"family": "de Vries", "given": "Maarten"}],
            "issued": {"date-parts": [[2021]]},
            "title": "Scheduling flexibility and volunteer hours",
            "DOI": "10.5555/nmr.2021.0120",
        },
        {
            "id": "osei2015",
            "type": "article-journal",
            "author": [{"family": "Osei", "given": "Kwame"}],
            "issued": 2015,
            "title": "Volunteer motives across city sizes",
            "DOI": "10.5555/uan.2015.0102",
        },
    ]
}


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    """Each test's own home, audit home, and connections home."""
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    return tmp_path


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def refs(project):
    path = project / "refs.yaml"
    path.write_text(yaml.safe_dump(REFERENCES, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path):
    opened = open_store(tmp_path / "audit_home")
    yield opened
    opened.db.close()


def session_lines(folder, turns, session_id=AI_ID, minute=0, agent=None):
    """A synthetic Claude Code session run in folder.

    Each turn is ("user", text), ("assistant", text), or ("call", name,
    input, result). Records are a second apart from the given minute. With
    agent, it is that subagent's conversation of the session session_id.
    """
    records = []

    def add(kind, content):
        number = len(records) + 1
        record = {
            "parentUuid": records[-1]["uuid"] if records else None,
            "isSidechain": agent is not None,
            "cwd": str(folder),
            "sessionId": session_id,
            "type": kind,
            "message": {"role": kind, "content": content},
            "uuid": "{}-0000-4000-8000-{:012d}".format(
                (agent or session_id)[:8], number + (500 if agent else 0)
            ),
            "timestamp": "2026-10-22T09:{:02d}:{:02d}.000Z".format(minute, number),
        }
        if agent is not None:
            record["agentId"] = agent
        records.append(record)

    for number, turn in enumerate(turns, start=1):
        if turn[0] == "user":
            add("user", turn[1])
        elif turn[0] == "assistant":
            add("assistant", [{"type": "text", "text": turn[1]}])
        else:
            _, name, given, result = turn
            call_id = "toolu_{}_{:02d}".format(session_id[:8], number)
            add("assistant", [{"type": "tool_use", "id": call_id, "name": name, "input": given}])
            add("user", [{"type": "tool_result", "tool_use_id": call_id, "content": result}])
    return [json.dumps(record) for record in records]


def capture(store, path, lines, settings=NO_FOLDERS):
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    return capture_file(store, path, settings)


def provenance(store, project, refs, artifacts=()):
    return citation_provenance(store, project, read_references(refs), artifacts)


def test_an_ai_search_result_naming_a_work_first_makes_its_origin_ai(store, project, refs, tmp_path):
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                ("user", "Find work on volunteer tenure."),
                (
                    "call",
                    "WebSearch",
                    {"query": "volunteer tenure named contacts"},
                    "Named Contacts and Volunteer Tenure in Three Cities. Urban Affairs Notes.",
                ),
                ("user", "Good, cite the named contacts and volunteer tenure in three cities paper."),
            ],
        ),
    )
    entry = provenance(store, project, refs)["works"]["whitlock2020"]
    assert entry["origin"] == "ai"
    assert [a["by"] for a in entry["appearances"]] == ["ai", "scholar"]
    assert entry["first_ai"]["excerpt"] == "Named Contacts and Volunteer Tenure in Three Cities."
    assert entry["first_ai"]["session_ref"] == public_id(AI_ID)
    assert entry["first_scholar"]["excerpt"].startswith("Good, cite the named contacts")
    # A text part takes the time of the tool call before it, so the two share one time.
    assert entry["first_ai"]["time"] <= entry["first_scholar"]["time"]


def test_a_scholar_message_naming_a_work_first_makes_its_origin_the_scholar(store, project, refs, tmp_path):
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                ("user", "Add Castellanos and Ibe (2017) on fit to the retention paragraph."),
                ("assistant", "Castellanos and Ibe (2017) report that role fit predicts retention."),
            ],
        ),
    )
    entry = provenance(store, project, refs)["works"]["castellanos2017"]
    assert entry["origin"] == "scholar"
    assert entry["first_scholar"]["by"] == "scholar"
    assert entry["first_ai"]["by"] == "ai"
    assert entry["appearances"][0] == entry["first_scholar"]


def test_a_later_session_comes_after_an_earlier_one(store, project, refs, tmp_path):
    capture(
        store,
        tmp_path / "later.jsonl",
        session_lines(project, [("assistant", "Tanaka (2016) is on training length.")], LATER_ID, minute=30),
    )
    capture(
        store,
        tmp_path / "earlier.jsonl",
        session_lines(project, [("user", "I want Tanaka 2016 in the training section.")], AI_ID, minute=5),
    )
    entry = provenance(store, project, refs)["works"]["tanaka2016"]
    assert entry["origin"] == "scholar"
    assert [a["session_ref"] for a in entry["appearances"]] == [public_id(AI_ID), public_id(LATER_ID)]


def test_a_work_named_only_in_an_ai_written_artifact_has_origin_ai(store, project, refs, tmp_path):
    folder = tmp_path / "ai_notes"
    folder.mkdir()
    note = folder / "lit_notes.md"
    note.write_text(
        "# Notes\n\nScheduling flexibility and volunteer hours, a study of 40 programs.\n",
        encoding="utf-8",
    )
    entry = provenance(store, project, refs, [folder])["works"]["devries2021"]
    assert entry["origin"] == "ai"
    # A file in an artifacts folder outside the project is named by the folder's
    # name and its path inside it, never by a full path.
    assert entry["appearances"][0]["artifact"] == "ai_notes/lit_notes.md"
    assert entry["appearances"][0]["by"] == "ai"
    assert "session_ref" not in entry["appearances"][0]
    assert entry["reason"]["text"] == "Scheduling flexibility and volunteer hours, a study of 40 programs."
    assert entry["reason"]["artifact"] == "ai_notes/lit_notes.md"


def test_an_ai_write_into_the_project_names_its_artifact_and_session(store, project, refs, tmp_path):
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                (
                    "call",
                    "Write",
                    {"file_path": str(project / "notes" / "sources.md"), "content": "Osei (2015) compares motives.\n"},
                    "File created.",
                ),
            ],
        ),
    )
    first = provenance(store, project, refs)["works"]["osei2015"]["first_ai"]
    assert first["artifact"] == "notes/sources.md"
    assert first["session_ref"] == public_id(AI_ID)


def test_an_ai_write_outside_the_project_and_artifacts_folders_is_named_by_its_file_name(
    store, project, refs, tmp_path
):
    scratch = tmp_path / "user" / "scratch" / "deep"
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                (
                    "call",
                    "Write",
                    {"file_path": str(scratch / "sources.md"), "content": "Osei (2015) compares motives.\n"},
                    "File created.",
                ),
            ],
        ),
    )
    entry = provenance(store, project, refs)["works"]["osei2015"]
    assert entry["first_ai"]["artifact"] == "sources.md"
    assert entry["reason"]["artifact"] == "sources.md"
    assert str(tmp_path) not in yaml.safe_dump(entry)


def test_a_work_never_named_has_no_appearances_and_origin_unknown(store, project, refs, tmp_path):
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("user", "Tidy the headings.")]))
    entry = provenance(store, project, refs)["works"]["osei2015"]
    assert entry == {
        "origin": "unknown",
        "appearances": [],
        "first_ai": None,
        "first_scholar": None,
        "reason": None,
        "quotes": [],
    }


def test_every_work_in_the_reference_list_gets_an_entry_in_its_order(store, project, refs):
    works = provenance(store, project, refs)["works"]
    assert list(works) == ["whitlock2020", "castellanos2017", "tanaka2016", "devries2021", "osei2015"]


@pytest.mark.parametrize(
    "text",
    [
        "See doi 10.5555/PSQ.2016.0071 for the details.",
        "See https://doi.org/10.5555/PSQ.2016.0071 for the details.",
        "See http://dx.doi.org/10.5555/psq.2016.0071 for the details.",
        "The paper Training Length and Volunteer-Retention is useful.",
        "As Tanaka et al. (2016) show, longer training helps.",
        "Tanaka's 2016 study is useful.",
    ],
    ids=["doi", "doi link", "dx doi link", "title", "author and year", "possessive author and year"],
)
def test_a_work_is_recognized_by_doi_title_or_author_with_year(store, project, refs, tmp_path, text):
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", text)]))
    entry = provenance(store, project, refs)["works"]["tanaka2016"]
    assert entry["origin"] == "ai"
    assert entry["first_ai"]["excerpt"] == text


@pytest.mark.parametrize(
    "text",
    [
        "Tanaka (2019) is a different paper.",
        "Tanaka 2014 and Moreno 2016 are older.",
        "See doi 10.5555/psq.2016.00712 instead.",
        "Training length and volunteer retentions differ.",
        "Write to tanaka2016@example.org for a copy.",
        "See https://example.org/x/10.5555/psq.2016.0071 for a copy.",
        "Cite [@tanaka2016] here.",
    ],
    ids=[
        "other year", "year of another author", "longer doi", "longer title word", "email address",
        "doi inside another path", "cited key alone",
    ],
)
def test_a_near_miss_is_not_an_appearance(store, project, refs, tmp_path, text):
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", text)]))
    assert provenance(store, project, refs)["works"]["tanaka2016"]["appearances"] == []


def test_a_recorded_reason_and_quote_come_from_the_ais_own_words(store, project, refs, tmp_path):
    paragraph = (
        "For the retention sentence I suggest Whitlock (2020). She writes that "
        "“named contacts doubled median tenure in all three cities,” which is the claim "
        "the sentence makes. It is a field study."
    )
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                ("call", "WebSearch", {"query": "volunteer tenure"}, "Whitlock 2020, Urban Affairs Notes."),
                ("assistant", "Here is what I found.\n\n" + paragraph + "\n\nShall I add it?"),
            ],
        ),
    )
    entry = provenance(store, project, refs)["works"]["whitlock2020"]
    assert entry["first_ai"]["excerpt"] == "Whitlock 2020, Urban Affairs Notes."
    assert entry["reason"]["text"] == (
        "For the retention sentence I suggest Whitlock (2020). She writes that "
        "“named contacts doubled median tenure in all three cities,” which is the claim "
        "the sentence makes."
    )
    assert entry["reason"]["session_ref"] == public_id(AI_ID)
    assert entry["quotes"] == [
        {
            "text": "named contacts doubled median tenure in all three cities,",
            "time": entry["reason"]["time"],
            "session_ref": public_id(AI_ID),
        }
    ]


def test_a_work_named_only_in_search_results_has_no_reason(store, project, refs, tmp_path):
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(project, [("call", "WebSearch", {"query": "q"}, "Whitlock 2020, \"a quoted snippet of four words\".")]),
    )
    entry = provenance(store, project, refs)["works"]["whitlock2020"]
    assert entry["origin"] == "ai"
    assert entry["reason"] is None
    assert entry["quotes"] == []


def test_a_quoted_title_is_not_a_quote_of_the_source(store, project, refs, tmp_path):
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(project, [("assistant", "Tanaka's \"Training length and volunteer retention\" fits here.")]),
    )
    assert provenance(store, project, refs)["works"]["tanaka2016"]["quotes"] == []


def test_the_ai_reading_the_scholars_draft_shows_the_scholars_draft(store, project, refs, tmp_path):
    draft = project / "draft.md"
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                ("call", "Read", {"file_path": str(draft)}, "Retention rises with fit (Castellanos and Ibe 2017)."),
                ("assistant", "Castellanos and Ibe (2017) back the first sentence."),
            ],
        ),
    )
    entry = provenance(store, project, refs)["works"]["castellanos2017"]
    assert entry["origin"] == "scholar"
    assert entry["first_scholar"]["artifact"] == "draft.md"


def test_the_ai_reading_a_file_it_wrote_shows_the_ai(store, project, refs, tmp_path):
    notes = project / "notes.md"
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                ("call", "Write", {"file_path": str(notes), "content": "Placeholder.\n"}, "File created."),
                ("call", "Read", {"file_path": str(notes)}, "Osei (2015) on motives."),
            ],
        ),
    )
    assert provenance(store, project, refs)["works"]["osei2015"]["origin"] == "ai"


def test_the_ai_searching_the_scholars_draft_shows_the_scholars_draft(store, project, refs, tmp_path):
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                ("call", "Grep", {"pattern": "fit", "path": str(project / "draft.md")}, "fit (Castellanos and Ibe 2017)"),
                ("assistant", "Castellanos and Ibe (2017) back the first sentence."),
            ],
        ),
    )
    assert provenance(store, project, refs)["works"]["castellanos2017"]["origin"] == "scholar"


def test_the_ai_searching_an_artifacts_folder_shows_the_ai(store, project, refs, tmp_path):
    folder = tmp_path / "ai_notes"
    folder.mkdir()
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [("call", "Grep", {"pattern": "Osei", "path": str(folder)}, "notes.md:Osei (2015) on motives.")],
        ),
    )
    entry = provenance(store, project, refs, [folder])["works"]["osei2015"]
    assert entry["origin"] == "ai"
    assert entry["first_ai"]["session_ref"] == public_id(AI_ID)


def test_the_ai_searching_a_file_it_wrote_shows_the_ai(store, project, refs, tmp_path):
    notes = project / "notes.md"
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                ("call", "Write", {"file_path": str(notes), "content": "Placeholder.\n"}, "File created."),
                ("call", "Grep", {"pattern": "Osei", "path": "notes.md"}, "Osei (2015) on motives."),
            ],
        ),
    )
    assert provenance(store, project, refs)["works"]["osei2015"]["origin"] == "ai"


AGENT = "b3c41e2b9d0f3856"


def test_a_subagent_prompt_the_ai_wrote_is_the_ais_words(store, project, refs, tmp_path):
    prompt = "Find the source for the motives sentence. Osei (2015) compares motives across city sizes."
    root = tmp_path / "root"
    main_file = root / (AI_ID + ".jsonl")
    main_file.parent.mkdir(parents=True)
    main_file.write_bytes(
        "".join(
            line + "\n"
            for line in session_lines(
                project,
                [
                    ("user", "Check the motives sentence."),
                    ("call", "Agent", {"description": "find a source", "prompt": prompt}, "Done."),
                ],
            )
        ).encode("utf-8")
    )
    agent_file = root / AI_ID / "subagents" / ("agent-" + AGENT + ".jsonl")
    agent_file.parent.mkdir(parents=True)
    agent_file.write_bytes(
        "".join(
            line + "\n"
            for line in session_lines(project, [("user", prompt), ("assistant", "Searching.")], minute=1, agent=AGENT)
        ).encode("utf-8")
    )
    summary = capture_session(store, "claude_code", main_file, NO_FOLDERS)
    assert [item.session_id for item in summary.subagents] == [AI_ID + "/agent-" + AGENT]
    entry = provenance(store, project, refs)["works"]["osei2015"]
    assert entry["origin"] == "ai"
    assert entry["first_scholar"] is None
    assert entry["first_ai"]["session_ref"] == public_id(AI_ID + "/agent-" + AGENT)
    assert entry["reason"]["text"] == prompt


def test_a_grep_content_line_shows_its_file_by_its_path_in_the_project(store, project, refs, tmp_path):
    draft = project / "draft.md"
    line = "{}:12:Motives differ by city size (Osei 2015).".format(draft)
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(project, [("call", "Grep", {"pattern": "Osei", "path": str(project)}, line)]),
    )
    entry = provenance(store, project, refs)["works"]["osei2015"]
    assert entry["first_scholar"]["excerpt"] == "draft.md:12:Motives differ by city size (Osei 2015)."
    assert str(tmp_path) not in yaml.safe_dump(entry)


def test_an_assistant_sentence_naming_a_full_path_shows_it_by_file_name(store, project, refs, tmp_path):
    scratch = tmp_path / "user" / "scratch" / "deep" / "sources.md"
    text = (
        "I saved the list to {}. Osei (2015) compares motives, and the paper says that "
        "\"motives in {} differ by size\". It fits."
    ).format(scratch, tmp_path / "user" / "cities.md")
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", text)]))
    entry = provenance(store, project, refs)["works"]["osei2015"]
    dumped = yaml.safe_dump(entry)
    assert str(tmp_path) not in dumped
    assert "user/" not in dumped
    assert entry["reason"]["text"].startswith("I saved the list to sources.md. Osei (2015)")
    assert entry["quotes"][0]["text"] == "motives in cities.md differ by size"


def test_a_cut_excerpt_never_shows_part_of_a_full_path(store, project, refs, tmp_path):
    scratch = tmp_path / "user" / "scratch" / "deep" / "notes.md"
    text = ("word " * 200) + str(scratch) + " says " + ("x " * 40) + "Osei (2015) matters " + ("word " * 200)
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", text)]))
    excerpt = provenance(store, project, refs)["works"]["osei2015"]["first_ai"]["excerpt"]
    assert "Osei (2015)" in excerpt
    assert "user/scratch" not in excerpt
    assert "notes.md says" in excerpt
    assert len(excerpt) <= EXCERPT_LIMIT + 6


def test_the_scholars_git_commit_through_the_wrappers_is_the_scholars(store, project, refs, tmp_path):
    day = "2026-10-22"
    events = tmp_path / "connections_home" / "events"
    events.mkdir(parents=True)
    path = events / "{}_abc.jsonl".format(day)
    line = {
        "harness": "wrappers",
        "harness_session_id": "{}_abc".format(day),
        "source_id": "{:032x}".format(1),
        "verb": "committed",
        "kind": "action",
        "object": "git commit -m Cite Osei 2015 on motives",
        "rationale": "Cite Osei 2015 on motives",
        "role": "",
        "at": "{}T01:00:00-07:00".format(day),
        "cwd": str(project),
        "program": "git",
    }
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    capture_session(store, "wrappers", path, NO_FOLDERS)
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", "Osei (2015) is cited.")]))
    entry = provenance(store, project, refs)["works"]["osei2015"]
    assert entry["origin"] == "scholar"
    assert entry["first_scholar"]["session_ref"] == public_id("{}_abc".format(day))
    assert entry["first_scholar"]["time"] == "2026-10-22T01:00:00-07:00"


def test_a_session_run_in_an_excluded_folder_is_never_read(store, project, refs, tmp_path):
    private = project / "private"
    private.mkdir()
    settings = {"excluded_folders": [str(private)]}
    summary = capture(
        store,
        tmp_path / "private.jsonl",
        session_lines(private, [("assistant", "Osei (2015) is the source.")]),
        settings,
    )
    assert summary.excluded
    (tmp_path / "private.jsonl").unlink()
    assert provenance(store, project, refs)["works"]["osei2015"]["origin"] == "unknown"


def test_excerpts_are_short_and_hold_the_mention(store, project, refs, tmp_path):
    long_text = ("word " * 200) + "Osei (2015) matters " + ("word " * 200)
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", long_text)]))
    excerpt = provenance(store, project, refs)["works"]["osei2015"]["first_ai"]["excerpt"]
    assert len(excerpt) <= EXCERPT_LIMIT + 6
    assert "Osei (2015)" in excerpt


def test_a_bibtex_reference_list_reads_the_same_works(project, tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{tanaka2016,\n  author = {Tanaka, Hiroshi},\n  year = 2016,\n"
        "  title = {Training length and {volunteer} retention},\n  doi = {10.5555/psq.2016.0071}\n}\n"
        "@book{devries2021, author = {Maarten de Vries and Jo Ames}, date = {2021-03}, title = {Scheduling}}\n",
        encoding="utf-8",
    )
    works = read_references(bib)
    assert [work["key"] for work in works] == ["tanaka2016", "devries2021"]
    assert works[0]["title"] == "Training length and volunteer retention"
    assert works[0]["family"] == "Tanaka"
    assert works[0]["year"] == "2016"
    assert works[0]["doi"] == "10.5555/psq.2016.0071"
    assert works[1]["family"] == "de Vries"
    assert works[1]["year"] == "2021"


def test_a_listed_doi_given_as_a_link_is_read_as_the_doi(project, tmp_path):
    listed = {
        "references": [
            {
                "id": "tanaka2016",
                "author": [{"family": "Tanaka"}],
                "issued": {"raw": "2016-05"},
                "title": "Training length and volunteer retention",
                "DOI": "https://doi.org/10.5555/psq.2016.0071",
            }
        ]
    }
    path = tmp_path / "linked.yaml"
    path.write_text(yaml.safe_dump(listed), encoding="utf-8")
    work = read_references(path)[0]
    assert work["doi"] == "10.5555/psq.2016.0071"
    assert work["year"] == "2016"
    bib = tmp_path / "linked.bib"
    bib.write_text(
        "@article{tanaka2016, author = {Tanaka, Hiroshi}, year = 2016,"
        " doi = {http://dx.doi.org/10.5555/psq.2016.0071}}\n",
        encoding="utf-8",
    )
    assert read_references(bib)[0]["doi"] == "10.5555/psq.2016.0071"


def test_the_written_file_reads_back_as_the_record(store, project, refs, tmp_path):
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", "Osei (2015) on motives.")]))
    out = tmp_path / "citation_provenance.yaml"
    record = write_citation_provenance(store, project, read_references(refs), [], out)
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == record
    assert out.read_text(encoding="utf-8").startswith("# ")
    assert "&id" not in out.read_text(encoding="utf-8")


def test_the_write_out_command_writes_the_record(store, project, refs, tmp_path, capsys):
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", "Osei (2015) on motives.")]))
    folder = tmp_path / "ai_notes"
    folder.mkdir()
    (folder / "a.md").write_text("Tanaka (2016) on training.\n", encoding="utf-8")
    out = tmp_path / "out.yaml"
    code = main(
        [
            "write-out", "citation-provenance", "--project", str(project), "--references",
            str(refs), "--out", str(out), "--artifacts", str(folder),
        ]
    )
    assert code == 0
    works = yaml.safe_load(out.read_text(encoding="utf-8"))["works"]
    assert works["osei2015"]["origin"] == "ai"
    assert works["tanaka2016"]["origin"] == "ai"
    printed = capsys.readouterr().out
    assert printed.startswith("wrote {}, 5 works".format(out))
    assert "2 first named by an AI" in printed


def test_the_write_out_command_refuses_a_home_with_no_store(project, refs, tmp_path, capsys):
    code = main(
        [
            "write-out", "citation-provenance", "--home", str(tmp_path / "nowhere"), "--project",
            str(project), "--references", str(refs), "--out", str(tmp_path / "out.yaml"),
        ]
    )
    assert code == 1
    assert "there is no audit store" in capsys.readouterr().err
    assert not (tmp_path / "out.yaml").exists()


def test_the_write_out_command_refuses_a_reference_list_it_cannot_read(store, project, tmp_path, capsys):
    bad = tmp_path / "refs.yaml"
    bad.write_text("references: [1, 2]\n", encoding="utf-8")
    code = main(
        [
            "write-out", "citation-provenance", "--project", str(project), "--references",
            str(bad), "--out", str(tmp_path / "out.yaml"),
        ]
    )
    assert code == 1
    assert "could not write out the citation provenance" in capsys.readouterr().err
    assert not (tmp_path / "out.yaml").exists()


def test_the_write_out_command_refuses_an_artifacts_folder_that_is_not_there(store, project, refs, tmp_path, capsys):
    code = main(
        [
            "write-out", "citation-provenance", "--project", str(project), "--references",
            str(refs), "--out", str(tmp_path / "out.yaml"), "--artifacts", str(tmp_path / "gone"),
        ]
    )
    assert code == 1
    assert "is not a folder" in capsys.readouterr().err
    assert not (tmp_path / "out.yaml").exists()


# What the proposal's real record showed (2026-10-31). Text the harness puts in
# a user record, an agent's task handed to Forge, a loose author and year, and
# working files named one by one.


def test_a_task_notice_in_a_user_record_is_the_ais_not_the_scholars(store, project, refs, tmp_path):
    lines = session_lines(
        project,
        [
            ("user", "Find a source on volunteer motives."),
            ("user", "<task-notification>\nOsei (2015) compares motives across city sizes.</task-notification>"),
        ],
    )
    records = [json.loads(line) for line in lines]
    records[1]["origin"] = {"kind": "task-notification"}
    capture(store, tmp_path / "ai.jsonl", [json.dumps(record) for record in records])
    entry = provenance(store, project, refs)["works"]["osei2015"]
    assert entry["origin"] == "ai"
    assert entry["first_scholar"] is None
    assert entry["appearances"][0]["kind"] == "harness"
    # Text the harness wrote is no AI's stated reason.
    assert entry["reason"] is None


def test_a_compaction_summary_is_the_ais_not_the_scholars(store, project, refs, tmp_path):
    lines = session_lines(
        project,
        [("user", "This session is being continued from a previous conversation. Osei (2015) was chosen.")],
    )
    records = [json.loads(line) for line in lines]
    records[0]["isCompactSummary"] = True
    capture(store, tmp_path / "ai.jsonl", [json.dumps(record) for record in records])
    entry = provenance(store, project, refs)["works"]["osei2015"]
    assert entry["origin"] == "ai"
    assert entry["appearances"][0]["kind"] == "harness"


def forge_store(path, project, initiator, prompt):
    """A synthetic Forge database holding one conversation run in project."""
    import importlib.util
    import sqlite3

    spec = importlib.util.spec_from_file_location(
        "forgecode_make_store", Path(__file__).parent / "fixtures" / "forgecode" / "make_store.py"
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    context = {
        "conversation_id": "c-agent",
        "messages": [
            fixture.text_message("System", "You are a coding assistant."),
            fixture.system_message(str(project)),
            fixture.text_message("User", prompt),
            fixture.text_message("Assistant", "Searching for it."),
        ],
    }
    if initiator is not None:
        context["initiator"] = initiator
    db = sqlite3.connect(str(path))
    try:
        db.execute(fixture.TABLE)
        db.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c-agent", "A task", 1, json.dumps(context), "2026-10-22 09:10:00", "2026-10-22 09:11:00", None),
        )
        db.commit()
    finally:
        db.close()
    return str(path) + "#c-agent"


@pytest.mark.parametrize("initiator, by", [("agent", "ai"), (None, "scholar")])
def test_a_forge_conversation_an_agent_began_has_the_agents_prompt_as_the_ais_words(
    store, project, refs, tmp_path, initiator, by
):
    prompt = "Check the motives sentence. Osei (2015) compares motives across city sizes."
    location = forge_store(tmp_path / "forge.db", project, initiator, prompt)
    capture_session(store, "forgecode", location, NO_FOLDERS)
    entry = provenance(store, project, refs)["works"]["osei2015"]
    assert entry["origin"] == by
    assert entry["appearances"][0]["kind"] == "conversation"
    if by == "ai":
        assert entry["reason"]["text"] == prompt


def test_each_appearance_says_how_the_record_named_the_work(store, project, refs, tmp_path):
    draft = project / "draft.md"
    capture(
        store,
        tmp_path / "ai.jsonl",
        session_lines(
            project,
            [
                ("user", "Is Tanaka (2016) the right source?"),
                ("call", "Read", {"file_path": str(draft)}, "Training helps (Tanaka 2016)."),
                ("call", "Bash", {"command": "grep -n Tanaka notes.txt"}, "3: Tanaka 2016 on training"),
                ("call", "WebSearch", {"query": "training length"}, "Training length and volunteer retention"),
                ("assistant", "Tanaka (2016) fits the sentence."),
                ("call", "Write", {"file_path": str(project / "notes.md"), "content": "Tanaka (2016) on training."}, "ok"),
            ],
        ),
    )
    found = [
        (a["by"], a["kind"], a.get("tool"))
        for a in provenance(store, project, refs)["works"]["tanaka2016"]["appearances"]
    ]
    assert found == [
        ("scholar", "conversation", None),
        ("scholar", "read", "Read"),
        ("ai", "tool", "Bash"),
        ("ai", "tool", "WebSearch"),
        ("ai", "conversation", None),
        ("ai", "artifact", None),
    ]


MORE_REFERENCES = {
    "references": [
        {"id": "will2026", "author": [{"family": "Will"}, {"family": "Bu"}], "issued": 2026, "title": "Journal rules on AI writing"},
        {
            "id": "lu2026",
            "author": [{"family": "Lu"}, {"family": "Chen"}, {"family": "Wu"}],
            "issued": 2026,
            "title": "Procedural graphs for agents",
        },
        {"id": "oxford2026", "author": [{"literal": "Oxford University Press"}], "issued": 2026, "title": "Disclosing AI use"},
        {"id": "rule2018", "author": [{"family": "Rule"}], "issued": 2018, "title": "Exploration in computational notebooks"},
    ]
}


@pytest.mark.parametrize(
    "key, text, named",
    [
        ("will2026", "Will and Bu 2026 found that 70 percent of journals have rules.", True),
        ("will2026", "As Will & Bu (2026) report, few authors disclose.", True),
        ("will2026", "As will be clear by 2026-07-22, the goals stayed.", False),
        ("will2026", "Will (2026) alone is not this paper.", False),
        ("lu2026", "Lu et al. 2026 describe self-evolving graphs.", True),
        ("lu2026", "Lu, Chen, and Wu (2026) describe self-evolving graphs.", True),
        ("lu2026", "Lu, Lu, Lange, Yamada and Clune 2026 automate research.", False),
        ("oxford2026", "Oxford University Press's 2026 survey asked 2,606 researchers.", True),
        ("oxford2026", "Searches found trade press and one 2026 framework paper.", False),
        ("rule2018", "Rule et al. 2018 found notebooks cleaned before sharing.", True),
        ("rule2018", "The rule 2018 brought in still holds.", False),
    ],
    ids=[
        "two authors with and", "two authors with an ampersand", "a common word and a date", "one of two authors",
        "et al.", "the first three authors", "another paper's author list", "an organization in full",
        "the organization's last word", "one author", "the name in lower case",
    ],
)
def test_an_author_and_year_name_the_work_only_as_a_citation_of_it_would(store, project, tmp_path, key, text, named):
    path = project / "more_refs.yaml"
    path.write_text(yaml.safe_dump(MORE_REFERENCES, sort_keys=False), encoding="utf-8")
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", text)]))
    entry = provenance(store, project, path)["works"][key]
    assert bool(entry["appearances"]) is named


def test_a_bibtex_organization_is_named_in_full_and_by_its_short_name(project, tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@report{oxford2026,\n  author = {{Oxford University Press}},\n  year = {2026},\n"
        "  title = {Disclosing {AI} Use},\n}\n\n"
        "@book{jcgm2012,\n  author = {{JCGM (Joint Committee for Guides in Metrology)}},\n  year = {2012},\n"
        "  title = {International Vocabulary of Metrology},\n}\n",
        encoding="utf-8",
    )
    works = {work["key"]: work for work in read_references(bib)}
    assert works["oxford2026"]["family"] == "Oxford University Press"
    # An organization named with its short form first is matched by that short form.
    assert works["jcgm2012"]["family"] == "JCGM"


def test_a_single_file_can_be_named_as_an_ai_written_artifact(store, project, refs, tmp_path):
    folder = tmp_path / "working"
    folder.mkdir()
    ai_file = folder / "lit_notes.md"
    ai_file.write_text("Scheduling flexibility and volunteer hours, a study of 40 programs.\n", encoding="utf-8")
    own = folder / "my_draft.md"
    own.write_text("Osei (2015) compares motives across city sizes.\n", encoding="utf-8")
    works = provenance(store, project, refs, [ai_file])["works"]
    assert works["devries2021"]["origin"] == "ai"
    assert works["devries2021"]["appearances"][0]["artifact"] == "lit_notes.md"
    # A file in the same folder that is not named is not read as the AI's.
    assert works["osei2015"]["appearances"] == []


def test_the_write_out_command_takes_a_file_as_an_artifact(store, project, refs, tmp_path, capsys):
    ai_file = tmp_path / "lit_notes.md"
    ai_file.write_text("Scheduling flexibility and volunteer hours.\n", encoding="utf-8")
    out = tmp_path / "out.yaml"
    code = main(
        [
            "write-out", "citation-provenance", "--project", str(project), "--references",
            str(refs), "--out", str(out), "--artifacts", str(ai_file),
        ]
    )
    assert code == 0
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["works"]["devries2021"]["origin"] == "ai"


def test_the_write_out_command_refuses_artifacts_inside_an_excluded_folder(store, project, refs, tmp_path, capsys):
    # A folder whose sessions are never recorded is never read as artifacts either.
    records = tmp_path / "student_records"
    folder = records / "notes"
    folder.mkdir(parents=True)
    (folder / "notes.md").write_text("Osei (2015) compares motives.\n", encoding="utf-8")
    (tmp_path / "audit_home" / "settings.yaml").write_text(
        yaml.safe_dump({"excluded_folders": [str(records)]}), encoding="utf-8"
    )
    out = tmp_path / "out.yaml"
    code = main(
        [
            "write-out", "citation-provenance", "--project", str(project), "--references",
            str(refs), "--out", str(out), "--artifacts", str(folder),
        ]
    )
    assert code == 1
    assert "inside an excluded folder" in capsys.readouterr().err
    assert not out.exists()


def test_a_quote_comes_from_the_sentence_naming_the_work_or_the_next_not_the_rest_of_the_paragraph(
    store, project, refs, tmp_path
):
    # In a working file a paragraph can hold many works, each with its own quotes.
    paragraph = (
        "Okafor (2019) says “written role descriptions kept people for longer.” "
        "For tenure, Whitlock (2020) is the source. She writes that "
        "“named contacts doubled median tenure in all three cities.” "
        "Later on, Osei (2015) says “motives differ across the three city sizes.”"
    )
    capture(store, tmp_path / "ai.jsonl", session_lines(project, [("assistant", paragraph)]))
    entry = provenance(store, project, refs)["works"]["whitlock2020"]
    assert [q["text"] for q in entry["quotes"]] == ["named contacts doubled median tenure in all three cities."]


def test_a_fetched_source_is_ai_output_but_not_the_ais_own_words(store, project, refs, tmp_path, capsys):
    # A paper's text saved by a search names the works in its reference list. It shows
    # the AI found them, but it is no reason the AI gave.
    fetched = tmp_path / "fetched"
    fetched.mkdir()
    (fetched / "paper.md").write_text(
        "References\n\n[3] Osei, K. Volunteer motives across city sizes. Urban Affairs Notes (2015).\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.yaml"
    code = main(
        [
            "write-out", "citation-provenance", "--project", str(project), "--references",
            str(refs), "--out", str(out), "--fetched", str(fetched),
        ]
    )
    assert code == 0
    entry = yaml.safe_load(out.read_text(encoding="utf-8"))["works"]["osei2015"]
    assert entry["origin"] == "ai"
    assert entry["appearances"][0]["kind"] == "fetched"
    assert entry["appearances"][0]["artifact"] == "fetched/paper.md"
    assert entry["reason"] is None and entry["quotes"] == []
