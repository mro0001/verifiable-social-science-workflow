# Publishing guide

Publishing turns a verified project into a verification repository that anyone can read and rebuild. The repository holds a `README.md` with the figure and the table of what each report found, a `docs/` folder that explains how to read the reports, the record behind them, and how to rebuild, and a `project/` folder with the project's files, every report, and the public index of the AI sessions. Every number the repository shows comes from the project's results files and ledgers, never from typed text.

Publishing has two commands and two procedures. `publish plan` shows what would be published and writes nothing. `publish build` writes the repository and the inputs of the two procedures. The scholar runs the ops_publish check on what `publish build` wrote before making anything public. The ops_github procedure then puts the repository on GitHub, and it only plans until its settings file says `apply: true`.

This guide is for the scholar and for an AI session working in the scholar's harness. The commands call no model.

## Before the first run

System setup must have run once, as the pipeline setup guide says, since publishing reads `system.yaml` in the features home to find the workflow's folder, the audit home, and the folders the scholar excluded. The project must be laid out by the workflow, with a `Makefile` that names each research product, and verified, with each stream's results file where the build reads it, such as `verification/<product>/prose.json`.

Run each command from the workflow's folder, the folder that holds `features/`, `ospipe/`, and `audit_layer/`. From any other folder, put the workflow's folder on `PYTHONPATH` first, as in `PYTHONPATH=/path/to/workflow python3 -m features publish plan ~/research/survey_study`. A features home other than the default is named with `--home`, as in `python3 -m features publish plan ~/research/survey_study --home ~/other_features_home`.

## 1. Plan the repository

```
python3 -m features publish plan ~/research/survey_study --answers ~/research/survey_publish.yaml
```

The plan writes nothing and runs no session index. It prints each product with its latest numbered build, each report with where it comes from, the streams that have no results file yet, how many project files would be copied, each file or folder left out with the reason, where the session index would come from, and the notes. With `--json` it prints the same content as one JSON object, for an AI session, as in `python3 -m features publish plan ~/research/survey_study --json`.

Each report's results file is always the project's own, such as `verification/manuscript/prose.json`, since that is the file the build read. The report beside it comes from the run folder of the same run id when that run's results match the project's, from the project's own report folder when its results match, or else is left out with a note, and the README then links the results file. The runs folder is `--runs`, else `runs` in the answers, else `verification_procedures/runs` in the workflow's folder, as in `python3 -m features publish plan ~/research/survey_study --runs ~/research/survey_study_runs`.

## 2. Write the answers file

Every field is optional. A field this command does not use is listed under the notes and is not a stop.

- `title`, the README's heading. By default it is "Verification reports for" and the project folder's name.
- `summary`, the README's first paragraph. By default it says which documents AI sessions helped write and how the workflow checked them. A sentence on the scholar's decisions always follows it.
- `repo_url`, the web address of the repository, for its clone line. Left out, the README says `URL-OF-THIS-REPOSITORY` and a note says so. An address like `git@github.com:owner/repo.git` is written as `https://github.com/owner/repo`, since the clone line is for anyone.
- `workflow_url`, the web address of the workflow, by default its public repository.
- `workflow_folder`, the folder `git clone` makes for the workflow, by default the last part of `workflow_url`. The published `Makefile` looks for the workflow at `../../<workflow_folder>`.
- `runs`, the folder that holds the run folders, a full path starting with / or ~.
- `exclude`, a list of paths inside the project to leave out, a folder ending in `/`.
- `harness_names`, the names shown for each harness, such as `claude_code: Claude Code`.
- `notes`, the scholar's own paragraphs, under any of `prose`, `references`, `data`, `build`, and `record`, placed in the docs as given.
- `files`, a description of a file or folder at the top of the project, placed in `project/README.md` in place of the built-in one.
- `anonymous`, true by default, so the repository does not name the scholar. The scholar's full name in `system.yaml` is then always withheld and looked for, and so is each word of it with three or more letters that does not end with a period, unless `scrub_terms` chooses the words. With `anonymous: false` the repository may name the scholar, so nothing is scrubbed unless `scrub_terms` names it, and the check looks only for its own `terms`. The manifest records which it is.
- `sessions`, the session index. `skip` true publishes no index. `also_folders` lists the full paths of folders the project's work was done in before it moved. `no_summaries` true leaves out the model-written title, gist, summary, and keywords of every session. `withhold` lists the public ids of sessions whose model-written fields are left out. `scrub_terms` lists names written as [withheld] in the model-written fields and the file names the index lists, each as a whole word. Left out, it is the scholar's name and its words when `anonymous` is true, and nothing when it is false. Given, it chooses which words of the name are withheld, the full name is added when it is not in the list, and a note says how many words of the name the list leaves out.
- `check`, the settings of the ops_publish check. `terms` lists names the check looks for in every file, with `scrub_terms` added when `anonymous` is true. `allow` lists what the check may accept, each an exact text the check showed or a mapping with `text`, `path`, or both, where `path` is a pattern over the file's path in the repository. `max_file_mb` (100) blocks larger files, `warn_file_mb` (50) warns on them, and `rebuild` (true) rebuilds each product in a copy.
- `github`, the settings of the ops_github procedure. With it, `publish build` writes that procedure's inputs. `repo_name` is required. `create_with` is `none` (the default, which needs `remote_url`, the remote the repository is pushed to) or `gh` (which needs `owner`, and makes the repository with the GitHub command line tool). `visibility` is `private` (the default) or `public`. `branch` is `main` by default, and `message` is the first commit's message.
- `phase_runs`, the run id of each data phase report, by product or group, such as `manuscript: {data_analysis: manuscript_analysis_2}`, when the run folder's name does not say which phase it ran.

```yaml
# The answers file for publish plan and publish build
title: Who Answers the Survey, verification reports
summary: AI sessions helped write the manuscript. Each report lists the items for the scholar to approve or hold.
repo_url: https://github.com/example-scholar/survey-verification
workflow_url: https://github.com/mro0001/verifiable-social-science-workflow
workflow_folder: verifiable-social-science-workflow
runs: ~/research/survey_study_runs
exclude:
  - drafts/
  - interviews.csv
harness_names:
  claude_code: Claude Code
notes:
  prose: The scholar wrote the discussion section by hand.
  record: Sessions before the project moved are in the earlier folder.
files:
  tools/: Scripts that make the figures
anonymous: true
sessions:
  skip: false
  also_folders:
    - ~/research/survey_study_old
  no_summaries: false
  withhold:
    - S0123456789ab
  # The full name is always withheld. List each word of it to withhold alone, and
  # leave out a word that is also an ordinary word, as Scholar is.
  scrub_terms:
    - A. Scholar
check:
  terms:
    - A. Scholar
  allow:
    - path: project/styles/*.csl
  max_file_mb: 100
  warn_file_mb: 50
  rebuild: true
github:
  repo_name: survey-verification
  owner: example-scholar
  visibility: private
  create_with: none
  remote_url: git@github.com:example-scholar/survey-verification.git
  branch: main
  message: First commit of the verification repository
phase_runs:
  manuscript:
    data_analysis: manuscript_analysis_2
```

### An anonymous repository

With `anonymous` true, which is the default, no file in the repository may hold the scholar's full name, and the check blocks each file that does, also when the name is written with its words joined, as in a web address or a handle, or in another Unicode form or encoding. When `scrub_terms` is left out, the same holds for each word of the name with three or more letters; when it is given, for the words it lists. The name the scholar gives `vg.py decide` with `--by` is copied into every results file and report, so in an anonymous repository the scholar decides each item with a label that is not a term, such as "the scholar":

```
python3 vg.py decide --run runs/survey_prose --item c01 --approve --by "the scholar"
```

The session index writes each scrub term as [withheld], in any case, where it stands as a whole word, so a short word of the name is not taken out of a longer word, such as Man out of manuscript. The check matches the terms the same way, so a word of the name that is also an ordinary word, such as Read, Young, or Scholar, would block ordinary text, the pages publish writes among it. The build stops when such a word is in a page it writes or in the session index, and says which word; then give `scrub_terms` to choose the words, such as the full name and the given name, and the full name is still withheld. The check reads every file's path as well as its text, so a project file named for the scholar is found too; leave it out with `exclude`, or accept it with an `allow` entry when its name may be shown. To publish a repository that names the scholar, set `anonymous: false`.

## 3. Build the repository

```
python3 -m features publish build ~/research/survey_study --out ~/research/survey_public --answers ~/research/survey_publish.yaml
```

The build writes three folders. `~/research/survey_public` is the repository, with a `.gitignore` at the top that keeps the Finder's `.DS_Store` files out of a commit. `~/research/survey_public.check` beside it holds `publish_check.yaml`, the check's settings, `repo.tar`, the repository packed the same way every time, and `left_out.json`, the full list of what was left out. `~/research/survey_public.github` holds `github.yaml` and `project.tar`, only when the answers have a `github` block. The two inputs folders stay on this machine.

Into `project/` go the project's files, byte for byte. The one change is the `Makefile`'s `WORKFLOW` default, which becomes `../../<workflow_folder>`, or, in a `Makefile` that names ospipe's folder on this machine, a `WORKFLOW` line and an `OSPIPE` line that uses it. When a `Makefile` line still names a folder on this machine, the build stops. Left out are the `audit/`, `sources/`, `notes/`, `ship/`, and `sessions/` folders at the top, whatever the case of their names, version control data, the workflow's homes, run folders, folders an editor keeps for itself, the files and folders where AI tools such as aider, SpecStory, and Cursor keep their saved chats, history files and saved R workspaces, an `.envrc` of settings, logs, links, a folder this account cannot read, with a note, what the project's `.gitignore` files, those of the folders above it, its repository's `info/exclude`, and git leave out, and the `exclude` list. The build asks git, read only, which files it ignores, and when git cannot run it says so in a note and applies the rules it reads itself. The session index is written fresh from the record into `project/sessions/` with the audit layer's `write-out session-index`. A failing index stops the build, and `sessions: {skip: true}` publishes without it.

The build plans every file of the three folders before it writes any, and every stop comes before the first write; only a write that fails part way, as on a full disk, can leave part of a build, and the message says so. It also stops when a run was decided after its results reached the project, since the README would count other decisions than the report shows, so run `handoffs/results_to_pipeline.py` again first, and when a line of the project's `.gitignore` would hide a page, the session index, or a report from git. To build again after changing the project or the answers, run the same command. The build replaces an earlier build in the same folder, removing only the files its manifest, `docs/publish_manifest.json`, lists, and it stops when the folder holds a file it did not write or a file changed since it was written. A top-level `.git` folder is kept.

## 4. Check it before it goes public

Run the ops_publish check on what the build wrote before making anything public. The build prints its run command. From the workflow's `verification_procedures` folder it is

```
python3 vg.py run graphs/ops_publish.yaml --run runs/survey_publish_check --inputs ~/research/survey_public.check
```

The check looks in every file for private files and text: email addresses, home folder paths, keys, raw session ids, the `terms`, and the folders the scholar excluded. It reads what a file is from its first bytes as well as its name. It opens an uncompressed `.tar` and scans it member by member, headers included, and opens Word, PowerPoint, Excel, and OpenDocument files part by part, an Office file inside one included. It reads the text and metadata of images and PDF files, but not what they show, so it lists each one for the scholar to look at. Any other archive or compressed file, such as a `.zip`, `.tar.gz`, `.rds`, or `.RData`, and an older Office file such as a `.doc`, blocks as not scanned until it is removed, unpacked, or accepted with an `allow` entry by path once the scholar has checked it, such as `{path: project/replication.tar:*}` for what the scan found inside a tar. It recounts every number the manifest records from the results files in the repository, checks that no page was changed after it was written, and with `rebuild` true rebuilds each product in a copy and compares it with its latest build. Read its report in the run folder, `files/report.md`. Fix each blocking finding in the project or the answers and build again, or, for a finding that is expected, add an `allow` entry and build again. A citation style file, `.csl`, often names its authors by their email addresses, so it usually needs a path entry like the one shown above. Pandoc writes its options, such as the bibliography, into each Word build's custom properties, and the check lists them as a note.

## 5. Put it on GitHub

When the check finds no blocking problem, the ops_github procedure puts the repository on GitHub. The build prints its run command. From the `verification_procedures` folder it is

```
python3 vg.py run graphs/ops_github.yaml --run runs/survey_publish_github --inputs ~/research/survey_public.github
```

The procedure only plans until `github.yaml` in the inputs folder says `apply: true`. The build always writes `apply: false`. Read the plan in the run's report, and only then set `apply: true` in `github.yaml` and run the procedure again with a new run folder. The repository is private unless the answers say `visibility: public`.

## What publishing never does

- It never writes in the project folder or changes a project file, and it writes only the repository folder and the two inputs folders beside it. The audit layer's session index opens the audit store, which can add its field definitions to an older store, wherever the audit home is.
- It never lists or opens a folder the scholar excluded, whether `system.yaml` or the audit home's settings name it. It stops when the project, an `also_folders` entry, the runs folder, or an output folder lies inside one, or when an output folder holds one. It also stops when an excluded folder lies inside the project or an `also_folders` entry, since the session index could name the files in it that a session read, unless `sessions: {skip: true}` leaves the index out. The folder is then left out of the copy unopened.
- It never publishes the record, its transcripts, the raw session ids, the source texts, or the scholar's notes. The session index names each session only by its public id.
- It never types a number. Each number comes from the results files and the ledgers, and the check recounts each one.
- It never overwrites a folder it did not write, and it never removes a file its manifest does not list.
- It runs git only to ask, read only, which project files git ignores. It never commits, makes a repository, pushes, or makes anything public. The ops_github procedure does that, and only once `apply: true` is set.
- It never calls a model.

## For an AI session publishing a project

Write the answers file from what the scholar says, then run `publish plan` with `--json` and show the scholar what it printed, above all what is left out and the notes. Run `publish build` only when the scholar agrees, then run the ops_publish check with the command the build printed, and show the scholar its report. Never set `apply: true` in `github.yaml` and never make a repository public on your own; leave both to the scholar's word. Never list, open, or search inside an excluded folder, and never put what one holds into the conversation. Never edit a page the build wrote, since the check finds a changed page, and every number must come from the results files.
