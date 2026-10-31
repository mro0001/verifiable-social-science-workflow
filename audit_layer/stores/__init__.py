"""The audit layer's other stores of Table A3, beside the audit store's sessions.

Each store keeps its rows in the one audit database (store.py), with the
spine on every row, and its files in the same file store.

- bibtex.py reads the citation manager's BibTeX export.
- sources.py keeps the sources store's records, retrieved originals, and
  extracted text (Table A3 Sources row).
- data.py keeps the data store's datasets, one typed table for each version,
  with its catalog row and codebook (Table A3 Data row).
- knowledge.py keeps the knowledge store sketch, loaded from the knowledge
  base's entry files, with the history of each entry (Table A3 Knowledge row).
- working.py keeps the working store's snapshots of the notes, scripts, and
  drafts AI sessions produced or edited, which the sweep takes (Table A3
  Working row).

is_date(text) says whether text is a calendar date written YYYY-MM-DD, the
form the stores' commands take a date in.
"""
import re
from datetime import datetime

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def is_date(text) -> bool:
    """Whether text is a calendar date written YYYY-MM-DD, such as 2026-10-20."""
    if not isinstance(text, str) or not _DATE.fullmatch(text):
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True
