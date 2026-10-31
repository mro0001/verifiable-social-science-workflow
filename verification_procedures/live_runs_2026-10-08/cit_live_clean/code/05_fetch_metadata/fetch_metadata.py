"""Look up each checked reference by DOI.

metadata_cache.json (keyed by lower-case DOI) stands in for Crossref/OpenAlex.
A DOI missing from the cache is tried live on Crossref unless VG_OFFLINE=1; with
VG_OFFLINE=1 it counts as not found. Record shape (cache and normalized
Crossref alike): {title, author: [{family, given}], issued: year,
container-title, type}. Marked replay: network."""
import json
import os
import urllib.parse
import urllib.request

import _lib


def crossref(doi):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")
    req = urllib.request.Request(url, headers={"User-Agent": "vg-citations/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            msg = json.load(r)["message"]
    except Exception as err:  # 404 = not found; anything else is reported, not passed
        code = getattr(err, "code", None)
        return None, "crossref_404" if code == 404 else "crossref_error"
    parts = (msg.get("issued") or {}).get("date-parts") or [[None]]
    return {
        "title": (msg.get("title") or [""])[0],
        "author": [{"family": a.get("family", ""), "given": a.get("given", "")} for a in msg.get("author", [])],
        "issued": parts[0][0],
        "container-title": (msg.get("container-title") or [""])[0],
        "type": msg.get("type", ""),
    }, "crossref"


index = _lib.read_json("refs_index.json")
cache = {k.lower(): v for k, v in _lib.read_json("metadata_cache.json").items()}
offline = os.environ.get("VG_OFFLINE") == "1"

out = []
for ref in index:
    if not (ref["in_refs"] and ref["cited_in_checked"]):
        continue
    doi = ref.get("doi", "").strip().lower()
    entry = {"id": ref["id"], "doi": doi, "found": False, "via": "no_doi", "record": None}
    if doi and doi in cache:
        entry.update(found=True, via="cache", record=cache[doi])
    elif doi and offline:
        entry.update(via="cache_miss_offline")
    elif doi:
        rec, via = crossref(doi)
        entry.update(found=rec is not None, via=via, record=rec)
    out.append(entry)

_lib.write_json("lookups.json", out)
