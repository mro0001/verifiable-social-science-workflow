"""Manifest and table substitution. FROZEN surface documented in CONTRACT.md.

Inside inline code and fenced code blocks, as pandoc prints them, a number
placeholder whose key the manifest holds is filled and any other placeholder is
left as written, so an example stays an example and a number bound in code is
filled (Track L, Step L6, and Track Q, Step Q3). Code is never counted for
missing keys and never scanned for remnants. The code is found by pandoc 3.9's rules. A fence is three or more
backticks or tildes after at most three spaces, followed by nothing, one word or
{attributes} such as {.r}, and closes at a line of the same character at least
as long. A fence that never closes opens no block, and a tilde fence right under
a line of text is part of that paragraph. Inline code opens at a run of backticks and
closes at the next run of the same length. A backtick after a backslash is text,
and so is the first backtick of a run with no close, the rest of the run being
read again.

Where pandoc's reading of inline code is unclear, the placeholder is filled, the
safe way to err. Inline code is set aside only where reading it line by line
and reading it up to the blank line agree, outside tables that cut lines into
cells, and away from an autolink, HTML tag, link target, math or TeX command
holding a backtick. So a placeholder in a code span that runs across lines is
filled too.
"""
import re
import string
from typing import List, Mapping, Tuple

from ospipe.foundation import PLACEHOLDER, SUSPECT, MissingKeyError

_SENT_OPEN = "\x00OSPIPE_TBL\x00"
_SENT_CLOSE = "\x00/OSPIPE_TBL\x00"


class ResolveError(ValueError):
    def __init__(self, line, remnant):
        self.line = line
        self.remnant = remnant
        super().__init__(f"unresolved placeholder-like remnant {remnant!r} at line {line}")


def _substitute(text: str, manifest: Mapping[str, str], tables: Mapping[str, str]) -> str:
    def table_pass(match):
        kind, key = match.group(1), match.group(2)
        if kind != "table" or key not in tables:
            return match.group(0)
        return _SENT_OPEN + tables[key].strip("\n") + _SENT_CLOSE

    stage = PLACEHOLDER.sub(table_pass, text)

    missing = set()
    for kind, key in PLACEHOLDER.findall(stage):
        if kind == "table":
            missing.add(key)
        elif key not in manifest:
            missing.add(key)
    if missing:
        raise MissingKeyError(missing)

    stage = PLACEHOLDER.sub(lambda m: manifest[m.group(2)], stage)

    stage = re.sub(r"[ \t]*\n*[ \t]*" + re.escape(_SENT_OPEN), "\n\n", stage)
    stage = re.sub(re.escape(_SENT_CLOSE) + r"[ \t]*\n*[ \t]*", "\n\n", stage)
    return stage.lstrip("\n")


def _scan_remnants(text: str) -> None:
    # Code is already set aside (its braces stand hidden), so every line is
    # scanned, and a fence pandoc would print as text is scanned too.
    for lineno, line in enumerate(text.split("\n"), start=1):
        hit = SUSPECT.search(line)
        if hit:
            raise ResolveError(lineno, hit.group(0))


_CODE_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(\s|$)")
# What pandoc may read after a fence, a word or {attributes}. Anything else, such
# as two words, makes the line text.
_FENCE_INFO = re.compile(
    r"^[ \t]*(?:[^\s{}]+|\{[ \t]*(?:(?:[#.][^\s{}=]+|=[^\s{}=]+"
    r"|[\w.-]+=(?:\"[^\"]*\"|[^\s{}\"]+))[ \t]*)+\})?[ \t]*$"
)
# A line that marks out the columns of a simple, multiline or grid table.
_TABLE_RULE = re.compile(r"^[ \t]*(?:-+(?:[ \t]+-+)*|\+[-=:+]+\+)[ \t]*$")
# An autolink or HTML tag, a link target, math, or a TeX command holding a
# backtick, which pandoc may read before any code.
_HOLDS_BACKTICK = re.compile(
    r"<[^<>]*`[^<>]*>|\]\([^()]*`[^()]*\)|\$(?=\S)[^$]*`[^$]*(?<=\S)\$"
    r"|\\[A-Za-z]+\*?(?:\[[^\]`]*\]|\{[^{}`]*\})*[\[{][^\]}]*`"
)


def _lines(text: str) -> List[str]:
    """text cut after each newline, as pandoc cuts lines (not at other breaks)."""
    return [line for line in re.split(r"(?<=\n)", text) if line]


def _blank(line: str) -> bool:
    return not line.strip(" \t\r\n")


def _fenced_blocks(text: str) -> List[Tuple[int, int]]:
    """The (start, end) of each fenced code block, its fences included."""
    lines = _lines(text)
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line)
    blocks: List[Tuple[int, int]] = []
    i, after_block = 0, True
    while i < len(lines):
        line = lines[i].rstrip("\r\n")
        opened = _CODE_FENCE.match(line)
        if opened:
            mark = opened.group(1)
            usable = bool(_FENCE_INFO.match(opened.group(2)))
            if mark[0] == "`" and "`" in opened.group(2):
                usable = False
            if mark[0] == "~" and not after_block:
                usable = False
            if usable:
                close = re.compile(r"^ {0,3}%s{%d,}[ \t]*$" % (re.escape(mark[0]), len(mark)))
                end = None
                for j in range(i + 1, len(lines)):
                    if close.match(lines[j].rstrip("\r\n")):
                        end = j
                        break
                if end is not None:
                    blocks.append((starts[i], starts[end] + len(lines[end])))
                    i, after_block = end + 1, True
                    continue
        after_block = _blank(line) or bool(_ATX_HEADING.match(line))
        i += 1
    return blocks


def _inline_code(text: str, start: int, end: int, by_line: bool) -> List[Tuple[int, int]]:
    """The (start, end) of each inline code span between start and end. The search
    for a closing run ends at the end of the line when by_line, else at end."""
    spans: List[Tuple[int, int]] = []
    k = start
    while k < end:
        ch = text[k]
        if ch == "\\" and k + 1 < end and text[k + 1] in string.punctuation:
            k += 2
            continue
        if ch == "`":
            run = len(text[k:end]) - len(text[k:end].lstrip("`"))
            stop = text.find("\n", k, end) if by_line else -1
            close = re.compile(r"(?<!`)`{%d}(?!`)" % run).search(
                text, k + run, end if stop < 0 else stop
            )
            if close:
                spans.append((k, close.end()))
                k = close.end()
            else:
                # Pandoc prints one backtick as text and looks again from the next.
                k += 1
            continue
        k += 1
    return spans


def _chunks(text: str, start: int, end: int) -> List[Tuple[int, int]]:
    """The (start, end) of each run of lines between blank lines."""
    chunks: List[Tuple[int, int]] = []
    first, at = None, start
    for line in _lines(text[start:end]):
        if not _blank(line):
            if first is None:
                first = at
        elif first is not None:
            chunks.append((first, at))
            first = None
        at += len(line)
    if first is not None:
        chunks.append((first, end))
    return chunks


def _in_tables(text: str, chunks: List[Tuple[int, int]]) -> List[bool]:
    """For each chunk, whether it holds part of a simple, multiline or grid table.
    A multiline table can run over blank lines, from a chunk that opens with a
    rule to the next chunk that ends with one."""
    rules = [
        [bool(_TABLE_RULE.match(line.rstrip("\r\n"))) for line in _lines(text[s:e])]
        for s, e in chunks
    ]
    flags = [any(r) for r in rules]
    for i, r in enumerate(rules):
        if r[0] and not r[-1]:
            for j in range(i + 1, len(rules)):
                if rules[j][-1]:
                    for k in range(i, j + 1):
                        flags[k] = True
                    break
    return flags


def _code(text: str) -> List[bool]:
    """For each character, whether pandoc surely reads it as code, fenced or inline.

    Inline code is read twice in each run of lines between blank lines, once with
    its search for a close ending at the end of the line and once at the blank
    line. Pandoc ends inline code with its block, which falls between the two, so
    where both readings agree pandoc reads the same. Where they differ, where the
    lines hold part of a table that cuts lines into cells, or where they hold an
    autolink, HTML tag, link target, math or TeX command with a backtick in it,
    no inline code there is set aside.
    """
    code = [False] * len(text)
    at = 0
    for start, end in _fenced_blocks(text) + [(len(text), len(text))]:
        chunks = _chunks(text, at, start)
        for (s, e), table in zip(chunks, _in_tables(text, chunks)):
            if table or _HOLDS_BACKTICK.search(text, s, e):
                continue
            spans = _inline_code(text, s, e, True)
            if spans != _inline_code(text, s, e, False):
                continue
            for span_start, span_end in spans:
                for i in range(span_start, span_end):
                    code[i] = True
        for i in range(start, end):
            code[i] = True
        at = end
    return code


def _stand_in(texts) -> str:
    """A character none of texts holds, to stand for an opening brace inside code."""
    for point in range(0xE000, 0xF900):
        candidate = chr(point)
        if not any(candidate in text for text in texts):
            return candidate
    raise ValueError("the text uses every private character, so code cannot be set aside")


def _hide_code(text: str, brace: str, manifest: Mapping[str, str]) -> str:
    """text with each opening brace inside code replaced by brace, the same length,
    apart from those of a number placeholder in code whose key the manifest
    holds, which are kept so that it is filled."""
    code = _code(text)
    bound = [False] * len(text)
    for match in PLACEHOLDER.finditer(text):
        kind, key = match.group(1), match.group(2)
        if kind == "num" and key in manifest and all(code[match.start():match.end()]):
            for i in range(match.start(), match.end()):
                bound[i] = True
    return "".join(
        brace if ch == "{" and code[i] and not bound[i] else ch for i, ch in enumerate(text)
    )


def resolve(text: str, manifest: Mapping[str, str], tables: Mapping[str, str]) -> str:
    brace = _stand_in([text] + list(tables.values()) + list(manifest.values()))
    hidden_tables = {key: _hide_code(table, brace, manifest) for key, table in tables.items()}
    resolved = _substitute(_hide_code(text, brace, manifest), manifest, hidden_tables)
    _scan_remnants(resolved)
    return resolved.replace(brace, "{")
