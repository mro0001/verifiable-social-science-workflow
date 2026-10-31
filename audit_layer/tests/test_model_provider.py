"""The audit model pass through the provider setting (Track D, step D16).

Appendix Table A4 gives the model pass one AI model call per session, and
Table A5 keeps its fields unreviewed until a person reviews them. A2.2 makes
the model swappable through a provider setting, a base URL and a model name,
and A6 reads the key from the environment. The pass's live kinds, live and
live:<model>, read provider.yaml in CONNECTIONS_HOME, else in
~/.workflow_connections, and the key from WORKFLOW_MODEL_KEY, as live
judgment does (reconciliation, Track D, D16).

The model service is stood in for inside the test process by replacing
urllib.request.urlopen, so nothing here reaches the network. The session is
the test story's synthetic Claude Code session, with its folder token
replaced with a temporary folder. No real session file is read. Run from the
repository root with python3 -m pytest -q audit_layer/tests.
"""
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.capture import capture_session  # noqa: E402
from audit_layer.cli import main  # noqa: E402
from audit_layer.queries import current_session  # noqa: E402
from audit_layer.store import open_store  # noqa: E402
from audit_layer.tagging import answers as answers_module  # noqa: E402
from audit_layer.tagging.answers import open_answers  # noqa: E402
from audit_layer.tagging.review import unreviewed  # noqa: E402

STORY_SESSION = ROOT / "examples" / "test_story" / "sessions" / "claude_code" / "story_session.jsonl"
BOOK = Path(__file__).parent / "fixtures" / "model_pass" / "recorded_tags.json"
STORY_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
TOKEN = "{{PROJECT}}"
BASE_URL = "http://127.0.0.1:9/v1"
DERIVED = ("title", "gist", "summary", "keywords")
TABLES = ("sessions", "events", "transcripts")


class StandIn:
    """A chat completions service that gives the story's recorded answer."""

    def __init__(self, reported="stand-in-model-2026"):
        self.reported = reported
        self.requests = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode())
        headers = {k.lower(): v for k, v in req.header_items()}
        self.requests.append({"url": req.full_url, "body": body, "headers": headers})
        answer = json.dumps(recorded(STORY_ID))
        data = {"model": self.reported or body["model"],
                "choices": [{"message": {"role": "assistant", "content": answer}}]}
        return io.BytesIO(json.dumps(data).encode())


def recorded(session_id):
    return json.loads(BOOK.read_text(encoding="utf-8"))[session_id]


def stored_rows(db, table):
    cursor = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def counts(home):
    store = open_store(home)
    try:
        return {table: len(stored_rows(store.db, table)) for table in TABLES}
    finally:
        store.db.close()


@pytest.fixture(autouse=True)
def folders(tmp_path, monkeypatch):
    home = tmp_path / "home_folder"
    home.mkdir()
    connections = tmp_path / "connections"
    connections.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CONNECTIONS_HOME", str(connections))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    monkeypatch.delenv("WORKFLOW_MODEL_KEY", raising=False)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    return connections


@pytest.fixture
def connections(folders):
    return folders


def write_provider(connections, base_url=BASE_URL, model="provider-model", extra=()):
    lines = []
    if base_url is not None:
        lines.append("base_url: %s" % base_url)
    if model is not None:
        lines.append("model: %s" % model)
    lines.extend(extra)
    (connections / "provider.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def home(tmp_path):
    """An audit home holding the captured story session."""
    project = tmp_path / "project"
    project.mkdir()
    text = STORY_SESSION.read_text(encoding="utf-8").replace(TOKEN, json.dumps(str(project))[1:-1])
    session = tmp_path / "root" / "-encoded-project-folder" / (STORY_ID + ".jsonl")
    session.parent.mkdir(parents=True)
    session.write_text(text, encoding="utf-8")
    home = tmp_path / "audit_home"
    store = open_store(home)
    try:
        capture_session(store, "claude_code", session,
                        {"excluded_folders": [str(project / "excluded_folder")]})
    finally:
        store.db.close()
    return home


@pytest.fixture
def service(monkeypatch):
    stand_in = StandIn()
    monkeypatch.setattr(urllib.request, "urlopen", stand_in)
    return stand_in


def story_row(home):
    store = open_store(home)
    try:
        return current_session(store, "claude_code", STORY_ID)
    finally:
        store.db.close()


def test_a_live_pass_sends_one_request_to_the_provider_and_stores_unreviewed_fields(
    home, connections, service, capsys
):
    write_provider(connections)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"tagged {STORY_ID}", "tagged 1 session, 0 failed"]
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request["url"] == BASE_URL + "/chat/completions"
    assert request["body"]["model"] == "provider-model"
    assert request["body"]["temperature"] == 0
    assert "authorization" not in request["headers"]
    row = story_row(home)
    answer = recorded(STORY_ID)
    assert {name: row[name] for name in DERIVED} == {name: answer[name] for name in DERIVED}
    assert row["origin"] == "model pass"
    assert row["method"] == "model_pass 1; model live:stand-in-model-2026"
    store = open_store(home)
    try:
        pending = unreviewed(store)
    finally:
        store.db.close()
    assert len(pending) == 1


def test_live_with_a_model_sends_that_model(home, connections, service):
    write_provider(connections)
    assert main(["tag", "--home", str(home), "--answers", "live:other-model"]) == 0
    assert [r["body"]["model"] for r in service.requests] == ["other-model"]


def test_the_key_travels_as_a_bearer_token_when_set(home, connections, service, monkeypatch):
    write_provider(connections)
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", "sk-test-value")
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    assert service.requests[0]["headers"]["authorization"] == "Bearer sk-test-value"
    store = open_store(home)
    try:
        for table in TABLES:
            assert "sk-test-value" not in json.dumps(stored_rows(store.db, table), default=str)
    finally:
        store.db.close()


def test_a_missing_provider_file_stops_the_pass_names_the_file_and_writes_nothing(
    home, connections, service, capsys
):
    held = counts(home)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 1
    err = capsys.readouterr().err
    assert str(connections / "provider.yaml") in err
    assert service.requests == []
    assert counts(home) == held
    assert story_row(home)["title"] is None


@pytest.mark.parametrize("missing", ["base_url", "model"])
def test_an_incomplete_provider_file_stops_the_pass_and_names_it(
    home, connections, service, capsys, missing
):
    write_provider(connections, **{missing: None})
    held = counts(home)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 1
    err = capsys.readouterr().err
    assert str(connections / "provider.yaml") in err and missing in err
    assert service.requests == []
    assert counts(home) == held


def test_the_provider_file_is_read_from_the_home_folder_without_connections_home(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CONNECTIONS_HOME", raising=False)
    folder = Path(os.environ["HOME"]) / ".workflow_connections"
    folder.mkdir()
    write_provider(folder, model="home-model")
    assert answers_module.provider_setting() == {"base_url": BASE_URL, "model": "home-model"}


def test_a_service_that_fails_four_times_fails_the_session_and_writes_nothing(
    home, connections, monkeypatch, capsys
):
    write_provider(connections)
    calls = []

    def failing(req, timeout=None):
        calls.append(req.full_url)
        raise OSError("service down")

    monkeypatch.setattr(urllib.request, "urlopen", failing)
    held = counts(home)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 1
    out = capsys.readouterr().out
    assert f"failed {STORY_ID}" in out and "service down" in out
    assert len(calls) == 4
    assert counts(home) == held


def test_recorded_mode_gives_the_same_fields_as_before(home):
    assert main(["tag", "--home", str(home), "--answers", f"recorded:{BOOK}"]) == 0
    row = story_row(home)
    answer = recorded(STORY_ID)
    assert {name: row[name] for name in DERIVED} == {name: answer[name] for name in DERIVED}
    assert row["method"] == "model_pass 1; model recorded:recorded_tags.json"


@pytest.mark.parametrize("spec", ["service:x", "openai", "livex"])
def test_another_kind_is_still_refused(spec):
    with pytest.raises(ValueError) as raised:
        open_answers(spec)
    assert "live" in str(raised.value) and "recorded" in str(raised.value)


def test_no_python_file_holds_the_old_service_address_or_its_key_name():
    address = "models" + ".anonymous-university" + ".edu"
    key_name = "MODEL_SERVICE" + "2_KEY"
    found = []
    for folder, names, files in os.walk(ROOT):
        names[:] = [n for n in names if n not in (".git", "runs", "__pycache__", ".worktrees")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(folder) / name
            text = path.read_text(encoding="utf-8", errors="replace")
            if address in text or key_name in text:
                found.append(str(path.relative_to(ROOT)))
    assert found == []


# The output limit (the ruling of 2026-10-29, step M5). The provider setting
# may name token_limit and token_limit_field. With neither, the request keeps the
# 4,000 tokens under max_tokens that Table A10 records.


def test_with_neither_limit_key_the_request_holds_max_tokens_4000_and_nothing_else(
    home, connections, service
):
    write_provider(connections)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    body = service.requests[0]["body"]
    assert body["max_tokens"] == 4000
    assert "max_completion_tokens" not in body


def test_a_named_limit_and_field_are_sent_under_that_field_only(home, connections, service):
    write_provider(connections, extra=["token_limit: 65536", "token_limit_field: max_completion_tokens"])
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    assert len(service.requests) == 1
    body = service.requests[0]["body"]
    assert body["max_completion_tokens"] == 65536
    assert "max_tokens" not in body


@pytest.mark.parametrize("extra, field, limit", [
    (["token_limit: 8000"], "max_tokens", 8000),
    (["token_limit_field: max_completion_tokens"], "max_completion_tokens", 4000),
])
def test_one_key_alone_keeps_the_other_at_its_old_value(home, connections, service, extra, field, limit):
    write_provider(connections, extra=extra)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    other = "max_tokens" if field == "max_completion_tokens" else "max_completion_tokens"
    body = service.requests[0]["body"]
    assert body[field] == limit
    assert other not in body


@pytest.mark.parametrize("extra, named", [
    (["token_limit: 0"], "token_limit"),
    (["token_limit: -5"], "token_limit"),
    (['token_limit: "65536"'], "token_limit"),
    (["token_limit: 1.5"], "token_limit"),
    (["token_limit: true"], "token_limit"),
    (["token_limit_field: max_output_tokens"], "token_limit_field"),
    (["token_limit_field: 7"], "token_limit_field"),
])
def test_a_wrong_limit_or_field_is_refused_before_any_call_naming_the_file(
    home, connections, service, capsys, extra, named
):
    write_provider(connections, extra=extra)
    held = counts(home)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 1
    err = capsys.readouterr().err
    assert str(connections / "provider.yaml") in err and named in err
    assert service.requests == []
    assert counts(home) == held


def test_the_provider_setting_gives_the_limit_keys_only_when_set(connections):
    write_provider(connections)
    assert answers_module.provider_setting() == {"base_url": BASE_URL, "model": "provider-model"}
    write_provider(connections, extra=["token_limit: 65536", "token_limit_field: max_completion_tokens"])
    assert answers_module.provider_setting() == {
        "base_url": BASE_URL, "model": "provider-model",
        "token_limit": 65536, "token_limit_field": "max_completion_tokens"}


# The request timeout and whole replies (Track L, Step L7, decision 46). The pass
# reads request_timeout from the provider setting, 300 seconds when it names none,
# and saves each live reply as the bytes the service sent, in the audit home's
# replies folder, named by the session, beside the answer the store keeps.


class WholeReply(StandIn):
    """A stand-in whose reply carries reasoning text, a finish reason, and token
    counts, laid out compactly, so a reply parsed and written again would differ."""

    def __init__(self, answer=None):
        StandIn.__init__(self)
        self.answer = answer
        self.sent = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode())
        headers = {k.lower(): v for k, v in req.header_items()}
        self.requests.append({"url": req.full_url, "body": body, "headers": headers, "timeout": timeout})
        answer = self.answer if self.answer is not None else json.dumps(recorded(STORY_ID))
        data = {"id": "reply-%d" % (len(self.sent) + 1), "model": self.reported,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": answer,
                                         "reasoning_content": "Thinking about the session."}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200}}
        raw = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
        self.sent.append(raw)
        return io.BytesIO(raw)


@pytest.fixture
def whole(monkeypatch):
    stand_in = WholeReply()
    monkeypatch.setattr(urllib.request, "urlopen", stand_in)
    return stand_in


def replies(home):
    folder = home / "replies"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_the_request_waits_300_seconds_when_no_timeout_is_named(home, connections, whole):
    write_provider(connections)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    assert [r["timeout"] for r in whole.requests] == [300]


def test_a_named_request_timeout_is_used(home, connections, whole):
    write_provider(connections, extra=["request_timeout: 1200"])
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    assert [r["timeout"] for r in whole.requests] == [1200]
    assert answers_module.provider_setting()["request_timeout"] == 1200


@pytest.mark.parametrize("line", ["request_timeout: 0", "request_timeout: -30", 'request_timeout: "600"',
                                  "request_timeout: 2.5", "request_timeout: true", "request_timeout: null"])
def test_a_wrong_request_timeout_is_refused_before_any_call_naming_the_file(
    home, connections, whole, capsys, line
):
    write_provider(connections, extra=[line])
    held = counts(home)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 1
    err = capsys.readouterr().err
    assert str(connections / "provider.yaml") in err and "request_timeout" in err
    assert whole.requests == []
    assert counts(home) == held


def test_a_live_pass_saves_the_reply_as_the_bytes_the_service_sent(home, connections, whole):
    write_provider(connections)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    assert replies(home) == [STORY_ID + ".reply.json"]
    saved = (home / "replies" / (STORY_ID + ".reply.json")).read_bytes()
    assert saved == whole.sent[0]
    message = json.loads(saved)["choices"][0]["message"]
    assert message["reasoning_content"] == "Thinking about the session."


def test_a_reply_whose_answer_fails_is_saved_too(home, connections, monkeypatch, capsys):
    write_provider(connections)
    stand_in = WholeReply(answer="I could not decide.")
    monkeypatch.setattr(urllib.request, "urlopen", stand_in)
    held = counts(home)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 1
    assert f"failed {STORY_ID}" in capsys.readouterr().out
    assert counts(home) == held
    assert (home / "replies" / (STORY_ID + ".reply.json")).read_bytes() == stand_in.sent[0]


def test_tagging_a_session_again_keeps_the_earlier_reply(home, connections, whole):
    write_provider(connections)
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    assert main(["tag", "--home", str(home), "--answers", "live", "--session", STORY_ID]) == 0
    assert replies(home) == [STORY_ID + ".2.reply.json", STORY_ID + ".reply.json"]
    assert (home / "replies" / (STORY_ID + ".reply.json")).read_bytes() == whole.sent[0]
    assert (home / "replies" / (STORY_ID + ".2.reply.json")).read_bytes() == whole.sent[1]


def test_no_file_holds_the_key(home, connections, whole, monkeypatch, tmp_path):
    write_provider(connections)
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", "sk-test-value")
    assert main(["tag", "--home", str(home), "--answers", "live"]) == 0
    assert whole.requests[0]["headers"]["authorization"] == "Bearer sk-test-value"
    assert replies(home)
    for folder, _, files in os.walk(tmp_path):
        for name in files:
            assert b"sk-test-value" not in (Path(folder) / name).read_bytes(), name


def test_a_recorded_pass_saves_no_reply(home):
    assert main(["tag", "--home", str(home), "--answers", f"recorded:{BOOK}"]) == 0
    assert replies(home) == []
