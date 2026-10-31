"""exclude_author: the record says which changes an AI made, and the rest are the scholar's.

Reads changes.json and rationales.yaml, the record of the AI's changes as the audit
layer writes it out ([{id, anchor, kind, rationale, session, session_ref}]). An entry's
anchor matches a change when it equals the change's revised or baseline sentence
(normalized), or is contained in one of them (anchors of four words or more). Each entry
binds to at most one change and each change to at most one entry, in entry order, except
that an edit or a move may take one delete entry and one insert entry, since the audit
layer writes an AI move or rewrite made by two edits that way. A change an entry names is the
AI's, and it carries the entry's id as record_id, the entry's rationale (empty when the AI
stated none), and its session_ref when the entry gives one. A change with two entries
carries both ids and both kinds joined by "and", and their distinct reasons in entry order.
Every other change is the scholar's own, listed and not checked.

An entry of kind write is an AI tool call that wrote the whole file. It names no sentence,
so the record cannot tell its changes from the scholar's, and a blocking finding on the
entry says so for the scholar to judge. Changes the AI made through shell commands are not
in the record at all, so they are listed as the scholar's. Writes ai_changes.json and
author_changes.json.
"""
import _lib


def matches(anchor, change):
    a = _lib.norm(anchor or "")
    if not a:
        return False
    sides = [_lib.norm(change["after"]), _lib.norm(change["before"])]
    if a in sides:
        return True
    return len(a.split()) >= 4 and any(a in s for s in sides if s)


changes = _lib.read_json("changes.json")
record = _lib.read_yaml("rationales.yaml") or []
if isinstance(record, dict):
    record = record.get("rationales") or []

PAIR = ("delete", "insert")


def kind_of(entry):
    return str(entry.get("kind") or "").strip().lower()


def can_take(c, entry, taken):
    """Whether change c can take entry, given the entries it already has."""
    if not taken:
        return True
    if len(taken) > 1 or c["kind"] not in ("edit", "move"):
        return False
    return {kind_of(taken[0]), kind_of(entry)} == set(PAIR)


bound = {}
writes = []
for n, entry in enumerate(record, 1):
    entry = dict(entry, id=str(entry.get("id") or f"r{n:02d}"))
    if kind_of(entry) == "write":
        writes.append(entry)
        continue
    hit = next((c for c in changes
                if can_take(c, entry, bound.get(c["id"], [])) and matches(entry.get("anchor"), c)), None)
    if hit is not None:
        bound.setdefault(hit["id"], []).append(entry)

ai, author, findings = [], [], []
for c in changes:
    entries = bound.get(c["id"])
    if not entries:
        author.append(dict(c))
        findings.append(_lib.finding(
            "exclude_author", "info", c["id"],
            "the scholar's own change, which no record entry names, listed not checked",
            _lib.cell(c["after"] or c["before"], 120)))
        continue
    reasons = []
    for e in entries:
        reason = str(e.get("rationale") or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
    row = dict(c, record_id=" and ".join(e["id"] for e in entries),
               record_kind=" and ".join(str(e.get("kind") or "") for e in entries),
               rationale=" ".join(reasons))
    ref = next((str(e["session_ref"]) for e in entries if e.get("session_ref")), None)
    if ref:
        row["session_ref"] = ref
    ai.append(row)

for entry in writes:
    reason = str(entry.get("rationale") or "").strip()
    ref = str(entry.get("session_ref") or "").strip()
    findings.append(_lib.finding(
        "exclude_author", "blocking", entry["id"],
        "an AI tool call wrote the whole file, so the record cannot tell which changes are the AI's",
        _lib.cell("Record entry {} {}{} The changes listed as the scholar's own may hold the AI's.".format(
            entry["id"], 'gives the reason "%s"%s' % (reason, "" if reason[-1:] in ".!?" else ".")
            if reason else "gives no reason.", " It came from session %s." % ref if ref else ""), 300)))

_lib.write_json("ai_changes.json", ai)
_lib.write_json("author_changes.json", author)
_lib.emit_findings("exclude_author", findings)
