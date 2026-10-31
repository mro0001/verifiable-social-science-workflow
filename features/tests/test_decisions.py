"""Step S1. The one list of setup's decisions.

Every decision in the scope report's section 2 tables, once per scholar and
once per project, holds every field, has a unique id, and the system
questions come in the order of the scope report's section 3.
"""
import re

from features.setup import decisions

FIELDS = ("id", "scope", "question", "explain", "how", "when", "default", "changes")

SYSTEM_IDS = [
    "excluded_folders", "scholar_name", "model_service", "model", "second_model", "model_key",
    "token_limit", "citation_export", "harness", "statistical_software", "word",
    "version_control", "pandoc_make", "light_check", "full_reports", "live_view",
    "session_titles", "online_lookup", "past_sessions", "homes", "hook_python", "servers",
    "capture_schedule", "wrapper_functions", "connect",
]

PROJECT_IDS = ["products", "title", "project_citation_export", "word_review",
               "project_light_check", "github"]

YES = "Make these changes? Each one is listed above. [yes]"


def test_every_decision_has_every_field_and_a_unique_id():
    assert decisions.Decision._fields == FIELDS
    ids = [item.id for item in decisions.DECISIONS]
    assert len(ids) == len(set(ids))
    for item in decisions.DECISIONS:
        assert item.scope in ("system", "project"), item.id
        assert item.how in ("ask", "detect", "default", "yes"), item.id
        assert item.explain and item.explain.strip(), item.id
        assert item.changes and item.changes.strip(), item.id
        if item.how in ("ask", "yes"):
            assert item.question, item.id
        if item.how == "default":
            assert item.question is None and item.default, item.id
        if item.when is not None:
            assert item.question, item.id


def test_the_list_holds_each_row_of_the_scope_reports_two_tables_in_the_order_setup_meets_them():
    assert [item.id for item in decisions.system_decisions()] == SYSTEM_IDS
    assert [item.id for item in decisions.project_decisions()] == PROJECT_IDS
    assert [item.id for item in decisions.DECISIONS] == SYSTEM_IDS + PROJECT_IDS


def test_the_system_questions_come_in_the_order_of_section_3_with_its_words():
    asked = []
    for item in decisions.system_decisions():
        if item.question and item.question not in asked:
            asked.append(item.question)
    assert asked == [
        "Which folders hold work whose AI sessions must never be recorded, such as student"
        " records or advising notes? Give one full path a line. Type none if there are none.",
        "Your name, as your approvals will record it.",
        "Which model service should answer the checks' questions? Give its web address, or press"
        " Enter to skip for now. Your assistant's own model does not change.",
        "Which model on that service?",
        "Which second model, different from the first, should recheck doubtful source verdicts?"
        " Press Enter to skip.",
        "Which file does your reference manager export, such as a BibTeX file Zotero keeps up to"
        " date? Press Enter for none.",
        "No AI assistant program was found. Which do you use, Claude Code, ForgeCode, or another?"
        " You can also install one first.",
        YES,
    ]


def test_the_project_question_is_the_products_in_section_3s_words():
    asked = [item for item in decisions.project_decisions() if item.question]
    assert [item.id for item in asked] == ["products"]
    assert asked[0].question == (
        "This project will produce manuscript.md as a Word document. Press Enter to accept, or"
        " give each product on its own line as NAME:SOURCE:FORMAT.")


def test_conditional_questions_say_when_they_are_asked():
    when = {item.id: item.when for item in decisions.DECISIONS if item.when}
    assert set(when) == {"scholar_name", "model", "second_model", "harness"}
    assert "git" in when["scholar_name"]
    assert "no harness" in when["harness"]
    assert "model service" in when["model"] and "model service" in when["second_model"]


def test_the_one_yes_covers_the_connections_and_is_asked_last():
    yes = [item for item in decisions.DECISIONS if item.how == "yes"]
    assert [item.id for item in yes] == ["servers", "capture_schedule", "wrapper_functions",
                                         "connect"]
    assert all(item.question == YES and item.default == "yes" for item in yes)
    assert decisions.system_decisions()[-1].id == "connect"


def test_the_excluded_folders_have_no_default_and_the_key_is_never_asked():
    folders = decisions.by_id("excluded_folders")
    assert folders.how == "ask" and folders.default is None
    key = decisions.by_id("model_key")
    assert key.how == "detect" and key.question is None


def test_the_texts_use_plain_sentences_without_long_dashes_or_inner_colons():
    for item in decisions.DECISIONS:
        for text in (item.question, item.explain, item.changes, item.when, item.default):
            if not text:
                continue
            assert "—" not in text and "–" not in text, item.id
            # NAME:SOURCE:FORMAT is the format of a product line, not a colon in a sentence.
            assert ":" not in re.sub(r"NAME:SOURCE:FORMAT", "", text), item.id


def test_by_id_refuses_an_unknown_decision():
    try:
        decisions.by_id("favourite_colour")
    except KeyError as error:
        assert "favourite_colour" in str(error)
    else:
        raise AssertionError("an unknown id was given back")
