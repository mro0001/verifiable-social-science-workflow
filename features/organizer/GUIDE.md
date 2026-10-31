# Project organizer guide

The project organizer helps a scholar keep a project's files, builds, and past AI sessions in order as the work grows. An AI session in the scholar's harness reads the project's inventory and writes a proposal. The organizer checks the proposal, and the scholar applies it. Every applied change goes into a journal with the bytes of each changed file before and after, so any change can be undone. The organizer never deletes. It moves a file, adds an archive line to an older draft, or marks an item, and nothing else.

This guide is for the scholar and for an AI session working in the scholar's harness. The organizer itself calls no model. The AI's part is the proposal file.

## Before the first run

System setup must have run once, as the pipeline setup guide says, since the organizer reads `system.yaml` in the features home to find the workflow's folder and the audit home. Run each command from the workflow's folder, the folder that holds `features/`, `ospipe/`, and `audit_layer/`. From any other folder, put the workflow's folder on `PYTHONPATH` first, as in `PYTHONPATH=/path/to/workflow python3 -m features organize log ~/research/survey_study`. A features home other than the default is named with `--home` on the scan, check, apply, and undo commands.

## 1. Scan the project

```
python3 -m features organize scan ~/research/survey_study
```

The scan writes `.organizer/inventory.json` in the project folder and changes no project file. The inventory lists each file with its kind and whether it is protected, each build with its ledger row, and each AI session that ran in the project or changed its files, read from the audit records without changing them. Its `inventory_id` names the state of the project the scan saw.

A file's kind is one of these. A `canonical` file is a product's one source, named in the build file. A `verification` file holds a verification result. A `build_input` is the build file, the numbers manifest, the references, the pipeline, parameter, and acquisition files, or a file a build names. A `declared` file is one the pipeline or the acquisition record names. An `archived` file is an older draft with an archive line. A `lookalike` is a markdown file with no archive line that reads as a canonical source, by its title or its file name. A `notes` file lies under `notes/`. Any other file is `other`. Canonical sources, verification results, build inputs, and declared files are protected, and so is any file named `author_draft.md`, since the prose and references procedures read it as the author's own earlier text.

## 2. Write a proposal

An AI session reads `.organizer/inventory.json` and writes its proposal as a new file in `.organizer/proposals/<YYYY-MM-DD>_<n>.yaml`, with the day's date and a number counting that day's proposals, such as `.organizer/proposals/2026-10-29_1.yaml` for the first one written on that day.

- Copy `inventory_id` from the inventory exactly as it is.
- Name who proposed the changes in `proposed_by`, as `ai:<harness>:<session id>` for an AI session, such as `ai:claude_code:` followed by the session's id, or `scholar:<name>` for the scholar.
- Give each change an `id`, an `op`, and a `reason` the scholar can read. The `op` is one of three.
- A `move` has `path` and `to`. It moves a file that is not protected to a new path inside the project that does not exist yet. It never moves a file into a builds folder, `verification/`, `.organizer/`, or `.git/`.
- An `archive_line` has `path` and `superseded_by`. It adds the line `> ARCHIVE <date>: superseded by <canonical>` as the first line after the front matter of a look-alike, so no one mistakes the older draft for the current one. The `superseded_by` is the canonical source it reads as.
- A `mark` has `item_kind`, `item`, `mark`, and `value`. The `item_kind` is `file`, `build`, or `session`. The `item` is a file's path in the project, a build as `<product>/<version>` such as `manuscript/v001`, or a session's harness session id. The `mark` is `unused`, `superseded` (with the replacing item as `value`), `belongs_to` (with the project folder as `value`), or `note` (with the note as `value`). An `unused` mark needs no `value`. A mark changes no project file. Marks are kept in `.organizer/marks.yaml`, since builds and audit records are never changed.

Never propose a deletion. To set an item aside, mark it `unused` instead. A proposal with a `delete`, `remove`, or any other operation the organizer does not have is refused. Mark `author_draft.md` with a `note` rather than archiving it, since it is protected.

Here is one complete proposal.

```yaml
schema: organizer-proposal
schema_version: 1
proposed_by: "ai:claude_code:5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
inventory_id: "copy the inventory_id from .organizer/inventory.json here"
changes:
  - id: c1
    op: archive_line
    reason: An older draft whose file name holds the manuscript's name.
    path: drafts/manuscript_old.md
    superseded_by: manuscript.md
  - id: c2
    op: move
    reason: A loose file at the top of the project.
    path: stray.txt
    to: misc/stray.txt
  - id: c3
    op: mark
    reason: An early draft that is already archived and no longer read.
    item_kind: file
    item: drafts/early.md
    mark: unused
```

## 3. Check the proposal

```
python3 -m features organize check ~/research/survey_study ~/research/survey_study/.organizer/proposals/2026-10-29_1.yaml
```

The check scans the project again and changes nothing. It prints each change and then each problem, or `No problems`. When the project changed after the AI read the inventory, the check refuses the whole proposal, so scan again and write a new proposal. An AI session runs the check, shows the scholar what it printed, and fixes its proposal until the check finds no problem.

## 4. Apply it, on the scholar's word only

```
python3 -m features organize apply ~/research/survey_study ~/research/survey_study/.organizer/proposals/2026-10-29_1.yaml --by "Your Name"
```

Only the scholar applies a proposal, and an AI session leaves this command to the scholar's word. To leave out a change, delete its lines from the proposal file before applying it. Apply runs the check first and applies nothing when it finds a problem. Then it applies the changes in order, journals each one in `.organizer/journal.jsonl` as `j0001`, `j0002`, and so on, keeps the bytes of each file an archive line changes in `.organizer/originals/`, and writes `.organizer/marks.yaml` and a fresh inventory.

## 5. Read the log and undo a change

```
python3 -m features organize log ~/research/survey_study
```

The log prints each journal entry with its time, who applied it, who proposed it, the operation, the item, the reason, and which entry undid it, then the current marks.

```
python3 -m features organize undo ~/research/survey_study j0002 --by "Your Name"
```

Undo reverses one entry while the project is still as that entry left it. It moves a moved file back, writes an archived file's original bytes back, or drops a mark, and it journals the undo as a new entry. When the file changed since, undo refuses and says what changed. An entry is undone once, and an undo is not undone. To redo a change, scan again and apply a new proposal.

## What the organizer never does

- It never deletes or overwrites a file. Every file's bytes before a change stay in the project or in `.organizer/originals/`.
- It never moves a protected file, and never changes a build, anything in a builds folder, or anything in `verification/`.
- It never changes the audit records. It reads them only, and session marks stay in `.organizer/marks.yaml`.
- It never applies a proposal written from an older inventory.
- It never calls a model, and it applies nothing until the scholar runs the apply command.
