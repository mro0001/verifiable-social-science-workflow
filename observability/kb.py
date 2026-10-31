"""Knowledge base retrievals, marked on tool spans.

Proposal Approach paragraph 4 has the layer show which knowledge base entries
the harness retrieves, so a harness asked to apply a verification procedure
can be seen retrieving it. Appendix A2.6 paragraph 1 names the knowledge base
entries the AI reads, and A2.4 "Knowledge base" has the entries served by a
server with five tools. A retrieval is a call to a listed server, by default
pipeline-kb and workflow-kb (the reconciliation file, Track E), or a read of a
markdown entry inside a listed folder (plan choice 10). The marking works on
spans alone, so it serves every adapter. Entry files are read, never changed.
"""
import json
import os
from pathlib import Path
from typing import Dict, List

import yaml

from observability import conventions as cv

KB_SERVERS = ("pipeline-kb", "workflow-kb")

DATASTORE = "datastore"
MCP_PREFIX = "mcp__"

# The server's tools whose input names one entry, and the one that searches.
ENTRY_TOOLS = ("get_entry", "lookup_provenance")
SEARCH_TOOL = "search_kb"

READ_ROLE = "read"


def mark_retrievals(spans, kb_servers=KB_SERVERS, kb_dirs=()):
    """Mark the knowledge base retrievals among spans, and return spans.

    A tool span named mcp__<server>__<tool> for a listed server gets the
    tool type datastore and the server as its data source. A get_entry or
    lookup_provenance call also gets the entry it names, and a search_kb call
    its query. A span with the role read whose file.path is a markdown file
    inside one of kb_dirs gets the tool type datastore, the folder's name as
    its data source, and the entry's id from its front matter (the file name
    without .md when the file can no longer be read). Spans are changed in
    place.
    """
    servers = set(kb_servers or ())
    folders = [str(folder) for folder in (kb_dirs or ())]
    for span in spans:
        attributes = span.get("attributes")
        if not isinstance(attributes, dict):
            continue
        if attributes.get(cv.OPERATION_NAME) != cv.EXECUTE_TOOL:
            continue
        name = attributes.get(cv.TOOL_NAME)
        if isinstance(name, str) and name.startswith(MCP_PREFIX):
            _mark_call(attributes, name, servers)
        elif attributes.get(cv.AUDIT_ROLE) == READ_ROLE:
            _mark_read(attributes, folders)
    return spans


def _mark_call(attributes, name, servers):
    server, _, tool = name[len(MCP_PREFIX):].partition("__")
    if server not in servers or not tool:
        return
    attributes[cv.TOOL_TYPE] = DATASTORE
    attributes[cv.DATA_SOURCE_ID] = server
    arguments = _arguments(attributes.get(cv.TOOL_CALL_ARGUMENTS))
    if tool in ENTRY_TOOLS and isinstance(arguments.get("id"), str):
        attributes[cv.RETRIEVAL_DOCUMENTS] = [{"id": arguments["id"]}]
    elif tool == SEARCH_TOOL and isinstance(arguments.get("query"), str):
        attributes[cv.RETRIEVAL_QUERY_TEXT] = arguments["query"]


def _arguments(value):
    """A call's arguments as a dict, whether kept as a dict or as JSON text."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    if isinstance(value, dict):
        return value
    return {}


def _mark_read(attributes, folders):
    path = attributes.get(cv.FILE_PATH)
    if not isinstance(path, str) or not path.endswith(".md"):
        return
    real = os.path.realpath(path)
    for folder in folders:
        root = os.path.realpath(folder)
        if real.startswith(root.rstrip(os.sep) + os.sep):
            matter = _front_matter(Path(path))
            entry_id = matter.get("id") if matter else None
            if not isinstance(entry_id, str) or not entry_id:
                entry_id = Path(path).stem
            attributes[cv.TOOL_TYPE] = DATASTORE
            attributes[cv.DATA_SOURCE_ID] = Path(folder).name
            attributes[cv.RETRIEVAL_DOCUMENTS] = [{"id": entry_id}]
            return


def _front_matter(path):
    """A markdown file's front matter as a dict, or None.

    None when the file cannot be read, does not open with a front matter
    block, or that block is not a YAML mapping.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for number in range(1, len(lines)):
        if lines[number].strip() == "---":
            try:
                matter = yaml.safe_load("\n".join(lines[1:number]))
            except yaml.YAMLError:
                return None
            return matter if isinstance(matter, dict) else None
    return None


def entries(kb_dirs) -> List[Dict]:
    """Each markdown entry with front matter in kb_dirs and their subfolders.

    Each is a dict with id, title, group, and path, in the order of the
    folders given and then of their paths. A file without front matter is
    skipped.
    """
    found = []
    for folder in kb_dirs or ():
        for path in sorted(Path(folder).rglob("*.md")):
            if not path.is_file():
                continue
            matter = _front_matter(path)
            if matter is None:
                continue
            found.append({
                "id": matter.get("id"),
                "title": matter.get("title"),
                "group": matter.get("group"),
                "path": str(path),
            })
    return found
