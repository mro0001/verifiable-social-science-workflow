# AI sessions of {{project}}

This folder lists every AI session that touched the project {{project}}, {{sessions}} in all, and {{contributing}} of them led to an AI contribution in the final verification reports. A session touched the project when it ran in the project's folder or when one of its tool calls read, edited, or wrote a file inside it. A session that made a contribution in the final reports is listed too, wherever it ran. The audit layer wrote the folder with `python3 -m audit_layer write-out session-index`.

## What the index holds

- `sessions.csv`, one row for each session.
- `index.html`, the same rows on one page, with a search box.
- One page for each session, named by its public id.
- For each session, its public id, its start and its length in minutes, the harness and its version, the models that answered in it, and, for a subagent, the public id of the session that started it.
- Its tool calls counted by verb, and the project files it read, edited, and wrote, each named relative to the project folder.{{files_note}}
- The sha256 and the size in bytes of its transcript.
- The title, gist, summary, and keywords a model wrote for the session. Each session marks them as written by a model, and as not reviewed by the author unless a person reviewed them. {{model_note}}
- The session's AI contributions that reached the final verification reports. Each has a reference id, the stream and the item, such as `citations/r02`. The stream's report and results file name the same item with the same public id. Beside each is the run of the results file and the decision recorded for the item, approved, held, not yet decided, or needs no decision.

## What the index does not hold

- No transcript text, prompt, or tool output. The transcripts stay private.
- No file outside the project named in the file fields, the project files read, edited, and written. Such files are counted and never named.
- No full path in the file fields.
- The title, gist, summary, and keywords a model wrote are not held to this. They may name other files and full paths, and in them only the home folder's path and the terms on the author's list are replaced.
- No harness's own id for a session. A public id is S followed by the first 12 hex characters of the sha256 of that id, which cannot be turned back into it.

## Checking a transcript against its checksum

A transcript shared later can be checked against its session's row. Its sha256 must equal the row's `transcript_sha256`, and its size in bytes the row's `transcript_bytes`.

```
shasum -a 256 TRANSCRIPT
wc -c < TRANSCRIPT
```

The session's public id can be worked out from the session id the transcript names. It is S followed by the 12 characters this prints.

```
printf '%s' 'SESSION ID' | shasum -a 256 | cut -c1-12
```

The checksum is that of the transcript as the audit layer last stored it.

## Searching the index

GitHub shows `sessions.csv` as a table with a search box. [index.html](index.html) shows the rows on one page with a search box and a checkbox, "Only sessions with an AI contribution in the final reports". It opens in a browser from disk, and from GitHub Pages when the repository publishes this folder.

## Sessions

{{table}}
