"""Checks on the story's data for the build stream (Track W, steps W5 and W7).

Appendix A2.5 "Build" asks that each product come only from its build, and the
build procedure's check_ai_touch flags an AI write in a builds folder. The
story's first session writes only source files, so a second short session
edits the built copy of the manuscript. The expected file of writes says what
the audit layer should write out for both sessions.

Appendix A2.3 "Project layout" asks that the project's build file name each
product's one source. The story project's Makefile has one rule for each
product, and each rule runs ospipe's build with the arguments the project
README gives.

Run from the repository root with python3 -m pytest examples/test_story.
Nothing here calls a model or the network.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

STORY = Path(__file__).resolve().parent
ROOT = STORY.parents[1]
PROJECT = STORY / "project"
SESSIONS = STORY / "sessions" / "claude_code"
STORY_SESSION = SESSIONS / "story_session.jsonl"
TOUCH_SESSION = SESSIONS / "build_touch_session.jsonl"
EXPECTED = STORY / "build" / "expected_session_writes.jsonl"
TOKEN = "{{PROJECT}}"
BUILT_COPY = TOKEN + "/builds/manuscript/v001.md"
MAKEFILE = PROJECT / "Makefile"
SOURCES = {"manuscript": "manuscript.md", "slides": "slides.md"}
PREREQS = {"manuscript": ["manuscript.md", "numbers.yml", "refs.bib", "top_words.md"],
           "slides": ["slides.md", "numbers.yml", "top_words.md"]}
BUILT = {"manuscript": "v001.docx", "slides": "v001.html"}


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def parts(record):
    content = (record.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def tool_uses(recs):
    return [p for r in recs for p in parts(r) if p.get("type") == "tool_use"]


def test_the_new_session_parses_as_json_lines_in_the_story_sessions_form():
    lines = TOUCH_SESSION.read_text(encoding="utf-8").splitlines()
    assert lines and all(line.strip() for line in lines)
    recs = [json.loads(line) for line in lines]
    story = records(STORY_SESSION)
    assert all(isinstance(r, dict) for r in recs)
    assert len({r["sessionId"] for r in recs}) == 1
    assert recs[0]["sessionId"] != story[0]["sessionId"]
    assert {r["type"] for r in recs} == {"user", "assistant"}
    for r in recs:
        # The same record fields as the story session's user and assistant records.
        same_type = [s for s in story if s["type"] == r["type"]]
        assert set(r) == set(same_type[0]), r["uuid"]
        assert r["cwd"] == TOKEN
        assert r["isSidechain"] is False
        assert r["message"]["role"] == r["type"]
        assert r["timestamp"].startswith("2026-10-22T")
    assert recs[0]["parentUuid"] is None
    for before, after in zip(recs, recs[1:]):
        assert after["parentUuid"] == before["uuid"]
    stamps = [r["timestamp"] for r in recs]
    assert stamps == sorted(stamps)
    assert stamps[0] > story[-1]["timestamp"]
    for use in tool_uses(recs):
        path = use["input"].get("file_path")
        assert path is None or path.startswith(TOKEN + "/")


def test_every_tool_use_in_the_new_session_has_a_matching_tool_result():
    used, answered = {}, {}
    for i, r in enumerate(records(TOUCH_SESSION)):
        for p in parts(r):
            if p.get("type") == "tool_use":
                assert r["type"] == "assistant"
                assert p["id"] not in used
                assert {"id", "name", "input"} <= set(p)
                used[p["id"]] = i
            elif p.get("type") == "tool_result":
                assert r["type"] == "user"
                assert p["tool_use_id"] not in answered
                answered[p["tool_use_id"]] = i
    assert used
    assert set(used) == set(answered)
    for tool_id, at in used.items():
        assert answered[tool_id] > at


def test_the_new_session_makes_one_edit_on_the_built_copy_and_closes():
    recs = records(TOUCH_SESSION)
    uses = tool_uses(recs)
    assert [u["name"] for u in uses] == ["Edit"]
    edit = uses[0]["input"]
    assert edit["file_path"] == BUILT_COPY
    assert edit["old_string"] == "This is a test manuscript."
    assert edit["new_string"] == "This is a short test manuscript."
    assert recs[0]["type"] == "user" and isinstance(recs[0]["message"]["content"], str)
    last = parts(recs[-1])
    assert recs[-1]["type"] == "assistant"
    assert [p["type"] for p in last] == ["text"]


def test_the_edits_old_text_occurs_once_in_the_manuscript_as_the_check_resolves_it(tmp_path):
    # The check runs on a copy, so the story's project stays as it is.
    project = tmp_path / "project"
    shutil.copytree(str(PROJECT), str(project))
    done = subprocess.run(
        [sys.executable, "-m", "ospipe", "check", "--manuscript", "manuscript.md",
         "--manifest", "numbers.yml", "--tables-dir", "."],
        cwd=str(project), capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH=str(ROOT / "ospipe")))
    assert done.returncode == 0, done.stdout + done.stderr
    edit = tool_uses(records(TOUCH_SESSION))[0]["input"]
    assert done.stdout.count(edit["old_string"]) == 1


def test_each_expected_write_has_the_five_keys_and_names_a_story_session():
    sessions = {records(path)[0]["sessionId"] for path in (STORY_SESSION, TOUCH_SESSION)}
    lines = EXPECTED.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    named = set()
    for line in lines:
        row = json.loads(line)
        assert sorted(row) == ["actor", "path", "session", "session_ref", "tool"]
        assert line == json.dumps(row, sort_keys=True)
        assert row["actor"] == "ai"
        assert row["tool"] in ("wrote", "edited")
        path = row["path"]
        assert "\\" not in path and not path.startswith("/") and TOKEN not in path
        assert ".." not in path.split("/")
        assert row["session"] in sessions
        # The session's public id, S and the first 12 hex characters of the sha256 of its id.
        assert row["session_ref"] == "S" + hashlib.sha256(row["session"].encode("utf-8")).hexdigest()[:12]
        named.add(row["session"])
    assert named == sessions


# ---------------------------------------------------------------- W7, the build file

def makefile():
    """A small reader for the story's Makefile. It gives the variables set with ?=,
    the .PHONY names, the comment lines, and each rule's prerequisites and recipe
    lines, the recipe lines being the tab-indented lines under the rule."""
    variables, phony, comments, rules = {}, [], [], {}
    current = None
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("\t"):
            assert current is not None, line
            rules[current]["recipe"].append(line[1:])
            continue
        current = None
        if not line.strip():
            continue
        if line.startswith("#"):
            comments.append(line)
            continue
        assign = re.match(r"^([A-Z]+) \?= (.*)$", line)
        if assign:
            variables[assign.group(1)] = assign.group(2)
            continue
        target, sep, rest = line.partition(":")
        assert sep, line
        if target == ".PHONY":
            phony = rest.split()
            continue
        assert target not in rules, target
        rules[target] = {"prereqs": rest.split(), "recipe": []}
        current = target
    return variables, phony, comments, rules


def recipe_args(rule, purpose):
    """The one recipe line of a rule as arguments, with $(OSPIPE) read as this
    Python's ospipe module and $(PURPOSE) as the purpose given."""
    recipe = makefile()[3][rule]["recipe"]
    assert len(recipe) == 1, recipe
    words = shlex.split(recipe[0])
    assert words[0] == "$(OSPIPE)", words
    args = [w.replace("$(PURPOSE)", purpose) for w in words[1:]]
    assert not any("$(" in a for a in args), args
    return args


def option_values(args, option):
    return [args[i + 1] for i, a in enumerate(args) if a == option]


def test_the_makefile_sets_its_two_variables_and_names_its_two_rules_phony():
    variables, phony, comments, rules = makefile()
    assert variables == {"OSPIPE": "python3 -m ospipe", "PURPOSE": "draft"}
    assert phony == ["manuscript", "slides"]
    assert any("PYTHONPATH" in c and "ospipe/" in c for c in comments), comments


def test_the_makefile_has_exactly_the_rules_manuscript_and_slides():
    rules = makefile()[3]
    assert sorted(rules) == ["manuscript", "slides"]
    for rule in rules:
        assert rules[rule]["prereqs"] == PREREQS[rule], rule


@pytest.mark.parametrize("rule", ["manuscript", "slides"])
def test_each_recipe_names_its_source_once_and_its_builds_folder(rule):
    args = recipe_args(rule, "draft")
    assert args[0] == "build"
    assert option_values(args, "--manuscript") == [SOURCES[rule]]
    assert args.count(SOURCES[rule]) == 1
    assert option_values(args, "--builds-dir") == ["builds/" + rule]
    assert option_values(args, "--manifest") == ["numbers.yml"]
    assert option_values(args, "--tables-dir") == ["."]
    assert option_values(args, "--purpose") == ["draft"]
    # Track B removes --allowlist from ospipe's check and build.
    assert "--allowlist" not in args
    if rule == "manuscript":
        assert option_values(args, "--bib") == ["refs.bib"] and "--to" not in args
    else:
        assert option_values(args, "--to") == ["revealjs"] and "--bib" not in args


@pytest.mark.parametrize("rule", ["manuscript", "slides"])
def test_each_recipe_run_through_ospipe_builds_v001_of_its_product(tmp_path, rule):
    # The build runs on a copy, so the story's project stays as it is.
    project = tmp_path / "project"
    shutil.copytree(str(PROJECT), str(project))
    args = recipe_args(rule, "story " + rule)
    done = subprocess.run([sys.executable, "-m", "ospipe"] + args,
                          cwd=str(project), capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=str(ROOT / "ospipe")))
    assert done.returncode == 0, done.stdout + done.stderr
    builds = project / "builds" / rule
    assert (builds / BUILT[rule]).is_file()
    assert (builds / "v001.md").is_file()
    ledger = (builds / "BUILDS.md").read_text(encoding="utf-8")
    assert "v001" in ledger and "story " + rule in ledger
    other = [r for r in SOURCES if r != rule][0]
    assert not (project / "builds" / other).exists()

