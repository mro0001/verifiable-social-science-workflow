"""The header block the R and Quarto adapters read (Track D, step D12).

The data procedure requires each step script to open with the sections
Purpose, Inputs, Outputs, Parameters, and Assumptions, and its check_docs
finds a section at a line holding only the name and a colon at the left
margin. An R script or a Quarto chunk keeps the same block in comment lines,
with an optional line Kind: <word> (Track D choice 17). These functions read
that block. They read text only and run nothing.
"""
import re
from typing import Dict, List, Optional, Sequence

# The five sections the data procedure's check_docs requires, in its order.
SECTIONS = ("Purpose", "Inputs", "Outputs", "Parameters", "Assumptions")

# check_docs's rule for a section line, a name and a colon at the left margin.
_SECTION = re.compile(r"^([A-Z][A-Za-z ]*):\s*$")
_KIND = re.compile(r"^Kind:\s*(\S+)\s*$")
_FILE = re.compile(r"\.[A-Za-z][A-Za-z0-9]*$")


def header_lines(text: str, marks: Sequence[str]) -> List[str]:
    """The comment lines at the top of text, each with its mark and one space removed.

    A first line starting #! is skipped, and so is any line starting #|, a
    Quarto chunk option. The block ends at the first other line that starts
    with none of marks, a blank line included. The longest mark that fits a
    line is the one removed, so with marks #' and # the line #' Inputs: gives
    Inputs:.
    """
    found = []
    ordered = sorted(marks, key=len, reverse=True)
    for number, line in enumerate(text.splitlines()):
        if number == 0 and line.startswith("#!"):
            continue
        if line.startswith("#|"):
            continue
        mark = next((m for m in ordered if line.startswith(m)), None)
        if mark is None:
            break
        rest = line[len(mark):]
        if rest.startswith(" "):
            rest = rest[1:]
        found.append(rest)
    return found


def sections(lines: Sequence[str]) -> Dict[str, List[str]]:
    """The lines under each of the five sections, by section name.

    A section starts at a line holding only its name and a colon at the left
    margin and runs to the next such line. Lines before the first section are
    left out. A line naming any other section stays a line of the section
    above it, as in check_docs.
    """
    found = {}  # type: Dict[str, List[str]]
    current = None
    for line in lines:
        match = _SECTION.match(line)
        if match and match.group(1) in SECTIONS:
            current = match.group(1)
            found[current] = []
        elif current is not None:
            found[current].append(line)
    return found


def kind_of(lines: Sequence[str]) -> Optional[str]:
    """The word on the first line Kind: <word> at the left margin, or None."""
    for line in lines:
        match = _KIND.match(line)
        if match:
            return match.group(1)
    return None


def file_names(section: Sequence[str]) -> List[str]:
    """The first word of each line of section that ends in a dot and an extension, in order.

    An extension starts with a letter, so a number such as 0.5 is not a file name.
    """
    found = []
    for line in section:
        words = line.split()
        if words and _FILE.search(words[0]):
            found.append(words[0])
    return found
