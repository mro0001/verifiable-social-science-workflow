"""Compare the run's answers with a reference answer book.

Each key present in both books is compared on the fields both answers hold whose
value in the run is true or false, a number, or text of at most 40 characters
without spaces, so a reason worded another way is never counted as a different
verdict. An item is compared when it has at least one such field, and agrees
when every compared field is equal. Each differing field is a warning whose item
is <node>:<item>. Each step with a key in both books gets an info note of agreed
of compared, and the keys found in only one book get one info note.

agreement.json is {compared: true, total, agreed, steps}, with steps a list of
{node, compared, agreed} sorted by node.
"""
import _lib

CHECK = "compare_reference"
SHORT = 40


def short(value):
    """True when a run's value is one the comparison reads."""
    if isinstance(value, (bool, int, float)):
        return True
    return isinstance(value, str) and len(value) <= SHORT and not any(c.isspace() for c in value)


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    return a == b


run_book = _lib.read_json("answer_book.json")
reference = _lib.read_json("reference.json")
if not isinstance(reference, dict):
    reference = {}

findings = []
steps = {}
for key in sorted(set(run_book) & set(reference)):
    node = key.partition(":")[0]
    step = steps.setdefault(node, {"node": node, "compared": 0, "agreed": 0})
    ours, theirs = run_book[key], reference[key]
    if not isinstance(ours, dict) or not isinstance(theirs, dict):
        continue
    fields = sorted(f for f in ours if f in theirs and short(ours[f]))
    if not fields:
        continue
    step["compared"] += 1
    differ = [f for f in fields if not same(ours[f], theirs[f])]
    if not differ:
        step["agreed"] += 1
    for field in differ:
        findings.append(_lib.finding(
            CHECK, "warning", key,
            "The run's {} differs from the reference.".format(field),
            "{} is {} in the run and {} in the reference".format(
                field, _lib.cell(ours[field], limit=80), _lib.cell(theirs[field], limit=80))))

for node in sorted(steps):
    step = steps[node]
    message = "{} of {} compared items agree with the reference.".format(step["agreed"], step["compared"])
    if not step["compared"]:
        message = "0 of 0 compared items agree with the reference, since its answers hold no short field to compare."
    findings.append(_lib.finding(CHECK, "info", node, message))

only = sorted(set(run_book) ^ set(reference))
if only:
    findings.append(_lib.finding(
        CHECK, "info", "reference",
        "{} keys are in only one of the two answer books, so they were not compared.".format(len(only)),
        ", ".join(only)))

rows = [steps[node] for node in sorted(steps)]
_lib.write_json("agreement.json", {"compared": True, "total": sum(r["compared"] for r in rows),
                                   "agreed": sum(r["agreed"] for r in rows), "steps": rows})
_lib.emit_findings(CHECK, findings)
