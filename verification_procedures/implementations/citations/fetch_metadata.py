"""Look up the DOI of each work an AI citation names (the authors' step 3a, Track C2 plan
choice 3).

Only works cited in a row whose origin is ai, and that have a reference entry, are looked
up. metadata_cache.json (keyed by lower-case DOI) is read first. A DOI missing from the
cache is asked of Crossref, and a DOI Crossref has no record of is asked of DataCite,
which registers arXiv and Zenodo DOIs, unless VG_OFFLINE=1, when it counts as not found
by this run. The addresses are VG_CROSSREF_URL (https://api.crossref.org/works/ when
unset) and VG_DATACITE_URL (https://api.datacite.org/dois/ when unset), so a test can
point both at a stand-in service on the local machine.

via says how each lookup ended, one of cache, crossref, datacite, not_found (neither
service holds the DOI), cache_miss_offline, no_doi, crossref_error, and datacite_error.
Each record, from the cache or either service, has the shape {title, author: [{family,
given}], issued: year, container-title, type}. Marked replay: network."""
import json
import os
import urllib.parse
import urllib.request

import _lib

AGENT = {"User-Agent": "vg-citations/0.2"}


def get(base, doi):
    """The parsed reply for the DOI, or None and how the request ended."""
    url = base + urllib.parse.quote(doi, safe="/")
    req = urllib.request.Request(url, headers=AGENT)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r), "ok"
    except Exception as err:  # a 404 is no record; anything else is a failed lookup
        return None, "404" if getattr(err, "code", None) == 404 else "error"


def crossref(doi):
    data, how = get(os.environ.get("VG_CROSSREF_URL") or "https://api.crossref.org/works/", doi)
    if data is None:
        return None, how
    msg = data["message"]
    parts = (msg.get("issued") or {}).get("date-parts") or [[None]]
    return {
        "title": (msg.get("title") or [""])[0],
        "author": [{"family": a.get("family", ""), "given": a.get("given", "")} for a in msg.get("author", [])],
        "issued": parts[0][0],
        "container-title": (msg.get("container-title") or [""])[0],
        "type": msg.get("type", ""),
    }, how


def datacite(doi):
    data, how = get(os.environ.get("VG_DATACITE_URL") or "https://api.datacite.org/dois/", doi)
    if data is None:
        return None, how
    att = (data.get("data") or {}).get("attributes") or {}
    publisher = att.get("publisher")
    if isinstance(publisher, dict):
        publisher = publisher.get("name")
    year = att.get("publicationYear")
    return {
        "title": ((att.get("titles") or [{}])[0] or {}).get("title", ""),
        "author": [{"family": c.get("familyName") or c.get("name", ""), "given": c.get("givenName", "")}
                   for c in att.get("creators") or []],
        "issued": int(year) if str(year or "").isdigit() else year,
        "container-title": (att.get("container") or {}).get("title") or publisher or "",
        "type": (att.get("types") or {}).get("resourceTypeGeneral", ""),
    }, how


def look_up(doi):
    rec, how = crossref(doi)
    if rec is not None:
        return rec, "crossref"
    if how != "404":
        return None, "crossref_error"
    rec, how = datacite(doi)
    if rec is not None:
        return rec, "datacite"
    return None, "not_found" if how == "404" else "datacite_error"


index = _lib.read_json("refs_index.json")
ai_keys = {r["citekey"] for r in _lib.read_json("rows_origin.json") if r["origin"] == "ai"}
cache = {k.lower(): v for k, v in _lib.read_json("metadata_cache.json").items()}
offline = os.environ.get("VG_OFFLINE") == "1"

out = []
for ref in index:
    if not (ref["in_refs"] and ref["id"] in ai_keys):
        continue
    doi = ref.get("doi", "").strip().lower()
    entry = {"id": ref["id"], "doi": doi, "found": False, "via": "no_doi", "record": None}
    if doi and doi in cache:
        entry.update(found=True, via="cache", record=cache[doi])
    elif doi and offline:
        entry.update(via="cache_miss_offline")
    elif doi:
        rec, via = look_up(doi)
        entry.update(found=rec is not None, via=via, record=rec)
    out.append(entry)

_lib.write_json("lookups.json", out)
