"""Live judgment through the provider setting (Track D, step D15).

Appendix A2.2 makes the model swappable through a provider setting, a base URL
and a model name, and A6 reads the key from the environment. Table A10 keeps
the request as it was (temperature 0, a 4,000 output token limit, four
attempts). A live run names its executor live, the provider's model, or
live:<model>, another model on the same service (Track D choices 6 and 7), and
its manifest holds the provider block the reconciliation fixes (item 7).

The model service is stood in for inside the test process by replacing
urllib.request.urlopen, so no test reaches the network.
"""
import hashlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vg  # noqa: E402

SELFTEST = ROOT / "fixtures" / "selftest"
GRAPH = str(ROOT / "graphs" / "selftest.yaml")
BASE_URL = "http://127.0.0.1:9/v1"
COLORS = {"red", "green", "blue"}


class StandIn:
    """A chat completions service that answers whether the asked word is a color."""

    def __init__(self, reported="stand-in-model-2026"):
        self.reported = reported
        self.requests = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode())
        headers = {k.lower(): v for k, v in req.header_items()}
        self.requests.append({"url": req.full_url, "body": body, "headers": headers, "timeout": timeout})
        word = re.search(r'Is the word "([^"]+)"', body["messages"][0]["content"]).group(1)
        answer = json.dumps({"is_color": word in COLORS})
        data = {"model": self.reported if self.reported else body["model"],
                "choices": [{"message": {"role": "assistant", "content": answer}}]}
        return io.BytesIO(json.dumps(data).encode())


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "connections"
    home.mkdir()
    monkeypatch.setenv("CONNECTIONS_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORKFLOW_MODEL_KEY", raising=False)
    monkeypatch.setattr(vg.time, "sleep", lambda seconds: None)
    return home


def write_provider(home, base_url=BASE_URL, model="provider-model", extra=()):
    lines = []
    if base_url is not None:
        lines.append("base_url: %s" % base_url)
    if model is not None:
        lines.append("model: %s" % model)
    lines.extend(extra)
    (home / "provider.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def service(monkeypatch):
    stand_in = StandIn()
    monkeypatch.setattr(vg.urllib.request, "urlopen", stand_in)
    return stand_in


def live_run(rd, judge="live"):
    return vg.main(["run", GRAPH, "--run", str(rd), "--inputs", str(SELFTEST), "--judge", judge])


def answers(rd):
    return json.loads((rd / "files" / "judge_items.json").read_text())


def test_a_self_test_run_with_live_completes_through_the_provider(home, service, tmp_path):
    write_provider(home)
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    assert (rd / "files" / "report.md").exists()
    assert len(service.requests) == 4
    for request in service.requests:
        assert request["url"] == BASE_URL + "/chat/completions"
        assert request["body"]["model"] == "provider-model"
        assert request["body"]["temperature"] == 0
        assert request["body"]["max_tokens"] == 4000
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["provider"] == {"base_url": BASE_URL, "model": "provider-model",
                                    "token_limit": 4000, "token_limit_field": "max_tokens",
                                    "request_timeout": 300}
    assert manifest["executors"]["judge"] == "live"
    assert [a["executor"] for a in answers(rd)] == ["live:stand-in-model-2026"] * 4
    assert {a["item_id"]: a["is_color"] for a in answers(rd)} == {
        "w1": True, "w2": True, "w3": False, "w4": True}
    assert vg.score(str(rd), str(SELFTEST / "truth.yaml"))["missed"] == []


def test_a_trailing_slash_on_the_base_url_is_not_doubled(home, service, tmp_path):
    write_provider(home, base_url=BASE_URL + "/")
    assert live_run(tmp_path / "run") == 0
    assert {r["url"] for r in service.requests} == {BASE_URL + "/chat/completions"}


def test_live_with_a_model_sends_that_model(home, service, tmp_path):
    write_provider(home)
    rd = tmp_path / "run"
    assert live_run(rd, "live:other-model") == 0
    assert {r["body"]["model"] for r in service.requests} == {"other-model"}
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["provider"] == {"base_url": BASE_URL, "model": "provider-model",
                                    "token_limit": 4000, "token_limit_field": "max_tokens",
                                    "request_timeout": 300}


def test_the_executor_falls_back_to_the_asked_model_when_none_is_reported(home, monkeypatch, tmp_path):
    write_provider(home)
    stand_in = StandIn(reported=None)
    monkeypatch.setattr(vg.urllib.request, "urlopen", stand_in)
    rd = tmp_path / "run"
    assert live_run(rd, "live:other-model") == 0
    assert {a["executor"] for a in answers(rd)} == {"live:other-model"}


def test_the_key_travels_as_a_bearer_token_when_set(home, service, tmp_path, monkeypatch):
    write_provider(home)
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", "sk-test-value")
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    assert {r["headers"].get("authorization") for r in service.requests} == {"Bearer sk-test-value"}
    for name in ("manifest.json", "trail.jsonl"):
        assert "sk-test-value" not in (rd / name).read_text()


def test_no_authorization_header_is_sent_when_the_key_is_unset(home, service, tmp_path):
    write_provider(home)
    assert live_run(tmp_path / "run") == 0
    assert all("authorization" not in r["headers"] for r in service.requests)


def test_a_key_set_to_nothing_sends_no_authorization_header(home, service, tmp_path, monkeypatch):
    write_provider(home)
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", "")
    assert live_run(tmp_path / "run") == 0
    assert all("authorization" not in r["headers"] for r in service.requests)


def test_with_no_provider_file_the_run_stops_before_its_folder_and_names_the_file(home, service, tmp_path):
    rd = tmp_path / "run"
    with pytest.raises(SystemExit) as stopped:
        live_run(rd)
    assert str(home / "provider.yaml") in str(stopped.value.code)
    assert not rd.exists()
    assert service.requests == []


@pytest.mark.parametrize("missing", ["base_url", "model"])
def test_a_provider_file_lacking_a_key_stops_the_run_and_names_it(home, service, tmp_path, missing):
    write_provider(home, **{missing: None})
    rd = tmp_path / "run"
    with pytest.raises(SystemExit) as stopped:
        live_run(rd)
    assert str(home / "provider.yaml") in str(stopped.value.code)
    assert missing in str(stopped.value.code)
    assert not rd.exists()


def test_the_provider_file_is_read_from_the_home_folder_without_connections_home(
        tmp_path, monkeypatch, service):
    monkeypatch.delenv("CONNECTIONS_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(vg.time, "sleep", lambda seconds: None)
    home = tmp_path / "home" / ".workflow_connections"
    home.mkdir(parents=True)
    write_provider(home, model="home-model")
    assert vg.provider_setting() == {"base_url": BASE_URL, "model": "home-model"}
    with pytest.raises(RuntimeError) as raised:
        (home / "provider.yaml").unlink()
        vg.provider_setting()
    assert str(home / "provider.yaml") in str(raised.value)


@pytest.mark.parametrize("spec", ["service:x", "openai:gpt", "livex", "recorded"])
def test_an_executor_of_another_kind_is_refused_before_the_run_folder(home, service, tmp_path, spec):
    write_provider(home)
    rd = tmp_path / "run"
    with pytest.raises(SystemExit) as stopped:
        live_run(rd, spec)
    assert spec in str(stopped.value.code)
    assert not rd.exists()
    assert service.requests == []


def test_a_second_of_another_kind_is_refused_too(home, service, tmp_path):
    write_provider(home)
    rd = tmp_path / "run"
    with pytest.raises(SystemExit):
        vg.main(["run", GRAPH, "--run", str(rd), "--inputs", str(SELFTEST),
                 "--judge", "live", "--second", "service:x"])
    assert not rd.exists()


def test_a_recorded_run_needs_no_provider_file_and_writes_no_provider_block(home, tmp_path):
    rd = tmp_path / "run"
    judge = "recorded:" + str(SELFTEST / "recorded_judge.json")
    assert vg.main(["run", GRAPH, "--run", str(rd), "--inputs", str(SELFTEST), "--judge", judge]) == 0
    assert "provider" not in json.loads((rd / "manifest.json").read_text())


def test_four_attempts_are_made_before_the_call_fails(home, monkeypatch, tmp_path):
    write_provider(home)
    calls = []

    def failing(req, timeout=None):
        calls.append(req.full_url)
        raise OSError("service down")

    monkeypatch.setattr(vg.urllib.request, "urlopen", failing)
    with pytest.raises(RuntimeError) as raised:
        vg.call_executor("live", "a prompt", "judge_items:w1",
                         {"base_url": BASE_URL, "model": "provider-model"})
    assert len(calls) == 4
    assert "service down" in str(raised.value)


def test_same_model_resolves_live_to_the_providers_model():
    provider = {"base_url": BASE_URL, "model": "Provider-Model"}
    assert vg.same_model("live", "live:provider-model", provider)
    assert vg.same_model("live:provider-model ", "live", provider)
    assert not vg.same_model("live", "live:other-model", provider)
    assert vg.same_model("live", "live", provider)


# The output limit (the ruling of 2026-10-29, step M5). The provider setting
# may name token_limit and token_limit_field. With neither, the request keeps the
# 4,000 tokens under max_tokens that Table A10 records.

def test_with_neither_limit_key_the_request_holds_max_tokens_4000_and_nothing_else(home, service, tmp_path):
    write_provider(home)
    assert live_run(tmp_path / "run") == 0
    for request in service.requests:
        assert request["body"]["max_tokens"] == 4000
        assert "max_completion_tokens" not in request["body"]


def test_a_named_limit_and_field_are_sent_under_that_field_only(home, service, tmp_path):
    write_provider(home, extra=["token_limit: 65536", "token_limit_field: max_completion_tokens"])
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    assert len(service.requests) == 4
    for request in service.requests:
        assert request["body"]["max_completion_tokens"] == 65536
        assert "max_tokens" not in request["body"]
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["provider"] == {"base_url": BASE_URL, "model": "provider-model",
                                    "token_limit": 65536, "token_limit_field": "max_completion_tokens",
                                    "request_timeout": 300}


@pytest.mark.parametrize("extra, field, limit", [
    (["token_limit: 8000"], "max_tokens", 8000),
    (["token_limit_field: max_completion_tokens"], "max_completion_tokens", 4000),
])
def test_one_key_alone_keeps_the_other_at_its_old_value(home, service, tmp_path, extra, field, limit):
    write_provider(home, extra=extra)
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    other = "max_tokens" if field == "max_completion_tokens" else "max_completion_tokens"
    for request in service.requests:
        assert request["body"][field] == limit
        assert other not in request["body"]
    provider = json.loads((rd / "manifest.json").read_text())["provider"]
    assert (provider["token_limit"], provider["token_limit_field"]) == (limit, field)


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
        home, service, tmp_path, extra, named):
    write_provider(home, extra=extra)
    rd = tmp_path / "run"
    with pytest.raises(SystemExit) as stopped:
        live_run(rd)
    assert str(home / "provider.yaml") in str(stopped.value.code)
    assert named in str(stopped.value.code)
    assert not rd.exists()
    assert service.requests == []


def test_a_provider_block_without_the_limit_keys_sends_the_old_request(service):
    vg.call_executor("live", 'Is the word "red" a color?', "judge_items:w1",
                     {"base_url": BASE_URL, "model": "provider-model"})
    body = service.requests[0]["body"]
    assert body["max_tokens"] == 4000
    assert "max_completion_tokens" not in body


def test_the_provider_setting_gives_the_limit_keys_only_when_set(home):
    write_provider(home)
    assert vg.provider_setting() == {"base_url": BASE_URL, "model": "provider-model"}
    write_provider(home, extra=["token_limit: 65536", "token_limit_field: max_completion_tokens"])
    assert vg.provider_setting() == {"base_url": BASE_URL, "model": "provider-model",
                                     "token_limit": 65536, "token_limit_field": "max_completion_tokens"}


# Whole live replies and the request timeout (Track L, step L1, decision 46). A live run
# saves each reply the service sent whole, beside the answer text, which stays as it was.
# The provider setting may name request_timeout in seconds, 300 when it is absent.

class WholeReply(StandIn):
    """A stand-in whose replies carry reasoning text, a finish reason, and token counts,
    as a reasoning model's do. With garble, the first ask gets an answer that does not
    parse, so that item is asked again."""

    def __init__(self, garble=False):
        StandIn.__init__(self)
        self.garble = garble
        self.sent = []
        self.raw = []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode())
        headers = {k.lower(): v for k, v in req.header_items()}
        self.requests.append({"url": req.full_url, "body": body, "headers": headers, "timeout": timeout})
        word = re.search(r'Is the word "([^"]+)"', body["messages"][0]["content"]).group(1)
        answer = json.dumps({"is_color": word in COLORS})
        if self.garble and len(self.sent) == 0:
            answer = "I think so, but"
        n = len(self.sent) + 1
        data = {"id": "reply-%d" % n, "object": "chat.completion", "model": self.reported,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": answer,
                                         "reasoning_content": "Thinking about %s, step %d." % (word, n)}}],
                "usage": {"prompt_tokens": 100 + n, "completion_tokens": 20 + n, "total_tokens": 120 + 2 * n}}
        self.sent.append(data)
        # Laid out as a service might send it, compact and with escaped characters,
        # so a reply parsed and written again would differ from these bytes.
        raw = json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
        self.raw.append(raw)
        return io.BytesIO(raw)


def judge_record(rd):
    return next(json.loads(p.read_text()) for p in sorted((rd / "records").iterdir())
                if json.loads(p.read_text())["node"] == "judge_items")


def test_a_live_run_saves_each_whole_reply_beside_the_unchanged_answer(home, monkeypatch, tmp_path):
    write_provider(home)
    stand_in = WholeReply()
    monkeypatch.setattr(vg.urllib.request, "urlopen", stand_in)
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    responses = rd / "responses" / "02_judge_items"
    replies = judge_record(rd)["execution"]["replies"]
    assert [r["path"] for r in replies] == [
        "responses/02_judge_items/%s.reply.json" % w for w in ("w1", "w2", "w3", "w4")]
    for listed, raw, sent in zip(replies, stand_in.raw, stand_in.sent):
        # The reply is the bytes the service sent, and the record holds their checksum.
        assert (rd / listed["path"]).read_bytes() == raw
        assert listed["sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()
        saved = json.loads((rd / listed["path"]).read_text(encoding="utf-8"))
        assert saved == sent
        assert saved["choices"][0]["message"]["reasoning_content"].startswith("Thinking about")
        assert saved["choices"][0]["finish_reason"] == "stop"
        assert saved["usage"]["completion_tokens"] > 20
        assert saved["model"] == "stand-in-model-2026"
    for item, sent in zip(("w1", "w2", "w3", "w4"), stand_in.sent):
        assert (responses / (item + ".txt")).read_text() == sent["choices"][0]["message"]["content"]
    assert sorted(p.name for p in responses.iterdir()) == sorted(
        ["%s.txt" % w for w in ("w1", "w2", "w3", "w4")] + ["%s.reply.json" % w for w in ("w1", "w2", "w3", "w4")])


def test_a_retry_writes_its_own_reply_file(home, monkeypatch, tmp_path):
    write_provider(home)
    stand_in = WholeReply(garble=True)
    monkeypatch.setattr(vg.urllib.request, "urlopen", stand_in)
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    responses = rd / "responses" / "02_judge_items"
    assert (responses / "w1.reply.json").read_bytes() == stand_in.raw[0]
    assert (responses / "w1.retry.reply.json").read_bytes() == stand_in.raw[1]
    assert (responses / "w1.txt").read_text() == "I think so, but"
    assert (responses / "w1.retry.txt").read_text() == stand_in.sent[1]["choices"][0]["message"]["content"]
    replies = judge_record(rd)["execution"]["replies"]
    assert replies[:2] == [
        {"path": "responses/02_judge_items/w1.reply.json",
         "sha256": "sha256:" + hashlib.sha256(stand_in.raw[0]).hexdigest()},
        {"path": "responses/02_judge_items/w1.retry.reply.json",
         "sha256": "sha256:" + hashlib.sha256(stand_in.raw[1]).hexdigest()}]
    assert len(replies) == 5


def test_a_recorded_run_writes_no_reply_file(home, tmp_path):
    rd = tmp_path / "run"
    judge = "recorded:" + str(SELFTEST / "recorded_judge.json")
    assert vg.main(["run", GRAPH, "--run", str(rd), "--inputs", str(SELFTEST), "--judge", judge]) == 0
    assert list((rd / "responses").glob("*/*.reply.json")) == []
    assert "replies" not in judge_record(rd)["execution"]


def test_call_executor_gives_back_the_whole_reply_and_nothing_for_recorded(service, tmp_path):
    raw, exe, reply = vg.call_executor("live", 'Is the word "red" a color?', "judge_items:w1",
                                       {"base_url": BASE_URL, "model": "provider-model"})
    assert (raw, exe) == ('{"is_color": true}', "live:stand-in-model-2026")
    # The reply comes back as the bytes the service sent.
    assert reply == json.dumps({"model": "stand-in-model-2026",
                                "choices": [{"message": {"role": "assistant", "content": raw}}]}).encode()
    raw, exe, reply = vg.call_executor("recorded:" + str(SELFTEST / "recorded_judge.json"),
                                       "any prompt", "judge_items:w1")
    assert (raw, exe, reply) == ('{"is_color": true}', "recorded:recorded_judge.json", None)


def test_verify_ignores_the_reply_files_and_holds_without_them(home, monkeypatch, tmp_path):
    write_provider(home)
    monkeypatch.setattr(vg.urllib.request, "urlopen", WholeReply())
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    assert vg.verify(str(rd)) == 0
    for reply in (rd / "responses").glob("*/*.reply.json"):
        reply.unlink()
    assert vg.verify(str(rd)) == 0


def test_the_request_waits_300_seconds_when_no_timeout_is_named(home, service, tmp_path):
    write_provider(home)
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    assert {r["timeout"] for r in service.requests} == {300}
    # Every live run's manifest records the timeout, 300 when the setting names none.
    assert json.loads((rd / "manifest.json").read_text())["provider"]["request_timeout"] == 300


def test_a_named_request_timeout_is_used_for_every_live_request(home, service, tmp_path):
    write_provider(home, extra=["request_timeout: 1200"])
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    assert len(service.requests) == 4
    assert {r["timeout"] for r in service.requests} == {1200}
    assert json.loads((rd / "manifest.json").read_text())["provider"]["request_timeout"] == 1200
    assert vg.provider_setting()["request_timeout"] == 1200


def test_a_step_run_on_its_own_uses_the_timeout_of_its_run(home, service, tmp_path):
    write_provider(home, extra=["request_timeout: 900"])
    rd = tmp_path / "run"
    assert live_run(rd) == 0
    write_provider(home)
    service.requests.clear()
    vg.step(str(rd), "judge_items")
    assert {r["timeout"] for r in service.requests} == {900}


@pytest.mark.parametrize("line", ["request_timeout: 0", "request_timeout: -30", 'request_timeout: "600"',
                                  "request_timeout: 2.5", "request_timeout: true", "request_timeout: null"])
def test_a_wrong_request_timeout_is_refused_before_any_call_naming_the_file(home, service, tmp_path, line):
    write_provider(home, extra=[line])
    rd = tmp_path / "run"
    with pytest.raises(SystemExit) as stopped:
        live_run(rd)
    assert str(home / "provider.yaml") in str(stopped.value.code)
    assert "request_timeout" in str(stopped.value.code)
    assert not rd.exists()
    assert service.requests == []


# The live runs of October 8 saved the answer text only. Their folders still verify, on
# copies, since verify writes into the folder it checks. The repository holds them in
# live_runs_2026-10-08/, and the test also looks in this checkout's runs folder and, from
# a worktree, in the main checkout's, and is skipped when none holds them.
OCTOBER_8 = ("cit_live_clean", "cit_live_seeded", "data_live_clean", "data_live_seeded",
             "prose_clean_live", "prose_live", "prose_live2")


def october_8_runs():
    places = [ROOT / "live_runs_2026-10-08", ROOT / "runs"]
    if ROOT.parents[1].name == ".worktrees":
        places.append(ROOT.parents[2] / "verification_procedures" / "runs")
    for place in places:
        if all((place / name / "manifest.json").exists() for name in OCTOBER_8):
            return place
    return None


@pytest.mark.parametrize("name", OCTOBER_8)
def test_an_october_8_run_folder_without_reply_files_still_verifies(tmp_path, name, capsys):
    place = october_8_runs()
    if place is None:
        pytest.skip("the October 8 run folders are not in this checkout")
    copy = tmp_path / name
    shutil.copytree(str(place / name), str(copy))
    assert list(copy.glob("responses/*/*.reply.json")) == []
    assert vg.verify(str(copy)) == 0
    assert "FAIL" not in capsys.readouterr().out
