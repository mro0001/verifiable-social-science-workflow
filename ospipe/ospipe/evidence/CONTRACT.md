# evidence Contract

Purpose. Writes what a research product's verification found and left open, read from the project's own files. The list of unverified claims names each stream that is not verified as a whole and each item still waiting for the scholar's approval. The citation evidence file gives each citation's check, the scholar's decision, and the session that introduced it, kept in a file since there is no links table (appendix Table A2, "Citation evidence file and the list of unverified claims", and A2.5 "Verification reports").

## Produces

- `unverified_claims(verification_dir, source_path, numbers_path) -> List[Unverified(stream, item, state, summary)]`, in `unverified.py`.
  - It reads each stream's results file through `build.verification.stream_detail`, the build's own rule, so the streams it lists are exactly the streams the build flags.
  - A stream whose state is `missing`, `unreadable`, or `out_of_date` gives one entry with item `-` and an empty summary.
  - Each open item gives one entry with the item's `id` and the state `held` or `undecided`. An out-of-date stream also lists its open items, after its own entry.
  - Entries come in the stream order prose, citations, data, build, and each stream's items in the results file's order.
  - `summary` is the first non-empty text field among the stream's `SUMMARY_FIELDS`, with its spaces and line breaks run together into single spaces, cut to 120 characters. It is empty when no field has text.
- `SUMMARY_FIELDS`, the item fields tried for each stream, in order.
  - `citations` tries `summary`, `reason`, `sentence`. The last two are fields a references run writes in each item, printed from a run on the test story (`id`, `citekey`, `category`, `origin`, `moved`, `sentence`, `reference`, `reference_check`, `passage`, `location`, `verdict`, `reason`, `second_verdict`, `disputed`, `access`, `issues`, `fix`, `needs_decision`).
  - `prose`, `data`, and `build` try `summary`. On the test story these streams write no items yet, and `summary` is the key every stream's items carry once their item lists are filled.
- `entry_line(entry)`, the printed line `<stream> <item> <state>` followed by `, <summary>` when there is one. `count_line(entries)`, the line `<n> unverified`. `markdown_list(entries)`, each line as a markdown list item, a blank line, and the count line.
- `citation_evidence(verification_dir, citation_log=None) -> dict`, in `citations.py`.
  - It reads `<verification_dir>/citations.json`. A missing file, bad JSON, a `schema` and `schema_version` other than `verification-results` and 1, or a file without the results file's shape (a text `run_id`, lists of items and decisions, each item with a text `id` and a true or false `needs_decision`, each decision naming its `item`) raises `EvidenceError`.
  - It returns, in this key order, `schema` (`citation-evidence`), `schema_version` (1), `results_file` (the path read, as text), `results_sha256` (the hex sha256 of the file's bytes), `run_id`, `procedure_version`, and `items`.
  - Each item, in the results file's order, holds in this key order `id`, `needs_decision`, `decision`, `by`, `at`, `introduced_by`, `session`, and `item`. `decision` is `approved`, `held`, or `undecided` by `build.verification.latest_decision` on the file's `run_id`, or `not needed` when the item needs no decision. `by` and `at` come from the decision that counts, and are empty otherwise. `introduced_by` and `session` come from the citation log's entry for the item's citekey, and are empty without one. `item` is the results item copied unchanged.
  - `citation_log` is a file in the audit layer's written-out shape, a `citations` mapping from citekey to an entry with `introduced_by`, `draft`, and `session`. A named log that is missing, is not YAML, or has another shape raises `EvidenceError`.
- `CITEKEY_FIELD`, `citekey`, the results item field that holds the citekey, printed from a references run on the test story.
- `evidence_yaml(evidence)`, the evidence file as YAML with keys in their order, the same text for the same inputs.
- `EvidenceError(ValueError)`.
- `python3 -m ospipe unverified` and `python3 -m ospipe citation-evidence`, in the root contract.

## Frozen

- The entries follow the build's verification rule (`build/CONTRACT.md`, `stream_status`). The list never calls a stream verified that the build flags, and never lists one the build does not flag.
- Only the project's files are read, `<verification_dir>/<stream>.json`, the files whose checksums a stream covers, and the citation log. No check is run, no database is queried, and nothing is written but the file `--out` names.
- The `Unverified` fields and the states `missing`, `unreadable`, `out_of_date`, `held`, `undecided`.
- The evidence file's keys and their order, its schema name and version, and the decision words `approved`, `held`, `undecided`, `not needed`. Decisions follow the build's rule, so an approval on another run does not count.
- The same inputs give byte-identical output.

## Soft

- The summary fields, the 120 character cut, the line formats, and refusal wording.
- As built. A summary field that is not text is passed over. Without `--verification-dir` the `unverified` command reads `verification` beside the source, the slice's default for the results folder. `citation-evidence` reads `verification` in the folder it runs in, and the citation log `audit/citation_log.yaml` there when that file exists. A citation log that is empty reads as no entries. Values from the log and from decisions are written as text.

## Consumers

- root calls these functions for `python3 -m ospipe unverified` and `python3 -m ospipe citation-evidence`.
- replication calls them in `replication.write_ship_files`, which writes the folder's `unverified_claims.md` and `citation_evidence.yaml`.

## Fixture

- `fixture.py`. Synthetic results files in the shape of the build status tests' files, a citations file with three fake reference rows and the item fields a references run writes, one item each for prose, data, and build, a fake source text and numbers file, a citation log in the audit layer's written-out shape, and a citations file with one item of each decision kind (approved, held, undecided, the author's warrant, and an approval on an older run).
- `tests/test_evidence_unverified.py` and `tests/test_evidence_citations.py` write them into temporary folders.

## Status

- realized

## Not in this module

- Any change to how a build is flagged. Running a check. Whether results are current, in the evidence file (the list covers it). Streams other than citations in the evidence file. Any database. A stream with no results file is listed as a whole, since without the verification layer nothing names its claims.
