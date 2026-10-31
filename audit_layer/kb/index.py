"""The knowledge base's index and its export (appendix A2.4 "Serving entries").

The index llms.txt is rebuilt from the corpus alone, as the moved contract
asks. Its two header lines are kept from the index already there. Then each
group, in sorted order, lists its entries by id, each with its title, its file,
and the first sentence of its point, uncut.

The export is one JSON file holding every entry, the exported index (kb-index
version 1) that the knowledge base server's graph answers from. The entry
files stay the store, and git keeps their versions.
"""
import json
from pathlib import Path

from audit_layer.kb.entries import load

DEFAULT_TITLE = "# Knowledge base"
DEFAULT_DESCRIPTION = "> Entries for any AI session to apply."

SCHEMA = "kb-index"
SCHEMA_VERSION = 1


def _header(corpus):
    """The existing index's first '# ' line and first '> ' line, else the defaults."""
    title = DEFAULT_TITLE
    description = DEFAULT_DESCRIPTION
    index = Path(corpus) / "llms.txt"
    if index.is_file():
        lines = index.read_text(encoding="utf-8").splitlines()
        titles = [line for line in lines if line.startswith("# ")]
        descriptions = [line for line in lines if line.startswith("> ")]
        if titles:
            title = titles[0]
        if descriptions:
            description = descriptions[0]
    return title, description


def _by_group(entries):
    """The entries grouped by their group, each group's entries sorted by id."""
    groups = {}
    for entry in entries:
        groups.setdefault(entry["front"].get("group", ""), []).append(entry)
    for members in groups.values():
        members.sort(key=lambda entry: entry["front"].get("id", ""))
    return groups


def render_llms(corpus):
    """The index text the corpus gives."""
    title, description = _header(corpus)
    lines = [title, "", description, ""]
    groups = _by_group(load(corpus))
    for group in sorted(groups):
        lines.append("## " + group)
        lines.append("")
        for entry in groups[group]:
            lines.append(
                "- [{}]({}): {}".format(
                    entry["front"].get("title", ""), entry["rel"], entry["description"]
                )
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def write_llms(corpus):
    """Write the index the corpus gives, and say whether the file changed."""
    index = Path(corpus) / "llms.txt"
    text = render_llms(corpus)
    if index.is_file() and index.read_text(encoding="utf-8") == text:
        return False
    index.write_text(text, encoding="utf-8")
    return True


def export_index(corpus):
    """Every entry of the corpus in one record, kb-index version 1."""
    title, description = _header(corpus)
    rows = []
    for entry in load(corpus):
        front = entry["front"]
        rows.append(
            {
                "id": front.get("id", ""),
                "title": front.get("title", ""),
                "group": front.get("group", ""),
                "source": front.get("source", ""),
                "source_commit": front.get("source_commit", ""),
                "updated": front.get("updated", ""),
                "path": entry["rel"],
                "point": entry["point"],
                "description": entry["description"],
                "body": entry["body"],
            }
        )
    rows.sort(key=lambda row: row["id"])
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "title": title[len("# "):],
        "description": description[len("> "):],
        "entries": rows,
    }


def write_export(corpus, out):
    """Write the export as JSON with sorted keys, a two-space indent, and a final newline."""
    text = json.dumps(export_index(corpus), sort_keys=True, indent=2, ensure_ascii=False)
    Path(out).write_text(text + "\n", encoding="utf-8")
