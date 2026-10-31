"""Give the knowledge base's title, description, entry count, count per group, and index."""
import _lib

call = _lib.read_json("request_ok.json")
index = _lib.read_json("kb_index.json")
entries = sorted(index["entries"], key=lambda e: e["id"])
groups = {}
for e in entries:
    groups[e["group"]] = groups.get(e["group"], 0) + 1
result = {
    "title": index.get("title", ""),
    "description": index.get("description", ""),
    "entry_count": len(entries),
    "groups": groups,
    "index": [{"id": e["id"], "title": e["title"], "group": e["group"],
               "description": e["description"]} for e in entries],
}
_lib.write_json("answer.json", {"tool": call["tool"], "result": result,
                                "returned": [e["id"] for e in entries]})
