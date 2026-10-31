"""Step S1. python3 -m features setup plan runs detection and writes nothing.

Every home is inside tmp_path. claude, forge, git, and the other programs are
reached only through detect's runner function, which each test replaces with
a stand-in that records each call, so no real program runs.
"""
import json
import os
from pathlib import Path

import pytest

from features import cli
from features.setup import decisions, detect, plan

SECRET = "sk-test-secret-0123456789"

MCP_ALL = ("workflow-kb: python3 -m connections serve kb - ✓ Connected\n"
           "workflow-audit: python3 -m connections serve audit - ✓ Connected\n"
           "workflow-events: python3 -m connections serve events - ✓ Connected\n")

CAPTURE = "/usr/bin/python3 /repo/audit_layer/hooks/claude_code_hook.py"

PROGRAMS = ("claude", "forge", "git", "gh", "make", "pandoc", "quarto", "Rscript")


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    """HOME and the three layer homes inside tmp_path, and the model key unset."""
    user = tmp_path / "user_home"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "features_home"))
    monkeypatch.delenv("WORKFLOW_MODEL_KEY", raising=False)
    return {"user": user, "audit": tmp_path / "audit_home",
            "connections": tmp_path / "connections_home", "features": tmp_path / "features_home"}


class StandIn(object):
    """The runner's stand-in. It answers by program and arguments and records each call."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        key = tuple([os.path.basename(argv[0])] + list(argv[1:]))
        for length in range(len(key), 0, -1):
            if key[:length] in self.answers:
                return self.answers[key[:length]]
        return (0, "%s 3.9.0.2\n" % key[0], "")


@pytest.fixture
def stand_in(monkeypatch):
    """Replace the runner, the program lookup, and the folder lookup. Change .programs to remove one."""
    runner = StandIn({("git", "config"): (0, "Test Scholar\n", ""),
                      ("claude", "mcp", "list"): (0, "", "")})
    runner.programs = set(PROGRAMS)
    runner.folders = set()
    monkeypatch.setattr(detect, "run_program", runner)
    monkeypatch.setattr(detect, "find_program",
                        lambda name: "/fake/bin/" + name if name in runner.programs else None)
    monkeypatch.setattr(detect, "folder_exists", lambda path: path in runner.folders)
    return runner


def run(capsys, *args):
    code = cli.main(["setup", "plan"] + list(args))
    out, err = capsys.readouterr()
    return code, out, err


def as_json(capsys, *args):
    code, out, err = run(capsys, "--json", *args)
    assert code == 0, err
    return json.loads(out)


def rows(capsys, *args):
    return {row["id"]: row for row in as_json(capsys, *args)["decisions"]}


def snapshot(folder):
    """Every file and folder under folder, with each file's bytes and times."""
    found = {}
    for path in sorted(Path(str(folder)).rglob("*")):
        stat = path.stat()
        found[str(path)] = (path.is_dir(), stat.st_mtime_ns,
                            None if path.is_dir() else path.read_bytes())
    return found


def fill_homes(homes):
    homes["audit"].mkdir()
    (homes["audit"] / "settings.yaml").write_text("excluded_folders:\n  - /records\n",
                                                  encoding="utf-8")
    homes["connections"].mkdir()
    (homes["connections"] / "provider.yaml").write_text(
        "base_url: http://127.0.0.1:9/v1\nmodel: first-model\n", encoding="utf-8")
    (homes["user"] / ".claude").mkdir()
    (homes["user"] / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": CAPTURE}]}]}}), encoding="utf-8")


# Writes nothing.


@pytest.mark.parametrize("filled", [False, True])
def test_setup_plan_writes_nothing_in_any_home(tmp_path, homes, stand_in, capsys, filled):
    if filled:
        fill_homes(homes)
    before = snapshot(tmp_path)
    assert run(capsys)[0] == 0
    assert run(capsys, "--json")[0] == 0
    assert run(capsys, "--home", str(tmp_path / "other_features"), "--audit-home",
               str(tmp_path / "other_audit"), "--connections-home",
               str(tmp_path / "other_connections"))[0] == 0
    assert snapshot(tmp_path) == before


def test_setup_plan_starts_no_program_but_through_the_stand_in(stand_in, capsys):
    run(capsys)
    started = sorted(set(os.path.basename(call[0]) for call in stand_in.calls))
    assert started == sorted(PROGRAMS)
    assert ["/fake/bin/claude", "mcp", "list"] in stand_in.calls
    assert ["/fake/bin/git", "config", "--global", "--get", "user.name"] in stand_in.calls


# The JSON object.


def test_the_json_holds_every_decision_in_order_with_its_state(stand_in, capsys):
    given = as_json(capsys)
    assert list(given) == ["decisions", "notes"]
    assert [row["id"] for row in given["decisions"]] == [item.id for item in decisions.DECISIONS]
    for row, item in zip(given["decisions"], decisions.DECISIONS):
        assert list(row) == list(plan.ROW_FIELDS)
        assert row["state"] in plan.STATES
        for field in decisions.Decision._fields:
            assert row[field] == getattr(item, field)
        if row["state"] == "default":
            assert row["detail"]
        if row["state"] == "open":
            assert row["question"]


def test_the_text_names_each_decision_with_its_state_and_each_open_question(stand_in, capsys):
    code, out, err = run(capsys)
    assert code == 0, err
    given = as_json(capsys)
    for row in given["decisions"]:
        assert "%s, %s" % (row["id"], row["state"]) in out
        if row["state"] == "open":
            assert row["question"] in out
        if row["detail"]:
            assert row["detail"] in out
    assert out.index("Once per scholar") < out.index("Once per project")
    assert "—" not in out


# Each decision's state.


def test_the_excluded_folders_stay_open_and_name_those_already_listed(homes, stand_in, capsys):
    assert rows(capsys)["excluded_folders"]["state"] == "open"
    fill_homes(homes)
    row = rows(capsys)["excluded_folders"]
    assert row["state"] == "open"
    assert "/records" in row["detail"]


def test_the_name_is_found_in_git_else_asked(stand_in, capsys):
    row = rows(capsys)["scholar_name"]
    assert row["state"] == "found" and "Test Scholar" in row["detail"]
    stand_in.answers[("git", "config")] = (1, "", "")
    assert rows(capsys)["scholar_name"]["state"] == "open"


def test_a_found_harness_is_named(stand_in, capsys):
    row = rows(capsys)["harness"]
    assert row["state"] == "found"
    assert "Claude Code" in row["detail"] and "ForgeCode" in row["detail"]
    stand_in.programs.discard("claude")
    row = rows(capsys)["harness"]
    assert row["state"] == "found"
    assert "Claude Code" not in row["detail"] and "ForgeCode" in row["detail"]


def test_a_missing_harness_is_reported_as_missing_and_asked(stand_in, capsys):
    stand_in.programs.difference_update({"claude", "forge"})
    row = rows(capsys)["harness"]
    assert row["state"] == "open"
    assert "not found" in row["detail"]
    assert row["question"] == decisions.by_id("harness").question
    code, out, err = run(capsys)
    assert "  harness, open\n" in out
    assert "harness, found" not in out


def test_the_model_key_is_reported_as_set_or_not_and_its_value_never_shown(stand_in, capsys,
                                                                           monkeypatch):
    row = rows(capsys)["model_key"]
    assert row["state"] == "missing" and "not set" in row["detail"]
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", SECRET)
    assert rows(capsys)["model_key"]["state"] == "found"
    code, text, err = run(capsys)
    code, data, err2 = run(capsys, "--json")
    for output in (text, err, data, err2):
        assert SECRET not in output


def test_the_provider_setting_already_written_is_found(homes, stand_in, capsys):
    found = rows(capsys)
    assert found["model_service"]["state"] == "open"
    assert found["token_limit"]["state"] == "default"
    assert "4,000" in found["token_limit"]["detail"]
    fill_homes(homes)
    (homes["connections"] / "provider.yaml").write_text(
        "base_url: http://127.0.0.1:9/v1\nmodel: first-model\nsecond_model: other-model\n"
        "token_limit: 65536\ntoken_limit_field: max_completion_tokens\n", encoding="utf-8")
    found = rows(capsys)
    assert found["model_service"]["state"] == "found"
    assert "http://127.0.0.1:9/v1" in found["model_service"]["detail"]
    assert found["model"]["state"] == "found" and "first-model" in found["model"]["detail"]
    assert found["second_model"]["state"] == "found"
    assert found["token_limit"]["state"] == "found"
    assert "65536" in found["token_limit"]["detail"]


def test_the_connections_home_option_is_where_the_provider_setting_is_read(tmp_path, stand_in,
                                                                           capsys):
    other = tmp_path / "other_connections"
    other.mkdir()
    (other / "provider.yaml").write_text("base_url: http://127.0.0.1:9/v1\nmodel: m\n",
                                         encoding="utf-8")
    assert rows(capsys)["model_service"]["state"] == "open"
    assert rows(capsys, "--connections-home", str(other))["model_service"]["state"] == "found"


def test_the_audit_home_option_is_where_the_excluded_folders_are_read(tmp_path, stand_in, capsys):
    other = tmp_path / "other_audit"
    other.mkdir()
    (other / "settings.yaml").write_text("excluded_folders:\n  - /elsewhere\n", encoding="utf-8")
    assert "/elsewhere" in rows(capsys, "--audit-home", str(other))["excluded_folders"]["detail"]


def test_the_homes_default_names_each_home_given(tmp_path, stand_in, capsys):
    row = rows(capsys, "--home", str(tmp_path / "f"), "--audit-home", str(tmp_path / "a"),
               "--connections-home", str(tmp_path / "c"))["homes"]
    assert row["state"] == "default"
    for name in ("f", "a", "c"):
        assert str(tmp_path / name) in row["detail"]


def test_make_missing_is_reported_with_its_install_line(stand_in, capsys):
    assert rows(capsys)["pandoc_make"]["state"] == "found"
    stand_in.programs.discard("make")
    row = rows(capsys)["pandoc_make"]
    assert row["state"] == "missing"
    assert detect.install_hint("make") in row["detail"]


def test_zotero_is_named_beside_the_citation_export_question(homes, stand_in, capsys):
    assert "Zotero" not in rows(capsys)["citation_export"]["detail"]
    stand_in.folders.add("/Applications/Zotero.app")
    row = rows(capsys)["citation_export"]
    assert row["state"] == "open" and "Zotero" in row["detail"]


def test_word_found_or_missing(stand_in, capsys):
    assert rows(capsys)["word"]["state"] == "missing"
    stand_in.folders.add("/Applications/Microsoft Word.app")
    found = rows(capsys)
    assert found["word"]["state"] == "found"
    assert found["word_review"]["state"] == "found"


def test_the_hooks_and_servers_already_present_are_found(homes, stand_in, capsys):
    found = rows(capsys)
    assert found["servers"]["state"] == "open"
    assert found["connect"]["state"] == "open"
    stand_in.answers[("claude", "mcp", "list")] = (0, MCP_ALL, "")
    (homes["user"] / ".claude").mkdir()
    (homes["user"] / ".claude" / "settings.json").write_text(json.dumps({"hooks": dict(
        (event, [{"hooks": [{"type": "command", "command": CAPTURE}]}])
        for event in ("Stop", "SubagentStop", "SessionEnd"))}), encoding="utf-8")
    found = rows(capsys)
    assert found["servers"]["state"] == "found"
    assert found["connect"]["state"] == "found"


def test_the_defaults_carry_their_values(stand_in, capsys):
    found = rows(capsys)
    for item in decisions.DECISIONS:
        if item.how == "default" and item.id not in ("homes", "token_limit"):
            assert found[item.id]["state"] == "default"
            assert found[item.id]["detail"] == item.default


def test_the_project_question_is_open(stand_in, capsys):
    row = rows(capsys)["products"]
    assert row["state"] == "open"
    assert row["question"] == decisions.by_id("products").question
