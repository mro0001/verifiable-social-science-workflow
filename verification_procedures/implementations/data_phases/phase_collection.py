"""phase_collection: the entry step of graphs/data_collection.yaml. It names the phase the report shows,
so the steps the three phase graphs share read it from phase.json."""
import _lib

_lib.write_json("phase.json", {"phase": "collection", "name": "data collection", "title": "Data collection report"})
