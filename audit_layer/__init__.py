"""The audit layer, which records, stores, and tags every AI session and tool call (appendix A2.4).

So far it holds the audit store (store.py) and the reads of it that several
parts share (queries.py), the one event schema (events.py), the Claude Code
adapter (capture/claude_code.py), the mechanical tagging pass
(tagging/mechanical.py), the model tagging pass and the answer source it asks
(tagging/model_pass.py, tagging/answers.py), the audit home and its excluded
folders (settings.py), capture on demand through a registry of adapters, one
for each harness (capture/__init__.py), the sweep over every session a
harness keeps (capture/sweep.py), the written-out citation log
(records/citation_log.py), the sources store's records, retrieved originals,
and extracted text, the data store's datasets, the knowledge store
sketch, and the working store's snapshots (stores/), the init, capture, sweep, check-captures, tag, review,
sources, data, knowledge, and write-out commands (cli.py), and the hook script and
schedule template that start the sweep, with notes for adding them by hand
(hooks/).
"""
