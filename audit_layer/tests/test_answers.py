"""Tests for the answer source of the model pass (Track A, Step A8).

Appendix Table A4 gives the model pass one AI model call per session, A2.2
makes the model swappable through a provider setting, and Table A5 says the
audit store records the model of the tagging pass. Tests never call a model,
so this step builds the recorded kind only, recorded:<file>, a JSON book of
answers keyed by session id (plan choice 14). The provider setting is added
later as another kind in the same file.

Every book here is written to a temporary folder. Nothing here calls a model
or the network. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.tagging import answers  # noqa: E402
from audit_layer.tagging.answers import KINDS, open_answers  # noqa: E402

SOURCE = ROOT / "audit_layer" / "tagging" / "answers.py"

STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
OTHER_ID = "1d6e2f07-4c8b-4a3e-9f15-b2c7d0e8a462"

OBJECT_ANSWER = {
    "title": "Add two findings on volunteer exit",
    "gist": "The scholar asked for two findings and the AI added them with citations.",
    "summary": "A made-up summary.",
    "keywords": ["volunteer exit", "citations", "findings"],
    "decisions": [{"ordinal": 2, "rationale": "The scholar asked for the finding."}],
}


def write_book(folder, book, name="answers.json"):
    path = Path(folder) / name
    path.write_text(json.dumps(book), encoding="utf-8")
    return path


def test_recorded_is_the_registered_kind():
    assert "recorded" in KINDS


def test_a_recorded_text_answer_comes_back_with_the_book_as_its_model(tmp_path):
    book = write_book(tmp_path, {STORY_ID: "a recorded answer"}, name="story_answers.json")
    source = open_answers(f"recorded:{book}")

    text, model = source.ask(STORY_ID, "the prompt")

    assert text == "a recorded answer"
    assert model == "recorded:story_answers.json"


def test_the_model_names_the_file_and_not_its_folders(tmp_path):
    book = write_book(tmp_path, {STORY_ID: "a recorded answer"})
    _, model = open_answers(f"recorded:{book}").ask(STORY_ID, "the prompt")
    assert str(tmp_path) not in model
    assert model == "recorded:answers.json"


def test_an_object_answer_comes_back_as_json_text(tmp_path):
    book = write_book(tmp_path, {STORY_ID: OBJECT_ANSWER})
    text, _ = open_answers(f"recorded:{book}").ask(STORY_ID, "the prompt")
    assert isinstance(text, str)
    assert json.loads(text) == OBJECT_ANSWER


def test_each_key_gives_its_own_answer(tmp_path):
    book = write_book(tmp_path, {STORY_ID: "first", OTHER_ID: OBJECT_ANSWER})
    source = open_answers(f"recorded:{book}")
    assert source.ask(STORY_ID, "one prompt")[0] == "first"
    assert json.loads(source.ask(OTHER_ID, "another prompt")[0]) == OBJECT_ANSWER
    # Asking again gives the same answer.
    assert source.ask(STORY_ID, "one prompt")[0] == "first"


def test_a_missing_key_is_refused_by_name(tmp_path):
    book = write_book(tmp_path, {STORY_ID: "first"})
    source = open_answers(f"recorded:{book}")
    with pytest.raises(ValueError) as raised:
        source.ask(OTHER_ID, "the prompt")
    assert OTHER_ID in str(raised.value)


@pytest.mark.parametrize("spec", ["service:x", "openai"])
def test_an_unknown_kind_is_refused(spec):
    with pytest.raises(ValueError) as raised:
        open_answers(spec)
    assert "there is no answer source of the kind" in str(raised.value)


def test_recorded_without_a_file_is_refused():
    with pytest.raises(ValueError, match="recorded"):
        open_answers("recorded:")
    with pytest.raises(ValueError, match="recorded"):
        open_answers("recorded")


def test_a_book_that_is_missing_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no_such_book.json"):
        open_answers(f"recorded:{tmp_path / 'no_such_book.json'}")


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '"text"'])
def test_a_book_that_is_not_a_json_object_is_refused(tmp_path, content):
    path = tmp_path / "answers.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="answers.json"):
        open_answers(f"recorded:{path}")


@pytest.mark.parametrize("value", [None, 3, True])
def test_an_answer_that_is_neither_text_nor_an_object_is_refused(tmp_path, value):
    book = write_book(tmp_path, {STORY_ID: value})
    source = open_answers(f"recorded:{book}")
    with pytest.raises(ValueError) as raised:
        source.ask(STORY_ID, "the prompt")
    assert STORY_ID in str(raised.value)


def test_only_the_live_kind_reaches_the_network():
    # Track D's live kinds (step D16) post through urllib.request.urlopen, and
    # nothing outside their class may reach the network.
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"http", "socket"}
    live = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LiveAnswers")
    inside = {id(n) for n in ast.walk(live)}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "urlopen"]
    assert calls and all(id(n) in inside for n in calls)
    assert answers.__file__ == str(SOURCE)
