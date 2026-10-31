"""A store with at least one current row in every table, for the tests of Steps A18 to A21.

build_full_store(tmp) builds it inside the folder tmp from the test story and
Track A's own fixtures, as plan Step A18 lists. The story session and its
subagent conversation are swept, which captures them, adds their project, and
snapshots the files they wrote. The model pass tags both from the recorded
answers, and a person reviews the story session. The story's refs.bib is
added, with one retrieved original and one extracted text for nakamura2020.
One dataset is added with its codebook, and one knowledge entry is synced,
changed, and synced again, so it has one replaced version.

Every path it reads is copied into tmp first, and every harness the sweep
reaches is given its root, so no default root and no real session file is
read. Nothing here calls a model or the network. This file holds no tests.
"""
import json
import shutil
from pathlib import Path
from typing import NamedTuple

import yaml

from audit_layer.capture.sweep import sweep
from audit_layer.store import Store, open_store
from audit_layer.stores.data import add_dataset
from audit_layer.stores.knowledge import sync
from audit_layer.stores.sources import add_from_bib, add_text, attach_original
from audit_layer.tagging.answers import open_answers
from audit_layer.tagging.model_pass import due, tag_session
from audit_layer.tagging.review import review

ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "examples" / "test_story"
STORY_SESSION = STORY / "sessions" / "claude_code" / "story_session.jsonl"
FIXTURES = Path(__file__).parent / "fixtures"
SUBAGENT = FIXTURES / "claude_code" / "subagent.jsonl"
BOOK = FIXTURES / "model_pass" / "recorded_tags.json"
DATA = FIXTURES / "data" / "next_word_conditions.csv"
CODEBOOK = FIXTURES / "data" / "next_word_conditions_codebook.yaml"
NAKAMURA = STORY / "references" / "source_nakamura2020.txt"
TOKEN = "{{PROJECT}}"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
AGENT_ID = "a7c41e2b9d0f3856"
SUBAGENT_ID = STORY_ID + "/agent-" + AGENT_ID
ENCODED = "-encoded-project-folder"
REVIEWER = "A. Reviewer"
ENTRY_ID = "standards-numbers-from-files"
DATASET = "next_word_conditions"

# What the story session's Write gives source_notes.md.
SOURCE_NOTES = (
    "# Sources added in this session\n\nTwo findings were added after the sentence on fit in"
    " the Results section.\n\n- Dumont 2014, clear end dates and signing up again\n- Nakamura"
    " 2020, recognition events and exit among long-serving volunteers\n\nCheck both against the"
    " sources before the next build.\n"
)

# A synthetic entry file of the knowledge base, before and after it changes.
ENTRY = """\
---
id: standards-numbers-from-files
title: Every number comes from a file
source: standards/numbers.md
source_commit: {commit}
updated: 2026-10-20
group: STANDARDS
---

# Every number comes from a file

A number in the manuscript is read from a results file, never typed by hand. {more}
"""

GIVEN = {"session": "none", "origin": "full store", "method": "build_full_store", "reason": "test"}


class FullStore(NamedTuple):
    """The store build_full_store made, open, and the folders it made it from."""

    store: Store
    # The audit home, which holds the database and the file store.
    home: Path
    # The copy of the story's project folder the sessions ran in.
    project: Path
    # The Claude Code root the sweep read.
    claude_root: Path
    settings: dict


def _lines(source: Path, project: Path):
    text = source.read_text(encoding="utf-8").replace(TOKEN, json.dumps(str(project))[1:-1])
    return "".join(line + "\n" for line in text.split("\n") if line)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def build_full_store(tmp) -> FullStore:
    """Build, inside tmp, a store with at least one current row in every table.

    The caller closes the store's database.
    """
    tmp = Path(tmp)
    project = tmp / "project"
    shutil.copytree(str(STORY / "project"), str(project))
    _write(project / "source_notes.md", SOURCE_NOTES)
    (project / "notes").mkdir()
    _write(
        project / "notes" / "reading_list.md",
        "# Reading list\n\n- A guide to plain-text social science [@healy2020].\n",
    )
    settings = {"excluded_folders": [str(project / "excluded_folder")]}

    claude_root = tmp / "claude_root"
    _write(claude_root / ENCODED / (STORY_ID + ".jsonl"), _lines(STORY_SESSION, project))
    _write(
        claude_root / ENCODED / STORY_ID / "subagents" / ("agent-" + AGENT_ID + ".jsonl"),
        _lines(SUBAGENT, project),
    )

    home = tmp / "audit_home"
    store = open_store(home)
    summary = sweep(store, settings, home, harnesses=["claude_code"], roots={"claude_code": str(claude_root)})
    if summary.failed or summary.refused or summary.captured != 2:
        raise AssertionError(f"the full store's sweep did not capture both sessions, {summary}")

    answers = open_answers(f"recorded:{BOOK}")
    for row in due(store):
        outcome = tag_session(store, row, answers)
        if outcome.status != "tagged":
            raise AssertionError(f"the full store's model pass failed, {outcome}")
    review(store, STORY_ID, REVIEWER, {"title": "Two findings on volunteer exit"}, {})

    bib = tmp / "inputs" / "refs.bib"
    bib.parent.mkdir(parents=True)
    shutil.copyfile(str(project / "refs.bib"), str(bib))
    add_from_bib(store, bib, GIVEN)
    original = tmp / "inputs" / NAKAMURA.name
    shutil.copyfile(str(NAKAMURA), str(original))
    attach_original(store, "nakamura2020", original, "copied from the test story", "2026-10-22", GIVEN)
    add_text(store, "nakamura2020", "fulltext", original, "plain text as given", GIVEN)

    csv_file = tmp / "inputs" / DATA.name
    shutil.copyfile(str(DATA), str(csv_file))
    descriptions = yaml.safe_load(CODEBOOK.read_text(encoding="utf-8"))
    add_dataset(store, DATASET, csv_file, "2026-10-20", descriptions, GIVEN)

    corpus = tmp / "corpus"
    entry = _write(corpus / "numbers.md", ENTRY.format(commit="3f2a9c1", more=""))
    sync(store, [corpus], GIVEN)
    _write(entry, ENTRY.format(commit="7b4e0d2", more="The build fails when the two differ."))
    synced = sync(store, [corpus], GIVEN)
    if synced.replaced != 1:
        raise AssertionError(f"the full store's knowledge entry was not replaced, {synced}")

    return FullStore(store, home, project, claude_root, settings)
