"""The entry checker, which keeps every knowledge base entry in shape.

check_corpus applies the rules of appendix A2.4 "Creating entries" and the
frozen entry shape in CONTRACT.md to every entry and to the index llms.txt. It
returns the problems as text, one per broken rule, each starting with the
entry's <folder>/<file> or with llms.txt. An empty list means the corpus
passes.

The last rule asks that llms.txt be exactly the index the corpus gives. It is
read only once every other rule passes, since the index is rendered from
entries in shape and a broken entry would otherwise be reported twice.
"""
import re
from pathlib import Path

from audit_layer.kb.entries import KEYS, load
from audit_layer.kb.index import render_llms

LONG_DASH = "\u2014"
ALLOWED_SECTIONS = ("## Gaps", "## Consult also")

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_COMMIT = re.compile(r"sha256:[0-9a-f]{12}|[0-9a-f]{7,12}")
_GROUP = re.compile(r"[A-Z]+")
# A /home/ or /tmp/ path starts a path, so one inside a web address or after
# another folder name is not counted.
_PROSE_PATH = re.compile(r"(?<![\w.:/-])/(home|tmp)/")
_LINK = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]*)")
_INDEX_LINK = re.compile(r"^- \[[^\]]*\]\(([^)]+)\)", re.M)
_INDEX_GROUP = re.compile(r"^## (.+)$", re.M)


def check_corpus(corpus):
    """Every problem in the corpus, as text, one per broken rule."""
    corpus = Path(corpus)
    entries = load(corpus)
    if not entries:
        return ["corpus: no entry file, an entry is <group lowercased>/<id>.md"]
    stems = {entry["path"].stem for entry in entries}
    problems = []
    for entry in entries:
        for problem in _check_entry(entry, stems):
            problems.append("{}: {}".format(entry["rel"], problem))
    problems.extend(_check_index(corpus, entries))
    if not problems:
        problems.extend(_check_rendered(corpus))
    return problems


def _check_rendered(corpus):
    text = (corpus / "llms.txt").read_text(encoding="utf-8")
    if text == render_llms(corpus):
        return []
    return [
        "llms.txt: differs from the index the corpus gives, run python3 -m audit_layer.kb llms"
        " to rewrite it"
    ]


def _check_entry(entry, stems):
    text = entry["path"].read_text(encoding="utf-8")
    if entry["problems"]:
        # Without a frontmatter block the other rules cannot be read, so the
        # block is reported alone, with only the machine path rule beside it.
        found = list(entry["problems"])
        found.extend(_machine_paths(text))
        return found
    front = entry["front"]
    found = []
    found.extend(_keys(front))
    found.extend(_id_and_group(entry))
    found.extend(_title_and_point(entry))
    found.extend(_sections(entry["body"]))
    if "updated" in front and not _DATE.fullmatch(front["updated"]):
        found.append("updated is not a YYYY-MM-DD date, it reads '{}'".format(front["updated"]))
    if "source_commit" in front and not _COMMIT.fullmatch(front["source_commit"]):
        found.append(
            "source_commit is neither sha256: plus 12 lowercase hex characters nor 7 to 12"
            " lowercase hex characters, it reads '{}'".format(front["source_commit"])
        )
    found.extend(_machine_paths(text))
    found.extend(_links(entry["body"]))
    found.extend(_consult_also(entry["body"], stems))
    return found


def _keys(front):
    missing = [key for key in KEYS if key not in front]
    extra = sorted(key for key in front if key not in KEYS)
    if not missing and not extra:
        return []
    parts = []
    if missing:
        parts.append("missing " + ", ".join(missing))
    if extra:
        parts.append("extra " + ", ".join(extra))
    return ["the frontmatter keys are not the six, " + ", ".join(parts)]


def _id_and_group(entry):
    front = entry["front"]
    path = entry["path"]
    reasons = []
    entry_id = front.get("id")
    group = front.get("group")
    if entry_id is not None and entry_id != path.stem:
        reasons.append("the id {} differs from the file name {}".format(entry_id, path.name))
    if group is not None:
        prefix = group.lower() + "-"
        if entry_id is not None and not entry_id.startswith(prefix):
            reasons.append("the id {} lacks the prefix {}".format(entry_id, prefix))
        if path.parent.name != group.lower():
            reasons.append(
                "the file sits in the folder {}, not {}".format(path.parent.name, group.lower())
            )
        if not _GROUP.fullmatch(group):
            reasons.append("the group {} is not capital letters only".format(group))
    if not reasons:
        return []
    return ["the id or group does not fit the file, " + "; ".join(reasons)]


def _title_and_point(entry):
    lines = entry["body"].splitlines()
    found = []
    first = lines[0] if lines else ""
    title = entry["front"].get("title")
    if title is not None and first != "# " + title:
        found.append("the first body line is not '# {}'".format(title))
    if first.startswith("# "):
        following = [line for line in lines[1:] if line.strip()]
        if not following or following[0].startswith("#"):
            found.append("no point paragraph follows the title line")
    return found


def _sections(body):
    headings = [line.rstrip() for line in _prose_lines(body) if line.startswith("## ")]
    reasons = []
    others = [heading for heading in headings if heading not in ALLOWED_SECTIONS]
    if others:
        reasons.append("found " + ", ".join("'{}'".format(h) for h in others))
    if "## Gaps" in headings and "## Consult also" in headings:
        if headings.index("## Gaps") > headings.index("## Consult also"):
            reasons.append("'## Gaps' comes after '## Consult also'")
    if not reasons:
        return []
    return [
        "the second-level headings may be only '## Gaps' then '## Consult also', "
        + "; ".join(reasons)
    ]


def _machine_paths(text):
    if "/Users/" in text or "/private/tmp/" in text:
        return ["holds an authoring machine path (/Users/ or /private/tmp/)"]
    for line in _prose_lines(text):
        if _PROSE_PATH.search(line):
            return ["holds an authoring machine path (/home/ or /tmp/) outside a code fence"]
    return []


def _links(body):
    targets = []
    for line in _prose_lines(body):
        for target in _LINK.findall(line):
            if not (target.startswith("http://") or target.startswith("https://")):
                targets.append(target)
    if not targets:
        return []
    return ["a link target is not a web address, " + ", ".join(targets)]


def _consult_also(body, stems):
    unknown = []
    in_section = False
    for line in _prose_lines(body):
        if line.startswith("## "):
            in_section = line.rstrip() == "## Consult also"
            continue
        if in_section and line.startswith("- "):
            ref = line[2:].split(" " + LONG_DASH + " ")[0].split(" - ")[0].strip().strip("`")
            if ref not in stems:
                unknown.append(ref)
    if not unknown:
        return []
    return ["Consult also names ids with no entry, " + ", ".join(unknown)]


def _prose_lines(text):
    """The lines of the text outside code fences."""
    inside = False
    for line in text.splitlines():
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            inside = not inside
            continue
        if not inside:
            yield line


def _check_index(corpus, entries):
    index = corpus / "llms.txt"
    if not index.is_file():
        return ["llms.txt: missing, the index lists every entry"]
    text = index.read_text(encoding="utf-8")
    found = []
    if not text.startswith("# "):
        found.append("llms.txt: does not start with '# '")
    if not re.search(r"^> ", text, flags=re.M):
        found.append("llms.txt: has no '> ' line")
    listed = _INDEX_LINK.findall(text)
    expected = [entry["rel"] for entry in entries]
    left_out = [rel for rel in expected if rel not in listed]
    if left_out:
        found.append("llms.txt: leaves out " + ", ".join(left_out))
    for rel in sorted(set(listed)):
        if rel not in expected:
            found.append("llms.txt: lists {}, which does not exist".format(rel))
        if listed.count(rel) > 1:
            found.append("llms.txt: lists {} twice or more".format(rel))
    index_groups = {group.strip() for group in _INDEX_GROUP.findall(text)}
    corpus_groups = {entry["front"]["group"] for entry in entries if "group" in entry["front"]}
    if index_groups != corpus_groups:
        parts = []
        extra = sorted(index_groups - corpus_groups)
        missing = sorted(corpus_groups - index_groups)
        if extra:
            parts.append("extra " + ", ".join(extra))
        if missing:
            parts.append("missing " + ", ".join(missing))
        found.append(
            "llms.txt: its ## sections differ from the corpus's groups, " + ", ".join(parts)
        )
    return found
