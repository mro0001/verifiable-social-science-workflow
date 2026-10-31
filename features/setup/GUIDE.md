# Pipeline setup guide

Pipeline setup connects the scholar's software and AI harness to the workflow and lays out a reproducible project, so the project builds with `make` on the first try. It has two commands. System setup runs once per scholar. Project setup runs once per project. A scholar can run both in a terminal, or an AI session in the scholar's harness can run them from the conversation with an answers file.

## Where to run the commands

Run each command from the workflow's folder, the folder that holds `features/`, `ospipe/`, and `audit_layer/`. From any other folder, put the workflow's folder on `PYTHONPATH` first, as in `PYTHONPATH=/path/to/workflow python3 -m features setup system --answers system_answers.yaml`.

With an answers file, setup asks nothing. Without one, setup asks each question in the terminal. System setup with no answers file and no terminal refuses and names the fields. Project setup with neither uses the defaults below.

## System setup, once per scholar

```
python3 -m features setup system --answers system_answers.yaml
```

The features home is `--home`, else the `FEATURES_HOME` variable, else `~/.workflow_features`. The audit home is `--audit-home`, else the `AUDIT_HOME` variable, else `~/.audit_layer`. A second scholar or a test can keep its own homes, as in `python3 -m features setup system --home /tmp/features_home --audit-home /tmp/audit_home --answers system_answers.yaml`.

In a terminal, setup asks in this order. First the folders whose AI sessions must never be recorded, one full path a line, or the word none. Then your name, only when git's settings hold none. Then the model service, the model, and a second model, each skipped with Enter. Last the citation export, and the harness only when none is found.

The answers fields are these.

- `excluded_folders`, a list of folders whose AI sessions are never recorded, such as folders that hold student records. Each is a full path starting with / or ~. It must be given, and `[]` gives none.
- `scholar_name`, the scholar's name as decisions will record it. It may be left out when git's settings hold a `user.name`.
- `model_service`, the web address of the model service that answers the checks' questions, or left out to skip. With it come `model`, the model on that service, and, if wanted, `second_model`, a different model that rechecks doubtful source verdicts.
- `token_limit` and `token_limit_field`, given together, the output limit of each live reply and the field it is sent under, `max_tokens` or `max_completion_tokens`. Left out, each reply may be 4,000 tokens under `max_tokens`.
- `citation_export`, the BibTeX file the scholar's citation manager exports, or empty for none.
- `harness`, `claude_code`, `forgecode`, or `another` for another program. When it is left out, setup takes `claude_code` if Claude Code is found, else `forgecode` if ForgeCode is found, else it records none and says the harness was not found.
- `connect`, yes or no, the answer to the review screen's one question. Left out, it is no.

```yaml
# answers for python3 -m features setup system
scholar_name: Test Scholar
excluded_folders:
  - ~/private_records
model_service: https://models.example.edu/v1
model: example-model
citation_export: ~/library/export.bib
```

System setup checks the software the workflow needs and prints a line to install anything missing, and checks that the workflow's three layers answer. Its first write lists the excluded folders under `excluded_folders` in the audit home's `settings.yaml` with `python3 -m audit_layer excluded add`, which adds and never removes. With no folders it sets up the audit home when it has no settings file. When a model service is given, it writes `provider.yaml` in the connections home again with `python3 -m connections provider set`, never with a key. That replaces the file whole, so when you give no output limit, setup keeps the one an earlier `provider.yaml` names and says so. When `WORKFLOW_MODEL_KEY` is not set, it prints the one line to add to the shell profile. Then it writes `system.yaml` in the features home.

Before writing, setup shows a review screen. It lists what was found and what each finding gets, the defaults, and each change setup would make outside the workflow's own folders, and ends with one question, whether to make these changes. Setup cannot make those changes itself yet. It records the answer as `connect` in `system.yaml` and prints the documents that say how to make each change by hand. With an answers file it asks nothing.

## Project setup, once per project

```
python3 -m features setup project ~/research/survey_study --answers project_answers.yaml
```

The flags give the same answers without a file, and a flag wins over the file. Give `--product` once for each product, as in `python3 -m features setup project ~/research/survey_study --title "Who Answers the Survey" --product manuscript:manuscript.md:docx --product slides:slides.md:revealjs`. The features home is found as for system setup, or named with `--home`, as in `python3 -m features setup project ~/research/survey_study --home /tmp/features_home`.

The answers fields are these.

- `title`, the project's title. By default it is the folder's name.
- `products`, a list of research products, each with a `name`, a `source` file inside the project, and a format `to` that is `docx` for a Word document or `revealjs` for slides. By default the one product is the manuscript, `manuscript.md`, as `docx`. On the command line a product is written `NAME:SOURCE:FORMAT`.
- `citation_export`, the BibTeX file the citation manager exports. By default it is the one in `system.yaml`. An empty value gives none.

```yaml
# answers for python3 -m features setup project
title: Who Answers the Survey
products:
  - name: manuscript
    source: manuscript.md
    to: docx
  - name: slides
    source: slides.md
    to: revealjs
citation_export: ~/library/export.bib
```

Project setup refuses until system setup has written `system.yaml`. It lays out the project's files, copies the notes templates into `notes/`, adds a rule for each product to a new `Makefile`, and adds the rule that copies the citation export to `refs.bib` whenever the export is newer. Then it checks each product's source and prints `make <product>` for each product the build file names. Run `make manuscript` in the project folder to make the first build. Each build is marked unverified for every stream until that stream's results are approved.

Setup runs no git. To add the project to version control on GitHub, use the GitHub procedure, whose run command setup prints.

## What setup never does

- It never installs software. It prints the line to install each missing tool.
- It never overwrites, changes, or removes a file that exists. It lists each file it kept. A `Makefile` that exists is kept and gets no rule. For each product the kept `Makefile` lacks, setup prints the `python3 -m ospipe add-product` line that adds its rule and says the project is not ready. When the kept `Makefile` builds a product from another source or as another format than you answered, or `ospipe products` finds a problem in it, setup prints that, gives no `make` line for the product, and says the project is not ready. The one file it writes again is its own `system.yaml`.
- It never lists or reads inside an excluded folder. Project setup writes only in the project folder named on its command line. Besides that folder it reads only `system.yaml`, the workflow's own files, and the citation export, so neither the project folder nor the citation export should be inside an excluded folder.
- It never makes a commit, starts a repository, or adds a remote.
- It never removes a folder from the audit layer's settings file. It only adds the excluded folders you give.
- It never asks for, prints, or stores the model key. It says only whether `WORKFLOW_MODEL_KEY` is set.

## For an AI session running setup

Write the answers file from what the scholar says, then run the command with `--answers`. For `excluded_folders`, write only the paths the scholar gives. Never list, open, or search inside an excluded folder, and never put what one holds into the conversation. Never ask for the model key or repeat it. Show the scholar what setup printed, including the review screen, each install line, and each later connection, and leave installing software to the scholar.
