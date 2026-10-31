"""The model tagging pass, which fills each session's title, gist, summary, and keywords.

Proposal Approach paragraph 5 has the audit layer tag every AI session
transcript and tool call. Appendix Table A4 gives the model pass one AI model
call per session, which fills the session's title, gist, summary, and
keywords and a rationale for each decision, and Table A3 stamps each with the
pass that produced it. Tagging fills the schema's fields and adds none, and
the derived layer is regenerable from the kept transcript (spec 0.11).

- due(store) lists the sessions the pass has yet to tag (Step A9).
- render_prompt(session_row, events, messages) fills the template
  model_pass.prompt.md with the action log and the conversation, cut to
  60,000 characters keeping the start and the end (plan choice 9).
- parse_answer(text, ordinals) reads the model's answer and checks it
  against the limits of plan choice 9 (Step A10).
- tag_session(store, session_row, answers) asks the answer source once for
  the session and writes a clean answer into the store (Step A10). A live
  source's whole reply, the bytes the service sent, is saved first in the
  audit home as replies/<session id>.reply.json, whether or not the answer is
  clean, and a later reply for the same session is saved beside it as
  <session id>.2.reply.json and so on (Track L, Step L7, decision 46). The
  session row is superseded with the four fields filled, and each decision
  supersedes the event it names with kind decision and its rationale (plan
  choice 10). Every row it writes has origin model pass, the method
  model_pass 1; model <model>, and reason tagging (plan choice 14), so its
  fields read as unreviewed until a person reviews them (Table A4). The
  session row and its decisions are written in one transaction, so an
  answer with problems, or one whose rows a sweep superseded while the pass
  waited, writes nothing.

The reconciliation drops the excluded-folder guard the plan gave the pass
(item 3), so the pass reads every session capture stored, and due skips
sessions whose adapter lacks the AI flag (reconciliation, Track A).
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from audit_layer import capture
from audit_layer.queries import session_events
from audit_layer.store import Store, StoreError, current, supersede_all

TEMPLATE = Path(__file__).with_name("model_pass.prompt.md")

# The most of the conversation a prompt holds, and the line put where its
# middle is left out (plan choice 9).
LIMIT = 60000
MIDDLE = "[... middle of the conversation left out ...]"

# The template's two slots.
_SLOTS = re.compile(r"\{\{(ACTION_LOG|CONVERSATION)\}\}")

# A row a person wrote has the origin person <name> (plan choice 12).
_PERSON = "person "

# The pass's version, which its method names with the model's name.
VERSION = 1
ORIGIN = "model pass"
REASON = "tagging"

# The folder in the audit home that holds each live reply whole.
REPLIES = "replies"

# The five keys of an answer, and the limits of plan choice 9.
KEYS = ("title", "gist", "summary", "keywords", "decisions")
TITLE_MOST = 80
GIST_MOST = 200
SUMMARY_MOST = 1200
KEYWORDS_FEWEST = 3
KEYWORDS_MOST = 10

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?[ \t]*\n(.*?)```", re.DOTALL)
# Closing and opening quotes and brackets, straight and curly.
_CLOSERS = "\"')]\u201d\u2019"
_OPENERS = "\"'([\u201c\u2018"
# A sentence ends at ., ?, or !, then any closing quote or bracket, then
# space and a capital letter, so "e.g. the" is not a break.
_BREAK = re.compile(
    r"[.?!][" + re.escape(_CLOSERS) + r"]*\s+[" + re.escape(_OPENERS) + r"]*[A-Z]"
)
_ENDS = (".", "?", "!")
# A full stop after one of these short titles, or after a single capital
# letter as in an initial, does not end a sentence.
_TITLES = ("Dr", "Mr", "Mrs", "Ms", "Prof")
_LAST_WORD = re.compile(r"(\w+)$")


class Outcome(NamedTuple):
    """What the pass did with one session."""

    # The harness's id for the session.
    session_id: str
    # tagged or failed.
    status: str
    # Why it failed, one line each, or empty when it was tagged.
    problems: Tuple[str, ...]


def due(store: Store) -> List[Dict[str, Any]]:
    """The current session rows the pass has yet to tag, in the order written.

    A row is due when its title is empty and no person wrote its current
    version, and its harness's adapter has the AI flag. A harness with no
    adapter is not due.
    """
    found = []
    for row in current(store, "sessions"):
        if row["title"]:
            continue
        if str(row["origin"]).startswith(_PERSON):
            continue
        reader = capture.ADAPTERS.get(row["harness"])
        if reader is None or getattr(reader, "AI", False) is not True:
            continue
        found.append(row)
    return found


def render_prompt(
    session_row: Dict[str, Any],
    events: Sequence[Dict[str, Any]],
    messages: Sequence[Tuple[str, str]],
) -> str:
    """The prompt for one session, the template with its action log and conversation.

    The action log has one line per event, <ordinal> <verb> <kind> <object>,
    in the order given, with any line break in an object made a space. The
    conversation is each message as <role>: <text>, with a blank line
    between, and is cut to LIMIT characters by keeping the first and last
    half with the MIDDLE line between them. Each slot is filled once, so text
    in a message that looks like a slot stays as it is. The session row
    names the session the prompt is for, and nothing of it goes in the
    prompt, since the template has no slot for it.
    """
    action_log = "\n".join(_event_line(event) for event in events)
    conversation = _cut("\n\n".join(f"{role}: {text}" for role, text in messages))
    filled = {"ACTION_LOG": action_log, "CONVERSATION": conversation}
    template = TEMPLATE.read_text(encoding="utf-8")
    return _SLOTS.sub(lambda match: filled[match.group(1)], template)


def _event_line(event: Dict[str, Any]) -> str:
    object_ = " ".join(str(event["object"] or "").splitlines())
    return "{} {} {} {}".format(event["ordinal"], event["verb"], event["kind"], object_)


def _cut(text: str) -> str:
    """The text, or its first and last half of LIMIT with the MIDDLE line between."""
    if len(text) <= LIMIT:
        return text
    half = LIMIT // 2
    return text[:half] + "\n" + MIDDLE + "\n" + text[-half:]


def parse_answer(text: str, ordinals: Sequence[int]) -> Tuple[Optional[Dict[str, Any]], Tuple[str, ...]]:
    """The tags an answer gives and its problems, or None and the problems.

    Any <think> block is dropped first, and when the answer holds a code
    fence the JSON object is read from inside it. The first JSON object in
    the text is read, so a line before or after it is passed over. The object
    must have the
    five keys and no other, within the limits of plan choice 9. Each decision
    names an ordinal of the action log, given in ordinals, and no ordinal is
    named twice. Each rationale is one sentence, ending with ., ?, or ! and
    with no sentence break inside. The tags hold the four fields as given,
    less space at their ends, and the decisions as (ordinal, rationale) pairs.
    """
    body = _THINK.sub("", str(text)).strip()
    fenced = _FENCE.search(body)
    if fenced:
        body = fenced.group(1).strip()
    answer = _first_object(body)
    if not isinstance(answer, dict):
        return None, ("the answer is not a JSON object",)

    problems = [f"{key} is missing" for key in KEYS if key not in answer]
    problems += [
        f"{key} is not one of the five keys" for key in sorted(map(str, answer)) if key not in KEYS
    ]
    tags: Dict[str, Any] = {}
    for key, most, one_line, one_paragraph in (
        ("title", TITLE_MOST, False, False),
        ("gist", GIST_MOST, True, False),
        ("summary", SUMMARY_MOST, False, True),
    ):
        if key in answer:
            problem = _text_problem(key, answer[key], most, one_line, one_paragraph)
            if problem:
                problems.append(problem)
            else:
                tags[key] = answer[key].strip()
    if "keywords" in answer:
        problem = _keywords_problem(answer["keywords"])
        if problem:
            problems.append(problem)
        else:
            tags["keywords"] = [term.strip() for term in answer["keywords"]]
    if "decisions" in answer:
        decisions, found = _decisions(answer["decisions"], ordinals)
        problems += found
        tags["decisions"] = decisions
    if problems:
        return None, tuple(problems)
    return tags, ()


def tag_session(store: Store, session_row: Dict[str, Any], answers) -> Outcome:
    """Ask once for the session's tags and write a clean answer into the store.

    answers is an answer source (answers.py), asked with the session's id as
    the key. A session whose transcript cannot be read, an answer the source
    cannot give, and an answer with problems write nothing and fail.
    """
    name = session_row["harness_session_id"]
    try:
        events = session_events(store, session_row)
        messages = capture.read_stored(store, session_row).messages
    except (OSError, ValueError) as error:
        return Outcome(name, "failed", (f"its stored transcript could not be read, {error}",))
    prompt = render_prompt(session_row, events, messages)
    try:
        text, model = answers.ask(name, prompt)
    except (OSError, ValueError) as error:
        return Outcome(name, "failed", (str(error),))
    reply = getattr(answers, "last_reply", None)
    if reply is not None:
        try:
            save_reply(store, name, reply)
        except OSError as error:
            return Outcome(name, "failed", (f"its reply could not be saved, {error}",))
    by_ordinal = {event["ordinal"]: event for event in events}
    tags, problems = parse_answer(text, list(by_ordinal))
    if problems:
        return Outcome(name, "failed", problems)

    provenance = {
        "session": name,
        "origin": ORIGIN,
        "method": f"model_pass {VERSION}; model {model}",
        "reason": REASON,
    }
    fields = {key: tags[key] for key in ("title", "gist", "summary", "keywords")}
    writes = [("sessions", session_row["id"], fields, provenance)]
    for ordinal, rationale in tags["decisions"]:
        changes = {"kind": "decision", "rationale": rationale}
        writes.append(("events", by_ordinal[ordinal]["id"], changes, provenance))
    # The session row and its decisions are written together or not at all.
    # A sweep that superseded one of their rows while the pass waited for the
    # answer leaves the session due again, so the next run tags it.
    try:
        supersede_all(store, writes)
    except StoreError as error:
        problem = f"its rows changed while it was tagged, so nothing was written, {error}"
        return Outcome(name, "failed", (problem,))
    return Outcome(name, "tagged", ())


def save_reply(store: Store, name: str, reply: bytes) -> Path:
    """Save a live reply as the bytes the service sent, never replacing an earlier one.

    The file is replies/<session id>.reply.json in the audit home, or
    <session id>.<n>.reply.json from the second reply on. Any character of the
    id other than a letter, a digit, a dot, a dash, or an underscore is
    written as an underscore, so the name stays inside the folder.
    """
    folder = store.home / REPLIES
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".") or "_"
    path = folder / f"{stem}.reply.json"
    count = 1
    while path.exists():
        count += 1
        path = folder / f"{stem}.{count}.reply.json"
    with open(path, "xb") as handle:
        handle.write(reply)
    return path


def _text_problem(key: str, value: Any, most: int, one_line: bool, one_paragraph: bool) -> Optional[str]:
    if not isinstance(value, str):
        return f"{key} must be text"
    value = value.strip()
    if not value:
        return f"{key} is empty"
    if len(value) > most:
        return f"{key} is longer than {most:,} characters"
    if one_line and len(value.splitlines()) > 1:
        return f"{key} is not one line"
    if one_paragraph and re.search(r"\n[ \t]*\n", value):
        return f"{key} is not one paragraph"
    return None


def _keywords_problem(value: Any) -> Optional[str]:
    if not isinstance(value, list) or not all(
        isinstance(term, str) and term.strip() for term in value
    ):
        return "keywords must be a list of terms"
    if not KEYWORDS_FEWEST <= len(value) <= KEYWORDS_MOST:
        return f"keywords must hold {KEYWORDS_FEWEST} to {KEYWORDS_MOST} terms"
    return None


def _decisions(value: Any, ordinals: Sequence[int]) -> Tuple[List[Tuple[int, str]], List[str]]:
    """The decisions as (ordinal, rationale) pairs, and their problems."""
    if not isinstance(value, list):
        return [], ["decisions must be a list"]
    known = set(ordinals)
    named = set()
    decisions = []
    problems = []
    for number, decision in enumerate(value, start=1):
        if not isinstance(decision, dict) or set(decision) != {"ordinal", "rationale"}:
            problems.append(
                f"decision {number} must be an object with an ordinal and a rationale"
            )
            continue
        ordinal = decision["ordinal"]
        rationale = decision["rationale"]
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            problems.append(f"decision {number} has an ordinal that is not a whole number")
        elif ordinal not in known:
            problems.append(f"decision {number} names ordinal {ordinal}, which the action log lacks")
        elif ordinal in named:
            problems.append(
                f"decision {number} names ordinal {ordinal}, which an earlier decision names"
            )
        if not _one_sentence(rationale):
            problems.append(f"decision {number} has a rationale that is not one sentence")
        if isinstance(ordinal, int) and not isinstance(ordinal, bool):
            named.add(ordinal)
        if isinstance(rationale, str):
            decisions.append((ordinal, rationale.strip()))
    return decisions, problems


def _first_object(text: str) -> Any:
    """The first JSON object in text, or None when it holds none."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            found, _ = decoder.raw_decode(text, start)
        except ValueError:
            found = None
        if isinstance(found, dict):
            return found
        start = text.find("{", start + 1)
    return None


def _one_sentence(value: Any) -> bool:
    """Whether value is one sentence, ending with ., ?, or ! and with no break inside.

    Closing quotes and brackets may follow the end mark. A full stop after a
    short title such as Dr. or after an initial is not a break.
    """
    if not isinstance(value, str):
        return False
    body = value.strip().rstrip(_CLOSERS)
    if not body or not body.endswith(_ENDS):
        return False
    body = body[:-1]
    for found in _BREAK.finditer(body):
        word = _LAST_WORD.search(body[: found.start()])
        if body[found.start()] == "." and word and (
            word.group(1) in _TITLES or (len(word.group(1)) == 1 and word.group(1).isupper())
        ):
            continue
        return False
    return True
