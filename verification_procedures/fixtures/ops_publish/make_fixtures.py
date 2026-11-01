"""Regenerate the fixtures for checking a verification repository (synthetic, with no
real name, address, key, or path).

    python3 fixtures/ops_publish/make_fixtures.py

clean/   repo.tar, a small verification repository written by hand in the shape that
         python3 -m features publish build writes, with two products, paper and
         slides, whose manifest records the counts its results give, and
         publish_check.yaml, with a synthetic workflow folder, the term Jordan Doe,
         and rebuild false.
seeded/  the same repository with the faults truth.yaml names, and the same settings.

The counts are written out by hand in COUNTS, not computed, so the clean run tests the
recount's rules. pack_files() writes a tar the same way every time (sorted names, mtime
0, mode 0644, USTAR format), and office() a Word file the same way, so a fixture changes
only when its files do. The tests use repository(), finish(), and pack_files() too.
"""
import collections
import hashlib
import io
import json
import os
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = "docs/publish_manifest.json"
GENERATED = ("README.md", "docs/reading_reports.md", "docs/rebuild.md", "docs/record.md", "docs/results.svg",
             "project/README.md")
NOT_SECRET = b"This is not a real secret. It is a synthetic file for a test.\n"
RAW_SESSION = "8f14e45f-ceea-467a-9575-8a3b2f0c1d2e"
EPOCH = 1792022400  # 2026-10-15, the date of the paper's latest build, at midnight UTC
SETTINGS = """\
# Settings for checking the synthetic verification repository. The workflow
# folder and the excluded folder are synthetic, and rebuild is false, so a run
# only scans the files and recounts the numbers.
workflow_root: /scholar/workflow
terms: [Jordan Doe]
allow: []
max_file_mb: 100
warn_file_mb: 50
rebuild: false
excluded_folders: [/scholar/private_records]
"""
TRUTH = """\
# The faults the seeded repository adds to the clean one. Each item is a file's
# path in the tar, a tar's path and a member's, a folder, or a count's key.
faults:
  - {id: f01, check: publish_files, item: project/manuscript.md}
  - {id: f02, check: publish_files, item: project/params.yaml}
  - {id: f03, check: publish_files, item: project/.env}
  - {id: f04, check: publish_files, item: project/audit/session_writes.jsonl}
  - {id: f05, check: publish_files, item: project/deploy/notes.txt}
  - {id: f06, check: publish_files, item: project/acknowledgments.md}
  - {id: f07, check: publish_files, item: project/drafts/draft.docx}
  - {id: f08, check: publish_counts, item: docs/reading_reports.md}
  - {id: f09, check: publish_counts, item: citations.ai}
  - {id: f10, check: publish_files, item: project/verification/runs/x}
  - {id: f11, check: publish_files, item: project/verification/paper/prose/report.md}
  - {id: f12, check: publish_files, item: project/session_log.txt}
  - {id: f13, check: publish_files, item: "project/archive.tar:inner.tar"}
  - {id: f14, check: publish_files, item: project/keys/token.txt}
  - {id: f15, check: publish_counts, item: prose.changes}
"""

# Every count the clean repository's results give, worked out by hand from the items
# below (design A.3 as revised by R11).
COUNTS = collections.OrderedDict((
    ("prose.changes", 7), ("prose.ai", 5), ("prose.no_reason", 3), ("prose.content", 2), ("prose.reports", 2),
    ("prose.paper.changes", 5), ("prose.paper.ai", 4), ("prose.paper.no_reason", 2), ("prose.paper.content", 2),
    ("prose.slides.changes", 2), ("prose.slides.ai", 1), ("prose.slides.no_reason", 1),
    ("prose.slides.content", 0),
    ("citations.rows", 7), ("citations.ai", 5), ("citations.scholar", 1), ("citations.unknown", 1),
    ("citations.not_found", 1), ("citations.not_looked_up", 1), ("citations.no_quote", 1),
    ("citations.record_quote_not_found", 1), ("citations.no_reason", 1), ("citations.reports", 1),
    ("citations.paper.rows", 7), ("citations.paper.ai", 5), ("citations.paper.scholar", 1),
    ("citations.paper.unknown", 1), ("citations.paper.not_found", 1), ("citations.paper.not_looked_up", 1),
    ("citations.paper.no_quote", 1), ("citations.paper.record_quote_not_found", 1),
    ("citations.paper.no_reason", 1),
    ("data.numbers", 3), ("data.reproduce", 2), ("data.changes", 2), ("data.change_no_reason", 1),
    ("data.parameters", 2), ("data.parameter_no_reason", 1), ("data.scripts", 3), ("data.scripts_ai", 2),
    ("data.reports", 1),
    ("data.paper.numbers", 3), ("data.paper.reproduce", 2), ("data.paper.changes", 2),
    ("data.paper.change_no_reason", 1), ("data.paper.parameters", 2), ("data.paper.parameter_no_reason", 1),
    ("phases.paper.data_analysis.descriptions", 4), ("phases.paper.data_analysis.missing", 1),
    ("phases.paper.data_analysis.not_found", 1), ("phases.paper.data_analysis.confirmed", 2),
    ("build.blocking", 3), ("build.warnings", 3), ("build.hardcoding", 2), ("build.ai_writes", 1),
    ("build.one_source", 1), ("build.reports", 2),
    ("builds.total", 2), ("builds.paper.latest", "v002"), ("builds.paper.date", "2026-10-15"),
    ("builds.paper.sha256", None), ("builds.paper.epoch", EPOCH),
    ("builds.paper.state", "unverified until the scholar decides"),
    ("decisions.approved", 3), ("decisions.held", 1), ("decisions.undecided", 30),
    ("phases.decisions.approved", 0), ("phases.decisions.held", 0), ("phases.decisions.undecided", 4),
    ("numbers.total", 3), ("refs.works", 5),
    ("sessions.indexed", 3), ("sessions.contributing", 2), ("sessions.contributions", 5),
    ("sessions.harnesses", "Claude Code; ForgeCode"),
    ("missing", "slides/citations; slides/data"),
))

SESSION_COLUMNS = ("public_id", "started_at", "minutes", "harness", "harness_version", "models", "parent",
                   "tool_calls", "files_read", "files_edited", "files_written", "other_files", "title", "gist",
                   "summary", "keywords", "model_fields", "transcript_sha256", "transcript_bytes", "contributions",
                   "references")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def public_id(text):
    return "S" + digest(text.encode("utf-8"))[:12]


SESSION_IDS = (public_id(RAW_SESSION), public_id("synthetic session two"), public_id("synthetic session three"))


def pack_files(files):
    """A tar of the given {name: bytes}, sorted, with mtime 0, mode 0644, and no owner."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def office(parts):
    """A zip of the given {part: text}, stored, with one fixed date, the way the
    fixtures' Word files are written."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, parts[name].encode("utf-8"))
    return buf.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def word(text, creator="", comment=False):
    """A small Word file holding one paragraph, with dc:creator set to creator."""
    comments = '<w:comments %s>%s</w:comments>' % (
        W, '<w:comment w:id="0" w:author=""><w:p><w:r><w:t>A note.</w:t></w:r></w:p></w:comment>' if comment else "")
    return office({
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types '
                               'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                               '<Default Extension="xml" ContentType="application/xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships '
                       'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                       'relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "docProps/core.xml": '<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties '
                             'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                             'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Paper</dc:title>'
                             '<dc:creator>%s</dc:creator><cp:lastModifiedBy></cp:lastModifiedBy>'
                             '</cp:coreProperties>' % creator,
        "docProps/app.xml": '<?xml version="1.0" encoding="UTF-8"?><Properties '
                            'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                            '<Company></Company></Properties>',
        "word/document.xml": '<?xml version="1.0" encoding="UTF-8"?><w:document %s><w:body><w:p><w:pPr/>'
                             '<w:r><w:t>%s</w:t></w:r></w:p></w:body></w:document>' % (W, text),
        "word/comments.xml": '<?xml version="1.0" encoding="UTF-8"?>' + comments,
    })


def dumps(obj):
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def finding(check, severity, message, evidence=""):
    return {"check": check, "severity": severity, "message": message, "evidence": evidence}


def results(stream, run_id, items, decisions=(), inputs=None):
    return dumps(collections.OrderedDict((
        ("schema", "verification-results"), ("schema_version", 1), ("stream", stream), ("run_id", run_id),
        ("procedure_version", 0.1), ("inputs", inputs or {"manuscript.md": "sha256:" + "0" * 64}),
        ("items", list(items)), ("decisions", list(decisions)))))


def decision(item, word_, run_id):
    return {"item": item, "decision": word_, "by": "A. Scholar", "at": "2026-10-16T10:00:00Z", "run_id": run_id}


def change(item_id, summary, findings, ai=True, sessions=()):
    out = {"id": item_id, "kind": "change", "summary": summary, "findings": list(findings), "needs_decision": ai}
    if sessions:
        out["sessions"] = list(sessions)
    return out


NO_REASON = finding("rationale_coverage", "blocking", "AI change with no recorded reason")
CONTENT = finding("content_handoff", "warning", "content change, hand off to citations|data stream")


def citation(item_id, citekey, origin, lookup, quote_in_source="not_checked", reason="", quotes=()):
    return {"id": item_id, "citekey": citekey, "sentence": "A sentence citing [@%s]." % citekey, "origin": origin,
            "origin_evidence": "First named in a session of the index.", "reference": "A work (2020).",
            "lookup": lookup, "existence": "found by its DOI" if lookup == "found" else lookup.replace("_", " "),
            "reason": reason, "quotes": list(quotes), "quote_in_source": quote_in_source,
            "source_file": "source_%s.txt" % citekey, "findings": [], "needs_decision": origin != "scholar"}


def build_items():
    """The build items both products' build runs give, since each run checks the whole map."""
    def item(item_id, kind, findings):
        return {"id": item_id, "kind": kind, "summary": "%d problems." % len(findings) if kind == "finding"
                else "source and builds folder", "findings": findings, "needs_decision": True}
    return [
        item("paper", "deliverable", [finding("read_map", "warning", "The canonical file is not a prerequisite of its rule.")]),
        item("slides", "deliverable", []),
        item("manuscript.md:3", "finding", [finding("check_hardcoding", "blocking", "Hard-coded result: equals numbers.yml key 'results.mean'.")]),
        item("manuscript.md:7", "finding", [finding("check_hardcoding", "warning", "A number that may be a result.")]),
        item("slides.md:2", "finding", [finding("check_hardcoding", "blocking", "Hard-coded result: equals numbers.yml key 'results.count'.")]),
        item("build_prefs.yaml", "finding", [finding("check_prefs", "warning", "The preferences name no builds folder.")]),
        item("builds/paper", "finding", [finding("check_ai_touch", "blocking", "An AI session wrote to a build folder.")]),
    ]


def report_md(title, lines):
    return ("# %s\n\n%s\n" % (title, "\n".join(lines))).encode("utf-8")


def ledger(rows):
    head = ("# Builds\n\n| version | date | git | sha256 | purpose | baseline | reviewed | verification | runs |\n"
            "|---|---|---|---|---|---|---|---|---|\n")
    return (head + "".join("| %s |\n" % " | ".join(r) for r in rows)).encode("utf-8")


def sessions_csv():
    rows = [
        (SESSION_IDS[0], "2026-10-01T09:00:00.000Z", "12.5", "claude_code", "2.1.0", "model-a", "",
         "wrote 2; edited 3", "manuscript.md", "manuscript.md", "s1_results.py", "", "Drafting the methods",
         "The session drafted the methods.", "The session wrote the methods paragraph and a script.",
         "methods; drafting", "", "1" * 64, "1200", "3",
         "paper/prose/c01 (approved, run paper_prose); paper/data/e01 (not yet decided, run paper_data)"),
        (SESSION_IDS[1], "2026-10-02T09:00:00.000Z", "3.0", "forgecode", "0.9.0", "model-b", "",
         "ran 4", "refs.bib", "", "", "", "Reading the references", "The session read the references.",
         "The session read the reference list and changed nothing.", "references", "", "2" * 64, "800", "0", ""),
        (SESSION_IDS[2], "2026-10-03T09:00:00.000Z", "8.0", "claude_code", "2.1.0", "model-a", SESSION_IDS[0],
         "edited 2", "slides.md", "slides.md", "", "", "Editing the slides", "The session edited the slides.",
         "The session shortened two slides.", "slides", "", "3" * 64, "950", "2",
         "slides/prose/c01 (not yet decided, run slides_prose); paper/citations/r01 (not yet decided, run paper_citations)"),
    ]
    out = io.StringIO()
    out.write(",".join(SESSION_COLUMNS) + "\n")
    for row in rows:
        out.write(",".join('"%s"' % cell if (";" in cell or "," in cell or " " in cell) else cell for cell in row) + "\n")
    return out.getvalue().encode("utf-8")


def repository():
    """The clean repository's files, every one but the manifest."""
    f = collections.OrderedDict()
    paper_v1 = word("A first draft of the paper.")
    paper_v2 = word("The paper, with its methods.")
    f["README.md"] = (
        "# Verification reports for a test paper\n\n"
        "AI sessions helped write paper and slides. The workflow found each AI contribution, checked it, and "
        "wrote a report for the scholar. No model gives a verdict in any report. The scholar approves or holds "
        "each item. 3 items are approved, 1 held, and 30 not yet decided.\n\n"
        "![Prose: 5 of 7 changes by an AI. References: 5 of 7 citations named by an AI. Data: 2 of 3 numbers "
        "reproduce. Build: 3 problems.](docs/results.svg)\n\n"
        "| Stream | What the check found | Reports |\n|---|---|---|\n"
        "| Prose | 5 of 7 changes were made by an AI. Each is shown with the reason the AI gave, and 3 have none "
        "on record. | [paper](project/verification/paper/prose/report.md) · "
        "[slides](project/verification/slides/prose/report.md) |\n"
        "| References | 5 of 7 citations were first named by an AI. For 1 of them, no quote was found in the "
        "source. 1 cited work was not found. | [paper](project/verification/paper/citations/report.md) |\n"
        "| Data and analysis code | AI sessions wrote or changed 2 of the 3 analysis scripts. 2 of the 3 numbers "
        "reproduce from the raw data. | [paper](project/verification/paper/data/report.md) |\n"
        "| Build | Each document has one source. AI sessions wrote to a build folder 1 time. The report flags 3 "
        "problems for the scholar, 2 of them from the check for results typed into the text. | "
        "[paper](project/verification/paper/build/report.md) · "
        "[slides](project/verification/slides/build/results.json) |\n\n"
        "## Try it\n\n```\ngit clone https://git.example.org/scholar/workflow.git\n"
        "git clone https://git.example.org/scholar/test-paper.git\ncd test-paper/project\n"
        "SOURCE_DATE_EPOCH=%d make paper\n```\n\n"
        "Each command builds the product again as its next numbered build. slides has no numbered build yet.\n\n"
        "## Read more\n\n- [Reading the reports](docs/reading_reports.md)\n- [The record](docs/record.md)\n"
        "- [Rebuilding](docs/rebuild.md)\n- [The session index](project/sessions/index.html)\n" % EPOCH
    ).encode("utf-8")
    f["docs/reading_reports.md"] = (
        "# Reading the reports\n\nEach report sits beside its results file, under "
        "project/verification/<product>/<stream>/.\n\n## What each report found\n\n"
        "| Prose | Count |\n|---|---|\n| Changes | 7 |\n| Made by an AI | 5 |\n| With no reason on record | 3 |\n\n"
        "| References | Count |\n|---|---|\n| Citations | 7 |\n| First named by an AI | 5 |\n"
        "| No quote found in the source | 1 |\n"
    ).encode("utf-8")
    f["docs/rebuild.md"] = (
        "# Rebuilding\n\nThe build needs Python 3.9 or later, PyYAML, python-docx, pandoc, make, and the workflow "
        "cloned beside this repository.\n\n```\ncd project\nSOURCE_DATE_EPOCH=%d make paper\n```\n" % EPOCH
    ).encode("utf-8")
    f["docs/record.md"] = (
        "# The record\n\nThe transcripts stay private. The index names each session by its public id, S and 12 "
        "characters of a checksum. The index lists 3 sessions, 2 of which contributed, with 5 contributions.\n"
    ).encode("utf-8")
    f["docs/results.svg"] = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="980" height="120" viewBox="0 0 980 120">'
        '<rect x="0" y="0" width="100%" height="100%" fill="#FFFFFF"/>'
        '<text x="12" y="30" font-family="Helvetica, Arial, sans-serif" font-size="14" fill="#16191F">'
        'Prose: 5 of 7 changes by an AI</text>'
        '<text x="12" y="60" font-family="Helvetica, Arial, sans-serif" font-size="14" fill="#16191F">'
        'paper v002, unverified until the scholar decides</text>'
        '<text x="12" y="90" font-family="Helvetica, Arial, sans-serif" font-size="14" fill="#6B7280">'
        'slides, no build yet</text></svg>\n'
    ).encode("utf-8")
    f["project/README.md"] = (
        "# The project\n\n| Entry | What it is |\n|---|---|\n| Makefile | The build file, one rule per research "
        "product |\n| manuscript.md | The source text of paper |\n| slides.md | The source text of slides |\n"
        "| builds/ | Every numbered build, with its ledger BUILDS.md |\n| verification/ | Each report, report.md, "
        "and its results file, results.json, by product |\n| sessions/ | The public index of the AI sessions "
        "behind the reports |\n"
    ).encode("utf-8")
    f["project/Makefile"] = (
        "# The build file. One rule per research product, each naming its one source file.\n"
        "WORKFLOW ?= ../../workflow\nOSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe\n"
        "MANIFEST ?= numbers.yml\nPURPOSE ?= draft\n\n"
        ".PHONY: paper\npaper: manuscript.md $(MANIFEST)\n\t$(OSPIPE) build --manuscript manuscript.md "
        "--manifest $(MANIFEST) --bib refs.bib --to docx --builds-dir builds/paper --verification-dir "
        "verification/paper --purpose \"$(PURPOSE)\"\n\n"
        ".PHONY: slides\nslides: slides.md $(MANIFEST)\n\t$(OSPIPE) build --manuscript slides.md --manifest "
        "$(MANIFEST) --to revealjs --builds-dir builds/slides --verification-dir verification/slides "
        "--purpose \"$(PURPOSE)\"\n"
    ).encode("utf-8")
    f["project/manuscript.md"] = (
        "# A test paper\n\nThe mean is {{num:results.mean}} over {{num:results.count}} cases [@smith2020]. "
        "Earlier work found the same [@lee2019; @park2021].\n\nThe share is {{num:results.share}} [@kim2018; "
        "@ross2017].\n"
    ).encode("utf-8")
    f["project/slides.md"] = b"# Slides\n\n- The mean is {{num:results.mean}}.\n"
    f["project/numbers.yml"] = (
        "numbers:\n  results.mean: {value: \"4.2\", from: \"results.csv\", field: \"mean\"}\n"
        "  results.count: {value: \"120\", from: \"results.csv\", field: \"count\"}\n"
        "  results.share: {value: \"0.35\", from: \"results.csv\", field: \"share\"}\n"
    ).encode("utf-8")
    f["project/refs.bib"] = "".join(
        "@article{%s,\n  title = {A work},\n  author = {Author, A.},\n  year = {%s},\n  doi = {10.5555/%s}\n}\n\n"
        % (key, key[-4:], key) for key in ("smith2020", "lee2019", "park2021", "kim2018", "ross2017")).encode("utf-8")
    f["project/pipeline.yaml"] = (
        "steps:\n  - {id: results, phase: analysis, runner: python3, script: s1_results.py, outputs: [results.csv]}\n"
        "  - {id: tables, phase: analysis, runner: python3, script: s2_tables.py, inputs: [results.csv]}\n"
        "  - {id: figures, phase: analysis, runner: python3, script: s3_figures.py, inputs: [results.csv]}\n"
    ).encode("utf-8")
    for n, name in enumerate(("s1_results.py", "s2_tables.py", "s3_figures.py"), 1):
        f["project/" + name] = ('"""Step %d of the pipeline."""\nprint("step %d")\n' % (n, n)).encode("utf-8")
    f["project/params.yaml"] = b"seed: 7\nsample: 100\n"
    f["project/results.csv"] = b"mean,count,share\n4.2,120,0.35\n"
    f["project/builds/paper/BUILDS.md"] = ledger([
        ("v001", "2026-10-01", "-", digest(paper_v1), "first draft", "-", "no",
         "unverified: prose, citations, data, build", "-"),
        ("v002", "2026-10-15", "-", digest(paper_v2), "draft", "-", "no",
         "unverified: prose, citations, data, build",
         "prose=paper_prose; citations=paper_citations; data=paper_data; build=paper_build"),
    ])
    f["project/builds/paper/v001.md"] = b"# A test paper\n\nA first draft of the paper.\n"
    f["project/builds/paper/v001.docx"] = paper_v1
    f["project/builds/paper/v002.md"] = b"# A test paper\n\nThe paper, with its methods.\n"
    f["project/builds/paper/v002.docx"] = paper_v2

    streams = collections.OrderedDict()
    streams[("paper", "prose")] = results("prose", "paper_prose", [
        change("c01", "edit: The methods paragraph names the sample.", [NO_REASON], sessions=[SESSION_IDS[0]]),
        change("c02", "edit: The mean is given with its count.", [NO_REASON, CONTENT]),
        change("c03", "edit: A sentence about earlier work.", []),
        change("c04", "edit: The title.", [], ai=False),
        change("c05", "edit: The share.", [CONTENT]),
        {"id": "r01", "kind": "finding", "summary": "1 problem. an AI tool call wrote the whole file",
         "findings": [finding("exclude_author", "blocking", "an AI tool call wrote the whole file")],
         "needs_decision": True},
    ], [decision("c01", "approved", "paper_prose"), decision("c02", "held", "paper_prose"),
        decision("c03", "approved", "paper_prose_earlier"), decision("c05", "held", "paper_prose"),
        decision("c05", "approved", "paper_prose")])
    streams[("paper", "citations")] = results("citations", "paper_citations", [
        citation("r01", "smith2020", "ai", "found", "yes", "The source reports the mean.",
                 [{"text": "the mean was 4.2", "from": "record", "in_source": "yes"}]),
        citation("r02", "lee2019", "ai", "found", "no", "",
                 [{"text": "a similar mean", "from": "record", "in_source": "no"}]),
        citation("r03", "park2021", "ai", "not_found"),
        citation("r04", "park2021", "ai", "not_found"),
        citation("r05", "kim2018", "ai", "not_looked_up"),
        citation("r06", "smith2020", "scholar", "found", "yes", "The scholar's own citation."),
        citation("r07", "ross2017", "unknown", "found", "yes", "The source gives the share."),
        {"id": "refs.bib", "kind": "finding", "citekey": "", "summary": "1 problem. An entry has no DOI.",
         "findings": [finding("check_refs", "warning", "An entry has no DOI.")], "needs_decision": True},
    ])
    streams[("paper", "data")] = results("data", "paper_data", [
        {"id": "results.mean", "kind": "number", "summary": "results.mean = 4.2, rerun 4.2", "findings": [],
         "needs_decision": True},
        {"id": "results.count", "kind": "number", "summary": "results.count = 120, rerun 120", "findings": [],
         "needs_decision": True},
        {"id": "results.share", "kind": "number", "summary": "results.share = 0.35, rerun 0.36",
         "findings": [finding("check_numbers", "blocking", "The number does not reproduce.")],
         "needs_decision": True},
        {"id": "e01", "kind": "change", "summary": "AI edit to s1_results.py, reason given", "findings": [],
         "needs_decision": True},
        {"id": "e02", "kind": "change", "summary": "AI write to s2_tables.py, no recorded reason",
         "findings": [finding("attribute_ai", "blocking", "an AI change to s2_tables.py with no recorded reason")],
         "needs_decision": True},
        {"id": "params.yaml:seed", "kind": "parameter", "summary": "seed set by the AI to 7",
         "findings": [finding("attribute_ai", "blocking", "a parameter the AI set with no recorded reason")],
         "needs_decision": True},
        {"id": "params.yaml:sample", "kind": "parameter", "summary": "sample set by the AI to 100",
         "findings": [finding("attribute_ai", "warning", "a parameter the AI set, for the scholar to check")],
         "needs_decision": True},
    ], [decision("results.mean", "approved", "paper_data")])
    streams[("paper", "build")] = results("build", "paper_build", build_items(),
                                          inputs={"project.tar": "sha256:" + "a" * 64})
    streams[("slides", "prose")] = results("prose", "slides_prose", [
        change("c01", "edit: The slide on the mean.", [NO_REASON], sessions=[SESSION_IDS[2]]),
        change("c02", "edit: The title slide.", [], ai=False),
    ])
    streams[("slides", "build")] = results("build", "slides_build", build_items(),
                                           inputs={"project.tar": "sha256:" + "b" * 64})
    for (product, stream), data in streams.items():
        f["project/verification/%s/%s.json" % (product, stream)] = data
        f["project/verification/%s/%s/results.json" % (product, stream)] = data
        if (product, stream) != ("slides", "build"):
            f["project/verification/%s/%s/report.md" % (product, stream)] = report_md(
                "The %s report for %s" % (stream, product), ["## Summary", "", "- Items: listed in results.json."])
    phase = results("data_phases", "paper_data_analysis", [
        {"id": "d01", "kind": "description", "summary": "The first step reads the cases.", "findings": [],
         "needs_decision": True},
        {"id": "d02", "kind": "description", "summary": "The second step drops the empty rows.",
         "findings": [finding("check_descriptions", "warning",
                              "The finding step gave no place in the scripts for this description.")],
         "needs_decision": True},
        {"id": "d03", "kind": "description", "summary": "The third step takes the mean.",
         "findings": [finding("check_descriptions", "warning",
                              "The place the finding step gave does not hold the step described.")],
         "needs_decision": True},
        {"id": "d04", "kind": "description", "summary": "The last step writes results.csv.", "findings": [],
         "needs_decision": True},
    ])
    f["project/verification/paper/data_analysis/results.json"] = phase
    f["project/verification/paper/data_analysis/report.md"] = report_md(
        "The data analysis report for paper", ["## Summary", "", "- Descriptions: 4."])
    f["project/sessions/README.md"] = (
        "# The session index\n\nEach row of sessions.csv is one AI session, named by its public id. "
        "The transcripts stay private.\n").encode("utf-8")
    f["project/sessions/sessions.csv"] = sessions_csv()
    f["project/sessions/index.html"] = (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>Sessions</title></head><body>\n<table>\n"
        + "".join('<tr><td><a href="%s.md">%s</a></td></tr>\n' % (s, s) for s in SESSION_IDS)
        + "</table>\n</body></html>\n").encode("utf-8")
    for s in SESSION_IDS:
        f["project/sessions/%s.md" % s] = ("# Session %s\n\nOne session of the index.\n" % s).encode("utf-8")
    return f


def counts_for(files):
    """COUNTS, with the paper's latest build checksum read from its Word file."""
    out = collections.OrderedDict(COUNTS)
    out["builds.paper.sha256"] = digest(files["project/builds/paper/v002.docx"])
    return out


def manifest(files, counts):
    """The manifest publish build would write for the files: the products, groups,
    reports, the counts, and each file's checksum."""
    latest = collections.OrderedDict((("version", "v002"), ("date", "2026-10-15"),
                                      ("sha256", digest(files["project/builds/paper/v002.docx"])),
                                      ("epoch", EPOCH)))
    reports = []
    for group, stream, run_id in (("paper", "prose", "paper_prose"), ("paper", "citations", "paper_citations"),
                                  ("paper", "data", "paper_data"), ("paper", "build", "paper_build"),
                                  ("paper", "data_analysis", "paper_data_analysis"),
                                  ("slides", "prose", "slides_prose"), ("slides", "build", "slides_build")):
        folder = "project/verification/%s/%s" % (group, stream)
        report = folder + "/report.md"
        reports.append(collections.OrderedDict((
            ("group", group), ("stream", stream), ("run_id", run_id), ("results", folder + "/results.json"),
            ("report", report if report in files else None))))
    return collections.OrderedDict((
        ("schema", "publish-repo"), ("schema_version", 1), ("assembled_on", "2026-10-20"),
        ("workflow", collections.OrderedDict((("url", "https://git.example.org/scholar/workflow"),
                                              ("folder", "workflow"), ("commit", "unknown")))),
        ("make_style", "workflow_var"),
        ("harness_names", collections.OrderedDict((("claude_code", "Claude Code"), ("forgecode", "ForgeCode")))),
        ("products", [
            collections.OrderedDict((("name", "paper"), ("source", "manuscript.md"), ("builds_dir", "builds/paper"),
                                     ("verification_dir", "verification/paper"), ("bib", "refs.bib"),
                                     ("numbers", "numbers.yml"), ("latest", latest),
                                     ("state", "unverified until the scholar decides"))),
            collections.OrderedDict((("name", "slides"), ("source", "slides.md"), ("builds_dir", "builds/slides"),
                                     ("verification_dir", "verification/slides"), ("bib", None),
                                     ("numbers", "numbers.yml"), ("latest", None),
                                     ("state", "unverified: no citations report"))),
        ]),
        ("groups", [
            collections.OrderedDict((("key", "paper"), ("products", ["paper"]),
                                     ("verification_dir", "verification/paper"))),
            collections.OrderedDict((("key", "slides"), ("products", ["slides"]),
                                     ("verification_dir", "verification/slides"))),
        ]),
        ("reports", reports),
        ("counts", counts),
        ("generated", collections.OrderedDict((p, "sha256:" + digest(files[p])) for p in GENERATED if p in files)),
        ("files", collections.OrderedDict((p, "sha256:" + digest(files[p])) for p in sorted(files))),
        ("rewritten", [{"path": "project/Makefile", "what": "WORKFLOW default set to ../../workflow"}]),
        ("left_out", collections.OrderedDict((
            ("fixed", ["audit/", "sources/", "notes/", "ship/", ".homes/", "verification/runs/", "sessions/"]),
            ("rules", [{"rule": "gitignore", "count": 2}])))),
        ("notes", []),
    ))


def finish(files, counts=None):
    """The files with the manifest added, its checksums taken from the files as given."""
    out = collections.OrderedDict(files)
    out.pop(MANIFEST, None)
    out[MANIFEST] = dumps(manifest(out, counts if counts is not None else counts_for(out)))
    return out


def seeded():
    """The clean repository with the faults of truth.yaml."""
    f = repository()
    f["project/manuscript.md"] += b"\nContact: scholar@university.edu\n"
    f["project/params.yaml"] += b"data_dir: /Users/jdoe/Documents/data\n"
    f["project/.env"] = NOT_SECRET
    f["project/audit/session_writes.jsonl"] = b'{"file": "manuscript.md", "tool": "Edit"}\n'
    f["project/deploy/notes.txt"] = (b"Deploy notes.\n-----BEGIN OPENSSH PRIVATE KEY-----\n"
                                     b"This is not a real key. It is a synthetic line for a test.\n"
                                     b"-----END OPENSSH PRIVATE KEY-----\n")
    f["project/acknowledgments.md"] = b"# Acknowledgments\n\nThanks go to Jordan Doe for comments on the draft.\n"
    f["project/drafts/draft.docx"] = word("An early draft.", creator="Jordan Doe")
    f["project/verification/runs/x/manifest.json"] = b'{"graph": {"path": "graphs/prose.yaml"}}\n'
    f["project/verification/runs/x/trail.jsonl"] = b'{"event": "run_initialized"}\n'
    f["project/verification/paper/prose/report.md"] += b"\nRun folder: -Users-jdoe-Documents-paper-runs-x\n"
    f["project/session_log.txt"] = ("Session %s wrote the methods.\n" % RAW_SESSION).encode("utf-8")
    f["project/archive.tar"] = pack_files({"readme.txt": b"An archive of the inputs.\n",
                                           "inner.tar": pack_files({"data.csv": b"a,b\n1,2\n"})})
    f["project/keys/token.txt"] = NOT_SECRET
    # f15: a count changed in the manifest and in the README together, with its checksum
    f["README.md"] = f["README.md"].replace(b"5 of 7 changes were made", b"5 of 8 changes were made")
    counts = counts_for(f)
    counts["prose.changes"] = 8
    # f09: a count changed in the manifest only
    counts["citations.ai"] = 6
    out = finish(f, counts)
    # f08: a generated page changed after the manifest was written
    out["docs/reading_reports.md"] = out["docs/reading_reports.md"].replace(b"| Changes | 7 |", b"| Changes | 9 |")
    return out


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def main():
    for name in ("clean", "seeded"):
        os.makedirs(os.path.join(HERE, name), exist_ok=True)
        write(os.path.join(HERE, name, "publish_check.yaml"), SETTINGS.encode("utf-8"))
    write(os.path.join(HERE, "clean", "repo.tar"), pack_files(finish(repository())))
    write(os.path.join(HERE, "seeded", "repo.tar"), pack_files(seeded()))
    write(os.path.join(HERE, "seeded", "truth.yaml"), TRUTH.encode("utf-8"))


if __name__ == "__main__":
    main()
