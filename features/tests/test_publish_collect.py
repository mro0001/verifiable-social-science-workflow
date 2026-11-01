"""Publish design A.1, A.2, R1 to R3, R7 to R9, R13, and R17. Reading a project to publish.

Each test builds a small project in tmp_path. A stand-in runner gives the
product map that ospipe products --json would give, except in the test of a
Makefile that ospipe add-product writes, where the layers run for real.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from features import layers
from features.publish import collect, model

ROOT = Path(__file__).resolve().parents[2]
PUBLISH = ROOT / "features" / "publish"

PAPER = {"name": "paper", "source": "paper.md", "builds_dir": "builds/paper",
         "verification_dir": "verification", "to": "docx", "manifest": "numbers.yml",
         "bib": "refs.bib"}
MAKEFILE = ("WORKFLOW ?= $(firstword $(wildcard ../workflow))\n"
            "OSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe\n"
            "\n"
            "paper: paper.md\n"
            "\t$(OSPIPE) build --manuscript paper.md --builds-dir builds/paper\n")


class StubRunner(object):
    """Gives the product map ospipe products --json would give, and records each call."""

    def __init__(self, products=(PAPER,), problems=()):
        self.products = [dict(product) for product in products]
        self.problems = list(problems)
        self.calls = []

    def __call__(self, layer, args, root=None, cwd=None, env=None, timeout=600):
        self.calls.append((layer, list(args), root, cwd))
        assert layer == "ospipe" and list(args) == ["products", "--json"]
        text = json.dumps({"products": self.products, "problems": self.problems})
        return layers.LayerResult(["ospipe"] + list(args), 0, text, "")


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and the home variables at temporary folders, so nothing real is touched."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    monkeypatch.delenv("CONNECTIONS_HOME", raising=False)
    monkeypatch.delenv("OBSERVABILITY_HOME", raising=False)
    return home


def write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def results(stream, run_id, items=(), decisions=()):
    return {"schema": "verification-results", "schema_version": 1, "stream": stream,
            "run_id": run_id, "procedure_version": 0.1, "inputs": {"paper.md": "sha256:00"},
            "items": list(items), "decisions": list(decisions)}


def write_json(path, value):
    return write(path, json.dumps(value, indent=2) + "\n")


def make_system(tmp_path, excluded=(), audit_excluded=()):
    audit = tmp_path / "audit_home"
    audit.mkdir(exist_ok=True)
    if audit_excluded is not None:
        write(audit / "settings.yaml", yaml.safe_dump({"excluded_folders": list(audit_excluded)}))
    return {"workflow_root": str(ROOT), "audit_home": str(audit),
            "excluded_folders": list(excluded), "scholar_name": "A. Scholar"}


def make_project(tmp_path, makefile=MAKEFILE):
    project = tmp_path / "project"
    write(project / "Makefile", makefile)
    write(project / "paper.md", "# Paper\n")
    write(project / "numbers.yml", "numbers:\n  n: 3\n  m: 4\n")
    write(project / "refs.bib", "@article{a,\n}\n@book{b,\n}\n% @misc{not}\n")
    write(project / "builds" / "paper" / "BUILDS.md",
          "# Builds\n\n| version | date | git | sha256 | purpose | baseline | reviewed |"
          " verification | runs |\n|---|---|---|---|---|---|---|---|---|\n"
          "| v001 | 2026-10-31 | - | abc | draft | - | no | unverified: prose | - |\n")
    return project


def run_collect(tmp_path, project, answers=None, system=None, runs=None, home=None,
                runner=None):
    system = system if system is not None else make_system(tmp_path)
    if answers is None:
        answers = collect.read_answers(None, project, system)
    runs = runs if runs is not None else tmp_path / "runs"
    return collect.collect(str(project), answers, system, str(runs), home,
                           runner=runner or StubRunner())


def answers_from(tmp_path, given, system=None, project=None):
    path = write(tmp_path / "answers.yaml", yaml.safe_dump(given))
    return collect.read_answers(str(path), str(project or tmp_path / "project"),
                                system if system is not None else make_system(tmp_path))


def left(found):
    return dict((relpath, rule) for relpath, rule, _ in found.left_out)


# The answers file.


def test_no_answers_file_gives_every_default(tmp_path):
    system = make_system(tmp_path)
    answers = collect.read_answers(None, str(tmp_path / "my_study"), system)
    assert answers.title == "Verification reports for my_study"
    assert answers.summary == ""
    assert answers.repo_url == ""
    assert answers.workflow_url == model.WORKFLOW_URL
    assert answers.workflow_folder == "verifiable-social-science-workflow"
    assert answers.runs == str(ROOT / "verification_procedures" / "runs")
    assert answers.exclude == []
    assert dict(answers.harness_names) == {"claude_code": "Claude Code", "forgecode": "ForgeCode"}
    assert answers.anonymous is True
    assert answers.sessions == {"skip": False, "also_folders": [], "no_summaries": False,
                                "withhold": [], "scrub_terms": ["A. Scholar", "Scholar"]}
    assert answers.check == {"terms": [], "allow": [], "max_file_mb": 100, "warn_file_mb": 50,
                             "rebuild": True}
    assert answers.github is None
    assert answers.phase_runs == {}
    assert answers.unknown_keys == []


def test_given_answers_are_kept_and_merged_with_the_defaults(tmp_path):
    answers = answers_from(tmp_path, {
        "title": "Reports", "workflow_url": "https://example.org/x/my-workflow.git/",
        "runs": "~/runs", "exclude": ["./docs/", "README.html"],
        "harness_names": {"aider": "Aider"}, "notes": {"prose": "A note."},
        "files": {"tools/": "Tools"},
        "sessions": {"also_folders": ["~/old"], "withhold": ["S0123456789ab"],
                     "scrub_terms": []},
        "check": {"allow": ["x", {"path": "project/*.tar:*"}], "max_file_mb": 10.5},
        "phase_runs": {"paper": {"data_analysis": "paper_analysis_2"}}})
    home = os.path.expanduser("~")
    assert answers.title == "Reports"
    assert answers.workflow_folder == "my-workflow"
    assert answers.runs == os.path.join(home, "runs")
    assert answers.exclude == ["docs/", "README.html"]
    assert answers.harness_names["aider"] == "Aider"
    assert answers.harness_names["claude_code"] == "Claude Code"
    assert answers.sessions["also_folders"] == [os.path.join(home, "old")]
    # An anonymous build always withholds the scholar's full name, whatever the list says.
    assert answers.sessions["scrub_terms"] == ["A. Scholar"]
    assert answers.check["allow"] == ["x", {"path": "project/*.tar:*"}]
    assert answers.check["max_file_mb"] == 10.5
    assert answers.phase_runs == {"paper": {"data_analysis": "paper_analysis_2"}}


@pytest.mark.parametrize("name, terms", [
    ("A. Scholar", ["A. Scholar", "Scholar"]),
    ("Jordan Doe", ["Jordan Doe", "Jordan", "Doe"]),
    ("  Jo   Ann  Smith-Jones Jr. ", ["Jo Ann Smith-Jones Jr.", "Ann", "Smith-Jones"]),
    ("O'Neil Li", ["O'Neil Li", "O'Neil"]),
    ("Smith", ["Smith"]),
    ("Ann ann", ["Ann ann", "Ann"]),
    ("", []),
    (None, []),
    (3, []),
])
def test_name_terms_are_the_name_and_its_words_of_three_letters_or_more(name, terms):
    assert collect.name_terms(name) == terms


def test_anonymous_scrubs_the_name_and_its_words_by_default(tmp_path):
    system = make_system(tmp_path)
    system["scholar_name"] = "Jordan B. Doe"
    answers = answers_from(tmp_path, {}, system=system)
    assert answers.anonymous is True
    assert answers.sessions["scrub_terms"] == ["Jordan B. Doe", "Jordan", "Doe"]
    # The answers choose the words, and the full name is always added.
    answers = answers_from(tmp_path, {"anonymous": True,
                                      "sessions": {"scrub_terms": ["J. Doe"]}}, system=system)
    assert answers.sessions["scrub_terms"] == ["Jordan B. Doe", "J. Doe"]
    answers = answers_from(tmp_path, {"sessions": {"scrub_terms": []}}, system=system)
    assert answers.sessions["scrub_terms"] == ["Jordan B. Doe"]
    answers = answers_from(tmp_path, {"sessions": {"scrub_terms": ["jordan b. doe", "Doe"]}},
                           system=system)
    assert answers.sessions["scrub_terms"] == ["jordan b. doe", "Doe"]


def test_not_anonymous_scrubs_nothing_unless_the_answers_say(tmp_path):
    system = make_system(tmp_path)
    answers = answers_from(tmp_path, {"anonymous": False}, system=system)
    assert answers.anonymous is False
    assert answers.sessions["scrub_terms"] == []
    answers = answers_from(tmp_path, {"anonymous": False,
                                      "sessions": {"scrub_terms": ["Scholar"]}}, system=system)
    assert answers.sessions["scrub_terms"] == ["Scholar"]
    with pytest.raises(model.PublishError) as caught:
        answers_from(tmp_path, {"anonymous": "no"}, system=system)
    assert str(caught.value) == "the answers file's anonymous must be true or false"


def test_unknown_keys_are_listed_and_become_a_note(tmp_path):
    project = make_project(tmp_path)
    answers = answers_from(tmp_path, {"titel": "x", "sessions": {"skp": True},
                                      "check": {"term": []}}, project=project)
    assert answers.unknown_keys == ["check.term", "sessions.skp", "titel"]
    found = run_collect(tmp_path, project, answers=answers)
    assert "the answers file has fields this command does not use: check.term, sessions.skp," \
           " titel" in found.notes


@pytest.mark.parametrize("given, words", [
    ({"title": 3}, "title must be text"),
    ({"exclude": ["../outside"]}, "exclude must be"),
    ({"exclude": ["/abs/path"]}, "exclude must be"),
    ({"exclude": "docs/"}, "exclude must be"),
    ({"runs": "relative/runs"}, "runs must be a full path"),
    ({"workflow_folder": "a/b"}, "workflow_folder must be"),
    ({"notes": {"methods": "x"}}, "notes must be"),
    ({"files": {"../x": "y"}}, "files must be"),
    ({"harness_names": {"aider": 3}}, "harness_names must be"),
    ({"sessions": {"skip": "yes"}}, "sessions skip must be true or false"),
    ({"sessions": {"also_folders": ["old"]}}, "sessions also_folders must be a full path"),
    ({"sessions": {"withhold": ["S12"]}}, "sessions withhold must be"),
    ({"check": {"max_file_mb": 0}}, "check max_file_mb must be a number above 0"),
    ({"check": {"allow": [{"where": "x"}]}}, "check allow must be"),
    ({"check": {"rebuild": 1}}, "check rebuild must be true or false"),
    ({"phase_runs": {"paper": {"data_mining": "r"}}}, "phase_runs must be"),
    ({"phase_runs": {"paper": {"data_analysis": "../r"}}}, "phase_runs must be"),
    ({"github": {"repo_name": "my repo", "remote_url": "u"}}, "github repo_name must be"),
    ({"github": {"repo_name": "r", "remote_url": "u", "visibility": "open"}},
     "github visibility must be private or public"),
])
def test_a_bad_value_stops_with_a_lowercase_message(tmp_path, given, words):
    with pytest.raises(model.PublishError) as caught:
        answers_from(tmp_path, given)
    message = str(caught.value)
    assert words in message
    assert message[:1] == message[:1].lower()


def test_an_answers_file_that_is_not_a_mapping_stops(tmp_path):
    path = write(tmp_path / "answers.yaml", "- a\n- b\n")
    with pytest.raises(model.PublishError, match="must be a mapping of fields"):
        collect.read_answers(str(path), str(tmp_path), make_system(tmp_path))


def test_the_github_block_needs_remote_url_when_create_with_is_none(tmp_path):
    with pytest.raises(model.PublishError) as caught:
        answers_from(tmp_path, {"github": {"repo_name": "demo"}})
    assert str(caught.value) == "the github block needs remote_url when create_with is none"


def test_the_github_block_needs_owner_when_create_with_is_gh(tmp_path):
    with pytest.raises(model.PublishError) as caught:
        answers_from(tmp_path, {"github": {"repo_name": "demo", "create_with": "gh"}})
    assert str(caught.value) == "the github block needs owner when create_with is gh"


def test_a_full_github_block_is_filled_with_the_defaults(tmp_path):
    answers = answers_from(tmp_path, {"github": {"repo_name": "demo",
                                                 "remote_url": "git@example.org:x/demo.git"}})
    assert answers.github == {"repo_name": "demo", "owner": "", "visibility": "private",
                              "create_with": "none", "remote_url": "git@example.org:x/demo.git",
                              "branch": "main",
                              "message": "First commit of the verification repository"}


# Excluded folders (design R7).


def test_inside_compares_whole_parts_and_ignores_case():
    assert collect.inside("/a/MPA", "/a/MPA")
    assert collect.inside("/a/mpa/class/x.csv", "/a/MPA")
    assert not collect.inside("/a/MPA_old", "/a/MPA")
    assert not collect.inside("/a", "/a/MPA")


def test_the_audit_settings_list_counts_even_when_system_lists_none(tmp_path, private_home):
    system = make_system(tmp_path, excluded=[], audit_excluded=["~/Private", "~/Other/"])
    notes = []
    found = collect.excluded_folders(system, notes)
    assert found == [os.path.realpath(str(private_home / "Private")),
                     os.path.realpath(str(private_home / "Other"))]
    assert notes == []


def test_unreadable_audit_settings_give_a_note_and_system_list_still_counts(tmp_path):
    system = make_system(tmp_path, excluded=[str(tmp_path / "Kept")], audit_excluded=None)
    write(tmp_path / "audit_home" / "settings.yaml", "excluded_folders: [\n")
    notes = []
    assert collect.excluded_folders(system, notes) == [os.path.realpath(str(tmp_path / "Kept"))]
    assert len(notes) == 1 and "audit home's settings.yaml cannot be read" in notes[0]
    assert str(tmp_path) not in notes[0]


def test_a_project_inside_an_excluded_folder_is_refused(tmp_path, private_home):
    project = make_project(private_home / "Private")
    system = make_system(tmp_path, audit_excluded=["~/private"])
    runner = StubRunner()
    with pytest.raises(model.PublishError) as caught:
        run_collect(tmp_path, project, system=system, runner=runner)
    assert str(caught.value).startswith("the project folder lies inside a folder the scholar"
                                        " excluded")
    assert runner.calls == []


def test_an_also_folder_inside_an_excluded_folder_is_refused(tmp_path, private_home):
    project = make_project(tmp_path)
    system = make_system(tmp_path, audit_excluded=["~/Private"])
    answers = answers_from(tmp_path, {"sessions": {"also_folders": ["~/Private/old"]}},
                           system=system, project=project)
    with pytest.raises(model.PublishError, match="also_folders entry lies inside"):
        run_collect(tmp_path, project, answers=answers, system=system)


def test_a_runs_folder_inside_an_excluded_folder_is_refused(tmp_path):
    project = make_project(tmp_path)
    system = make_system(tmp_path, excluded=[str(tmp_path / "secret")])
    with pytest.raises(model.PublishError, match="the runs folder lies inside"):
        run_collect(tmp_path, project, system=system, runs=tmp_path / "secret" / "runs")


def test_an_excluded_folder_inside_the_project_stops_before_anything_is_read(tmp_path):
    project = make_project(tmp_path)
    write(project / "class" / "grades.csv", "a,b\n")
    system = make_system(tmp_path, audit_excluded=[str(project / "CLASS")])
    runner = StubRunner()
    with pytest.raises(model.PublishError) as caught:
        run_collect(tmp_path, project, system=system, runner=runner)
    assert str(caught.value) == (
        "an excluded folder lies inside the project, so the session index could name its"
        " files; move it out or leave the project out of the index with sessions: {skip: true}")
    assert runner.calls == []


def test_an_excluded_folder_inside_an_also_folder_stops(tmp_path, private_home):
    project = make_project(tmp_path)
    system = make_system(tmp_path, audit_excluded=["~/old_study/class"])
    answers = answers_from(tmp_path, {"sessions": {"also_folders": ["~/old_study"]}},
                           system=system, project=project)
    runner = StubRunner()
    with pytest.raises(model.PublishError) as caught:
        run_collect(tmp_path, project, answers=answers, system=system, runner=runner)
    assert str(caught.value).startswith(
        "an excluded folder lies inside a sessions also_folders entry, so the session index"
        " could name its files; move it out")
    assert runner.calls == []
    skipped = answers_from(tmp_path, {"sessions": {"skip": True,
                                                   "also_folders": ["~/old_study"]}},
                           system=system, project=project)
    found = run_collect(tmp_path, project, answers=skipped, system=system)
    assert found.products[0].name == "paper"


def test_with_the_index_skipped_an_excluded_folder_in_the_project_is_pruned_unopened(
        tmp_path, monkeypatch):
    project = make_project(tmp_path)
    write(project / "class" / "grades.csv", "a,b\n")
    write(project / "class" / "deep" / "more.csv", "c\n")
    system = make_system(tmp_path, audit_excluded=[str(project / "CLASS")])
    answers = answers_from(tmp_path, {"sessions": {"skip": True}}, system=system,
                           project=project)
    walked = []
    real_walk = os.walk

    def spy_walk(top, *args, **kwargs):
        for root, dirs, files in real_walk(top, *args, **kwargs):
            walked.append(root)
            yield root, dirs, files

    monkeypatch.setattr(collect.os, "walk", spy_walk)
    found = run_collect(tmp_path, project, answers=answers, system=system)
    assert left(found)["class/"] == "excluded_folder"
    assert not any(relpath.startswith("class") for relpath in found.project_files)
    assert not any(collect.inside(root, str(project / "class")) for root in walked)
    assert "a folder the scholar excluded lies inside the project folder and is left out" \
           " unopened" in found.notes
    assert found.excluded_folders == [os.path.realpath(str(project / "CLASS"))]


# What the walk leaves out (design A.2, R9).


def test_the_fixed_editor_history_and_exclude_rules_leave_files_out(tmp_path):
    project = make_project(tmp_path)
    for relpath in [".git/HEAD", "__pycache__/x.pyc", "sub/__pycache__/y.pyc", ".homes/a",
                    ".organizer/inventory.json", "node_modules/p/index.js", ".DS_Store",
                    "sub/._paper.md", "tool.pyc", "figures/src/f.aux", "figures/src/f.log",
                    "figures/src/f.log.txt", "audit/session_writes.jsonl", "sources/a.txt",
                    "notes/n.md", "ship/paper/x", "sessions/sessions.csv",
                    "verification/runs/r1/x.json", "old/run/manifest.json", "old/run/trail.jsonl",
                    ".claude/settings.json", "sub/.vscode/s.json", ".idea/x", ".venv/bin/python",
                    "venv/x", ".quarto/x", ".pytest_cache/x", ".ipynb_checkpoints/x",
                    ".Rproj.user/x", ".bash_history", "sub/.zsh_history", ".Rhistory",
                    ".python_history", ".viminfo", ".lesshst", "README.html", "docs/a.md",
                    "keep/notes/kept.md", "keep/audit/kept.md", "keep/sessions.md"]:
        write(project / relpath, "x\n")
    answers = answers_from(tmp_path, {"exclude": ["README.html", "docs/"]}, project=project)
    found = run_collect(tmp_path, project, answers=answers)
    rules = left(found)
    assert rules == {
        ".git/": "fixed", "__pycache__/": "fixed", "sub/__pycache__/": "fixed",
        ".homes/": "fixed", ".organizer/": "fixed", "node_modules/": "fixed",
        ".DS_Store": "fixed", "sub/._paper.md": "fixed", "tool.pyc": "fixed",
        "figures/src/f.aux": "fixed", "figures/src/f.log": "fixed",
        "figures/src/f.log.txt": "fixed", "audit/": "fixed", "sources/": "fixed",
        "notes/": "fixed", "ship/": "fixed", "sessions/": "fixed", "verification/runs/": "fixed",
        "old/run/": "fixed", ".claude/": "editor", "sub/.vscode/": "editor", ".idea/": "editor",
        ".venv/": "editor", "venv/": "editor", ".quarto/": "editor", ".pytest_cache/": "editor",
        ".ipynb_checkpoints/": "editor", ".Rproj.user/": "editor", ".bash_history": "history",
        "sub/.zsh_history": "history", ".Rhistory": "history", ".python_history": "history",
        ".viminfo": "history", ".lesshst": "history", "README.html": "exclude",
        "docs/": "exclude"}
    assert sorted(found.project_files) == [
        "Makefile", "builds/paper/BUILDS.md", "keep/audit/kept.md", "keep/notes/kept.md",
        "keep/sessions.md", "numbers.yml", "paper.md", "refs.bib"]
    reasons = dict((relpath, why) for relpath, _, why in found.left_out)
    assert reasons["audit/"] == "raw session ids and the AI's words, kept private"
    assert reasons["old/run/"] == ("a run folder, whose manifest names local paths and the"
                                   " model service")


def test_private_folders_written_with_a_capital_letter_are_left_out(tmp_path):
    # A Mac's disk ignores case, so Notes/ is the notes folder.
    project = make_project(tmp_path)
    for name in ("Notes/advisor.md", "Sources/scan.txt", "Ship/replication/readme.txt",
                 "Audit/x.jsonl", "Verification/Runs/r1/report.md", "x/.GIT/HEAD"):
        write(project / name, "x\n")
    rules = left(run_collect(tmp_path, project))
    for folder in ("Notes/", "Sources/", "Ship/", "Audit/", "Verification/Runs/", "x/.GIT/"):
        assert rules.get(folder) == "fixed", folder


def test_other_ai_tools_records_and_settings_files_are_left_out(tmp_path):
    project = make_project(tmp_path)
    for name in (".aider.chat.history.md", ".aider.input.history", ".specstory/history/chat.md",
                 ".cursor/rules/x.mdc", ".continue/config.json", ".codex/x", ".gemini/x",
                 ".windsurf/x", ".Rapp.history", ".RData", ".envrc"):
        write(project / name, "x\n")
    found = run_collect(tmp_path, project)
    rules = left(found)
    for name in (".aider.chat.history.md", ".aider.input.history", ".specstory/", ".cursor/",
                 ".continue/", ".codex/", ".gemini/", ".windsurf/", ".Rapp.history", ".RData",
                 ".envrc"):
        assert name in rules, name
    assert not [path for path in found.project_files if path.startswith((".", "x"))
                and path != ".gitignore"]


def test_a_folder_that_cannot_be_read_is_left_out_with_a_note(tmp_path):
    project = make_project(tmp_path)
    write(project / "secret_dir" / "a.txt", "x\n")
    os.chmod(str(project / "secret_dir"), 0)
    try:
        found = run_collect(tmp_path, project)
    finally:
        os.chmod(str(project / "secret_dir"), 0o755)
    assert ("secret_dir/", "unreadable", collect.UNREADABLE_WHY) in found.left_out
    assert collect.UNREADABLE_NOTE % (1, "folder", "it is", "it") in found.notes


def test_an_unreadable_ledger_or_results_file_stops_with_a_reason(tmp_path):
    project = make_project(tmp_path)
    ledger = project / "builds" / "paper" / "BUILDS.md"
    os.chmod(str(ledger), 0)
    try:
        with pytest.raises(model.PublishError) as raised:
            run_collect(tmp_path, project)
    finally:
        os.chmod(str(ledger), 0o644)
    assert str(raised.value) == "the ledger builds/paper/BUILDS.md cannot be read"
    path = write_json(project / "verification" / "prose.json", results("prose", "paper_prose"))
    os.chmod(str(path), 0)
    try:
        with pytest.raises(model.PublishError) as raised:
            run_collect(tmp_path, project)
    finally:
        os.chmod(str(path), 0o644)
    assert "verification/prose.json cannot be read (" in str(raised.value)


def test_a_run_file_that_cannot_be_read_counts_as_no_run(tmp_path):
    project = make_project(tmp_path)
    write_json(project / "verification" / "prose.json", results("prose", "paper_prose"))
    run = write_json(tmp_path / "runs" / "paper_prose" / "results.json",
                     results("prose", "paper_prose"))
    os.chmod(str(run), 0)
    try:
        found = run_collect(tmp_path, project)
    finally:
        os.chmod(str(run), 0o644)
    assert collect.NO_REPORT_NOTE % "paper_prose" in found.notes


def test_an_ssh_repository_address_becomes_its_web_address(tmp_path):
    answers = answers_from(tmp_path, {
        "repo_url": "git@github.com:example-scholar/story-verification.git",
        "workflow_url": "ssh://git@github.com/example/workflow.git"})
    assert answers.repo_url == "https://github.com/example-scholar/story-verification"
    assert answers.workflow_url == "https://github.com/example/workflow"
    assert answers.workflow_folder == "workflow"
    assert collect.web_url("https://example.org/a/b") == "https://example.org/a/b"


def test_notes_say_when_an_anonymous_build_has_no_name_or_leaves_words_out(tmp_path):
    project = make_project(tmp_path)
    system = make_system(tmp_path)
    system["scholar_name"] = ""
    found = run_collect(tmp_path, project, system=system)
    assert collect.NO_NAME_NOTE in found.notes
    system["scholar_name"] = "Jordan B. Doe"
    answers = answers_from(tmp_path, {"sessions": {"scrub_terms": ["J. Doe"]}}, system=system)
    found = run_collect(tmp_path, project, answers=answers, system=system)
    assert collect.WORDS_LEFT_NOTE % (2, "words", "them", "them") in found.notes
    assert not [note for note in found.notes if "Jordan" in note or "Doe" in note]


def test_an_excluded_folder_spelled_in_another_unicode_form_is_found(tmp_path, private_home):
    import unicodedata
    nfc = unicodedata.normalize("NFC", "Ense\u00f1anza")
    nfd = unicodedata.normalize("NFD", nfc)
    project = make_project(tmp_path / nfd)
    system = make_system(tmp_path, excluded=[str(tmp_path / nfc)])
    with pytest.raises(model.PublishError) as raised:
        run_collect(tmp_path, project, system=system)
    assert "the project folder lies inside a folder the scholar excluded" in str(raised.value)
    assert collect.inside(str(tmp_path / nfd / "x"), str(tmp_path / nfc))

    # An excluded folder inside the project, stored decomposed, excluded composed.
    project = make_project(tmp_path / "plain")
    write(project / nfd / "roster.csv", "Jane Roe,B+\n")
    system = make_system(tmp_path, excluded=[str(project / nfc)])
    answers = collect.read_answers(None, project, system)
    answers = answers._replace(sessions=dict(answers.sessions, skip=True))
    found = run_collect(tmp_path, project, answers=answers, system=system)
    assert not [path for path in found.project_files if "roster" in path]
    assert collect.relative_inside(str(project / nfd), str(project)) == nfc


def test_symbolic_links_are_left_out_and_listed(tmp_path):
    project = make_project(tmp_path)
    write(tmp_path / "outside" / "secret.txt", "x\n")
    os.symlink(str(tmp_path / "outside"), str(project / "linked_folder"))
    os.symlink(str(tmp_path / "outside" / "secret.txt"), str(project / "linked_file.txt"))
    found = run_collect(tmp_path, project)
    assert left(found)["linked_folder"] == "symlink"
    assert left(found)["linked_file.txt"] == "symlink"
    assert not any(relpath.startswith("linked") for relpath in found.project_files)


def test_a_workflow_home_inside_the_project_is_left_out(tmp_path):
    project = make_project(tmp_path)
    write(project / "my_audit" / "audit.sqlite", "db")
    write(project / "fhome" / "system.yaml", "x: 1\n")
    write(project / "conn" / "provider.yaml", "base_url: x\n")
    system = make_system(tmp_path)
    system["audit_home"] = str(project / "my_audit")
    system["connections_home"] = str(project / "conn")
    found = run_collect(tmp_path, project, system=system, home=str(project / "fhome"))
    assert left(found)["my_audit/"] == "home"
    assert left(found)["fhome/"] == "home"
    assert left(found)["conn/"] == "home"


# The .gitignore subset (design R8).


def test_gitignore_rules_follow_git_for_the_common_patterns(tmp_path):
    project = make_project(tmp_path)
    write(project / ".gitignore",
          "# a comment\n\n*.csv   \nfigures/src/*.pdf\na/b/\nbuild/\n/top_only.txt\n"
          "**/cache/\n!keep.csv\n")
    files = ["figures/src/fig.pdf", "figures/src/deep/kept.pdf", "figures/fig.pdf",
             "a/b/c.txt", "x/a/b/kept.txt", "data/raw.csv", "deep/build/out.txt",
             "deep/build", "top_only.txt", "sub/top_only.txt", "q/r/cache/c.bin", "keep.csv"]
    for relpath in files:
        if relpath == "deep/build":
            continue
        write(project / relpath, "x\n")
    write(project / "other" / "build", "a file named build\n")
    write(project / "data" / "restricted" / ".gitignore", "*\n")
    write(project / "data" / "restricted" / "interviews.txt", "x\n")
    write(project / "data" / "restricted" / "more" / "x.txt", "x\n")
    found = run_collect(tmp_path, project)
    rules = left(found)
    for relpath in ["figures/src/fig.pdf", "a/b/", "data/raw.csv", "deep/build/", "top_only.txt",
                    "q/r/cache/", "keep.csv", "data/restricted/interviews.txt",
                    "data/restricted/.gitignore", "data/restricted/more/"]:
        assert rules.get(relpath) == "gitignore", relpath
    for relpath in ["figures/src/deep/kept.pdf", "figures/fig.pdf", "x/a/b/kept.txt",
                    "sub/top_only.txt", "other/build"]:
        assert relpath in found.project_files, relpath
    assert ("a .gitignore negation in .gitignore is not applied, so what it would bring back"
            " stays out") in found.notes
    reasons = dict((relpath, why) for relpath, _, why in found.left_out)
    assert reasons["figures/src/fig.pdf"] == "matched by figures/src/*.pdf in .gitignore"


def fake_git(tmp_path, monkeypatch, body, version="echo 'git version 2.39.0'\nexit 0\n"):
    """A git on PATH that answers --version with version, rev-parse with true, and
    check-ignore with body."""
    folder = tmp_path / "fake_bin"
    folder.mkdir(exist_ok=True)
    script = write(folder / "git", "#!/bin/sh\nif [ \"$1\" = --version ]; then\n" + version
                   + "fi\ncase \"$*\" in *rev-parse*) echo true; exit 0;; esac\ncat > /dev/null\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", str(folder) + os.pathsep + os.environ.get("PATH", ""))


def test_git_check_ignore_adds_what_git_ignores_when_the_project_holds_git(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    (project / ".git").mkdir()
    write(project / "private.txt", "x\n")
    fake_git(tmp_path, monkeypatch, "printf 'private.txt\\000'\nexit 0\n")
    notes = []
    assert collect.gitignore_ignored(str(project), ["paper.md", "private.txt"], notes) == \
        {"private.txt"}
    assert notes == []
    found = run_collect(tmp_path, project)
    assert ("private.txt", "gitignore", "ignored by git") in found.left_out
    assert "private.txt" not in found.project_files


def test_git_that_cannot_run_gives_a_note(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    (project / ".git").mkdir()
    fake_git(tmp_path, monkeypatch, "echo 'xcrun: error' >&2\nexit 128\n")
    notes = []
    assert collect.gitignore_ignored(str(project), ["paper.md"], notes) == set()
    assert notes == [collect.GIT_NOTE]


def test_git_that_answers_one_with_an_error_or_fails_to_start_gives_a_note(tmp_path, monkeypatch):
    # The xcrun stand-in for git, with no Command Line Tools or from a Rosetta Python,
    # exits 1, which check-ignore also gives when it ignores nothing.
    project = make_project(tmp_path)
    (project / ".git").mkdir()
    fake_git(tmp_path, monkeypatch, "echo 'xcrun: error: unable to load libxcrun' >&2\nexit 1\n")
    notes = []
    assert collect.gitignore_ignored(str(project), ["paper.md"], notes) == set()
    assert notes == [collect.GIT_NOTE]
    fake_git(tmp_path, monkeypatch, "exit 0\n",
             version="echo 'xcrun: error: invalid active developer path' >&2\nexit 1\n")
    notes = []
    assert collect.gitignore_ignored(str(project), ["paper.md"], notes) == set()
    assert notes == [collect.GIT_NOTE]
    fake_git(tmp_path, monkeypatch, "exit 1\n")
    notes = []
    assert collect.gitignore_ignored(str(project), ["paper.md"], notes) == set()
    assert notes == []


def test_git_is_asked_when_a_parent_folder_is_the_repository(tmp_path, monkeypatch):
    # The project lies inside a repository it does not hold, so the parent's .gitignore
    # and info/exclude apply, and git answers for them.
    (tmp_path / ".git").mkdir()
    project = make_project(tmp_path)
    assert not (project / ".git").exists()
    write(project / "draft_for_committee.md", "x\n")
    fake_git(tmp_path, monkeypatch, "printf 'draft_for_committee.md\\000'\nexit 0\n")
    found = run_collect(tmp_path, project)
    assert ("draft_for_committee.md", "gitignore", "ignored by git") in found.left_out


def test_a_parent_repositorys_ignore_rules_apply_even_when_git_cannot_run(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    write(root / ".git" / "info" / "exclude", "draft_for_committee.md\n")
    write(root / ".gitignore", "*.private.csv\nsecrets/\n/project/top_only.md\n")
    project = make_project(root)
    for name in ("data/roster.private.csv", "secrets/x.txt", "draft_for_committee.md",
                 "top_only.md", "sub/top_only.md"):
        write(project / name, "x\n")
    fake_git(tmp_path, monkeypatch, "exit 0\n", version="echo 'xcrun: error' >&2\nexit 1\n")
    found = run_collect(root, project)
    for name in ("data/roster.private.csv", "secrets/", "draft_for_committee.md", "top_only.md"):
        assert left(found).get(name) == "gitignore", name
    assert "sub/top_only.md" in found.project_files
    assert collect.GIT_NOTE in found.notes


def git_runs():
    try:
        done = subprocess.run(["git", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return False
    return done.returncode == 0 and done.stdout.startswith(b"git version")


@pytest.mark.skipif(not git_runs(), reason="git does not run from this Python")
def test_a_real_parent_repository_and_its_exclude_file_are_applied(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    write(root / ".gitignore", "*.private.csv\nsecrets/\n")
    write(root / ".git" / "info" / "exclude", "draft_for_committee.md\n")
    project = make_project(root)
    for name in ("data/roster.private.csv", "secrets/x.txt", "draft_for_committee.md"):
        write(project / name, "x\n")
    found = run_collect(root, project)
    for name in ("data/roster.private.csv", "secrets/x.txt", "draft_for_committee.md"):
        assert name not in found.project_files, name


def test_gitignore_lines_are_read_as_git_reads_them(tmp_path):
    # A byte order mark, an escaped space, and a name in another case.
    project = make_project(tmp_path)
    (project / ".gitignore").write_bytes(b"\xef\xbb\xbfbom_hidden.txt\nmy\\ notes/\nHidden_Plan.md\n"
                                         b"trailing.txt   \n")
    for name in ("bom_hidden.txt", "my notes/plan.md", "hidden_plan.md", "trailing.txt", "kept.md"):
        write(project / name, "x\n")
    found = run_collect(tmp_path, project)
    for name in ("bom_hidden.txt", "my notes/plan.md", "hidden_plan.md", "trailing.txt"):
        assert name not in found.project_files, name
    assert "kept.md" in found.project_files


def test_no_git_is_run_when_the_project_holds_no_git(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    fake_git(tmp_path, monkeypatch, "exit 128\n")
    notes = []
    assert collect.gitignore_ignored(str(project), ["paper.md"], notes) == set()
    assert notes == []


# The Makefile (design R1).


def test_a_workflow_line_gets_the_relative_default(tmp_path):
    project = make_project(tmp_path, makefile=(
        "# The build file.\n"
        "WORKFLOW ?= $(firstword $(wildcard ../../x \\\n"
        "  ../private/worktree))\n" + MAKEFILE.split("\n", 1)[1]))
    answers = answers_from(tmp_path, {"workflow_folder": "public-workflow"}, project=project)
    found = run_collect(tmp_path, project, answers=answers)
    text = found.project_files["Makefile"].decode("utf-8")
    assert text.splitlines()[:3] == [
        "# The build file.", "WORKFLOW ?= ../../public-workflow",
        "OSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe"]
    assert "private" not in text
    assert found.makefile_style == "workflow_var"
    assert [path for path, _ in found.rewritten] == ["Makefile"]


def test_an_add_product_ospipe_line_becomes_a_workflow_line(tmp_path):
    root = str(ROOT)
    makefile = ("OSPIPE ?= PYTHONPATH='%s/ospipe' python3 -m ospipe\nMANIFEST ?= numbers.yml\n\n"
                "paper: paper.md\n\t$(OSPIPE) build --manuscript paper.md\n" % root)
    project = make_project(tmp_path, makefile=makefile)
    found = run_collect(tmp_path, project)
    text = found.project_files["Makefile"].decode("utf-8")
    assert text.splitlines()[:2] == [
        "WORKFLOW ?= ../../verifiable-social-science-workflow",
        "OSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe"]
    assert root not in text
    assert found.makefile_style == "workflow_var"
    assert len(found.rewritten) == 2


def test_a_makefile_with_neither_line_is_left_as_it_is(tmp_path):
    makefile = "paper: paper.md\n\tpython3 -m ospipe build --manuscript paper.md\n"
    project = make_project(tmp_path, makefile=makefile)
    found = run_collect(tmp_path, project)
    assert found.project_files["Makefile"] == makefile.encode("utf-8")
    assert found.makefile_style == "pythonpath_env"
    assert found.rewritten == []


@pytest.mark.parametrize("line", [
    "# built on %(home)s/Documents\n",
    "DATA ?= %(root)s/examples\n",
])
def test_a_machine_path_left_in_the_makefile_stops(tmp_path, private_home, line):
    makefile = MAKEFILE + line % {"home": str(private_home), "root": str(ROOT)}
    project = make_project(tmp_path, makefile=makefile)
    with pytest.raises(model.PublishError) as caught:
        run_collect(tmp_path, project)
    assert str(caught.value).startswith("the Makefile line 6 still names a folder on this machine")


def test_a_makefile_written_by_add_product_is_rewritten(tmp_path):
    project = tmp_path / "project"
    write(project / "paper.md", "# Paper\n")
    write(project / "numbers.yml", "numbers: {}\n")
    done = layers.run_layer("ospipe", ["add-product", "--name", "paper", "--source", "paper.md"],
                            root=str(ROOT), cwd=str(project))
    assert done.returncode == 0, done.stderr
    written = (project / "Makefile").read_text(encoding="utf-8")
    assert os.path.join(str(ROOT), "ospipe") in written
    found = run_collect(tmp_path, project, runner=layers.run_layer)
    text = found.project_files["Makefile"].decode("utf-8")
    assert "WORKFLOW ?= ../../verifiable-social-science-workflow" in text
    assert "OSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe" in text
    assert str(ROOT) not in text
    assert [product.name for product in found.products] == ["paper"]
    assert found.products[0].latest is None


# Products, groups, ledgers (design R2, R5).


def test_products_that_share_a_verification_folder_form_one_group(tmp_path):
    project = make_project(tmp_path)
    shared = dict(PAPER, verification_dir="verification")
    runner = StubRunner([dict(shared, name="manuscript", source="manuscript.md",
                              builds_dir="builds/manuscript"),
                         dict(shared, name="slides", source="slides.md", builds_dir="builds/s"),
                         dict(shared, name="poster", source="poster.md", builds_dir="builds/p"),
                         dict(shared, name="appendix", source="appendix.md",
                              builds_dir="builds/a", verification_dir="verification/appendix")])
    found = run_collect(tmp_path, project, runner=runner)
    assert [(group.key, group.label, group.verification_dir) for group in found.groups] == [
        ("manuscript+slides+poster", "manuscript, slides, and poster", "verification"),
        ("appendix", "appendix", "verification/appendix")]
    assert [product.name for product in found.groups[0].products] == \
        ["manuscript", "slides", "poster"]


def test_two_products_get_a_label_joined_with_and(tmp_path):
    project = make_project(tmp_path)
    runner = StubRunner([PAPER, dict(PAPER, name="slides", source="slides.md")])
    found = run_collect(tmp_path, project, runner=runner)
    assert found.groups[0].label == "paper and slides"
    assert found.groups[0].key == "paper+slides"


def test_a_project_with_no_product_is_refused(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(model.PublishError, match="no research product to publish"):
        run_collect(tmp_path, project, runner=StubRunner(products=[]))
    (project / "Makefile").unlink()
    with pytest.raises(model.PublishError, match="there is no build file"):
        run_collect(tmp_path, project)


def test_read_ledger_reads_nine_and_seven_column_rows(tmp_path):
    ledger = write(tmp_path / "builds" / "BUILDS.md",
                   "# Builds\n\n| version | date | git | sha256 | purpose | baseline | reviewed |\n"
                   "|---|---|---|---|---|---|---|\n"
                   "| v001 | 2026-10-30 | abc1234 | aaa | first | - | no |\n"
                   "| v002 | 2026-10-31 | - | bbb | draft | v001 | no | verified | prose=p1 |\n"
                   "| v003 | not a date | - | ccc | draft | - | no | x | - |\n"
                   "| bad | row |\n")
    rows = collect.read_ledger(str(ledger))
    assert rows[0] == model.LedgerRow("v001", "2026-10-30", "abc1234", "aaa", "first", "", "",
                                      1793318400)
    assert rows[1] == model.LedgerRow("v002", "2026-10-31", "-", "bbb", "draft", "verified",
                                      "prose=p1", 1793404800)
    assert rows[2].epoch is None
    assert len(rows) == 3
    assert collect.read_ledger(str(tmp_path / "builds")) == rows
    assert collect.read_ledger(str(tmp_path / "nowhere" / "BUILDS.md")) == []


def test_products_carry_their_ledger_and_latest_row(tmp_path):
    project = make_project(tmp_path)
    found = run_collect(tmp_path, project)
    product = found.products[0]
    assert product == model.Product("paper", "paper.md", "builds/paper", "verification", "docx",
                                    product.ledger, product.ledger[-1])
    assert product.latest.version == "v001" and product.latest.epoch == 1793404800


def test_numbers_references_and_pipeline_are_read_from_the_project_files(tmp_path):
    project = make_project(tmp_path)
    write(project / "pipeline.yaml", "steps:\n  - {id: a, script: s1.py}\n")
    write(project / "other.bib", "@misc{c,\n}\n")
    runner = StubRunner([PAPER, dict(PAPER, name="slides", source="slides.md", bib="other.bib",
                                     verification_dir="v2")])
    found = run_collect(tmp_path, project, runner=runner)
    assert found.numbers_keys == ["n", "m"]
    assert found.refs_works == 3
    assert found.pipeline == {"steps": [{"id": "a", "script": "s1.py"}]}
    (project / "pipeline.yaml").unlink()
    assert run_collect(tmp_path, project).pipeline is None


# Reports (design R3).


def prose_items():
    return [{"id": "c01", "kind": "change", "summary": "edit: x", "findings": [],
             "needs_decision": True}]


def test_a_run_whose_results_match_gives_the_report(tmp_path):
    project = make_project(tmp_path)
    stream_file = write_json(project / "verification" / "prose.json",
                             results("prose", "paper_prose", prose_items()))
    runs = tmp_path / "runs"
    write_json(runs / "paper_prose" / "results.json",
               results("prose", "paper_prose", prose_items()))
    write(runs / "paper_prose" / "files" / "report.md", "# Run report\n")
    found = run_collect(tmp_path, project, runs=runs)
    report = found.reports[0]
    assert (report.group.key, report.stream, report.run_id) == ("paper", "prose", "paper_prose")
    assert report.report_bytes == b"# Run report\n"
    assert report.report_from == "run paper_prose"
    assert report.results_bytes == stream_file.read_bytes()
    assert report.results["run_id"] == "paper_prose"
    assert report.note is None


def test_a_run_decided_later_gives_its_decided_report_and_a_note(tmp_path):
    project = make_project(tmp_path)
    write_json(project / "verification" / "prose.json",
               results("prose", "paper_prose", prose_items()))
    runs = tmp_path / "runs"
    decision = {"item": "c01", "decision": "approved", "by": "A. Scholar", "at": "2026-10-31",
                "run_id": "paper_prose"}
    write_json(runs / "paper_prose" / "results.json",
               results("prose", "paper_prose", prose_items(), [decision]))
    write(runs / "paper_prose" / "files" / "report.md", "# Run report\n")
    write(runs / "paper_prose" / "report_decided.md", "# Decided report\n")
    found = run_collect(tmp_path, project, runs=runs)
    report = found.reports[0]
    assert report.report_bytes == b"# Decided report\n"
    assert report.note == ("run paper_prose was decided after its results reached the project;"
                           " run handoffs/results_to_pipeline.py again")
    assert report.note in found.notes
    assert report.results["decisions"] == []


def test_a_stale_run_with_the_same_id_gives_way_to_the_project_report(tmp_path):
    project = make_project(tmp_path)
    write_json(project / "verification" / "prose.json",
               results("prose", "paper_prose", prose_items()))
    write_json(project / "verification" / "prose" / "results.json",
               results("prose", "paper_prose", prose_items()))
    write(project / "verification" / "prose" / "report.md", "# Project report\n")
    runs = tmp_path / "runs"
    write_json(runs / "paper_prose" / "results.json", results("prose", "paper_prose", []))
    write(runs / "paper_prose" / "files" / "report.md", "# Stale report\n")
    found = run_collect(tmp_path, project, runs=runs)
    report = found.reports[0]
    assert report.report_bytes == b"# Project report\n"
    assert report.report_from == "project"
    assert ("the runs folder holds another run named paper_prose, whose results differ from the"
            " project's, so its report is not used") in found.notes


def test_no_matching_report_leaves_the_report_out_with_a_note(tmp_path):
    project = make_project(tmp_path)
    data = write_json(project / "verification" / "prose.json",
                      results("prose", "paper_prose", prose_items())).read_bytes()
    write_json(project / "verification" / "prose" / "results.json",
               results("prose", "paper_prose", []))
    write(project / "verification" / "prose" / "report.md", "# Older report\n")
    found = run_collect(tmp_path, project)
    report = found.reports[0]
    assert report.report_bytes is None and report.report_from is None
    assert report.results_bytes == data
    assert report.note == ("no report for run paper_prose was found whose results match the"
                           " project's; the report is left out")
    assert "verification/prose/report.md" not in found.project_files
    assert ("verification/prose/report.md", "fixed",
            "a report whose results differ from the project's results file") in found.left_out


def test_a_stream_with_no_results_file_has_no_report(tmp_path):
    project = make_project(tmp_path)
    write_json(project / "verification" / "build.json", results("build", "paper_build"))
    found = run_collect(tmp_path, project)
    assert [report.stream for report in found.reports] == ["build"]


def phase_items():
    return [{"id": "d01", "kind": "description", "summary": "x", "findings": [],
             "needs_decision": True}]


def test_phase_reports_come_from_the_answers_then_the_run_manifest_then_the_project(tmp_path):
    project = make_project(tmp_path)
    write(project / "pipeline.yaml", "steps: []\n")
    runs = tmp_path / "runs"
    write_json(runs / "chosen_run" / "results.json",
               results("data_phases", "chosen_run", phase_items()))
    write(runs / "chosen_run" / "files" / "report.md", "# Chosen\n")
    write_json(runs / "paper_data_cleaning" / "results.json",
               results("data_phases", "paper_data_cleaning"))
    write_json(runs / "paper_data_cleaning" / "manifest.json",
               {"graph": {"path": "graphs/data_cleaning.yaml"}})
    write(runs / "paper_data_cleaning" / "files" / "report.md", "# Cleaning\n")
    write_json(runs / "paper_data_collection" / "results.json",
               results("data_phases", "paper_data_collection"))
    write_json(runs / "paper_data_collection" / "manifest.json",
               {"graph": {"path": "graphs/data_analysis.yaml"}})
    write_json(project / "verification" / "data_collection" / "results.json",
               results("data_phases", "own_collection"))
    write(project / "verification" / "data_collection" / "report.md", "# Own\n")
    answers = answers_from(tmp_path, {"phase_runs": {"paper": {"data_analysis": "chosen_run"}}},
                           project=project)
    found = run_collect(tmp_path, project, answers=answers, runs=runs)
    phases = dict((report.stream, report) for report in found.reports)
    assert phases["data_analysis"].report_bytes == b"# Chosen\n"
    assert phases["data_analysis"].report_from == "run chosen_run"
    assert phases["data_cleaning"].report_from == "run paper_data_cleaning"
    assert phases["data_collection"].report_from == "project"
    assert phases["data_collection"].report_bytes == b"# Own\n"
    assert phases["data_collection"].run_id == "own_collection"
    assert not any("no data phase report" in note for note in found.notes)


def test_a_missing_phase_gives_one_note_only_with_a_pipeline_and_data_results(tmp_path):
    project = make_project(tmp_path)
    write_json(project / "verification" / "data.json", results("data", "paper_data"))
    found = run_collect(tmp_path, project)
    assert not any("data phase report" in note for note in found.notes)
    write(project / "pipeline.yaml", "steps: []\n")
    found = run_collect(tmp_path, project)
    notes = [note for note in found.notes if "data phase report" in note]
    assert notes == ["the project has a pipeline.yaml, and no data phase report was found for"
                     " paper data collection, paper data cleaning, and paper data analysis"]


def test_the_phase_note_names_only_groups_that_have_data_results(tmp_path):
    project = make_project(tmp_path)
    write(project / "pipeline.yaml", "steps: []\n")
    appendix = dict(PAPER, name="appendix", source="appendix.md", builds_dir="builds/appendix",
                    verification_dir="verification/appendix")
    paper = dict(PAPER, verification_dir="verification/paper")
    write(project / "appendix.md", "# Appendix\n")
    write_json(project / "verification" / "paper" / "prose.json", results("prose", "paper_prose"))
    write_json(project / "verification" / "appendix" / "data.json",
               results("data", "appendix_data"))
    found = run_collect(tmp_path, project, runner=StubRunner(products=(paper, appendix)))
    notes = [note for note in found.notes if "data phase report" in note]
    assert notes == ["the project has a pipeline.yaml, and no data phase report was found for"
                     " appendix data collection, appendix data cleaning, and appendix data"
                     " analysis"]
    # A project whose groups have no data results gets no note at all.
    os.remove(str(project / "verification" / "appendix" / "data.json"))
    found = run_collect(tmp_path, project, runner=StubRunner(products=(paper, appendix)))
    assert not any("data phase report" in note for note in found.notes)


# The workflow's commit (design R17).


SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


def test_the_commit_is_read_from_a_loose_ref_or_packed_refs(tmp_path):
    root = tmp_path / "workflow"
    write(root / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(root / ".git" / "packed-refs", "# pack-refs with: peeled\n%s refs/heads/main\n" % SHA)
    assert collect.workflow_commit(str(root)) == SHA
    write(root / ".git" / "refs" / "heads" / "main", OTHER + "\n")
    assert collect.workflow_commit(str(root)) == OTHER
    write(root / ".git" / "HEAD", SHA + "\n")
    assert collect.workflow_commit(str(root)) == SHA


def test_a_worktree_commit_follows_gitdir_and_commondir(tmp_path):
    main = tmp_path / "main"
    write(main / ".git" / "packed-refs", "%s refs/heads/clean-build\n" % SHA)
    worktree_git = main / ".git" / "worktrees" / "clean-build"
    write(worktree_git / "HEAD", "ref: refs/heads/clean-build\n")
    write(worktree_git / "commondir", "../..\n")
    worktree = tmp_path / "worktree"
    write(worktree / ".git", "gitdir: %s\n" % worktree_git)
    assert collect.workflow_commit(str(worktree)) == SHA


def test_an_unreadable_checkout_gives_unknown(tmp_path):
    assert collect.workflow_commit(str(tmp_path / "nothing")) == "unknown"
    write(tmp_path / "bare" / ".git" / "HEAD", "ref: refs/heads/none\n")
    assert collect.workflow_commit(str(tmp_path / "bare")) == "unknown"


def test_collect_records_the_workflow_and_its_commit(tmp_path):
    project = make_project(tmp_path)
    found = run_collect(tmp_path, project)
    assert found.workflow_root == str(ROOT)
    assert found.workflow_commit == collect.workflow_commit(str(ROOT))
    assert found.project_dir == str(project)


# Wording.


def test_the_publish_code_has_no_long_or_en_dash():
    for path in [PUBLISH / "collect.py", PUBLISH / "counts.py", PUBLISH / "__init__.py",
                 Path(__file__), Path(__file__).with_name("test_publish_counts.py")]:
        text = path.read_text(encoding="utf-8")
        assert chr(0x2014) not in text and chr(0x2013) not in text, path
