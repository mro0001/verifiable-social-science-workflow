"""The observability layer, which lets the scholar watch AI work and reopen it afterwards (appendix A2.6).

So far it holds the names of OpenTelemetry's conventions for AI calls that the
layer writes (conventions.py), the span model with its OTLP JSON file form
(spans.py), the reader of the audit layer's record (record.py), the Claude
Code adapter for tool calls, their results, and model turns with their
reasoning (adapters/claude_code.py), the marking of knowledge base
retrievals (kb.py), and the build of the view's trace files and data file
(build.py), run by python3 -m observability build (cli.py), live mode,
which rebuilds the view while the record grows (watch.py, run by
python3 -m observability watch), and the dashboard page that opens from
disk (dashboard/). Sessions of other harnesses come from the audit events
table (adapters/events.py), and verification runs from vg.py's run folders
(adapters/vg_run.py). It reads other
layers' files read only and imports none of their code.
"""

__version__ = "0.1"
