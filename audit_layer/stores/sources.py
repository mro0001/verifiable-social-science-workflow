"""The sources store's records.

Proposal Overview paragraph 2 and Figure 2 give the databases the sources a
manuscript draws on. Appendix Table A3's Sources row gives each source its
bibliographic metadata, an identifier block with DOI, OpenAlex, and Semantic
Scholar, its retrieval status, and a content fingerprint for deduplication,
and Figure A4 has sources arrive by routes other than capture. They arrive
from the citation manager's BibTeX export (plan choice 15), and every row
carries the session and reason its command is given (plan choice 23).

- fingerprint(title, year) is the sha256 of the title in lower case with
  everything but letters and digits removed, followed by the year.
- add_from_bib(store, bib_path, provenance) adds one record per entry of the
  file and says what it did.
- attach_original(store, citekey, file_path, method, retrieved_on, provenance)
  keeps a retrieved original once in the file store, with its retrieval
  method and date, and turns the record's status to retrieved, since a source
  retrieved once may not be retrievable again (spec 0.11 Sources).
- add_text(store, citekey, kind, text_path, conversion_method, provenance)
  keeps text extracted from a source, by kind, with its conversion method, so
  extraction can be rerun when tools improve. The newest text of a kind
  counts, as it supersedes the one before.

An original's row and a text's row name the source by its record's row id
when they were written. Every version of a record carries its citekey, so a
later version of the record still finds them.

The OpenAlex and Semantic Scholar ids stay empty, since no route that fills
them is designed.
"""
import hashlib
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from audit_layer.store import Store, add_row, current, put_file, supersede, writing
from audit_layer.stores import is_date
from audit_layer.stores.bibtex import read_bib

VERSION = 1
NOT_RETRIEVED = "not retrieved"
RETRIEVED = "retrieved"

# The kinds of extracted text (Table A3 Sources row).
KINDS = ("abstract", "body", "fulltext", "references")


class SourceError(ValueError):
    """An original or a text the sources store refuses."""

# The record fields an entry of the bib file gives, beside the DOI.
_FROM_BIB = ("title", "authors", "year", "venue")


class Summary(NamedTuple):
    """What one add_from_bib did."""

    added: int
    unchanged: int
    superseded: int
    # Each refused entry as (citekey, why), in the file's order.
    refused: List[Tuple[str, str]]


def fingerprint(title: str, year: Any) -> str:
    """The sha256 of the title, lower case, letters and digits only, followed by the year."""
    letters = "".join(char for char in str(title or "").lower() if char.isalnum())
    return hashlib.sha256((letters + str(year or "")).encode("utf-8")).hexdigest()


def add_from_bib(store: Store, bib_path, provenance: Dict[str, str]) -> Summary:
    """Add one record for each entry of the bib file at bib_path.

    An entry whose current record has the same fields is skipped. An entry
    whose fields changed supersedes its record, which keeps its retrieval
    status and its OpenAlex and Semantic Scholar ids. An entry with no title,
    or whose fingerprint or DOI matches a current record under another
    citekey, is refused, naming that citekey, and the other entries go on. A
    file that cannot be read or read as BibTeX raises and adds nothing.
    """
    entries = read_bib(Path(bib_path).read_text(encoding="utf-8"))
    added = unchanged = superseded = 0
    refused = []
    for entry in entries:
        key = entry["key"]
        record = _record(entry)
        if not record["title"]:
            refused.append((key, f"{key} has no title, so it has no content fingerprint"))
            continue
        rows = current(store, "sources")
        clash = _clash(rows, key, record)
        if clash:
            refused.append((key, clash))
            continue
        own = [row for row in rows if row["citekey"] == key]
        if not own:
            fields = dict(record, citekey=key, retrieval_status=NOT_RETRIEVED)
            fields["identifiers"] = {"doi": record["doi"], "openalex": "", "semantic_scholar": ""}
            del fields["doi"]
            add_row(store, "sources", fields, provenance)
            added += 1
            continue
        old = own[-1]
        old_doi = (old["identifiers"] or {}).get("doi", "")
        changes = {name: record[name] for name in _FROM_BIB if record[name] != old[name]}
        if record["content_fingerprint"] != old["content_fingerprint"]:
            changes["content_fingerprint"] = record["content_fingerprint"]
        if record["doi"] != old_doi:
            changes["identifiers"] = dict(old["identifiers"] or {}, doi=record["doi"])
        if not changes:
            unchanged += 1
            continue
        supersede(store, "sources", old["id"], changes, provenance)
        superseded += 1
    return Summary(added, unchanged, superseded, refused)


def _record(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The record fields one bib entry gives."""
    fields = entry["fields"]
    title = fields.get("title", "")
    year = fields.get("year", "")
    return {
        "title": title,
        "authors": fields.get("author", ""),
        "year": year,
        "venue": fields.get("journal") or fields.get("booktitle") or "",
        "doi": fields.get("doi", ""),
        "content_fingerprint": fingerprint(title, year),
    }


def _clash(rows: List[Dict[str, Any]], key: str, record: Dict[str, Any]) -> Optional[str]:
    """Why the entry is refused when a current record under another citekey matches it."""
    doi = record["doi"].strip().lower()
    for row in rows:
        if row["citekey"] == key:
            continue
        if row["content_fingerprint"] == record["content_fingerprint"]:
            return (
                f"{key} has the content fingerprint of {row['citekey']}, already in the store,"
                " so it was not added"
            )
        other = str((row["identifiers"] or {}).get("doi", "")).strip().lower()
        if doi and other == doi:
            return f"{key} has the DOI of {row['citekey']}, already in the store, so it was not added"
    return None


def attach_original(
    store: Store,
    citekey: str,
    file_path,
    method: str,
    retrieved_on: str,
    provenance: Dict[str, str],
) -> str:
    """Keep the retrieved original at file_path for citekey and return its row's id.

    The file is kept once in the file store under its sha256, so the same
    bytes attached again add a row and no second file. The row records the
    retrieval method and the date, written YYYY-MM-DD. The source's record is
    first superseded with status retrieved unless it already says so, and the
    row names that current record, all in one transaction. An unknown citekey, a blank method, or a date in
    another form is refused before anything is kept.
    """
    if not str(method or "").strip():
        raise SourceError("an original needs its retrieval method, and none was given")
    if not is_date(retrieved_on):
        raise SourceError(f"the retrieval date {retrieved_on!r} is not a date written YYYY-MM-DD")
    _record_of(store, citekey)
    data = Path(file_path).read_bytes()
    checksum = put_file(store, data)
    with writing(store) as write:
        record = _record_of(store, citekey)
        source = record["id"]
        if record["retrieval_status"] != RETRIEVED:
            source = write.supersede("sources", source, {"retrieval_status": RETRIEVED}, provenance)
        return write.add(
            "source_originals",
            {
                "source": source,
                "file_sha256": checksum,
                "byte_size": len(data),
                "retrieval_method": method,
                "retrieved_on": retrieved_on,
            },
            provenance,
        )


def add_text(
    store: Store,
    citekey: str,
    kind: str,
    text_path,
    conversion_method: str,
    provenance: Dict[str, str],
) -> str:
    """Keep the text at text_path, extracted from citekey's source, and return its row's id.

    kind is one of abstract, body, fulltext, and references. The file is read
    as UTF-8 text. A text of a kind the source already has supersedes it, so
    the newest of a kind counts and the earlier one stays in the table. An
    unknown citekey or kind, or a blank conversion method, is refused.
    """
    if kind not in KINDS:
        raise SourceError(f"{kind!r} is not a kind of text. The kinds are {', '.join(KINDS)}")
    if not str(conversion_method or "").strip():
        raise SourceError("a text needs its conversion method, and none was given")
    _record_of(store, citekey)
    text = Path(text_path).read_bytes().decode("utf-8")
    fields = {"kind": kind, "text": text, "conversion_method": conversion_method}
    with writing(store) as write:
        record = _record_of(store, citekey)
        fields["source"] = record["id"]
        versions = set(_row_ids(store, citekey))
        earlier = [
            row
            for row in current(store, "source_texts", kind=kind)
            if row["source"] in versions
        ]
        if earlier:
            return write.supersede("source_texts", earlier[-1]["id"], fields, provenance)
        return write.add("source_texts", fields, provenance)


def _record_of(store: Store, citekey: str) -> Dict[str, Any]:
    """The current record of citekey, or a refusal naming it."""
    rows = current(store, "sources", citekey=citekey)
    if not rows:
        raise SourceError(f"there is no source {citekey} in the sources store")
    return rows[-1]


def _row_ids(store: Store, citekey: str) -> List[str]:
    """The ids of every version of citekey's record, current or superseded."""
    cursor = store.db.execute("SELECT id FROM sources WHERE citekey = ? ORDER BY rowid", (citekey,))
    return [row[0] for row in cursor.fetchall()]
