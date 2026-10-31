"""Advisory literal-number linter for canonical markdown.

FROZEN surface (see CONTRACT.md): the lint() signature, the Finding shape,
and the six not-flagged categories. lint never mutates text and never raises
on content (only on non-str input). Everything else -- the numeral-token
regex, masking details, the citation-year heuristic -- is SOFT.
"""
import re
from typing import Collection, List, NamedTuple

# The placeholder grammar, copied rather than imported because layers never
# import each other's code. It copies the grammar frozen in the pipeline's
# foundation contract, and a change there needs the same change here.
# Group 1 is the kind (num or table), group 2 the key.
PLACEHOLDER = re.compile(r"\{\{(num|table):([A-Za-z0-9_.\-]+)\}\}")


class Finding(NamedTuple):
    line: int
    token: str
    context: str


# Fence delimiter: ``` or ~~~ after up to three spaces of indent.
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
# Inline code span: one or more backticks, content, matching run of backticks.
_INLINE_CODE = re.compile(r"(`+)(.+?)\1")
# Ordered-list marker at line start: '1. ', '2) ', optionally indented.
_LIST_MARKER = re.compile(r"^(\s*)(\d{1,9}[.)])(?=\s)")
# Heading number: '## 3.', '### 2.4', etc.
_HEADING_NUM = re.compile(r"^(\s{0,3}#{1,6}\s+)(\d+(?:\.\d+)*\.?)(?=\s|$)")
# Parenthetical group (single line), for the citation-year heuristic.
_PAREN = re.compile(r"\(([^()]*)\)")
# A 4-digit year, optionally with a disambiguating letter ('2020a').
_CITE_YEAR = re.compile(r"\b\d{4}[a-z]?\b")
# What must precede a year inside parens to read as a citation:
# a capitalized token (two+ letters) or 'et al.'.
_CITE_LEADIN = re.compile(r"[A-Z][A-Za-z'’\-]+|\bet al\.?")
# Bare numeral token: starts and ends on a digit, may contain commas and
# dots inside, optional trailing '%'. Not preceded by a word char or '.'.
_NUMERAL = re.compile(r"(?<![\w.])\d(?:[\d,.]*\d)?%?")
_PURE_YEAR = re.compile(r"\d{4}")
# Name-attached numeral: a capitalized token directly before a number reads
# as a name or reference (Phi 4, Table 3, June 10) UNLESS the capitalized
# token opens the sentence (Approximately 40 ...), where real quantities live.
_NAME_NUM = re.compile(r"([A-Z][A-Za-z]*[ \t]+)(\d(?:[\d,.]*\d)?%?)")
_SENTENCE_EDGE = re.compile(r"(?:^|[.!?;:]\s*|[-*>]\s+)$")


def _blank(match):
    """Replace a match with same-length spaces (keeps positions and lines)."""
    return " " * len(match.group(0))


def _keep1_blank2(match):
    """Keep group 1, blank group 2 with same-length spaces."""
    return match.group(1) + " " * len(match.group(2))


def _mask_citation_years(match):
    """Blank 4-digit years inside a parenthetical when a capitalized token
    or 'et al.' precedes them (e.g. '(Chung et al. 2025)', '(Darwin 1859)')."""
    inner = match.group(1)
    pieces = []
    last = 0
    for year in _CITE_YEAR.finditer(inner):
        if _CITE_LEADIN.search(inner, 0, year.start()):
            pieces.append(inner[last:year.start()])
            pieces.append(" " * (year.end() - year.start()))
            last = year.end()
    pieces.append(inner[last:])
    return "(" + "".join(pieces) + ")"


def _mask_name_numbers(line):
    """Blank numerals attached to a mid-sentence capitalized token (Phi 4,
    Table 3, June 10). A sentence-initial capitalized token keeps its number
    flagged, since real quantities follow openers like 'Approximately 40'."""
    out = []
    last = 0
    for match in _NAME_NUM.finditer(line):
        if _SENTENCE_EDGE.search(line[:match.start()]):
            continue
        out.append(line[last:match.end(1)])
        out.append(" " * len(match.group(2)))
        last = match.end(2)
    out.append(line[last:])
    return "".join(out)


def _is_table_separator(line):
    """True for markdown table separator rows like |---|---| or --- | ---."""
    stripped = line.strip()
    if not stripped or "-" not in stripped or "|" not in stripped:
        return False
    return re.fullmatch(r"[\s|:\-]+", stripped) is not None


def lint(text, allowlist=()):
    # type: (str, Collection[str]) -> List[Finding]
    """Scan canonical markdown for bare numeral tokens in prose.

    Advisory only: returns findings, never raises on content. Raises
    TypeError only when ``text`` is not a str.
    """
    if not isinstance(text, str):
        raise TypeError(
            "lint() expects text as str, got %s" % type(text).__name__
        )
    allowed = frozenset(str(item) for item in allowlist)

    findings = []  # type: List[Finding]
    fence_char = None  # first char of the open fence marker, or None
    for lineno, raw in enumerate(text.split("\n"), start=1):
        fence = _FENCE.match(raw)
        if fence_char is not None:
            # Inside a fenced block: the whole line is masked.
            if fence and fence.group(1)[0] == fence_char:
                fence_char = None
            continue
        if fence:
            fence_char = fence.group(1)[0]
            continue
        if _is_table_separator(raw):
            continue

        work = _INLINE_CODE.sub(_blank, raw)
        work = PLACEHOLDER.sub(_blank, work)
        work = _PAREN.sub(_mask_citation_years, work)
        work = _LIST_MARKER.sub(_keep1_blank2, work)
        work = _HEADING_NUM.sub(_keep1_blank2, work)
        work = _mask_name_numbers(work)

        context = raw.strip()
        for match in _NUMERAL.finditer(work):
            token = match.group(0)
            following = work[match.end():match.end() + 1]
            if following and (following.isalnum() or following == "_"):
                # Glued to a word ('86x', 'v2foo'): not a bare numeral.
                continue
            if _PURE_YEAR.fullmatch(token) and 1900 <= int(token) <= 2099:
                continue
            if token in allowed:
                continue
            findings.append(Finding(lineno, token, context))
    return findings
