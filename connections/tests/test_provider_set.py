"""Tests for provider set and the second model (Track S, step S2, choice 4).

python3 -m connections provider set --base-url URL --model NAME
[--second-model NAME] [--token-limit N --token-limit-field FIELD] [--home DIR]
writes provider.yaml in the connections home and never a key. The second
model for the references recheck is kept as second_model beside model, and
provider show prints it.

Every test runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a
temporary folder. Nothing here calls a model or the network. Run from the
repository root with python3 -m pytest -q connections/tests.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections.provider import (  # noqa: E402
    KEY_ENV, ProviderError, load_provider, provider_path, write_provider)

SECRET = "sk-test-0123456789abcdef"
URL = "https://models.example.edu/v1"


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    monkeypatch.delenv(KEY_ENV, raising=False)
    return tmp_path


def connections(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "connections"] + list(args),
        cwd=str(ROOT), env=env or dict(os.environ), capture_output=True, text=True, timeout=60)


def read(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# The module.


def test_write_provider_writes_both_values_in_the_connections_home():
    path = write_provider(URL, "open-model-70b")
    assert path == provider_path()
    assert read(path) == {"base_url": URL, "model": "open-model-70b"}
    assert load_provider() == {"base_url": URL, "model": "open-model-70b"}


def test_write_provider_takes_the_second_model_and_the_limit():
    write_provider(URL, "open-model-70b", second_model="other-model-8b", token_limit=65536,
                   token_limit_field="max_completion_tokens")
    assert list(read(provider_path())) == ["base_url", "model", "second_model", "token_limit",
                                           "token_limit_field"]
    assert load_provider()["second_model"] == "other-model-8b"


def test_write_provider_writes_in_a_home_it_is_given(tmp_path):
    path = write_provider(URL, "open-model-70b", home=tmp_path / "elsewhere")
    assert path == tmp_path / "elsewhere" / "provider.yaml"
    assert not provider_path().exists()


@pytest.mark.parametrize("given, key", [
    ({"base_url": "models.example.edu/v1", "model": "m"}, "base_url"),
    ({"base_url": URL, "model": " "}, "model"),
    ({"base_url": URL, "model": "m", "second_model": "m"}, "second_model"),
    ({"base_url": URL, "model": "m", "token_limit": 0, "token_limit_field": "max_tokens"},
     "token_limit"),
    ({"base_url": URL, "model": "m", "token_limit": 10, "token_limit_field": "tokens"},
     "token_limit_field"),
])
def test_write_provider_refuses_a_wrong_value_and_writes_nothing(given, key):
    with pytest.raises(ProviderError) as raised:
        write_provider(**given)
    assert key in str(raised.value)
    assert not provider_path().exists()


def test_a_file_naming_a_second_model_is_read():
    provider_path().parent.mkdir(parents=True)
    provider_path().write_text("base_url: %s\nmodel: a\nsecond_model: b\n" % URL,
                               encoding="utf-8")
    assert load_provider() == {"base_url": URL, "model": "a", "second_model": "b"}


def test_an_empty_second_model_is_refused():
    provider_path().parent.mkdir(parents=True)
    provider_path().write_text("base_url: %s\nmodel: a\nsecond_model: ''\n" % URL,
                               encoding="utf-8")
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert "second_model" in str(raised.value)


# The command.


def test_set_writes_the_file_and_prints_what_show_prints():
    done = connections("provider", "set", "--base-url", URL, "--model", "open-model-70b",
                       "--second-model", "other-model-8b")
    assert done.returncode == 0, done.stderr
    assert read(provider_path()) == {"base_url": URL, "model": "open-model-70b",
                                     "second_model": "other-model-8b"}
    assert str(provider_path()) in done.stdout
    assert "second_model other-model-8b" in done.stdout


def test_set_never_writes_or_prints_the_key():
    env = dict(os.environ)
    env[KEY_ENV] = SECRET
    done = connections("provider", "set", "--base-url", URL, "--model", "open-model-70b",
                       env=env)
    assert done.returncode == 0, done.stderr
    assert SECRET not in provider_path().read_text(encoding="utf-8")
    assert SECRET not in done.stdout + done.stderr
    assert "WORKFLOW_MODEL_KEY is set" in done.stdout


def test_set_with_home_writes_there(tmp_path):
    done = connections("provider", "set", "--base-url", URL, "--model", "m",
                       "--home", str(tmp_path / "given_home"))
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "given_home" / "provider.yaml").is_file()
    assert not provider_path().exists()


def test_set_takes_the_limit_and_its_field_together():
    done = connections("provider", "set", "--base-url", URL, "--model", "m",
                       "--token-limit", "65536", "--token-limit-field", "max_completion_tokens")
    assert done.returncode == 0, done.stderr
    assert read(provider_path())["token_limit"] == 65536
    alone = connections("provider", "set", "--base-url", URL, "--model", "m",
                        "--token-limit", "65536")
    assert alone.returncode == 2
    assert "--token-limit-field" in alone.stderr


def test_set_with_a_wrong_base_url_exits_1_and_writes_nothing():
    done = connections("provider", "set", "--base-url", "models.example.edu", "--model", "m")
    assert done.returncode == 1
    assert "base_url" in done.stderr
    assert not provider_path().exists()


def test_set_replaces_an_earlier_setting():
    connections("provider", "set", "--base-url", URL, "--model", "a", "--second-model", "b")
    connections("provider", "set", "--base-url", URL, "--model", "c")
    assert read(provider_path()) == {"base_url": URL, "model": "c"}


def test_show_prints_the_second_model_when_set():
    write_provider(URL, "a", second_model="b")
    done = connections("provider", "show")
    assert done.returncode == 0, done.stderr
    assert "second_model b" in done.stdout
    write_provider(URL, "a")
    assert "second_model" not in connections("provider", "show").stdout


def test_set_writes_a_request_timeout_and_show_prints_it():
    done = connections("provider", "set", "--base-url", URL, "--model", "open-model-70b",
                       "--request-timeout", "900")
    assert done.returncode == 0, done.stderr
    assert read(provider_path()) == {"base_url": URL, "model": "open-model-70b",
                                     "request_timeout": 900}
    assert "request_timeout 900" in done.stdout


def test_set_refuses_a_request_timeout_that_is_not_above_0():
    done = connections("provider", "set", "--base-url", URL, "--model", "open-model-70b",
                       "--request-timeout", "0")
    assert done.returncode == 1
    assert "request_timeout" in done.stderr
    assert not provider_path().exists()

