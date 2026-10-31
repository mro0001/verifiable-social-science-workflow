"""phase_analysis: the entry step of graphs/data_analysis.yaml. It names the phase the report shows,
so the steps the three phase graphs share read it from phase.json."""
import _lib

_lib.write_json("phase.json", {"phase": "analysis", "name": "data analysis", "title": "Data analysis report"})
