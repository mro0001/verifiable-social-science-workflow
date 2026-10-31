"""report: the build stream's fill function. It reads the step outputs, fills the fields of
schemas/build.yaml (copied beside this file as schema.yaml) with the wording the report
shows, and hands them to the one report builder, which writes fields.json, findings.json,
and report.md. An item whose AI write the session record names by its session's public id
carries it in sessions, and the report names the session on a line of its own."""
import _lib
import _report


# A check the ledger's columns cannot support is not run (ospipe's ledger records no
# build command, snapshot checksum, or source and numbers checksums).
NO_COMMAND = "the ledger records no build command"
NO_SNAPSHOT_SUM = "the ledger records no snapshot checksum"
NO_SOURCE_SUMS = "the ledger records no source or numbers checksum"


def yn(v):
    return {True: "yes", False: "**no**", None: "n/a"}[v]


def session_fields(findings):
    """sessions, and session_line, its text for the report, for each item an AI write's
    finding gives a session's public id, in the order the findings name them."""
    refs = {}
    for f in findings:
        ref = f.get("session_ref")
        if f["check"] == "check_ai_touch" and ref and ref not in refs.setdefault(f["item"], []):
            refs[f["item"]].append(ref)
    return {item: {"sessions": found, "session_line": ", ".join(found)}
            for item, found in refs.items() if found}


def items(m, ledger, findings):
    """One item for each deliverable in the map, giving its source, its builds folder, and
    its ledgered versions, each needing a decision, then one item for each other group of
    problems. A problem found on a deliverable's own name is carried by its row."""
    builds = ledger.get("builds") or []
    attached, problems = _lib.problem_items(findings, [d["name"] for d in m["deliverables"]])
    rows = []
    for d in m["deliverables"]:
        versions = [b["version"] for b in builds if b.get("deliverable") == d["name"]]
        summary = "source %s, builds folder %s, ledgered versions %s" % (
            d.get("source") or "(none)", d.get("builds_dir") or "(none)",
            ", ".join(versions) or "none")
        rows.append({"id": d["name"], "kind": "deliverable", "summary": summary,
                     "findings": attached.get(d["name"], []), "needs_decision": True})
    sessions = session_fields(findings)
    return [dict(row, **sessions.get(row["id"], {})) for row in rows + problems]


def deliverable_rows(m, ledger, prefs, rb):
    rb_by_path = {r["path"]: r for r in rb["builds"]}
    rows = []
    for d in m["deliverables"]:
        bs = [b for b in ledger["builds"] if b["deliverable"] == d["name"]]
        ps = [p for p in prefs if p["deliverable"] == d["name"]]
        if not rb["exercised"]:
            rebuilt = "not exercised"
        elif not bs:
            rebuilt = "n/a"
        elif not any(b["command_sha256"] for b in bs):
            rebuilt = "not run"
        else:
            ok = sum(1 for b in bs if rb_by_path.get(b["path"], {}).get("matches"))
            rebuilt = "%d/%d" % (ok, len(bs)) if ok == len(bs) else "**%d/%d**" % (ok, len(bs))
        led_ok = sum(1 for b in bs if b["file_ok"] and b["snapshot_ok"] is not False)
        led = ("%d/%d" % (led_ok, len(bs)) if led_ok == len(bs) else "**%d/%d**" % (led_ok, len(bs))) if bs else "n/a"
        missing = [p["pref"] for p in ps if not p["in_command"]]
        pr = ("all %d" % len(ps) if not missing else "**missing: %s**" % ", ".join(missing)) if ps else "none declared"
        rows.append({"name": "%s" % d["name"], "source": "%s" % d["source"],
                     "builds": ", ".join(b["version"] for b in bs) or "none",
                     "ledger_ok": led, "rebuild": rebuilt, "prefs": pr})
    return rows


def build_rows(ledger, rb):
    rb_by_path = {r["path"]: r for r in rb["builds"]}
    rows = []
    for b in ledger["builds"]:
        r = rb_by_path.get(b["path"], {})
        sw = r.get("snapshot_witnessed")
        no_command = bool(r) and not b["command_sha256"]
        no_sums = bool(r) and not (b["source_sha256"] and b["numbers_sha256"])
        rows.append({
            "path": b["path"], "deliverable": b["deliverable"], "version": b["version"],
            "date": b["date"], "purpose": b["purpose"],
            "file_ok": b["file_ok"],
            "snapshot_ok": {"not_run": NO_SNAPSHOT_SUM} if b["snapshot_ok"] is None else b["snapshot_ok"],
            "rebuild_matches": {"not_run": NO_COMMAND} if no_command else r.get("matches"),
            "snapshot_witnessed": {"not_run": NO_SOURCE_SUMS} if no_sums else sw,
            "purpose_cell": _lib.cell(b["purpose"], 40),
            "file_cell": yn(b["file_ok"]),
            "snapshot_cell": "not run" if b["snapshot_ok"] is None else yn(b["snapshot_ok"]),
            "rebuild_cell": yn(r.get("matches")) if rb["exercised"] and not no_command else "not run",
            "witnessed_cell": "not run" if not r or no_sums else
            {True: "yes", False: "**no**", None: "no (canonical moved on)"}[sw],
        })
    return rows


def main():
    m = _lib.read_json("map.json")
    ledger = _lib.read_json("ledger.json")
    prefs = _lib.read_json("prefs.json")
    rb = _lib.read_json("rebuild.json")
    competing = [x for x in m["look_alikes"] if x["banner"] is None]
    run = {"n_look_alikes": len(m["look_alikes"]), "n_competing": len(competing),
           "pandoc": "pandoc %s" % rb["pandoc"] if rb.get("pandoc") else {"not_run": "pandoc was not found"}}
    _report.build({
        "run": run,
        "items": items(m, ledger, _lib.collect_findings()),
        "tables": {"deliverables": deliverable_rows(m, ledger, prefs, rb),
                   "builds": build_rows(ledger, rb)},
    })


if __name__ == "__main__":
    main()
