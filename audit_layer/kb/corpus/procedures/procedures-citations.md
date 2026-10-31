---
id: procedures-citations
title: Source support
source: verification_procedures/graphs/citations.yaml
source_commit: sha256:669c69d01bd6
updated: 2026-10-31
group: PROCEDURES
---

# Source support

Lay out, for the scholar to approve or hold, each citation in the final build. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Lay out, for the scholar to approve or hold, each citation in the final build. Say which citations came from an AI in the record of sessions and artifacts. For each one, say whether the cited work can be found, and for each work that can be found give the sentence, the reason the AI gave for the citation, and a quote from the source with a check that the quote is in the source text. Programs establish the facts and the record supplies the evidence. The scholar decides every item.
2. Triggers. It starts on the harness events `ai_edit`, `turn_end`, `build`, and `commit`. It starts on a request that uses the phrase "verify citations", "check references", or "citation report".
3. Steps. 11 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `pin_document` (tool step) Hash the final build's text (draft.md) and every other input, so the report names exactly what was read.
   - `extract_citations` (tool step) One row for each cited key in each sentence of the final build's text, with the sentence and its locator.
   - `match_references` (tool step) Match each cited key to the reference list. A cited key with no entry and an entry the final build does not cite are each a note.
   - `read_origin` (tool step) Read each citation's origin from the citation provenance record, ai, scholar, or unknown, with the record's evidence for it.
   - `fetch_metadata` (tool step) Look up the DOI of each work an AI citation names, in the metadata cache first, then Crossref, then DataCite for a DOI Crossref lacks, unless VG_OFFLINE=1.
   - `check_existence` (tool step) Say for each AI citation's work whether it was found, not found, or not looked up, and show the record that was found.
   - `pin_sources` (tool step) Pin the source texts (source_<citekey>.txt) with their access level and sha256, so each quote check names the copy it read.
   - `gather_reason_and_quote` (tool step) For each AI citation whose work was found, take the AI's recorded reason and any recorded quote from the provenance record, and mark the citations that have no recorded quote for the passage step.
   - `locate_passage` (judgment step, once per item in `rows_reasons.json` where status in [to_locate]) For a citation whose record holds no quote that is in its source text, find the passage in the source text that the sentence draws on, and give it word for word, or a section pointer, or a paraphrase marked as one. No verdict.
   - `verify_quote` (tool step) Check every exact quote, from the record or from the passage step, against the source text, and say whether it was found and where.
   - `report` (tool step) Write fields.json, findings.json, and report.md. Counts first, then each citation with its sentence, origin, and evidence, and for AI citations the lookup, the reason, the quote, and the quote check.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/citations.yaml --run runs/<new run folder> --inputs <inputs folder> --judge <executor>`. The inputs folder holds `citation_provenance.yaml`, `draft.md`, `metadata_cache.json`, and `refs.yaml`, and any files matching `source_*.txt`. An executor is `recorded:<answers file>` or a model the runtime can reach.
5. Version. Graph version 0.2, 11 steps and 10 transitions, checked with `python3 vg.py check graphs/citations.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
