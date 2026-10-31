---
id: procedures-ops-github
title: Add a project to version control on GitHub
source: verification_procedures/graphs/ops_github.yaml
source_commit: sha256:9524c72496e9
updated: 2026-10-29
group: PROCEDURES
---

# Add a project to version control on GitHub

Put a project folder under version control and on GitHub, committing only files that are safe to publish, by explicit path, to a private repository unless the scholar chooses public. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Put a project folder under version control and on GitHub, committing only files that are safe to publish, by explicit path, to a private repository unless the scholar chooses public. Run commands only when the settings file says so, and only on the folder the check saw.
2. Triggers. The scholar asks to put a project under version control on GitHub. A project folder that holds research work has no repository yet.
3. Steps. 5 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `github_settings` (tool step) Read the settings file, fill each missing field with its default, and block on a missing folder, a bad repository name, or a missing remote or owner.
   - `github_files` (tool step) List the files in the project snapshot, block on a repository already there, a credential-like name, or a file too large, warn on data in a public repository, and record each file's checksum.
   - `github_plan` (tool step) Plan the commands that start the repository, stage the checked files by path, commit, name the remote, and push, and the .gitignore to write first.
   - `run_commands` (tool step) Run the planned commands in order when the settings file sets apply to true, after checking that the folder still matches its snapshot, and stop at the first failure. Otherwise list them as planned.
   - `report` (tool step) Write a report with the settings, the file counts, and each command with its result.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/ops_github.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `github.yaml` and `project.tar`.
5. Version. Graph version 0.2, 5 steps and 6 transitions, checked with `python3 vg.py check graphs/ops_github.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
