---
id: capabilities-scholar-trio
title: The scholar-reimagined source trio
source: scholar-reimagined-search
source_commit: sha256:2ef49676cfa5
updated: 2026-10-30
group: CAPABILITIES
---

# The scholar-reimagined source trio

Propose /scholar-reimagined-search, /scholar-reimagined-retrieve, and /scholar-reimagined-read as one pipeline whenever a task needs scholarly sources found, obtained in full text, and read with verifiable quotes. The trio is an option a session can offer, and calling skills such as /ground delegate all source work to it rather than reimplementing search or extraction.

The three stages operate on one shared record set.

1. /scholar-reimagined-search takes a faceted search request covering purpose, search terms by facet, screening criteria, diversity dimensions, and optional known items. It returns Standard Source Records v2 with retrieval_status set to discovered and initializes the session bundle.
2. /scholar-reimagined-retrieve obtains full text for the records and updates them in place through the retrieval status vocabulary, which includes retrieved, partial, paywalled, and cannot_locate. It writes a retrieval worksheet and summary into the bundle.
3. /scholar-reimagined-read extracts content from retrieved records, with one model reading and another judging, and writes one extraction JSON per source, plus logs.

The bundle is a scholar_session directory named for the session and created inside the calling skill's workspace. It holds session.yaml, source_records.yaml as the single evolving record set that all three stages update, and subdirectories for search logs, retrieval worksheets, extractions, run logs, and exports.

The witness is mechanical quote verification. Every quote the read stage extracts is checked against the source text and stamped with a quote_match value of exact, normalized, fuzzy, or failed, and the checks are logged in the bundle. Extractions therefore carry their own evidence rather than an agent's account of what a source says.

The trio also maintains continuity with a local scholarly corpus. Retrieval checks the corpus before external lookup to deduplicate, new sources can be ingested back into the corpus, and round-to-round continuity in grounding is corpus-based rather than session-based.

## Gaps

- The per-purpose search pattern catalog and per-database execution details are omitted here; the search skill's SKILL.md defines them.

## Consult also

- capabilities-preground-and-ground — for the grounding loop that consumes these bundles.
- verification-witness-rule — for why the mechanical quote check is the citation witness.
