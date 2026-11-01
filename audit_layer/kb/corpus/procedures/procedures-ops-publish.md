---
id: procedures-ops-publish
title: Check a verification repository before it is published
source: verification_procedures/graphs/ops_publish.yaml
source_commit: sha256:04f4c328147e
updated: 2026-10-31
group: PROCEDURES
---

# Check a verification repository before it is published

Check a folder written by python3 -m features publish build before it goes public: that it holds no private file or text, that every number its README shows still comes from its results files, and that each research product rebuilds from it. The procedural graph system runs it with the command below, so a session finds it here and does not carry out its steps by hand.

1. Purpose. Check a folder written by python3 -m features publish build before it goes public: that it holds no private file or text, that every number its README shows still comes from its results files, and that each research product rebuilds from it.
2. Triggers. The scholar asks to check a verification repository before it is published. A folder written by publish build is about to be published.
3. Steps. 5 steps, in the order the runtime runs them, each only when a transition into it fires.
   - `publish_settings` (tool step) Read the settings file, fill each missing field with its default, and block on a value of the wrong kind or a workflow folder that is not an absolute path.
   - `publish_files` (tool step) Scan every file in the repository and in each archive it holds, and block on a private folder, a run folder, a database, a credential-like name, an archive that cannot be scanned, a file too large, an email address, a home folder path on a Mac, Linux, or Windows machine or a temporary folder, an excluded folder, a key, a name from the settings, a raw id of an indexed session, an author named in an Office file, a tar header that names its maker, or a file a .gitignore in the repository would hide from git.
   - `publish_counts` (tool step) Recount every number the manifest records from the results files, the ledgers, the numbers file, the references, and the session index in the repository, and block on a count that differs, a generated page changed after it was assembled, or a file missing from the repository or not listed in its manifest.
   - `publish_rebuild` (tool step) Rebuild each research product with make from a copy of the repository's project folder, dated by its latest build, and block when make fails or the new build's text differs from the latest one.
   - `publish_report` (tool step) Write a report with the settings, the file scan, the recount, and the rebuild.
4. Run command. From the `verification_procedures` folder, run `python3 vg.py run graphs/ops_publish.yaml --run runs/<new run folder> --inputs <inputs folder>`. The inputs folder holds `publish_check.yaml` and `repo.tar`.
5. Version. Graph version 0.1, 5 steps and 6 transitions, checked with `python3 vg.py check graphs/ops_publish.yaml`.

## Consult also

- guidelines-authoring-procedures - to write a new procedure or revise this one.
