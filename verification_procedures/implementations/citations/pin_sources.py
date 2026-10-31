"""Pin every source text, source_<citekey>.txt, whose first line is `ACCESS: fulltext`
or `ACCESS: abstract`. Writes sources.json {citekey: {file, sha256, access, text}}.

The copies are read through the contract's reads_optional pattern, so each one is a
hashed input of this step and replays exactly, and every quote check names the copy it
read."""
import glob
import hashlib
import os

import _lib

out = {}
for p in sorted(glob.glob(os.path.join(_lib.files_dir(), "source_*.txt"))):
    name = os.path.basename(p)
    key = name[len("source_"):-len(".txt")]
    with open(p, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    first, _, rest = text.partition("\n")
    access = "unknown"
    if first.upper().startswith("ACCESS:"):
        val = first.split(":", 1)[1].strip().lower()
        access = val if val in ("fulltext", "abstract") else "unknown"
        text = rest
    out[key] = {"file": name, "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "access": access, "text": text.strip()}

_lib.write_json("sources.json", out)
