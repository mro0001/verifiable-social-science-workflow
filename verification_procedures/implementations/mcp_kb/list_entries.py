"""List every entry's id, title, and group, sorted by id, filtered by group when one is given."""
import _lib

call = _lib.read_json("request_ok.json")
group = call["arguments"].get("group")
rows = [{"id": e["id"], "title": e["title"], "group": e["group"]}
        for e in sorted(_lib.read_json("kb_index.json")["entries"], key=lambda e: e["id"])
        if group is None or e["group"] == group]
_lib.write_json("answer.json", {"tool": call["tool"], "result": {"entries": rows},
                                "returned": [row["id"] for row in rows]})
