# Design documents

This folder holds the design documents the proposal's technical appendix cites, so a reader can check the rows the appendix marks "Specified".

| File | What it is | Where the appendix cites it |
|---|---|---|
| `verification_procedures_design_2026-10-09.md` | The build spec for the verification procedures, draft 1 of October 9, 2026. It sets the schemas, the shared report, the adapters, the triggers, and the build order | Table A9, as "Verification procedures design (October 9)" |
| `file_protocol_design_2026-09-18.md` | The file protocol, draft 1.0 of September 18, 2026. It says how a project moves from loose files to a map file and then to a self-contained ship folder | The paragraph after Table A9, as part of "Designs for the databases and the file protocol" |
| `2026-10-08_four_streams_notes.md` | The authors' design notes of October 8, 2026, kept verbatim. The procedural graphs cite them by date | Not cited by the appendix. It was already in this folder |

The system specification, draft 0.10 of October 22, 2026, is `MANUSCRIPT_WORKFLOW.md` at the repository root. Table A9 cites it as "system specification draft 0.10 (October 22)". Its section The stores is the database design that the paragraph after Table A9 names.

## How these copies differ from the originals

The two design copies are the originals with private lines removed or reworded. Every other line is as written. The kinds of line changed are these.

- Absolute paths on the authors' machine. The verification procedures design now says "folders that hold student records" where it named two folders by full path.
- Names of private systems, such as the authors' session store, wiki, and local skills.
- Pointers to working notes and decision logs that are not in this repository. Each now says the source is not public.
- The file protocol's worked example, which came from an unpublished manuscript. Its folder, draft, and data file names are replaced with neutral ones (`my_paper/`, `draft_a.md`, `data/raw/responses.jsonl`). What the protocol says is unchanged.

A brainstorm of August 4, 2026 on the streams and the project lifecycle is not included, since the appendix does not cite it.
