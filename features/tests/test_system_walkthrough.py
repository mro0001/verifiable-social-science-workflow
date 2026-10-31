"""Step S2. System setup asks the decisions in order.

The questions come in the order and words of decisions.py (scope report
section 3). The excluded folders come first and reach the audit settings
through audit_layer excluded add before any other file is written (stuck
point 1). A path that does not start with / or ~ and an empty first line are
asked again, and none gives none (stuck points 6 and 7). The provider
setting is written through connections provider set, never with a key. The
review screen names each change setup would make outside the workflow's own
homes and ends with the one yes, which until steps S5 to S8 is recorded in
system.yaml as connect: yes while the hand steps are printed.

Every test sets HOME, AUDIT_HOME, CONNECTIONS_HOME, and FEATURES_HOME inside
tmp_path. Detection is faked, and the one runner function for outside
programs, detect.run_program, is replaced with a stand-in that records each
call. The one network call, the service's list of models, reaches only a
stand-in server on 127.0.0.1. Run from the repository root as
python3 -m pytest -q features/tests.
"""
import datetime
import http.server
import io
import json
import os
import socket
import sqlite3
import threading
from pathlib import Path

import pytest
import yaml

from features import cli, layers
from features.setup import decisions, detect, system

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.datetime(2026, 10, 30, 9, 30, 0, tzinfo=datetime.timezone.utc)
SECRET = "sk-test-0123456789abcdef"
URL = "https://models.example.edu/v1"

COMMANDS = {
    "pandoc": "/fake/bin/pandoc",
    "make": "/fake/bin/make",
    "git": "/fake/bin/git",
    "gh": "/fake/bin/gh",
    "quarto": "/fake/bin/quarto",
    "Rscript": "/fake/bin/Rscript",
    "claude": "/fake/bin/claude",
    "forge": "/fake/bin/forge",
}


def fake_detector(missing=(), folders=True):
    commands = {name: path for name, path in COMMANDS.items() if name not in missing}

    def detector():
        return detect.detect(
            which=commands.get,
            run_version=lambda argv: (0, "%s 3.9.0.2\n" % os.path.basename(argv[0]), ""),
            path_exists=lambda path: folders,
            package_version=lambda name: "1.2.0",
            python_version=(3, 9, 5))
    return detector


def fake_state(git_name="", key_set=False, hooks=None, servers=()):
    return detect.State(git_name=git_name, model_key_set=key_set, excluded_folders=None,
                        hooks=hooks or {"capture": [], "trigger": []},
                        servers=list(servers), notes=[])


class Programs(object):
    """The stand-in for detect.run_program. It records each call and runs nothing."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        return 1, "", "a stand-in ran nothing"


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "env_connections_home"))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.delenv("WORKFLOW_MODEL_KEY", raising=False)
    programs = Programs()
    monkeypatch.setattr(detect, "run_program", programs)
    monkeypatch.setattr(detect, "find_program", lambda name: None)
    return home


@pytest.fixture
def programs():
    return detect.run_program


def q(decision_id):
    return decisions.by_id(decision_id).question


class Replies(object):
    def __init__(self, *replies):
        self.replies = list(replies)
        self.asked = []

    def __call__(self, prompt):
        self.asked.append(prompt)
        return self.replies.pop(0)


def ask(replies, found=None, state=None, models=None):
    out = io.StringIO()
    given = system.ask_answers((found or fake_detector())(), state or fake_state(), ask=replies,
                               out=out, models=models or (lambda url: []))
    return given, out.getvalue()


# The questions, in order and in the list's words.


def test_the_questions_come_in_the_lists_order_and_words():
    replies = Replies("/srv/records", "", "Test Scholar", URL, "open-model-70b", "", "")
    given, _ = ask(replies, models=lambda url: ["open-model-70b", "other-model-8b"])
    assert replies.asked[0] == q("excluded_folders") + " "
    assert replies.asked[1] == system.NEXT_FOLDER
    assert replies.asked[2:5] == [q("scholar_name") + " ", q("model_service") + " ",
                                  q("model") + " "]
    assert replies.asked[5].startswith("Which second model, different from the first,")
    assert "other-model-8b" in replies.asked[5]
    assert replies.asked[5].endswith("Press Enter to skip. ")
    assert replies.asked[6] == q("citation_export") + " "
    assert len(replies.asked) == 7
    assert given["excluded_folders"] == ["/srv/records"]
    assert given["scholar_name"] == "Test Scholar"
    assert (given["model_service"], given["model"], given["second_model"]) == (
        URL, "open-model-70b", "")


def test_the_system_questions_follow_the_order_of_the_decisions_list():
    ids = [item.id for item in decisions.system_decisions() if item.how == "ask"
           or item.id in ("scholar_name", "harness")]
    assert ids == ["excluded_folders", "scholar_name", "model_service", "model",
                   "second_model", "citation_export", "harness"]


def test_the_name_is_not_asked_when_git_has_one():
    replies = Replies("none", "", "")
    given, _ = ask(replies, state=fake_state(git_name="Git Scholar"))
    assert q("scholar_name") + " " not in replies.asked
    assert given["scholar_name"] == "Git Scholar"


def test_an_empty_name_is_asked_again():
    replies = Replies("none", "", "Test Scholar", "", "")
    given, out = ask(replies)
    assert replies.asked[1] == replies.asked[2] == q("scholar_name") + " "
    assert given["scholar_name"] == "Test Scholar"


@pytest.mark.parametrize("relative", ["records", "./records", "Documents/Courses"])
def test_a_path_not_starting_with_a_slash_or_tilde_is_asked_again(relative):
    replies = Replies(relative, "~/records", "", "Test Scholar", "", "")
    given, out = ask(replies)
    assert replies.asked[0] == replies.asked[1] == q("excluded_folders") + " "
    assert relative in out and "full path" in out
    assert given["excluded_folders"] == ["~/records"]


def test_a_relative_path_after_the_first_folder_is_asked_again():
    replies = Replies("/srv/records", "advising", "/srv/advising", "", "Test Scholar", "", "")
    given, out = ask(replies)
    assert replies.asked[1] == replies.asked[2] == system.NEXT_FOLDER
    assert given["excluded_folders"] == ["/srv/records", "/srv/advising"]


def test_an_empty_first_line_is_asked_again_and_none_gives_none():
    replies = Replies("", "None", "Test Scholar", "", "")
    given, out = ask(replies)
    assert replies.asked[0] == replies.asked[1] == q("excluded_folders") + " "
    assert "none" in out
    assert given["excluded_folders"] == []


def test_the_model_service_is_skipped_with_enter_and_its_questions_with_it():
    replies = Replies("none", "Test Scholar", "", "")
    given, _ = ask(replies)
    assert q("model") + " " not in replies.asked
    assert given["model_service"] == "" and given["model"] == ""


def test_a_service_that_is_not_a_web_address_is_asked_again():
    replies = Replies("none", "Test Scholar", "models.example.edu", URL, "m", "", "")
    given, out = ask(replies)
    assert replies.asked[2] == replies.asked[3] == q("model_service") + " "
    assert "http://" in out
    assert given["model_service"] == URL


def test_enter_at_the_model_skips_the_service():
    replies = Replies("none", "Test Scholar", URL, "", "")
    given, out = ask(replies)
    assert given["model_service"] == "" and given["model"] == ""
    assert "skipped" in out


def test_a_second_model_equal_to_the_first_is_asked_again():
    replies = Replies("none", "Test Scholar", URL, "m", "m", "n", "")
    given, out = ask(replies)
    assert replies.asked[4] == replies.asked[5]
    assert given["second_model"] == "n"


def test_with_no_list_of_models_the_second_question_proposes_nothing():
    replies = Replies("none", "Test Scholar", URL, "m", "", "")
    ask(replies, models=lambda url: [])
    assert replies.asked[4] == q("second_model") + " "


def test_zotero_is_named_before_the_citation_export_question():
    replies = Replies("none", "Test Scholar", "", "")
    _, out = ask(replies)
    assert "Zotero" in out


def test_the_harness_is_asked_last_and_only_when_none_is_found():
    replies = Replies("none", "Test Scholar", "", "", "ForgeCode")
    given, _ = ask(replies, found=fake_detector(missing=("claude", "forge")))
    assert replies.asked[-1] == q("harness") + " "
    assert given["harness"] == "forgecode"
    found = Replies("none", "Test Scholar", "", "")
    ask(found)
    assert q("harness") + " " not in found.asked


@pytest.mark.parametrize("reply, harness", [
    ("Claude Code", "claude_code"), ("claude", "claude_code"), ("forgecode", "forgecode"),
    ("another", "another"), ("Cursor", "another"), ("", ""),
])
def test_the_harness_answer_names_a_program_another_or_none(reply, harness):
    replies = Replies("none", "Test Scholar", "", "", reply)
    given, _ = ask(replies, found=fake_detector(missing=("claude", "forge")))
    assert given["harness"] == harness


# The service's list of models, from a stand-in server on 127.0.0.1.


@pytest.fixture
def model_server():
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            body = json.dumps({"object": "list", "data": [
                {"id": "open-model-70b"}, {"id": "other-model-8b"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/v1" % server.server_address[1], seen
    finally:
        server.shutdown()
        server.server_close()


def test_list_models_reads_the_services_list(model_server, monkeypatch):
    url, seen = model_server
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    assert system.list_models(url) == ["open-model-70b", "other-model-8b"]
    assert [path for path, _ in seen] == ["/v1/models"]


def test_the_second_model_is_proposed_from_the_stand_in_and_enter_skips_it(model_server,
                                                                           monkeypatch):
    url, seen = model_server
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", SECRET)
    replies = Replies("none", "Test Scholar", url, "open-model-70b", "", "")
    out = io.StringIO()
    given = system.ask_answers(fake_detector()(), fake_state(key_set=True), ask=replies, out=out)
    assert "other-model-8b" in replies.asked[4]
    assert given["second_model"] == ""
    assert len(seen) == 1
    assert SECRET not in out.getvalue() + "".join(replies.asked)


def test_a_service_that_does_not_answer_gives_no_list():
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        port = taken.getsockname()[1]
    assert system.list_models("http://127.0.0.1:%d/v1" % port, timeout=2) == []


# The answers file.


def write_answers(tmp_path, given):
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump(given), encoding="utf-8")
    return str(path)


def test_the_answers_file_takes_the_new_keys(tmp_path):
    path = write_answers(tmp_path, {
        "scholar_name": "Test Scholar", "excluded_folders": ["/srv/records"],
        "model_service": URL, "model": "a", "second_model": "b", "token_limit": 65536,
        "token_limit_field": "max_completion_tokens", "connect": True})
    given = system.read_answers(path)
    assert given["model_service"] == URL and given["second_model"] == "b"
    assert given["token_limit"] == 65536
    assert given["connect"] == "yes"
    for key in ("model_service", "model", "second_model", "token_limit", "token_limit_field",
                "connect"):
        assert key in system.FIELDS


def test_the_name_may_be_left_out_when_git_has_one(tmp_path):
    path = write_answers(tmp_path, {"excluded_folders": []})
    assert system.read_answers(path, git_name="Git Scholar")["scholar_name"] == "Git Scholar"
    with pytest.raises(system.SetupError) as raised:
        system.read_answers(path)
    assert "scholar_name" in str(raised.value)


def test_the_harness_may_be_left_out_and_another_is_allowed(tmp_path):
    path = write_answers(tmp_path, {"scholar_name": "S", "excluded_folders": [],
                                    "harness": "another"})
    assert system.read_answers(path)["harness"] == "another"


@pytest.mark.parametrize("more, named", [
    ({"excluded_folders": ["records"]}, "full path"),
    ({"model": "a"}, "model_service"),
    ({"model_service": "models.example.edu", "model": "a"}, "model_service"),
    ({"model_service": URL}, "model"),
    ({"model_service": URL, "model": "a", "second_model": "a"}, "second_model"),
    ({"model_service": URL, "model": "a", "token_limit": 100}, "token_limit_field"),
    ({"model_service": URL, "model": "a", "token_limit": 0, "token_limit_field": "max_tokens"},
     "token_limit"),
    ({"connect": "maybe"}, "connect"),
])
def test_a_wrong_answer_is_refused_and_named(tmp_path, more, named):
    given = {"scholar_name": "S", "excluded_folders": []}
    given.update(more)
    with pytest.raises(system.SetupError) as raised:
        system.read_answers(write_answers(tmp_path, given))
    assert named in str(raised.value)


def test_connect_left_out_or_no_is_no(tmp_path):
    path = write_answers(tmp_path, {"scholar_name": "S", "excluded_folders": []})
    assert system.read_answers(path)["connect"] == "no"
    path = write_answers(tmp_path, {"scholar_name": "S", "excluded_folders": [], "connect": "no"})
    assert system.read_answers(path)["connect"] == "no"


# What setup writes, and in what order.


class OrderSpy(object):
    """Runs each layer command for real and notes which files existed at each call."""

    def __init__(self, watched):
        self.watched = watched
        self.calls = []

    def __call__(self, layer, args, root=None, cwd=None, env=None, timeout=600):
        present = sorted(str(p) for top in self.watched if top.exists()
                         for p in top.rglob("*") if p.is_file())
        self.calls.append((layer, list(args), present))
        return layers.run_layer(layer, args, root=root, cwd=cwd, env=env, timeout=timeout)

    def writing(self):
        return [call for call in self.calls if call[1] != ["--help"]]


@pytest.fixture
def homes(tmp_path):
    return tmp_path / "features_home", tmp_path / "audit_home", tmp_path / "connections_home"


def answers(folders, **more):
    given = {"scholar_name": "Test Scholar", "excluded_folders": [str(f) for f in folders]}
    given.update(more)
    return given


def setup(homes, given, runner=None, detector=None, git_name=None):
    home, audit, connections = homes
    return system.run_system_setup(
        str(home), str(audit), given, str(ROOT), NOW, detector=detector or fake_detector(),
        runner=runner or layers.run_layer, connections_home=str(connections), git_name=git_name)


def read_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_the_excluded_folders_reach_the_audit_settings_before_any_other_file(homes):
    spy = OrderSpy(list(homes))
    setup(homes, answers(["/srv/records", "~/advising"], model_service=URL, model="a"),
          runner=spy)
    first, second = spy.writing()[:2]
    assert first[0] == "audit_layer" and first[1][:2] == ["excluded", "add"]
    assert first[2] == []
    assert second[0] == "connections" and second[1][:2] == ["provider", "set"]
    assert [call[1][:1] for call in spy.writing()] == [["excluded"], ["provider"]]
    home = Path(os.environ["HOME"])
    assert read_yaml(homes[1] / "settings.yaml")["excluded_folders"] == [
        "/srv/records", str(home / "advising")]
    assert read_yaml(homes[0] / "system.yaml")["excluded_folders"] == [
        "/srv/records", str(home / "advising")]


def test_an_earlier_list_in_the_audit_settings_is_kept(homes):
    audit = homes[1]
    assert layers.run_layer("audit_layer", ["init", "--home", str(audit)]).returncode == 0
    settings = audit / "settings.yaml"
    settings.write_text(settings.read_text(encoding="utf-8").replace(
        "excluded_folders: []", "excluded_folders:\n  - /srv/kept"), encoding="utf-8")
    setup(homes, answers(["/srv/records"]))
    assert read_yaml(settings)["excluded_folders"] == ["/srv/kept", "/srv/records"]


def test_folders_an_earlier_run_recorded_reach_the_audit_settings_too(homes):
    setup(homes, answers(["/srv/records"]))
    setup(homes, answers(["/srv/advising"]))
    assert read_yaml(homes[1] / "settings.yaml")["excluded_folders"] == [
        "/srv/records", "/srv/advising"]


def test_none_sets_up_the_audit_home_with_an_empty_list(homes):
    result = setup(homes, answers([]))
    assert read_yaml(homes[1] / "settings.yaml") == {"excluded_folders": []}
    assert result.audit_initialized is True


def test_capture_skips_a_session_in_a_folder_setup_listed(homes, tmp_path):
    story = ROOT / "examples" / "test_story" / "sessions" / "claude_code" / "excluded_session.jsonl"
    project = tmp_path / "project"
    (project / "excluded_folder").mkdir(parents=True)
    session = tmp_path / "excluded_session.jsonl"
    session.write_text(story.read_text(encoding="utf-8").replace("{{PROJECT}}", str(project)),
                       encoding="utf-8")
    setup(homes, answers([project / "excluded_folder"]))
    audit = homes[1]
    done = layers.run_layer("audit_layer", ["capture", "--harness", "claude_code", str(session)],
                            env={"AUDIT_HOME": str(audit)})
    assert done.returncode == 0, done.stderr
    db = sqlite3.connect(str(audit / "audit.sqlite"))
    try:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        db.close()


def test_the_provider_file_holds_the_answers_and_no_key(homes, monkeypatch):
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", SECRET)
    result = setup(homes, answers([], model_service=URL, model="a", second_model="b",
                                  token_limit=65536, token_limit_field="max_completion_tokens"))
    provider = homes[2] / "provider.yaml"
    assert read_yaml(provider) == {"base_url": URL, "model": "a", "second_model": "b",
                                   "token_limit": 65536,
                                   "token_limit_field": "max_completion_tokens"}
    for path in (provider, homes[0] / "system.yaml"):
        assert SECRET not in path.read_text(encoding="utf-8")
    assert result.provider == str(provider)


def test_an_earlier_output_limit_survives_a_run_that_gives_none(homes):
    setup(homes, answers([], model_service=URL, model="a", token_limit=65536,
                         token_limit_field="max_completion_tokens"))
    result = setup(homes, answers([], model_service=URL, model="c"))
    assert read_yaml(homes[2] / "provider.yaml") == {
        "base_url": URL, "model": "c", "token_limit": 65536,
        "token_limit_field": "max_completion_tokens"}
    assert any("65536" in message and "max_completion_tokens" in message
               for message in result.messages)


def test_a_limit_given_again_replaces_the_earlier_one(homes):
    setup(homes, answers([], model_service=URL, model="a", token_limit=65536,
                         token_limit_field="max_completion_tokens"))
    result = setup(homes, answers([], model_service=URL, model="a", token_limit=8000,
                                  token_limit_field="max_tokens"))
    assert read_yaml(homes[2] / "provider.yaml") == {
        "base_url": URL, "model": "a", "token_limit": 8000, "token_limit_field": "max_tokens"}
    assert not [message for message in result.messages if "65536" in message]


def test_an_earlier_request_timeout_survives_a_run_that_rewrites_the_setting(homes):
    homes[2].mkdir(parents=True)
    (homes[2] / "provider.yaml").write_text(
        "base_url: %s\nmodel: a\nrequest_timeout: 900\n" % URL, encoding="utf-8")
    result = setup(homes, answers([], model_service=URL, model="b"))
    assert read_yaml(homes[2] / "provider.yaml") == {
        "base_url": URL, "model": "b", "request_timeout": 900}
    assert any("900" in message and "request" in message for message in result.messages)


def test_an_earlier_limit_with_no_field_is_kept_under_max_tokens(homes):
    homes[2].mkdir(parents=True)
    (homes[2] / "provider.yaml").write_text(
        "base_url: %s\nmodel: a\ntoken_limit: 12000\n" % URL, encoding="utf-8")
    setup(homes, answers([], model_service=URL, model="a"))
    assert read_yaml(homes[2] / "provider.yaml") == {
        "base_url": URL, "model": "a", "token_limit": 12000, "token_limit_field": "max_tokens"}


def test_an_earlier_setting_setup_cannot_read_is_named_and_replaced(homes):
    homes[2].mkdir(parents=True)
    (homes[2] / "provider.yaml").write_text("token_limit: [\n", encoding="utf-8")
    result = setup(homes, answers([], model_service=URL, model="a"))
    assert read_yaml(homes[2] / "provider.yaml") == {"base_url": URL, "model": "a"}
    assert any("could not be read" in message for message in result.messages)


def test_the_report_says_the_earlier_limit_was_kept(homes, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CONNECTIONS_HOME", str(homes[2]))
    setup(homes, answers([], model_service=URL, model="a", token_limit=65536,
                         token_limit_field="max_completion_tokens"))
    given = answers([], model_service=URL, model="a")
    code, out, err = run_command(command_args(homes, "--answers", write_answers(tmp_path, given)),
                                 monkeypatch, capsys)
    assert code == 0, err
    assert "65536" in out and "max_completion_tokens" in out


def test_with_no_service_no_provider_file_is_written(homes):
    spy = OrderSpy(list(homes))
    setup(homes, answers([]), runner=spy)
    assert not (homes[2] / "provider.yaml").exists()
    assert not [call for call in spy.calls if call[0] == "connections"]


def test_the_name_comes_from_git_when_the_answers_leave_it_out(homes):
    setup(homes, {"excluded_folders": []}, git_name="Git Scholar")
    assert read_yaml(homes[0] / "system.yaml")["scholar_name"] == "Git Scholar"


@pytest.mark.parametrize("connect", ["yes", "no"])
def test_the_answer_to_the_one_yes_is_recorded(homes, connect):
    setup(homes, answers([], connect=connect))
    assert read_yaml(homes[0] / "system.yaml")["connect"] == connect


def test_another_harness_is_recorded_as_such(homes):
    setup(homes, answers([], harness="another"), detector=fake_detector(missing=("claude", "forge")))
    assert read_yaml(homes[0] / "system.yaml")["harness"] == "another"


# The review screen.


def review(found=None, state=None, given=None, harness=None, platform="darwin",
           shell="/bin/zsh"):
    found = (found or fake_detector())()
    given = given or system.read_answers_from({"scholar_name": "S",
                                               "excluded_folders": ["/srv/records"]})
    if harness is None:
        harness = given["harness"] or system.default_harness(found)
    return "\n".join(system.review_screen(found, state or fake_state(), given, harness,
                                          platform=platform, shell=shell))


def test_the_review_names_each_change_for_claude_code_on_a_mac(private_home):
    text = review()
    settings = str(private_home / ".claude" / "settings.json")
    assert "capture hooks to %s" % settings in text
    assert "trigger hooks to %s" % settings in text
    assert "claude mcp add" in text
    for server in detect.SERVERS:
        assert server in text
    assert str(private_home / "Library" / "LaunchAgents" / "audit_layer.sweep.plist") in text
    assert "launchctl" in text
    assert str(private_home / ".zshrc") in text
    assert text.splitlines()[-1] == decisions.YES_QUESTION


def test_the_review_uses_crontab_elsewhere_and_the_shells_own_profile(private_home):
    text = review(platform="linux", shell="/bin/bash")
    assert "crontab" in text and "launchctl" not in text
    assert str(private_home / ".bashrc") in text


def test_the_review_for_forgecode_alone_changes_no_claude_settings():
    text = review(found=fake_detector(missing=("claude",)))
    assert "settings.json" not in text and "claude mcp add" not in text
    assert "every 30 minutes" in text
    assert "ForgeCode" in text and "server registration" in text


def test_the_review_with_no_harness_offers_only_the_wrapper_lines():
    text = review(found=fake_detector(missing=("claude", "forge")))
    changes = text.split(system.CHANGES_HEADING)[1]
    assert "wrapper functions" in changes
    assert "launchctl" not in changes and "settings.json" not in changes
    assert "No AI assistant program" in text


def test_the_review_leaves_out_what_is_already_in_place():
    state = fake_state(hooks={"capture": list(system.CAPTURE_EVENTS), "trigger": ["Stop"]},
                       servers=detect.SERVERS)
    text = review(state=state)
    assert "settings.json" not in text.split(system.CHANGES_HEADING)[1]
    assert "claude mcp add" not in text


def test_the_review_states_the_defaults():
    text = review()
    for decision_id in ("light_check", "full_reports", "live_view", "session_titles",
                        "online_lookup", "past_sessions"):
        assert decisions.by_id(decision_id).default in text
    assert "earlier sessions" in text.lower() or "from the day of setup on" in text


def test_the_review_lists_what_was_found_and_what_it_gets():
    given = system.read_answers_from({"scholar_name": "S", "excluded_folders": ["/srv/records"],
                                      "model_service": URL, "model": "a", "second_model": "b"})
    text = review(given=given)
    assert "Claude Code at /fake/bin/claude" in text
    assert "Microsoft Word" in text and "Zotero" in text
    assert URL in text and "/srv/records" in text
    assert "WORKFLOW_MODEL_KEY is not set" in text


# The command.


def snapshot(folder):
    found = {}
    for path in Path(folder).rglob("*"):
        found[str(path)] = path.read_bytes() if path.is_file() else None
    return found


def run_command(argv, monkeypatch, capsys, detector=None, state=None, interactive=False):
    monkeypatch.setattr(system, "detect", detector or fake_detector())
    monkeypatch.setattr(system, "detect_state", lambda audit: state or fake_state())
    monkeypatch.setattr(system, "_interactive", lambda: interactive)
    code = cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def command_args(homes, *more):
    home, audit, _ = homes
    return ["setup", "system", "--home", str(home), "--audit-home", str(audit)] + list(more)


@pytest.mark.parametrize("connect", [None, "no", "yes"])
def test_nothing_outside_the_workflows_homes_changes(homes, tmp_path, monkeypatch, capsys,
                                                     private_home, connect):
    (private_home / ".zshrc").write_text("# mine\n", encoding="utf-8")
    before = snapshot(private_home)
    given = answers(["/srv/records"])
    if connect:
        given["connect"] = connect
    monkeypatch.setenv("CONNECTIONS_HOME", str(homes[2]))
    code, out, err = run_command(command_args(homes, "--answers", write_answers(tmp_path, given)),
                                 monkeypatch, capsys)
    assert code == 0, err
    assert snapshot(private_home) == before
    assert detect.run_program.calls == []
    assert decisions.YES_QUESTION in out
    for guide in ("audit_layer/hooks/INSTALL.md", "connections/README.md"):
        assert guide in out
    assert read_yaml(homes[0] / "system.yaml")["connect"] == (connect or "no")
    if connect == "yes":
        assert "make them by hand" in out
    else:
        assert "changes nothing outside" in out


def test_the_review_comes_before_the_report(homes, tmp_path, monkeypatch, capsys):
    code, out, err = run_command(
        command_args(homes, "--answers", write_answers(tmp_path, answers([]))),
        monkeypatch, capsys)
    assert out.index(system.CHANGES_HEADING) < out.index("Wrote ")


def test_the_terminal_asks_the_one_yes_last_and_enter_says_yes(homes, monkeypatch, capsys):
    replies = Replies("none", "Test Scholar", "", "", "")
    monkeypatch.setattr("builtins.input", replies)
    code, out, err = run_command(command_args(homes), monkeypatch, capsys, interactive=True)
    assert code == 0, err
    assert replies.asked[-1] == decisions.YES_QUESTION + " "
    assert read_yaml(homes[0] / "system.yaml")["connect"] == "yes"


def test_the_terminal_takes_no_and_asks_again_after_another_answer(homes, monkeypatch, capsys):
    replies = Replies("none", "Test Scholar", "", "", "maybe", "no")
    monkeypatch.setattr("builtins.input", replies)
    code, out, err = run_command(command_args(homes), monkeypatch, capsys, interactive=True)
    assert code == 0, err
    assert replies.asked[-1] == replies.asked[-2] == decisions.YES_QUESTION + " "
    assert read_yaml(homes[0] / "system.yaml")["connect"] == "no"


def test_the_key_line_is_printed_when_a_service_is_given_and_the_key_is_not_set(
        homes, tmp_path, monkeypatch, capsys, private_home):
    monkeypatch.setenv("CONNECTIONS_HOME", str(homes[2]))
    given = answers([], model_service=URL, model="a")
    code, out, err = run_command(command_args(homes, "--answers", write_answers(tmp_path, given)),
                                 monkeypatch, capsys)
    assert code == 0, err
    assert "export WORKFLOW_MODEL_KEY=" in out
    assert str(private_home / ".zshrc") in out
    assert (homes[2] / "provider.yaml").is_file()


def test_the_key_is_never_printed_when_it_is_set(homes, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CONNECTIONS_HOME", str(homes[2]))
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", SECRET)
    given = answers([], model_service=URL, model="a")
    code, out, err = run_command(command_args(homes, "--answers", write_answers(tmp_path, given)),
                                 monkeypatch, capsys, state=fake_state(key_set=True))
    assert code == 0, err
    assert SECRET not in out + err
    assert "export WORKFLOW_MODEL_KEY=" not in out


def test_the_answers_file_may_leave_out_the_name_when_git_has_one(homes, tmp_path, monkeypatch,
                                                                  capsys):
    code, out, err = run_command(
        command_args(homes, "--answers", write_answers(tmp_path, {"excluded_folders": []})),
        monkeypatch, capsys, state=fake_state(git_name="Git Scholar"))
    assert code == 0, err
    assert read_yaml(homes[0] / "system.yaml")["scholar_name"] == "Git Scholar"
