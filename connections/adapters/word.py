"""The Word adapter, which turns a reviewed Word document into the prose stream's input files (Track D, step D19).

Appendix-only. Table A6 lists an adapter for Word as specified, and its note
says the adapter that fills the prose stream's files is not built. A2.5 Prose
says that for Word, programs show AI changes as tracked changes and then read
back the scholar's responses, and the A2.2 Adapters bullet names an adapter
from a Word document with tracked changes to the files the prose procedure
checks. It reads the document with the Word reader (step D18).

python3 -m connections adapt word --out DIR --docx FILE --ai-author NAME
[--annotations FILE] [--builds-dir DIR --baseline-version vNNN] writes the
four files the prose procedure of version 0.3 requires.

- baseline.md and revised.md, the document's text with every tracked change
  rejected and with every one accepted, as side_text writes them.
- rationales.yaml, the record of the AI's changes (Track V choices 2 and 3),
  each entry an id rNN, an anchor, a kind, and a rationale. Each sentence the
  AI author's tracked changes touch gets one entry, in document order, so the
  changes inside one sentence share it. The anchor is the revised sentence
  holding the change, or for a deletion the revised form of its sentence,
  found through a character the sentence keeps, or the baseline sentence when
  none is kept. The change's own kind is edit inside a sentence that keeps
  some of its text, insert for a whole new sentence, and delete for a whole
  removed one, so an AI move given as a deletion and an insertion of one
  sentence is a delete entry and an insert entry on that sentence.
  An AI comment covers an entry when it marks text of the entry's sentence.
  The kind is copied from the covering comment's leading [edit], [insert],
  [delete], or [move] tag when there is one (Track D choice 14), and is
  otherwise the change's own kind. A [move] tag on one half of a move gives
  that half its own kind, since the record gives a move as a delete entry and
  an insert entry. The rationale is the rest of the comment's text, or empty
  text when no comment covers the entry, which the prose procedure reports as
  an AI change with no recorded reason. Of several covering comments, the
  first the document lists whose tag is the change's own kind is taken, or
  else the first. Another author's tracked changes get no entry, since a
  change no entry names is the scholar's own, and their comments are left
  out.
  An AI comment no entry takes gets an entry of its own after the others, so
  a reason given for a sentence that did not change still reaches the
  report. Its anchor is the revised sentence holding the first character it
  covers, or the baseline sentence when it covers only deleted text, and its
  kind is its tag, empty when there is none. One on a sentence holding only
  another author's tracked changes is left out, and the adapter prints why.
  With --annotations, the YAML list annotate read (anchor, text, tag) takes
  the place of the comments, each read as the comment annotate writes from
  it. An annotation covers each sentence its anchor names, equal to the
  sentence or a part of it of four words or more as the prose procedure
  matches, and one no entry takes keeps its anchor as given.
- versions.yaml. With --builds-dir and --baseline-version it finds the
  version's row in BUILDS.md by the ledger's header names and checks
  <version>.docx against the row's sha256. When they match it pins that build,
  with the sha256 of the build's text as side_text writes it. Otherwise, and
  without the options, it writes versions: [] and prints why, and the prose
  procedure reports the diff as unanchored (Track D choice 15).

sentences(text) and the match by which an anchor names a sentence are the
prose procedure's rules, copied here because connections imports no
verification code. A sentence ends at ., ?, or !, keeping a closing quotation
mark, before a space and a capital letter, a quotation mark, or a bracket.
"""
import hashlib
import re
import unicodedata
from collections import namedtuple
from pathlib import Path

import yaml

from connections.adapters import ADAPTERS, Adapter, AdapterError
from connections.adapters.docx_text import SIDES, DocxError, read_docx, side_text

FILLS = ("baseline.md", "revised.md", "rationales.yaml", "versions.yaml")
LEDGER = "BUILDS.md"

# The prose procedure's sentence rule, _lib.sentences plus diff_changes' split
# after a sentence that ends inside a closing quote.
FRONT_MATTER = re.compile(r"^---\n.*?\n---\n", re.S)
PARAGRAPH = re.compile(r"\n\s*\n")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"(\[])")
CLOSE_QUOTE_END = re.compile(r'(?<=[.!?]["”\'’])\s+(?=[A-Z"“(\[])')
SPACE = re.compile(r"\s+")

KIND_TAG = re.compile(r"\s*\[(edit|insert|delete|move)\]")

# One sentence of a paragraph on one side. key names the entry the sentence
# belongs to, anchor is that entry's anchor, and kind is the own kind of an AI
# change inside the sentence.
Sentence = namedtuple("Sentence", "start end text key anchor kind")


def sentences(text: str) -> list:
    """The sentences of a markdown text, in order, as the prose procedure splits them."""
    body = FRONT_MATTER.sub("", text)
    out = []
    for para in PARAGRAPH.split(body):
        para = para.strip()
        if not para or para.startswith("#"):
            continue
        para = SPACE.sub(" ", para)
        for s in SENTENCE_END.split(para):
            if s.strip():
                out.extend(p for p in CLOSE_QUOTE_END.split(s.strip()) if p.strip())
    return out


def _norm(text: str) -> str:
    """Text as the prose procedure normalizes it for matching (_lib.norm)."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u00ad", "")
    text = re.sub(r"-\s*\n\s*", "", text)
    return SPACE.sub(" ", text).strip().lower()


def _names(anchor: str, sentence: str) -> bool:
    """Whether a normalized anchor names a normalized sentence, equal to it or a part of it of four words or more."""
    return bool(anchor) and (anchor == sentence or (len(anchor.split()) >= 4 and anchor in sentence))


def add_arguments(parser) -> None:
    parser.add_argument("--docx", required=True, metavar="FILE", help="the reviewed Word document")
    parser.add_argument(
        "--ai-author", required=True, metavar="NAME",
        help="the author name the AI's tracked changes and comments carry",
    )
    parser.add_argument(
        "--annotations", metavar="FILE",
        help="the YAML list annotate read, which gives the rationales instead of the comments",
    )
    parser.add_argument("--builds-dir", metavar="DIR", help="the build folder holding BUILDS.md")
    parser.add_argument(
        "--baseline-version", metavar="vNNN", help="the ledgered build the baseline should match",
    )


# ---------------------------------------------------------------- sentences in one paragraph

def _pieces(text: str, start: int, end: int, pattern) -> list:
    """The spans of text[start:end] between the matches of pattern."""
    chunk = text[start:end]
    spans, last = [], 0
    for match in pattern.finditer(chunk):
        spans.append((start + last, start + match.start()))
        last = match.end()
    spans.append((start + last, end))
    return spans


def _spans(paragraph: dict, side: str) -> list:
    """Each sentence of one paragraph on one side, as (start, end, sentence), split as sentences() splits."""
    text = paragraph[side]
    if paragraph["level"]:
        stripped = text.strip()
        if not stripped:
            return []
        start = len(text) - len(text.lstrip())
        return [(start, start + len(stripped), SPACE.sub(" ", stripped))]
    out = []
    for a, b in _pieces(text, 0, len(text), PARAGRAPH):
        chunk = text[a:b].strip()
        if not chunk or chunk.startswith("#"):
            continue
        for s0, s1 in _pieces(text, a, b, SENTENCE_END):
            for p0, p1 in _pieces(text, s0, s1, CLOSE_QUOTE_END):
                while p0 < p1 and text[p0].isspace():
                    p0 += 1
                while p1 > p0 and text[p1 - 1].isspace():
                    p1 -= 1
                if p0 < p1:
                    out.append((p0, p1, SPACE.sub(" ", text[p0:p1])))
    return out


def _sentence_at(doc: dict, side: str, index: int, offset: int):
    """The span of the sentence holding character offset of paragraph index on side, or None."""
    for span in _spans(doc["paragraphs"][index], side):
        if span[0] <= offset < span[1]:
            return span
    return None


def _first_character(doc: dict, side: str, start, end):
    """The first character that is not a space between start and end on side, as (paragraph, offset), or None."""
    (p0, o0), (p1, o1) = start, end
    for index in range(p0, min(p1, len(doc["paragraphs"]) - 1) + 1):
        text = doc["paragraphs"][index][side]
        low = o0 if index == p0 else 0
        high = o1 if index == p1 else len(text)
        for offset in range(low, min(high, len(text))):
            if not text[offset].isspace():
                return index, offset
    return None


def _plain_segments(paragraph: dict) -> list:
    """The text a paragraph keeps on both sides, as (baseline start, revised start, length).

    Its changes are in document order, so the text between two of them is
    plain. An empty list means the sides do not line up as expected.
    """
    base, rev = paragraph["baseline"], paragraph["revised"]
    b = r = 0
    segments = []
    for change in paragraph["changes"]:
        if change["side"] == "baseline":
            length = change["start"] - b
            if length < 0:
                return []
            segments.append((b, r, length))
            b, r = change["end"], r + length
        else:
            length = change["start"] - r
            if length < 0:
                return []
            segments.append((b, r, length))
            b, r = b + length, change["end"]
    tail = len(base) - b
    if tail < 0 or r + tail != len(rev):
        return []
    segments.append((b, r, tail))
    if any(base[b0:b0 + n] != rev[r0:r0 + n] for b0, r0, n in segments):
        return []
    return segments


def _sentence_map(doc: dict, index: int) -> dict:
    """The sentences of paragraph index on each side, as Sentence tuples.

    A revised sentence is its own entry's sentence, of kind edit when it keeps
    a character that is not a space from the baseline and insert when it keeps
    none. A baseline sentence that keeps one belongs to the revised sentence
    holding the first, of kind edit, and one that keeps none is its own, of
    kind delete.
    """
    paragraph = doc["paragraphs"][index]
    segments = _plain_segments(paragraph)

    def kept(side, start, end):
        # The revised offset of the first character between start and end on
        # side that is not a space and that both sides keep, or None.
        for b0, r0, length in segments:
            low = b0 if side == "baseline" else r0
            for offset in range(max(low, start), min(low + length, end)):
                if not paragraph[side][offset].isspace():
                    return r0 + offset - low
        return None

    revised = [
        Sentence(s0, s1, text, ("revised", index, s0), text,
                 "insert" if kept("revised", s0, s1) is None else "edit")
        for s0, s1, text in _spans(paragraph, "revised")
    ]
    baseline = []
    for s0, s1, text in _spans(paragraph, "baseline"):
        offset = kept("baseline", s0, s1)
        holder = None if offset is None else next((s for s in revised if s.start <= offset < s.end), None)
        if holder is not None:
            baseline.append(Sentence(s0, s1, text, holder.key, holder.anchor, "edit"))
        else:
            baseline.append(Sentence(s0, s1, text, ("baseline", index, s0), text,
                                     "delete" if offset is None else "edit"))
    return {"revised": revised, "baseline": baseline}


def _touched(paragraph: dict, side: str, found: list, start: int, end: int) -> list:
    """The sentences in found holding a character that is not a space between start and end on side."""
    text = paragraph[side]
    return [s for s in found
            if any(not text[o].isspace() for o in range(max(start, s.start), min(end, s.end)))]


# ---------------------------------------------------------------- the AI's changes

def _change_entries(doc: dict, maps: list, ai_author: str):
    """One entry per sentence the AI's tracked changes touch, in document order, and the sentences only others changed."""
    entries, others = {}, set()
    for index, paragraph in enumerate(doc["paragraphs"]):
        for change in paragraph["changes"]:
            side = change["side"]
            for s in _touched(paragraph, side, maps[index][side], change["start"], change["end"]):
                if change["author"] != ai_author:
                    others.add(s.key)
                elif s.key not in entries:
                    entries[s.key] = {"key": s.key, "anchor": s.anchor, "kind": s.kind}
    return list(entries.values()), others - set(entries)


# ---------------------------------------------------------------- comments and annotations

def _kind_and_rationale(text: str):
    found = KIND_TAG.match(text)
    if found:
        return found.group(1), text[found.end():].strip()
    return "", text.strip()


def _note(name: str, anchor: str, keys: set, body: str) -> dict:
    kind, rationale = _kind_and_rationale(body)
    return {"name": name, "anchor": anchor, "keys": keys, "kind": kind, "rationale": rationale}


def _comment_anchor(doc: dict, comment: dict) -> str:
    span = comment["span"]
    if span is None:
        print(f"comment {comment['id']} by {comment['author']} marks no range, so its anchor is empty")
        return ""
    for side in ("revised", "baseline"):
        found = _first_character(doc, side, span[side]["start"], span[side]["end"])
        if found is not None:
            sentence = _sentence_at(doc, side, found[0], found[1])
            if sentence is not None:
                return sentence[2]
    print(f"comment {comment['id']} by {comment['author']} covers no sentence, so its anchor is empty")
    return ""


def _comment_keys(doc: dict, maps: list, span) -> set:
    """The keys of the sentences holding a character that is not a space which a comment marks, on either side."""
    if span is None:
        return set()
    keys = set()
    for side in SIDES:
        (p0, o0), (p1, o1) = span[side]["start"], span[side]["end"]
        for index in range(p0, min(p1, len(doc["paragraphs"]) - 1) + 1):
            paragraph = doc["paragraphs"][index]
            low = o0 if index == p0 else 0
            high = o1 if index == p1 else len(paragraph[side])
            keys.update(s.key for s in _touched(paragraph, side, maps[index][side], low, high))
    return keys


def _comment_notes(doc: dict, maps: list, ai_author: str) -> list:
    """The AI author's comments, in the order the document lists them."""
    return [
        _note(f"comment {c['id']} by {c['author']}", _comment_anchor(doc, c), _comment_keys(doc, maps, c["span"]),
              c["text"])
        for c in doc["comments"] if c["author"] == ai_author
    ]


def _annotation_notes(path: str, maps: list) -> list:
    """The YAML list annotate read, in its order, each read as the comment annotate writes from it."""
    try:
        items = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise AdapterError(f"{path} cannot be read as YAML, {error}")
    if not isinstance(items, list):
        raise AdapterError(f"{path} is not a YAML list of annotations")
    every = [(s.key, _norm(s.text)) for found in maps for side in SIDES for s in found[side]]
    out = []
    for number, item in enumerate(items, 1):
        if not isinstance(item, dict) or "anchor" not in item or "text" not in item:
            raise AdapterError(f"annotation {number} in {path} needs anchor and text")
        tag = item.get("tag")
        body = f"[{tag}] {item['text']}" if tag else str(item["text"])
        anchor = str(item["anchor"])
        named = _norm(anchor)
        keys = {key for key, text in every if _names(named, text)}
        out.append(_note(f"annotation {number} in {path}", anchor, keys, body))
    return out


def _record(entries: list, notes: list, others: set) -> list:
    """The rationales entries, one for each AI change and then one for each note no change took."""
    deleted = {_norm(e["anchor"]) for e in entries if e["kind"] == "delete"}
    inserted = {_norm(e["anchor"]) for e in entries if e["kind"] == "insert"}
    halves = {"delete": inserted, "insert": deleted}
    used, out = set(), []
    for entry in entries:
        covering = [n for n, note in enumerate(notes) if entry["key"] in note["keys"]]
        chosen = next((n for n in covering if notes[n]["kind"] == entry["kind"]), covering[0] if covering else None)
        kind, rationale = entry["kind"], ""
        if chosen is not None:
            used.add(chosen)
            tag, rationale = notes[chosen]["kind"], notes[chosen]["rationale"]
            half = _norm(entry["anchor"]) in halves.get(entry["kind"], ())
            if tag and not (tag == "move" and half):
                kind = tag
        out.append({"anchor": entry["anchor"], "kind": kind, "rationale": rationale})
    for n, note in enumerate(notes):
        if n in used:
            continue
        if note["keys"] & others:
            print(f"{note['name']} is left out of rationales.yaml, since a sentence it covers holds only"
                  " another author's tracked changes")
            continue
        out.append({"anchor": note["anchor"], "kind": note["kind"], "rationale": note["rationale"]})
    return [dict({"id": f"r{n:02d}"}, **r) for n, r in enumerate(out, 1)]


# ---------------------------------------------------------------- versions

def _cells(line: str):
    line = line.strip()
    if len(line) < 2 or not (line.startswith("|") and line.endswith("|")):
        return None
    return [cell.strip() for cell in line[1:-1].split("|")]


def _sha_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _versions(builds_dir: str, version: str, read_paths: list):
    """The versions list and, when it is empty, why."""
    if builds_dir is None:
        return [], "since --builds-dir and --baseline-version were not given"
    ledger = Path(builds_dir) / LEDGER
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as error:
        return [], f"since {ledger} cannot be read, {error}"
    read_paths.append(str(ledger))
    header = None
    for line in lines:
        cells = _cells(line)
        if cells is None:
            continue
        names = [cell.lower() for cell in cells]
        if header is None:
            if "version" in names and "sha256" in names:
                if len(cells) not in (7, 9):
                    return [], f"since the header of {ledger} has {len(cells)} columns, not seven or nine"
                header = names
            continue
        if len(cells) != len(header) or cells[header.index("version")] != version:
            continue
        build = Path(builds_dir) / f"{version}.docx"
        try:
            data = build.read_bytes()
        except OSError as error:
            return [], f"since {build.name} cannot be read, {error}"
        read_paths.append(str(build))
        recorded = cells[header.index("sha256")].lower()
        if recorded.startswith("sha256:"):
            recorded = recorded[len("sha256:"):]
        actual = _sha_hex(data)
        if actual != recorded:
            return [], (
                f"since {build.name} no longer matches its {LEDGER} row, "
                f"sha256 {actual} on disk and {recorded} in the ledger"
            )
        try:
            text = side_text(read_docx(build), "revised")
        except DocxError as error:
            raise AdapterError(str(error))
        sha = "sha256:" + _sha_hex(text.encode("utf-8"))
        return [{"version": version, "file": build.name, "sha256": sha}], None
    if header is None:
        return [], f"since {ledger} has no header naming version and sha256"
    return [], f"since {ledger} has no row for {version}"


# ---------------------------------------------------------------- the adapter

def _dump(data) -> bytes:
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True).encode("utf-8")


def read(args):
    if (args.builds_dir is None) != (args.baseline_version is None):
        raise AdapterError("--builds-dir and --baseline-version go together, give both or neither")
    try:
        doc = read_docx(args.docx)
    except DocxError as error:
        raise AdapterError(str(error))
    read_paths = [args.docx]

    maps = [_sentence_map(doc, index) for index in range(len(doc["paragraphs"]))]
    entries, others = _change_entries(doc, maps, args.ai_author)
    if args.annotations is not None:
        notes = _annotation_notes(args.annotations, maps)
        read_paths.append(args.annotations)
    else:
        notes = _comment_notes(doc, maps, args.ai_author)
    rationales = _record(entries, notes, others)

    versions, why = _versions(args.builds_dir, args.baseline_version, read_paths)
    if why:
        print(f"versions.yaml lists no version {why}, so the prose procedure reports the diff as unanchored")

    files = {
        "baseline.md": side_text(doc, "baseline").encode("utf-8"),
        "revised.md": side_text(doc, "revised").encode("utf-8"),
        "rationales.yaml": _dump(rationales),
        "versions.yaml": _dump({"versions": versions}),
    }
    return read_paths, files


ADAPTER = Adapter("word", "prose", FILLS, add_arguments, read)
ADAPTERS[ADAPTER.name] = ADAPTER
