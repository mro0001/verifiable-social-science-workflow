"""The provider setting, which says which model service and model to use (Track D, step D14).

Appendix A2.2 says a provider setting, a base URL and a model name, makes the
model swappable, so the workflow runs on any model the scholar can reach
(proposal Approach paragraph 1). Figure A2 draws it between the harness and
the model, and Table A1 lists it as specified. A6 says the key is read from
the environment and no key or credential is stored in the repository.

The setting is the file <connections home>/provider.yaml holding base_url
and model, and the key is the environment variable WORKFLOW_MODEL_KEY. The
file may also name the output limit of a live reply, token_limit, a whole
number above 0, and the field it is sent under, token_limit_field, max_tokens
or max_completion_tokens. Left out, the live requests keep the 4,000 tokens
under max_tokens that Table A10 records (the ruling of 2026-10-29). It
may also name second_model, the model on the same service that rechecks
doubtful source verdicts (Track S choice 4), and request_timeout, the seconds a
live request waits, a whole number above 0, and left out a request waits 300
seconds (Track L, step L1). The file holds nothing else. No key is sent when the
variable is unset, since a local service needs none (Track D choice 6).
write_provider writes the file for provider set (Track S, step S2), never with a
key. This module makes no model call.
"""
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict

import yaml

from connections.home import connections_home

KEY_ENV = "WORKFLOW_MODEL_KEY"
PROVIDER_FILE = "provider.yaml"
KEYS = ("base_url", "model")
SECOND_KEY = "second_model"
LIMIT_KEYS = ("token_limit", "token_limit_field")
TIMEOUT_KEY = "request_timeout"
TOKEN_LIMIT_FIELDS = ("max_tokens", "max_completion_tokens")


class ProviderError(ValueError):
    """The provider setting is missing or unclear. The message names the file and the problem."""


def provider_path(home=None) -> Path:
    """<connections home>/provider.yaml, or provider.yaml in the home given."""
    if home is not None:
        return Path(os.path.expanduser(str(home))) / PROVIDER_FILE
    return connections_home() / PROVIDER_FILE


def load_provider(home=None) -> Dict[str, Any]:
    """The setting's base_url and model, with second_model, token_limit,
    token_limit_field, and request_timeout when set.

    Raises ProviderError naming the file and the missing or wrong key. A
    base_url must start with http:// or https:// and name a host, a model
    must be text that is not empty, a token_limit and a request_timeout whole
    numbers above 0, and a token_limit_field max_tokens or max_completion_tokens. A file that is
    missing, does not parse, is not a mapping, or holds any other setting is
    refused too, so a key written into the file is never taken up.
    """
    path = provider_path(home)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ProviderError(f"there is no provider setting at {path}. Write base_url and model there")
    except (OSError, ValueError) as error:
        raise ProviderError(f"the provider setting {path} cannot be read, {error}")
    try:
        setting = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ProviderError(f"the provider setting {path} is not YAML")
    if not isinstance(setting, dict):
        raise ProviderError(f"the provider setting {path} must map base_url and model to their values")
    others = sorted(str(name) for name in setting
                    if name not in KEYS + (SECOND_KEY,) + LIMIT_KEYS + (TIMEOUT_KEY,))
    if others:
        names = ", ".join(repr(name) for name in others)
        raise ProviderError(
            f"the provider setting {path} holds {names}, and only base_url, model, second_model,"
            " token_limit, token_limit_field, and request_timeout belong there"
        )
    for key in KEYS:
        if key not in setting:
            raise ProviderError(f"the provider setting {path} is missing {key}")
    return _checked(setting, path)


def _checked(setting: Dict[str, Any], path: Path) -> Dict[str, Any]:
    """The setting's values in their order, or ProviderError naming the file and the key."""
    base_url = setting["base_url"]
    if not isinstance(base_url, str) or not _is_web_address(base_url):
        raise ProviderError(
            f"the provider setting {path} has a wrong base_url, which must start with http:// or"
            " https:// and name a host"
        )
    model = setting["model"]
    if not isinstance(model, str) or not model.strip():
        raise ProviderError(f"the provider setting {path} has a wrong model, which must be a model name")
    found: Dict[str, Any] = {"base_url": base_url, "model": model}
    if SECOND_KEY in setting:
        second = setting[SECOND_KEY]
        if not isinstance(second, str) or not second.strip() or second == model:
            raise ProviderError(
                f"the provider setting {path} has a wrong second_model, which must be a model name"
                " other than model"
            )
        found[SECOND_KEY] = second
    if "token_limit" in setting:
        limit = setting["token_limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ProviderError(
                f"the provider setting {path} has a wrong token_limit, which must be a whole number above 0"
            )
        found["token_limit"] = limit
    if "token_limit_field" in setting:
        field = setting["token_limit_field"]
        if not isinstance(field, str) or field not in TOKEN_LIMIT_FIELDS:
            raise ProviderError(
                f"the provider setting {path} has a wrong token_limit_field, which must be "
                + " or ".join(TOKEN_LIMIT_FIELDS)
            )
        found["token_limit_field"] = field
    if TIMEOUT_KEY in setting:
        wait = setting[TIMEOUT_KEY]
        if isinstance(wait, bool) or not isinstance(wait, int) or wait <= 0:
            raise ProviderError(
                f"the provider setting {path} has a wrong request_timeout, which must be a whole"
                " number of seconds above 0"
            )
        found[TIMEOUT_KEY] = wait
    return found


def write_provider(base_url, model, second_model=None, token_limit=None, token_limit_field=None,
                   request_timeout=None, home=None) -> Path:
    """Write provider.yaml with the values given and give back its path.

    The values are checked as load_provider checks them, and a wrong one
    raises ProviderError before anything is written. A value left as None is
    left out of the file. The file never holds a key. An earlier setting is
    replaced whole, in one step.
    """
    path = provider_path(home)
    setting: Dict[str, Any] = {"base_url": base_url, "model": model}
    for key, value in ((SECOND_KEY, second_model), ("token_limit", token_limit),
                       ("token_limit_field", token_limit_field), (TIMEOUT_KEY, request_timeout)):
        if value is not None:
            setting[key] = value
    found = _checked(setting, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(yaml.safe_dump(found, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(str(partial), str(path))
    return path


def key_is_set() -> bool:
    """Whether WORKFLOW_MODEL_KEY holds a key. A variable set to nothing counts as not set."""
    return bool(os.environ.get(KEY_ENV))


def show(home=None) -> str:
    """The lines provider show prints, naming the file, both values, the second model, the
    limit, its field, and the request timeout when they are set, and whether the key is set.

    The key's value is never part of them. Raises ProviderError as load_provider does.
    """
    setting = load_provider(home)
    key = f"{KEY_ENV} is set" if key_is_set() else f"{KEY_ENV} is not set, so no key is sent"
    lines = [
        f"provider setting {provider_path(home)}",
        f"base_url {setting['base_url']}",
        f"model {setting['model']}",
    ]
    for name in (SECOND_KEY,) + LIMIT_KEYS + (TIMEOUT_KEY,):
        if name in setting:
            lines.append(f"{name} {setting[name]}")
    lines.append(key)
    return "\n".join(lines) + "\n"


def _is_web_address(text: str) -> bool:
    if not (text.startswith("http://") or text.startswith("https://")):
        return False
    return bool(urllib.parse.urlsplit(text).netloc)
