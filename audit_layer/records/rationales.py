"""The written-out AI rationales record, which gives each AI edit to a source its stated reason.

Appendix A2.5 "Prose" asks that each AI edit come with a stated reason, and
Table A5 lists the AI rationales among the records the procedures read, which
nothing wrote before. A2.4 writes a project's records out as files. The prose
procedure's reader, rationale_coverage, reads a list of entries with an id, an
anchor, a kind, and a rationale, the anchor being the revised sentence or the
deleted one.

A stated reason is the assistant's own text written after its previous tool
call and before the edit, read from the stored transcript (Track W choice 7).
A typed prompt from the scholar clears it, and thinking parts are left out.
It is read from the session's ordered parts (role, then text or a tool call),
which every harness's adapter gives, and the stored transcript is parsed with
the session's own harness's adapter (capture.read_stored), so a ForgeCode
session gives the same entries as a Claude Code session with the same
actions (Track A, Step A4). A ForgeCode patch comes as an Edit.
Each Edit on the source is split into sentence changes with the prose
procedure's rules, written again here since layers do not share code (choice
9), and each change gets one entry naming its session by the harness's id and
by its public id, session_ref (Track P, step P2). An Edit with no stated
reason gets entries with an empty rationale, since the prose procedure takes
the record's entries as the changes an AI made and reports each one with no
recorded reason (Track V, step V1).

Each edit of a MultiEdit on the source is split the same way. A Write on the
source gives the whole file and not what it replaced, so it gives one entry of
kind write with an empty anchor, which tells the prose procedure that an AI
tool call rewrote the file and that its changes cannot be told apart. Moves
inside one edit are not seen (Track W gap G7), and changes made through shell
commands are not in the record. Only sessions whose harness's adapter has the
AI flag are read, and another session is skipped and named on standard error.
The stored event's rationale stays the model pass's field, and the reason is
read from the transcript each time the record is written out.
"""
import difflib
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import yaml

from audit_layer.capture import ADAPTERS, read_stored
from audit_layer.capture.claude_code import Part
from audit_layer.queries import current_session
from audit_layer.records.session_index import public_id
from audit_layer.store import Store, current

# The prose procedure's threshold for pairing two sentences as an edit.
EDIT_SIMILARITY = 0.5

FIELDS = ("id", "anchor", "kind", "rationale", "session", "session_ref")

# The prose procedure's sentence rules. A sentence ends at ., !, or ? before a
# space and a capital, a quote, a parenthesis, or a bracket, and after a
# sentence that ends inside a closing quote.
_FRONT_MATTER = re.compile(r"^---\n.*?\n---\n", re.S)
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"(\[])")
_CLOSE_QUOTE_END = re.compile(r'(?<=[.!?]["”\'’])\s+(?=[A-Z"“(\[])')


def stated_reasons(parts: Sequence[Part]) -> Dict[str, str]:
    """Each tool call's id mapped to the assistant text written before it since the last call.

    parts are a session's ordered parts, as any adapter gives them. A user
    text part, a typed prompt, clears the text waiting for a call, and so does
    a meta part, text the harness put in a user record. Tool results sit on
    their calls' parts, and thinking and system records are not parts, so they
    change nothing.
    """
    reasons: Dict[str, str] = {}
    pending: List[str] = []
    for part in parts:
        if part.tool_call is not None:
            reasons[part.tool_call.record_id] = " ".join(pending).strip()
            pending = []
        elif part.role in ("user", "meta"):
            pending = []
        elif part.role == "assistant" and isinstance(part.text, str):
            pending.append(part.text)
    return reasons


def sentence_changes(old: str, new: str) -> List[Tuple[str, str]]:
    """The sentence changes from old to new text, as (kind, anchor).

    A sentence on both sides is unchanged. Each other new sentence pairs with
    the most similar remaining old one at a word similarity of 0.5 or more,
    an edit anchored on the new sentence. An unpaired new sentence is an
    insert, and an unpaired old one a delete anchored on itself. Inserts and
    edits come in the new text's order, then deletes in the old text's order.
    """
    old_sentences = _sentences(old)
    new_sentences = _sentences(new)
    old_norm = [_norm(s) for s in old_sentences]
    new_norm = [_norm(s) for s in new_sentences]
    free_old = list(range(len(old_sentences)))
    free_new = []
    for j, sentence in enumerate(new_norm):
        match = next((i for i in free_old if old_norm[i] == sentence), None)
        if match is None:
            free_new.append(j)
        else:
            free_old.remove(match)
    changes = []
    for j in free_new:
        best = None
        best_similarity = 0.0
        for i in free_old:
            similarity = difflib.SequenceMatcher(
                None, old_norm[i].split(), new_norm[j].split(), autojunk=False
            ).ratio()
            if similarity > best_similarity:
                best, best_similarity = i, similarity
        if best is not None and best_similarity >= EDIT_SIMILARITY:
            free_old.remove(best)
            changes.append(("edit", new_sentences[j]))
        else:
            changes.append(("insert", new_sentences[j]))
    changes.extend(("delete", old_sentences[i]) for i in free_old)
    return changes


def rationales(store: Store, source) -> List[Dict[str, str]]:
    """One entry for each sentence change an AI Edit or MultiEdit made to the source, and one
    of kind write for each AI Write on it, with its stated reason or "".

    The sessions are those with a current event that may change the source
    (an edited or wrote event on it, compared as real paths, or a MultiEdit),
    in the order they started. Each one's latest stored
    transcript is read with its harness's adapter. A session from a harness
    whose adapter lacks the AI flag, or that has no adapter, is skipped and
    named on standard error.
    """
    target = os.path.realpath(str(source))
    entries: List[Dict[str, str]] = []
    for harness, session_id in _editing_sessions(store, target):
        if getattr(ADAPTERS.get(harness), "AI", False) is not True:
            print(
                f"skipped session {session_id} from harness {harness},"
                " which is not a harness of AI sessions",
                file=sys.stderr,
            )
            continue
        row = current_session(store, harness, session_id)
        if row is None:
            raise ValueError(f"session {session_id} has no current row in the store")
        session = read_stored(store, row)
        reasons = stated_reasons(session.parts)
        for tool_call in session.tool_calls:
            if tool_call.name not in ("Edit", "MultiEdit", "Write"):
                continue
            given = tool_call.input if isinstance(tool_call.input, dict) else {}
            path_given = given.get("file_path")
            if not isinstance(path_given, str) or not path_given.strip():
                continue
            resolved = os.path.normpath(os.path.join(session.cwd, path_given))
            if os.path.realpath(resolved) != target:
                continue
            reason = reasons.get(tool_call.record_id, "")
            for kind, anchor in _call_changes(tool_call.name, given):
                entries.append(
                    {
                        "id": "r{:02d}".format(len(entries) + 1),
                        "anchor": anchor,
                        "kind": kind,
                        "rationale": reason,
                        "session": session_id,
                        "session_ref": public_id(session_id),
                    }
                )
    return entries


def write_rationales(entries: List[Dict[str, str]], out) -> None:
    """Write the entries to the file out as a YAML list, each in the field order."""
    ordered = [{name: entry[name] for name in FIELDS} for entry in entries]
    text = yaml.safe_dump(
        ordered, sort_keys=False, default_flow_style=False, allow_unicode=True, width=4096
    )
    Path(out).write_text(text, encoding="utf-8")


def _editing_sessions(store: Store, target: str) -> List[Tuple[str, str]]:
    """The harness and session id of each session with a current event that may change target.

    That is an edited or wrote event on target, or a MultiEdit, whose event names
    the tool and not the file, so its transcript says which file it changed.

    They come earliest start first, and sessions with the same start in the
    order their first such event was stored.
    """
    found: Dict[str, Tuple[str, str]] = {}
    for event in current(store, "events"):
        if not _may_change(event, target):
            continue
        row = store.db.execute(
            "SELECT harness, harness_session_id, started_at FROM sessions WHERE id = ?",
            (event["session_row_id"],),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"event {event['id']} points to session row {event['session_row_id']},"
                " which the store does not hold"
            )
        harness, session_id, started_at = row
        if session_id not in found:
            found[session_id] = (started_at or "", harness)
    ordered = sorted(found.items(), key=lambda item: item[1][0])
    return [(harness, session_id) for session_id, (_, harness) in ordered]


def _call_changes(name: str, given: Dict[str, Any]) -> List[Tuple[str, str]]:
    """The (kind, anchor) changes one Edit, MultiEdit, or Write call made to the source."""
    if name == "Write":
        return [("write", "")]
    if name == "MultiEdit":
        edits = given.get("edits")
        pairs = [edit for edit in edits if isinstance(edit, dict)] if isinstance(edits, list) else []
    else:
        pairs = [given]
    changes: List[Tuple[str, str]] = []
    for edit in pairs:
        changes.extend(sentence_changes(_text(edit.get("old_string")), _text(edit.get("new_string"))))
    return changes


def _may_change(event: Dict[str, Any], target: str) -> bool:
    if event["verb"] == "ran":
        return event["object"] == "MultiEdit"
    if event["verb"] not in ("edited", "wrote") or not isinstance(event["object"], str):
        return False
    return os.path.realpath(event["object"]) == target


def _sentences(text: str) -> List[str]:
    """The prose procedure's sentences, with front matter, blank lines, and headings left out."""
    body = _FRONT_MATTER.sub("", text, count=1)
    out = []
    for paragraph in _PARAGRAPH.split(body):
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith("#"):
            continue
        paragraph = re.sub(r"\s+", " ", paragraph)
        for sentence in _SENTENCE_END.split(paragraph):
            for part in _CLOSE_QUOTE_END.split(sentence.strip()):
                if part.strip():
                    out.append(part.strip())
    return out


def _norm(text: str) -> str:
    """Text as the prose procedure compares it, NFKC, straight quotes, plain hyphens, collapsed spaces, lower case."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("–", "-").replace("—", "-").replace("­", "")
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""
