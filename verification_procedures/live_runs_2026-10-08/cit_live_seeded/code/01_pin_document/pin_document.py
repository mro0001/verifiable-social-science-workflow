"""Hash the draft and every fixed input so the report names exactly what was checked."""
import hashlib

import _lib

INPUTS = ["draft.md", "author_draft.md", "citation_log.yaml", "refs.yaml",
          "metadata_cache.json", "prior_checks.json"]


def sha(name):
    with open(_lib.path(name), "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


hashes = {name: sha(name) for name in INPUTS}
_lib.write_json("doc_pin.json", {"draft_sha256": hashes["draft.md"], "inputs": hashes})
