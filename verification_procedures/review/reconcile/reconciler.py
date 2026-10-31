"""Classify a reviewed return docx against its build lineage. FROZEN surface in CONTRACT.md.

Semantics (FROZEN): rejection means restoration of baseline text within a known
AI change region; silence is never converted into a ruling (pending stays
pending, unmatchable stays conflict); reconcile never writes any file. Regions
are derived mechanically by word-diffing the ledgered baseline snapshot against
the revision snapshot; docx extraction is delegated to the returns leaf.

Mechanics (SOFT, documented here and in the contract's Soft section):

- Normalization. Both snapshots and the return's accepted markdown pass
  through the same token normalizer: table decoration lines (only ``| : + = -``
  and whitespace) are dropped, pipe separators become spaces (so source pipe
  tables and pandoc's re-rendered tables tokenize identically), hard-line-break
  backslashes are stripped, pandoc backslash escapes are undone, leading ATX
  ``#`` markers are dropped, common smart punctuation is mapped to ASCII, and
  whitespace runs collapse. Multiline pandoc tables that wrap a single cell
  across lines are outside this normalizer's guarantees.
- Regions. Word-level SequenceMatcher opcodes (autojunk off), with non-equal
  opcodes merged when separated by an equal run of <= merge_gap tokens (so
  "without enforcing an output format" -> "with no output format enforced"
  stays one region despite the shared middle word).
- Classification is context-anchored containment against the normalized return
  tokens: context+revision present = accepted (checked first; ties break toward
  accepted); context+baseline present = rejected; context anchors present
  exactly once around a bounded window = modified (found_text = the window);
  anchors absent or ambiguous = conflict, never guessed.
- Pending. Deltas from returns.extract whose author is in ai_authors. Because
  pandoc's --track-changes=accept applies unresolved changes, a region whose
  "acceptance" is manufactured by a pending AI delta (delta text contains or is
  contained by the region's changed text) is suppressed from accepted and
  reported only via pending.
- Author edits. Word-diff of return vs revision snapshot; hunks overlapping any
  derived region are attributed to that region's classification (rejected and
  modified regions necessarily produce such hunks); only hunks outside every
  region are reported as the author's own work. A hunk that straddles a region
  boundary is attributed to the region; the region's found_text carries the
  return text.
- Unresolved tracked changes by non-AI authors are not "pending"; accept-mode
  applies them, so they surface as author edits or modified regions.
"""
import difflib
import re
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple, Union

from review.returns import extract

PathLike = Union[str, Path]

LEDGER_NAME = "BUILDS.md"
VERSION_COLUMN = "version"  # the header row starts with this column
BASELINE_COLUMN = "baseline"  # the only other column reconcile uses

DEFAULT_AI_AUTHORS = ("Claude",)
CONTEXT_WORDS = 4
MERGE_GAP = 2

_SEPARATOR_CELL = re.compile(r":?-{3,}:?$")
_VERSION_DIGITS = re.compile(r"^v?(\d+)$")
_DECORATION_LINE = re.compile(r"^[\s|:+=\-]+$")
_UNESCAPE = re.compile(r"\\([^A-Za-z0-9\s])")
_SMART_ASCII = (
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u2013", "-"),
    ("\u2014", "-"),
    ("\u2026", "..."),
    ("\u00a0", " "),
)


class ReconcileError(RuntimeError):
    """Lineage cannot be established (ledger, row, baseline, or snapshot absent)."""


class Change(NamedTuple):
    baseline_text: str
    revision_text: str
    context: str
    found_text: Optional[str] = None


class Reconciliation(NamedTuple):
    accepted: List[Change]
    rejected: List[Change]
    modified: List[Change]
    pending: List
    author_edits: List[str]
    comments: List
    conflicts: List[str]


# --- normalization -----------------------------------------------------------


def normalize_tokens(text):
    # type: (str) -> List[str]
    """Normalize markdown to a word-token list; identical treatment for
    snapshots and pandoc round-tripped return text (see module docstring)."""
    tokens = []  # type: List[str]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _DECORATION_LINE.match(line):
            continue  # pipe/grid/simple table rules, horizontal rules
        if line.endswith("\\"):
            line = line[:-1]  # pandoc hard line break marker
            if not line.strip():
                continue
        if line.startswith("#"):
            line = line.lstrip("#")  # ATX heading marker; title words remain
        for smart, ascii_form in _SMART_ASCII:
            line = line.replace(smart, ascii_form)
        line = _UNESCAPE.sub(r"\1", line)
        line = line.replace("|", " ")  # pipe-table cell separators
        tokens.extend(line.split())
    return tokens


# --- ledger and snapshots ----------------------------------------------------


def _normalize_version(key):
    # type: (str) -> str
    """'2' and 'v2' become 'v002'; anything already vNNN (or odd) passes through."""
    match = _VERSION_DIGITS.match(str(key).strip())
    if match:
        digits = match.group(1)
        return "v" + (digits if len(digits) >= 3 else digits.zfill(3))
    return str(key).strip()


def _ledger_rows(ledger):
    # type: (Path) -> List[dict]
    """Defensive BUILDS.md parse by the header row's column names.

    Each row's cells are mapped to the names in the header row above it, so a
    ledger of any width reads. A row with more cells than its header (a newer
    build appended under an older ledger's header) is read by the header's names
    for its first cells and its extra trailing cells are ignored. A row with
    fewer cells than its header, or a row before any header, is skipped."""
    rows = []  # type: List[dict]
    header = None  # type: Optional[List[str]]
    for raw in ledger.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if len(line) < 2 or not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if cells[0].lower() == VERSION_COLUMN:
            header = [cell.lower() for cell in cells]
            continue  # header row
        if cells and all(_SEPARATOR_CELL.match(cell) for cell in cells):
            continue  # separator row
        if header is None or len(cells) < len(header):
            continue  # malformed row: never a crash, never a guess
        rows.append(dict(zip(header, cells[: len(header)])))
    return rows


def _lineage(builds_dir, version):
    # type: (Path, str) -> Tuple[str, str, str]
    """Return (baseline_version, baseline_md, revision_md) or raise ReconcileError."""
    ledger = builds_dir / LEDGER_NAME
    if not ledger.is_file():
        raise ReconcileError("ledger absent: {0}".format(ledger))
    rows = _ledger_rows(ledger)
    row = None
    for candidate in rows:
        if candidate.get(VERSION_COLUMN) == version:
            row = candidate
            break
    if row is None:
        raise ReconcileError(
            "no ledger row for {0} in {1} ({2} rows read)".format(version, ledger, len(rows))
        )
    baseline = _normalize_version(row.get(BASELINE_COLUMN, ""))
    if not baseline or baseline == "-":
        raise ReconcileError(
            "{0} has no baseline in {1} (baseline column = {2!r}); nothing to reconcile against".format(
                version, ledger, row.get(BASELINE_COLUMN, "")
            )
        )
    texts = []
    for ver in (baseline, version):
        snapshot = builds_dir / (ver + ".md")
        if not snapshot.is_file():
            raise ReconcileError("snapshot absent: {0}".format(snapshot))
        texts.append(snapshot.read_text(encoding="utf-8"))
    return baseline, texts[0], texts[1]


# --- region derivation -------------------------------------------------------


class _Region(NamedTuple):
    a1: int
    a2: int
    b1: int
    b2: int


def _derive_regions(base_tokens, rev_tokens, merge_gap):
    # type: (List[str], List[str], int) -> List[_Region]
    matcher = difflib.SequenceMatcher(a=base_tokens, b=rev_tokens, autojunk=False)
    regions = []  # type: List[_Region]
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if regions and a1 - regions[-1].a2 <= merge_gap:
            prev = regions[-1]
            regions[-1] = _Region(prev.a1, a2, prev.b1, b2)
        else:
            regions.append(_Region(a1, a2, b1, b2))
    return regions


# --- containment matching ----------------------------------------------------


def _find_all(haystack, needle):
    # type: (Sequence[str], Sequence[str]) -> List[int]
    if not needle or len(needle) > len(haystack):
        return []
    first = needle[0]
    hits = []
    for index in range(len(haystack) - len(needle) + 1):
        if haystack[index] == first and list(haystack[index : index + len(needle)]) == list(needle):
            hits.append(index)
    return hits


def _contains(haystack, needle):
    # type: (Sequence[str], Sequence[str]) -> bool
    return bool(_find_all(haystack, needle))


class _Classified(NamedTuple):
    verdict: str  # accepted | rejected | modified | conflict
    change: Change
    region: _Region
    base_words: Tuple[str, ...]
    rev_words: Tuple[str, ...]
    reason: str


def _classify_region(region, base_tokens, rev_tokens, ret_tokens, context_words):
    # type: (_Region, List[str], List[str], List[str], int) -> _Classified
    base_words = tuple(base_tokens[region.a1 : region.a2])
    rev_words = tuple(rev_tokens[region.b1 : region.b2])
    before = tuple(rev_tokens[max(0, region.b1 - context_words) : region.b1])
    after = tuple(rev_tokens[region.b2 : region.b2 + context_words])
    context = "{0} ... {1}".format(" ".join(before), " ".join(after)).strip()
    change = Change(
        baseline_text=" ".join(base_words),
        revision_text=" ".join(rev_words),
        context=context,
    )

    accepted_form = before + rev_words + after
    if _contains(ret_tokens, accepted_form):
        return _Classified("accepted", change, region, base_words, rev_words, "")
    rejected_form = before + base_words + after
    if _contains(ret_tokens, rejected_form):
        return _Classified("rejected", change, region, base_words, rev_words, "")

    # Neither form: anchor on context alone, never guessing between matches.
    before_ends = [i + len(before) for i in _find_all(ret_tokens, before)] if before else [0]
    after_starts = _find_all(ret_tokens, after) if after else [len(ret_tokens)]
    window = 3 * max(len(rev_words), len(base_words), 1) + 4 * context_words
    pairs = [
        (p, q) for p in before_ends for q in after_starts if p <= q <= p + window
    ]
    if len(pairs) == 1:
        p, q = pairs[0]
        found = " ".join(ret_tokens[p:q])
        return _Classified(
            "modified", change._replace(found_text=found), region, base_words, rev_words, ""
        )
    if not before_ends or not after_starts or not pairs:
        reason = "context not found in return"
    else:
        reason = "context matches {0} places in return".format(len(pairs))
    return _Classified("conflict", change, region, base_words, rev_words, reason)


# --- pending shadowing -------------------------------------------------------


def _shadowed_by_pending(classified, pending_deltas):
    # type: (_Classified, List) -> bool
    """True when an accepted verdict is manufactured by --track-changes=accept
    applying an unresolved AI delta rather than by the author's own ruling."""
    for delta in pending_deltas:
        delta_words = tuple(normalize_tokens(delta.text))
        if not delta_words:
            continue
        target = classified.rev_words if delta.kind == "insertion" else classified.base_words
        if not target:
            continue
        if _contains(target, delta_words) or _contains(delta_words, target):
            return True
    return False


# --- author edits ------------------------------------------------------------


def _quote(words):
    # type: (Sequence[str]) -> str
    return '"' + " ".join(words) + '"'


def _author_edits(rev_tokens, ret_tokens, regions):
    # type: (List[str], List[str], List[_Region]) -> List[str]
    matcher = difflib.SequenceMatcher(a=rev_tokens, b=ret_tokens, autojunk=False)
    edits = []  # type: List[str]
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        attributed = False
        for region in regions:
            if a1 == a2:  # pure insertion point
                if region.b1 < a1 < region.b2:
                    attributed = True
                    break
            elif a1 < region.b2 and a2 > region.b1:
                attributed = True
                break
        if attributed:
            continue
        anchor = rev_tokens[max(0, a1 - 3) : a1]
        where = ' (after {0})'.format(_quote(anchor)) if anchor else " (at document start)"
        if tag == "insert":
            edits.append("added: {0}{1}".format(_quote(ret_tokens[b1:b2]), where))
        elif tag == "delete":
            edits.append("removed: {0}{1}".format(_quote(rev_tokens[a1:a2]), where))
        else:
            edits.append(
                "changed: {0} -> {1}{2}".format(
                    _quote(rev_tokens[a1:a2]), _quote(ret_tokens[b1:b2]), where
                )
            )
    return edits


# --- entry point --------------------------------------------------------------


def reconcile(
    return_docx,  # type: PathLike
    builds_dir,  # type: PathLike
    version,  # type: str
    *,
    ai_authors=DEFAULT_AI_AUTHORS,  # type: Sequence[str]
    pandoc="pandoc",  # type: str
    context_words=CONTEXT_WORDS,  # type: int
    merge_gap=MERGE_GAP,  # type: int
):
    # type: (...) -> Reconciliation
    """Classify *return_docx* (the reviewed copy of build *version*) against the
    ledgered baseline and revision snapshots in *builds_dir*. Read-only."""
    builds = Path(builds_dir)
    version = _normalize_version(version)
    _, baseline_md, revision_md = _lineage(builds, version)

    base_tokens = normalize_tokens(baseline_md)
    rev_tokens = normalize_tokens(revision_md)

    bundle = extract(return_docx, pandoc=pandoc)
    ret_tokens = normalize_tokens(bundle.accepted_markdown)
    pending = [d for d in bundle.deltas if d.author in tuple(ai_authors)]

    regions = _derive_regions(base_tokens, rev_tokens, merge_gap)
    classified = [
        _classify_region(region, base_tokens, rev_tokens, ret_tokens, context_words)
        for region in regions
    ]

    accepted = []  # type: List[Change]
    rejected = []  # type: List[Change]
    modified = []  # type: List[Change]
    conflicts = []  # type: List[str]
    for item in classified:
        if item.verdict == "accepted":
            if _shadowed_by_pending(item, pending):
                continue  # unresolved AI change: reported via pending, never ruled
            accepted.append(item.change)
        elif item.verdict == "rejected":
            rejected.append(item.change)
        elif item.verdict == "modified":
            modified.append(item.change)
        else:
            conflicts.append(
                "cannot classify region {0} -> {1} (context {2!r}: {3})".format(
                    _quote(item.base_words),
                    _quote(item.rev_words),
                    item.change.context,
                    item.reason,
                )
            )

    author_edits = _author_edits(rev_tokens, ret_tokens, [c.region for c in classified])

    return Reconciliation(
        accepted=accepted,
        rejected=rejected,
        modified=modified,
        pending=pending,
        author_edits=author_edits,
        comments=list(bundle.comments),
        conflicts=conflicts,
    )


# --- presentation (for the CLI the parent wires) ------------------------------


def _change_line(change):
    # type: (Change) -> str
    if not change.baseline_text:
        head = 'insertion "{0}"'.format(change.revision_text)
    elif not change.revision_text:
        head = 'deletion "{0}"'.format(change.baseline_text)
    else:
        head = '"{0}" -> "{1}"'.format(change.baseline_text, change.revision_text)
    if change.found_text is not None:
        head += ' ; return reads "{0}"'.format(change.found_text)
    return head + " (context {0!r})".format(change.context)


def format_reconciliation(rec):
    # type: (Reconciliation) -> str
    lines = []  # type: List[str]
    for label, changes in (
        ("accepted", rec.accepted),
        ("rejected", rec.rejected),
        ("modified", rec.modified),
    ):
        lines.append("{0} ({1}):".format(label, len(changes)))
        for change in changes:
            lines.append("  - " + _change_line(change))
    lines.append("pending ({0}):".format(len(rec.pending)))
    for delta in rec.pending:
        lines.append(
            '  - {0} by {1}: "{2}"'.format(delta.kind, delta.author, delta.text)
        )
    lines.append("author edits ({0}):".format(len(rec.author_edits)))
    for edit in rec.author_edits:
        lines.append("  - " + edit)
    lines.append("comments ({0}):".format(len(rec.comments)))
    for comment in rec.comments:
        lines.append("  - {0}: {1}".format(comment.author, comment.text))
    lines.append("conflicts ({0}):".format(len(rec.conflicts)))
    for conflict in rec.conflicts:
        lines.append("  - " + conflict)
    return "\n".join(lines)
