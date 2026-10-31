"""no_rebuild: the ledger is empty, so the rebuild witness did not run. Says so.

Writes the same two files rebuild writes (rebuild.json, findings_rebuild.json) so
the report reads one shape whichever branch fired. The finding's check is
"rebuild" because it reports on that witness.
"""
import _lib

ledger = _lib.read_json("ledger.json")
_lib.write_json("rebuild.json", {"exercised": False, "pandoc": None, "rebuilt": 0, "matched": 0, "builds": []})
_lib.emit_findings("rebuild", [_lib.finding("rebuild", "info", "ledger",
                                            "No ledgered builds, so nothing was rebuilt; the rebuild witness was not exercised.",
                                            "rows=%d" % ledger["rows"])])
