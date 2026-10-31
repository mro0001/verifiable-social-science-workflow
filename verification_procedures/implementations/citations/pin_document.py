"""Hash the final build's text, draft.md, and every other fixed input, so the report
names exactly what was read. The handoff gathers the final build's text, the latest
build's filled-in text, as draft.md (Track C2 plan choice 1)."""
import hashlib

import _lib

INPUTS = ["draft.md", "citation_provenance.yaml", "refs.yaml", "metadata_cache.json"]


def sha(name):
    with open(_lib.path(name), "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


hashes = {name: sha(name) for name in INPUTS}
_lib.write_json("doc_pin.json", {"draft_sha256": hashes["draft.md"], "inputs": hashes})
