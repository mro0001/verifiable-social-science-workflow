"""Tests for the provider setting (Track D, step D14).

Appendix A2.2 says a provider setting, a base URL and a model name, makes the
model swappable, and A6 says the key is read from the environment and never
stored. The setting is <connections home>/provider.yaml with base_url and
model, and the key is the variable WORKFLOW_MODEL_KEY (Track D choice 6).

Every test runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a
temporary folder. Nothing here calls a model or the network. Run from the
repository root with python3 -m pytest -q connections/tests.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections import provider  # noqa: E402
from connections.provider import KEY_ENV, ProviderError, load_provider, provider_path  # noqa: E402

SECRET = "sk-test-0123456789abcdef"


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    monkeypatch.delenv(KEY_ENV, raising=False)
    return tmp_path


def write_provider(text):
    path = Path(os.environ["CONNECTIONS_HOME"]) / "provider.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


COMPLETE = "base_url: https://models.example.edu/v1\nmodel: open-model-70b\n"


def show(env=None):
    done = subprocess.run(
        [sys.executable, "-m", "connections", "provider", "show"],
        cwd=str(ROOT),
        env=env or dict(os.environ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done


# The module.


def test_the_key_variable_is_workflow_model_key():
    assert KEY_ENV == "WORKFLOW_MODEL_KEY"


def test_the_setting_lives_in_the_connections_home():
    assert provider_path() == Path(os.environ["CONNECTIONS_HOME"]) / "provider.yaml"


def test_the_setting_defaults_to_the_home_folder(monkeypatch):
    monkeypatch.delenv("CONNECTIONS_HOME")
    assert provider_path() == Path(os.environ["HOME"]) / ".workflow_connections" / "provider.yaml"


def test_a_complete_file_gives_both_values():
    write_provider(COMPLETE)
    assert load_provider() == {"base_url": "https://models.example.edu/v1", "model": "open-model-70b"}


def test_a_local_service_with_http_is_accepted():
    write_provider("base_url: http://127.0.0.1:11434/v1\nmodel: small\n")
    assert load_provider()["base_url"] == "http://127.0.0.1:11434/v1"


def test_a_missing_file_names_the_file():
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert str(provider_path()) in str(raised.value)
    assert "no provider" in str(raised.value) or "missing" in str(raised.value)


def test_a_missing_model_names_the_file_and_the_key():
    path = write_provider("base_url: https://models.example.edu/v1\n")
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert str(path) in str(raised.value)
    assert "model" in str(raised.value)


def test_a_missing_base_url_names_the_key():
    write_provider("model: open-model-70b\n")
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert "base_url" in str(raised.value)


def test_a_base_url_with_no_scheme_names_the_key():
    path = write_provider("base_url: models.example.edu/v1\nmodel: open-model-70b\n")
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert str(path) in str(raised.value)
    assert "base_url" in str(raised.value)
    assert "http://" in str(raised.value)


@pytest.mark.parametrize(
    "text, key",
    [
        ("base_url: ftp://models.example.edu\nmodel: m\n", "base_url"),
        ("base_url: https://\nmodel: m\n", "base_url"),
        ("base_url: 8080\nmodel: m\n", "base_url"),
        ("base_url: https://models.example.edu/v1\nmodel: ''\n", "model"),
        ("base_url: https://models.example.edu/v1\nmodel: 70\n", "model"),
        ("base_url: https://models.example.edu/v1\nmodel: [a, b]\n", "model"),
    ],
)
def test_a_wrong_value_names_its_key(text, key):
    write_provider(text)
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert key in str(raised.value)


@pytest.mark.parametrize("text", ["- base_url\n- model\n", "just text\n", "", "base_url: [\n"])
def test_a_file_that_is_not_a_mapping_names_the_file(text):
    path = write_provider(text)
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert str(path) in str(raised.value)


def test_another_setting_in_the_file_is_named():
    write_provider(COMPLETE + "key: " + SECRET + "\n")
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert "'key'" in str(raised.value)
    assert SECRET not in str(raised.value)


def test_the_module_imports_no_other_layer():
    source = Path(provider.__file__).read_text(encoding="utf-8")
    for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
        assert "import " + layer not in source and "from " + layer not in source


def test_the_module_makes_no_network_call():
    source = Path(provider.__file__).read_text(encoding="utf-8")
    for name in ("urllib.request", "http.client", "socket", "requests"):
        assert "import " + name not in source


# The command.


def test_show_prints_the_file_both_values_and_that_the_key_is_not_set():
    path = write_provider(COMPLETE)
    done = show()
    assert done.returncode == 0, done.stderr
    assert str(path) in done.stdout
    assert "https://models.example.edu/v1" in done.stdout
    assert "open-model-70b" in done.stdout
    assert "WORKFLOW_MODEL_KEY is not set" in done.stdout


def test_show_says_the_key_is_set_and_never_prints_it():
    write_provider(COMPLETE)
    env = dict(os.environ)
    env[KEY_ENV] = SECRET
    done = show(env)
    assert done.returncode == 0, done.stderr
    assert "WORKFLOW_MODEL_KEY is set" in done.stdout
    assert "not set" not in done.stdout
    assert SECRET not in done.stdout
    assert SECRET not in done.stderr
    assert SECRET[:8] not in done.stdout


def test_show_counts_an_empty_key_as_not_set():
    write_provider(COMPLETE)
    env = dict(os.environ)
    env[KEY_ENV] = ""
    done = show(env)
    assert "WORKFLOW_MODEL_KEY is not set" in done.stdout


def test_show_with_a_missing_file_exits_1_and_names_the_file():
    done = show()
    assert done.returncode == 1
    assert str(provider_path()) in done.stderr
    assert done.stdout == ""


def test_show_with_a_missing_model_exits_1_and_names_it():
    write_provider("base_url: https://models.example.edu/v1\n")
    done = show()
    assert done.returncode == 1
    assert "model" in done.stderr


def test_show_with_a_base_url_with_no_scheme_exits_1_and_names_it():
    write_provider("base_url: models.example.edu/v1\nmodel: open-model-70b\n")
    done = show()
    assert done.returncode == 1
    assert "base_url" in done.stderr


def test_provider_with_no_action_prints_usage_and_exits_2():
    done = subprocess.run(
        [sys.executable, "-m", "connections", "provider"],
        cwd=str(ROOT), env=dict(os.environ), capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 2
    assert "show" in done.stderr


# The output limit (the ruling of 2026-10-29, step M5). The setting may
# also name token_limit and token_limit_field, and show prints them when set.

LIMITED = COMPLETE + "token_limit: 65536\ntoken_limit_field: max_completion_tokens\n"


def test_a_file_naming_the_limit_and_its_field_gives_them_too():
    write_provider(LIMITED)
    assert load_provider() == {
        "base_url": "https://models.example.edu/v1",
        "model": "open-model-70b",
        "token_limit": 65536,
        "token_limit_field": "max_completion_tokens",
    }


@pytest.mark.parametrize(
    "line, key",
    [
        ("token_limit: 0\n", "token_limit"),
        ("token_limit: -5\n", "token_limit"),
        ('token_limit: "65536"\n', "token_limit"),
        ("token_limit: 1.5\n", "token_limit"),
        ("token_limit: true\n", "token_limit"),
        ("token_limit_field: max_output_tokens\n", "token_limit_field"),
        ("token_limit_field: 7\n", "token_limit_field"),
    ],
)
def test_a_wrong_limit_or_field_names_the_file_and_its_key(line, key):
    path = write_provider(COMPLETE + line)
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert str(path) in str(raised.value)
    assert key in str(raised.value)


def test_show_prints_the_limit_and_its_field_when_set():
    write_provider(LIMITED)
    done = show()
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert "token_limit 65536" in lines
    assert "token_limit_field max_completion_tokens" in lines


def test_show_prints_no_limit_lines_when_neither_is_set():
    write_provider(COMPLETE)
    done = show()
    assert done.returncode == 0, done.stderr
    assert "token_limit" not in done.stdout


def test_show_with_a_wrong_limit_exits_1_and_names_it():
    write_provider(COMPLETE + "token_limit: 0\n")
    done = show()
    assert done.returncode == 1
    assert "token_limit" in done.stderr
    assert done.stdout == ""


# The request timeout (Track L, step L1). The setting may also name request_timeout,
# the seconds a live request waits, and show prints it when set.

def test_a_file_naming_the_request_timeout_gives_it_too():
    write_provider(COMPLETE + "request_timeout: 1200\n")
    assert load_provider() == {
        "base_url": "https://models.example.edu/v1",
        "model": "open-model-70b",
        "request_timeout": 1200,
    }


@pytest.mark.parametrize(
    "line",
    ["request_timeout: 0\n", "request_timeout: -30\n", 'request_timeout: "600"\n',
     "request_timeout: 2.5\n", "request_timeout: true\n", "request_timeout: null\n"],
)
def test_a_wrong_request_timeout_names_the_file_and_the_key(line):
    path = write_provider(COMPLETE + line)
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert str(path) in str(raised.value)
    assert "request_timeout" in str(raised.value)


def test_another_setting_is_still_named_beside_the_request_timeout():
    write_provider(COMPLETE + "request_timeout: 600\nretries: 9\n")
    with pytest.raises(ProviderError) as raised:
        load_provider()
    assert "'retries'" in str(raised.value)
    assert "request_timeout" in str(raised.value)


def test_show_prints_the_request_timeout_when_set_and_not_otherwise():
    write_provider(COMPLETE + "request_timeout: 1200\n")
    done = show()
    assert done.returncode == 0, done.stderr
    assert "request_timeout 1200" in done.stdout.splitlines()
    write_provider(COMPLETE)
    done = show()
    assert done.returncode == 0, done.stderr
    assert "request_timeout" not in done.stdout
