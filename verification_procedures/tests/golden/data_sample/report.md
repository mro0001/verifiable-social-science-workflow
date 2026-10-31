# Data verification, the final numbers

This report lists each number in the final build with the output and the script that produce it, for the scholar to verify. A script or a parameter is the AI's when the record of the AI's file edits shows that an AI tool call changed it. Each AI change to a script is shown with its text before and after and the reason the record gives, and each parameter the AI set is listed. A number that comes from AI work waits for the scholar to approve or hold it. A program notes each AI change with no recorded reason. No model judges anything. The Reproducibility section reruns the pipeline from the raw data in an empty folder and gives each number's match or mismatch, which covers every number whoever wrote its code.

No record of the AI's file edits was given, so nothing is marked as the AI's and every number waits for the scholar. Numbers 10 (from AI work 0). AI changes to scripts 0 (with no recorded reason 0). Parameters the AI set 0. Steps 1, raw files 1.

## Summary

- Blocking: 0
- Warnings: 0
- Notes: 3

## Problems

None.

## Numbers

Each number names the output it is read from and the script of the step that writes that output. AI work lists the AI changes and the parameters the AI set in that script, the scripts of the earlier steps it reads from, and the helpers.

| Key | numbers.yml | Output | Script | AI work |
|---|---|---|---|---|
| definition.distinct | 10 | next_word_results.json | s1_results.py | not known, no record |
| definition.top_pct | 30.0 | next_word_results.json | s1_results.py | not known, no record |
| definition.top_word | meticulous | next_word_results.json | s1_results.py | not known, no record |
| model | mistral-small:22b | next_word_results.json | s1_results.py | not known, no record |
| n_per_condition | 60 | next_word_results.json | s1_results.py | not known, no record |
| none.distinct | 16 | next_word_results.json | s1_results.py | not known, no record |
| none.top_pct | 30.0 | next_word_results.json | s1_results.py | not known, no record |
| none.top_word | proactive | next_word_results.json | s1_results.py | not known, no record |
| question | The ideal candidate for this internship is someone who is | next_word_results.json | s1_results.py | not known, no record |
| temperature | 1.0 | next_word_results.json | s1_results.py | not known, no record |

## AI changes to scripts

Each change below is one an AI tool call made, as the record of the AI's file edits gives it. An AI change made through a shell command is not in the record and is not shown here.

None.

## Parameters the AI set

Each parameter below is one whose value an AI tool call set in params.yaml, as the record gives it, with the scripts that read it.

None.

## Scripts

Each step script and helper, with the AI changes the record gives for it. Docs ok covers the docstring sections and the parameter scan of the script.

| Script | Step | AI changes | Docs ok |
|---|---|---|---|
| s1_results.py | results | none | yes |
| params_io.py | helper | none | yes |

## Reproducibility

The pipeline was rerun from the raw data in an empty folder. This covers every number, whoever wrote its code, and a number that does not reproduce is a problem to fix. The steps of the rerun follow.

| Step | Script | Reproduces | Records ok | Stderr |
|---|---|---|---|---|
| results | s1_results.py | yes | yes | clean |

Each number against the rerun follows.

| Key | numbers.yml | Rerun | Agrees |
|---|---|---|---|
| definition.distinct | 10 | 10 | yes |
| definition.top_pct | 30.0 | 30.0 | yes |
| definition.top_word | meticulous | meticulous | yes |
| model | mistral-small:22b | mistral-small:22b | yes |
| n_per_condition | 60 | 60 | yes |
| none.distinct | 16 | 16 | yes |
| none.top_pct | 30.0 | 30.0 | yes |
| none.top_word | proactive | proactive | yes |
| question | The ideal candidate for this internship is someone who is | The ideal candidate for this internship is someone who is | yes |
| temperature | 1.0 | 1.0 | yes |

Each raw file's checksum, recorded at collection and as it is now, follows.

| File | At collection | Now | Agrees |
|---|---|---|---|
| next_word_counts.json | sha256:91d7bb242135199f7fa4aa51ee40695105308198df9944828244d4cc3c4aa42d | sha256:91d7bb242135199f7fa4aa51ee40695105308198df9944828244d4cc3c4aa42d | yes |

The parameter record follows, assembled from the records the rerun wrote and not from the committed copies.

| Param | Value recorded | params.yaml | Agrees | Step | Script |
|---|---|---|---|---|---|
| share_digits | 1 | 1 | yes | results | s1_results.py |
| top_words | 3 | 3 | yes | results | s1_results.py |

The model records follow.

None.

## Notes

- attribute_ai / file_edits.yaml: no record of the AI's file edits was given, so no script or parameter is marked as the AI's and every number waits for the scholar
- check_params / params_io.py:L106: literal declared not a parameter
- check_params / s1_results.py:L81: literal declared not a parameter
