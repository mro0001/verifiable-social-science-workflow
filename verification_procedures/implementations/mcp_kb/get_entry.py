"""Return one entry whole, its six frontmatter fields and its body, or not_found."""
import _lib

FIELDS = ("id", "title", "source", "source_commit", "updated", "group", "body")

call = _lib.read_json("request_ok.json")
wanted = call["arguments"]["id"]
entry = next((e for e in _lib.read_json("kb_index.json")["entries"] if e.get("id") == wanted), None)
if entry is None:
    result = {"error": {"code": "not_found", "message": "No entry with id %r" % wanted}}
    returned = []
else:
    result = {key: entry[key] for key in FIELDS}
    returned = [entry["id"]]
_lib.write_json("answer.json", {"tool": call["tool"], "result": result, "returned": returned})
