# Live run records of October 8, 2026

This folder holds the records of the seven runs made with live models on October 8, 2026, the runs appendix A5 describes. Each subfolder is one run, kept as the runtime wrote it apart from the changes for blind review given at the end. The runs made the same day with recorded answers are not here, since they are offline runs of the kind A4's commands repeat.

The seven runs are listed below. Every judgment step except the recheck asked the judge, and the recheck asked the second checker. The test files are the build's own synthetic test files, and every input named in a manifest is byte for byte the file of the same name in the folder shown.

| Run folder | Procedure | Test files | Graph version | Judge | Second checker |
|---|---|---|---|---|---|
| `cit_live_clean` | References (`graphs/citations.yaml`) | `fixtures/citations/clean`, 12 files | 0.1 | `qwen/qwen3.5-122b` | `openai/gpt-oss-120b`, named but never asked, since every verdict was supports |
| `cit_live_seeded` | References (`graphs/citations.yaml`) | `fixtures/citations/seeded`, 21 files | 0.1 | `qwen/qwen3.5-122b` | `openai/gpt-oss-120b`, asked 5 times |
| `data_live_clean` | Data (`graphs/data.yaml`) | `fixtures/data/clean`, 17 files | 0.1 | `qwen/qwen3.5-122b` | None |
| `data_live_seeded` | Data (`graphs/data.yaml`) | `fixtures/data/seeded`, 17 files | 0.1 | `qwen/qwen3.5-122b` | None |
| `prose_clean_live` | Prose (`graphs/prose.yaml`) | `fixtures/prose/clean`, 5 files | 0.2 | `qwen/qwen3.5-122b` | None |
| `prose_live` | Prose (`graphs/prose.yaml`) | `fixtures/prose/seeded`, 5 files | 0.1 | `qwen/qwen3.5-122b` | None |
| `prose_live2` | Prose (`graphs/prose.yaml`) | `fixtures/prose/seeded`, 5 files | 0.2 | `qwen/qwen3.5-122b` | None |

Each run folder holds `manifest.json`, `trail.jsonl`, `records/`, `code/`, `prompts/`, `responses/`, `files/`, and `logs/`, the parts the main README of `verification_procedures/` describes under "How a run works". None holds a `results.json`, which the runtime began writing later. Four also hold the `verify.json` written on October 8, and the four seeded runs hold `score.json`.

## Checking a run

Every run verifies under this commit's runtime. `verify` writes `verify.json` and adds a line to `trail.jsonl` in the folder it checks, so copy a folder first and verify the copy. From `verification_procedures/` the commands are these.

```
mkdir -p runs
cp -R live_runs_2026-10-08/cit_live_seeded runs/cit_live_seeded
python3 vg.py verify --run runs/cit_live_seeded
```

`verify` replays each tool step and lists each judgment step. It asks no model and makes no network call. `tests/test_live_runs.py` does the same for all seven runs and expects no failure.

## What stays as recorded

The records are kept as written on October 8, so a few things in them belong to that day.

- Step code. `code/` holds the code each tool step ran on October 8, and `verify` replays that saved code, not the code in `implementations/`. Some of that code has changed since, among it the shared helper `_lib.py`, the report steps, and the reference lookup. A pass shows that the records are intact and that this runtime reads them.
- Graph and contract checksums. Each manifest records the checksums of the graph and contracts of October 8, which differ from the files committed today.
- Empty folders. Git keeps no empty folder, so `prompts/15_draft_fix` and `responses/15_draft_fix` in `cit_live_clean` are absent. That step had nothing to ask, since every verdict was supports.

## Changes for blind review

This copy of the records was prepared for double-blind review. Two things in the seven runs differ from what the runtime wrote on October 8.

- Executor labels. On October 8 each executor was written as the model's name with the name of the model service used that day before it. This copy writes each as `live:` and the model's name, the form this runtime writes for a live executor.
- One recorded path. Each manifest's `inputs_from` gave the absolute path of the test files on the computer that made the run. This copy gives a neutral path that begins `/path/to/repository/`. Nothing reads that field, and the test files themselves are in each run's `files/`.

A personal name was also taken out of one comment in the saved step code of the two references runs. Since `verify` checks each step's files by checksum, every checksum the records give for a file these changes reached was updated to match, including the checksums in record files that list such a file. Nothing else in the records changed, and every run still verifies.
