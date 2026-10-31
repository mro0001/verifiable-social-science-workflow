"""The answer source, where the model pass gets its answer for each session.

Appendix Table A4 gives the model pass one AI model call per session. A2.2
makes the model swappable through a provider setting, a base URL and a model
name, and Table A5 says the audit store records the model of the tagging
pass. Tests never call a model, so they use recorded answers.

open_answers(spec) gives a source whose ask(key, prompt) gives back the
answer text and the name of the model that gave it. The spec is
<kind>:<rest>, and KINDS maps each kind to the class that answers for it.

- recorded:<path>. A JSON book keyed by session id. Each value is the answer
  text, or an object, which is given back as JSON text. The model is named
  recorded:<file name>. A key the book does not hold is refused by name.

- live and live:<model> (Track D, step D16). The answer comes from the model
  service the provider setting names, provider.yaml in CONNECTIONS_HOME, else
  in ~/.workflow_connections, with base_url and model, read by
  provider_setting() as live judgment reads it in vg.py. live asks the
  provider's model and live:<model> asks another model on the same service.
  The request posts to <base_url>/chat/completions with temperature 0 and an
  output token limit, tries four times, and sends the key in
  WORKFLOW_MODEL_KEY as a bearer token only when it is set. The provider
  setting may name token_limit, a whole number above 0, and
  token_limit_field, max_tokens or max_completion_tokens, and the limit is
  sent under that field only. When they are absent the request keeps the
  4,000 tokens under max_tokens that Table A10 records (the ruling of
  2026-10-29). The setting may also name request_timeout, the seconds each
  request waits, a whole number above 0, 300 when it is absent (Track L,
  Step L7). The model is named
  live:<the model the service reports>. A missing or incomplete provider file
  refuses the source by the file's name, so the pass stamps nothing. After
  each answer the source holds the whole reply, the bytes the service sent, as
  last_reply, which the model pass saves (decision 46).

Any other kind is refused. Only the live kinds reach the network.
"""
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

# The provider setting (Track D choice 6). The key is read from the
# environment and never stored.
PROVIDER_FILE = "provider.yaml"
KEY_ENV = "WORKFLOW_MODEL_KEY"
# The output limit (the ruling of 2026-10-29). The default limit and
# the first field are the request Table A10 records.
DEFAULT_TOKEN_LIMIT = 4000
TOKEN_LIMIT_FIELDS = ("max_tokens", "max_completion_tokens")
# The seconds a live request waits when the provider setting names no
# request_timeout (Track L, Step L7).
DEFAULT_REQUEST_TIMEOUT = 300


class RecordedAnswers:
    """Answers read from a JSON book keyed by session id, for tests and replays."""

    def __init__(self, rest: str):
        if not rest:
            raise ValueError("the recorded kind needs a file, given as recorded:<path>")
        path = Path(rest)
        try:
            book = json.loads(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ValueError(f"the recorded answers {path} could not be read ({error})") from error
        except ValueError as error:
            raise ValueError(f"the recorded answers {path} are not JSON ({error})") from error
        if not isinstance(book, dict):
            raise ValueError(f"the recorded answers {path} must be a JSON object keyed by session id")
        self.book = book
        self.model = "recorded:" + path.name

    def ask(self, key: str, prompt: str) -> Tuple[str, str]:
        """The recorded answer for key, as text, and the model's name. The prompt is not read."""
        if key not in self.book:
            raise ValueError(f"the recorded answers hold no answer for {key}")
        value = self.book[key]
        if isinstance(value, str):
            return value, self.model
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False), self.model
        raise ValueError(
            f"the recorded answer for {key} is neither text nor an object, so it cannot be used"
        )


def provider_path() -> Path:
    """provider.yaml in CONNECTIONS_HOME when it is set, else in ~/.workflow_connections."""
    home = os.environ.get("CONNECTIONS_HOME") or os.path.join(
        os.path.expanduser("~"), ".workflow_connections"
    )
    return Path(home) / PROVIDER_FILE


def provider_setting() -> Dict[str, Any]:
    """The provider setting's base_url and model, with token_limit,
    token_limit_field, and request_timeout when the file names them.

    Raises ValueError naming the file when it is missing, cannot be read,
    lacks base_url or model, or names a limit or a timeout that is not a
    whole number above 0 or a field other than max_tokens or
    max_completion_tokens.
    """
    path = provider_path()
    try:
        setting = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"there is no provider setting at {path}. Write base_url and model there")
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise ValueError(f"the provider setting {path} cannot be read ({error})")
    if not isinstance(setting, dict):
        raise ValueError(f"the provider setting {path} must hold base_url and model")
    for key in ("base_url", "model"):
        value = setting.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"the provider setting {path} lacks {key}")
    found: Dict[str, Any] = {"base_url": setting["base_url"], "model": setting["model"]}
    if "token_limit" in setting:
        limit = setting["token_limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError(
                f"the provider setting {path} has a wrong token_limit, which must be a whole number above 0"
            )
        found["token_limit"] = limit
    if "token_limit_field" in setting:
        field = setting["token_limit_field"]
        if not isinstance(field, str) or field not in TOKEN_LIMIT_FIELDS:
            raise ValueError(
                f"the provider setting {path} has a wrong token_limit_field, which must be "
                + " or ".join(TOKEN_LIMIT_FIELDS)
            )
        found["token_limit_field"] = field
    if "request_timeout" in setting:
        wait = setting["request_timeout"]
        if isinstance(wait, bool) or not isinstance(wait, int) or wait <= 0:
            raise ValueError(
                f"the provider setting {path} has a wrong request_timeout, which must be a whole"
                " number of seconds above 0"
            )
        found["request_timeout"] = wait
    return found


class LiveAnswers:
    """Answers from the model service the provider setting names."""

    def __init__(self, rest: str):
        self.provider = provider_setting()
        self.asked = rest.strip() or self.provider["model"]
        self.url = self.provider["base_url"].rstrip("/") + "/chat/completions"
        self.limit = self.provider.get("token_limit", DEFAULT_TOKEN_LIMIT)
        self.field = self.provider.get("token_limit_field", TOKEN_LIMIT_FIELDS[0])
        self.wait = self.provider.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)
        # The bytes of the latest reply, or None before one comes.
        self.last_reply: Optional[bytes] = None

    def ask(self, key: str, prompt: str) -> Tuple[str, str]:
        """The service's answer to the prompt, as text, and the model it reports.

        The whole reply, as the bytes the service sent, is kept as last_reply.
        Raises OSError when four attempts fail, so the pass fails the session
        and writes nothing for it.
        """
        self.last_reply = None
        headers = {"Content-Type": "application/json"}
        secret = os.environ.get(KEY_ENV)
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        body = {"model": self.asked, "temperature": 0, self.field: self.limit,
                "messages": [{"role": "user", "content": prompt}]}
        last = None
        for attempt in range(4):
            try:
                request = urllib.request.Request(
                    self.url, data=json.dumps(body).encode("utf-8"), headers=headers
                )
                with urllib.request.urlopen(request, timeout=self.wait) as response:
                    sent = response.read()
                data = json.loads(sent)
                text = data["choices"][0]["message"]["content"] or ""
                self.last_reply = sent
                return text, "live:" + (data.get("model") or self.asked)
            except Exception as error:  # retry transient failures (429, timeouts)
                last = error
                time.sleep(5 * (attempt + 1))
        raise OSError(f"the model service at {self.url} did not answer for {key} ({last})")


# Each kind of answer source, by the kind's name.
KINDS = {"recorded": RecordedAnswers, "live": LiveAnswers}


def open_answers(spec: str):
    """The answer source the spec names, <kind>:<rest>, refusing a kind KINDS does not hold."""
    kind, _, rest = str(spec).partition(":")
    if kind not in KINDS:
        raise ValueError(
            f"there is no answer source of the kind {kind}. The kinds are "
            + ", ".join(sorted(KINDS))
        )
    return KINDS[kind](rest)
