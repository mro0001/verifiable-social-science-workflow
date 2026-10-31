"""phase_cleaning: the entry step of graphs/data_cleaning.yaml. It names the phase the report shows,
so the steps the three phase graphs share read it from phase.json."""
import _lib

_lib.write_json("phase.json", {"phase": "cleaning", "name": "data cleaning", "title": "Data cleaning report"})
