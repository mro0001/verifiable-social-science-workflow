"""The synthetic corpus the knowledge base tests build on.

make_corpus writes a valid corpus of three entries in two groups, with its
index llms.txt, into a temporary folder and returns the corpus folder. Any file
can be overridden by its path inside the corpus, and an override of None leaves
the file out. The entries are made up and hold no real project data.
"""
import itertools

import pytest

LONG_DASH = "\u2014"

ALPHA = """---
id: formats-alpha
title: The alpha format
source: docs/alpha.md
source_commit: sha256:0123456789ab
updated: 2026-10-01
group: FORMATS
---

# The alpha format

An alpha record holds one row per sample. Each row names its sample.

1. The first fact about alpha records.
2. The second fact about alpha records.

## Gaps

- Nothing is known about very large alpha records.

## Consult also

- formats-beta {dash} for the beta format alpha records point to.
- loop-gamma - for the loop that writes alpha records.
""".replace("{dash}", LONG_DASH)

BETA = """---
id: formats-beta
title: The beta format
source: docs/beta.md
source_commit: abc1234
updated: 2026-10-02
group: FORMATS
---

# The beta format

A beta record names the alpha rows it summarizes!

The beta record is written once, after the alpha rows are complete.
"""

GAMMA = """---
id: loop-gamma
title: The gamma loop
source: docs/gamma.md
source_commit: sha256:fedcba987654
updated: 2026-10-03
group: LOOP
---

# The gamma loop

Does the gamma loop run twice? It runs once per sample, and it writes one alpha record.

```
python3 gamma.py --out records/alpha.csv
```

See [the outside guide](https://example.org/gamma) for the loop's history.

## Consult also

- formats-alpha {dash} for the record the loop writes.
""".replace("{dash}", LONG_DASH)

LLMS = """# Synthetic knowledge base

> Entries made up for the knowledge base tests.

## FORMATS

- [The alpha format](formats/formats-alpha.md): An alpha record holds one row per sample.
- [The beta format](formats/formats-beta.md): A beta record names the alpha rows it summarizes!

## LOOP

- [The gamma loop](loop/loop-gamma.md): Does the gamma loop run twice?
"""

FILES = {
    "formats/formats-alpha.md": ALPHA,
    "formats/formats-beta.md": BETA,
    "loop/loop-gamma.md": GAMMA,
    "llms.txt": LLMS,
}


@pytest.fixture
def make_corpus(tmp_path):
    counter = itertools.count(1)

    def make(overrides=None):
        corpus = tmp_path / "corpus_{}".format(next(counter))
        files = dict(FILES)
        files.update(overrides or {})
        for rel, text in files.items():
            if text is None:
                continue
            path = corpus / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        corpus.mkdir(parents=True, exist_ok=True)
        return corpus

    return make


# Synthetic procedures for the graph entry tests (Steps G4 and G5). They copy
# the shape vg.py reads, a graph in graphs/ naming its contract in contracts/,
# and hold no real procedure.

TWO_STEPS_GRAPH = """# A synthetic graph with a title and triggers, tool steps only.
stream: wordcount
version: 0.2
title: The word count procedure
triggers:
  - A new words file arrives in the project
  - The scholar asks for a word count.
goal: >
  Count the words in a words file and report the count.
  The count is kept for the next run.
contracts: contracts/two_steps.yaml
entry: read_words
exit: report_count
nodes:
  - {id: report_count, kind: tool, does: Write the count to the report.}
  - {id: read_words, kind: tool, does: Read the words file and count its words.}
edges:
  - {from: read_words, rel: LEADS_TO, to: report_count, condition: Always., guidance: Count once., pitfalls: [Counting blank lines.], source: proposed}
"""

TWO_STEPS_CONTRACT = """read_words:
  reads: [words.txt]
  reads_optional: [stopwords.txt]
  produces:
    count.json: {n: int}
report_count:
  reads_optional: ["findings_*.json"]
  reads: [count.json]
  produces:
    report.md: {headings: [Summary]}
"""

JUDGED_GRAPH = """# A synthetic graph with no title or triggers and two judgment steps.
stream: claims
version: 1.0
goal: Judge each open claim in a draft, then have a second checker look again.
contracts: contracts/judged.yaml
entry: list_claims
exit: report
nodes:
  - {id: list_claims, kind: tool, does: List the claims in the draft as items.}
  - {id: judge_claims, kind: judgment, foreach: claims.json, where: "status in [open]", does: Say whether each claim holds.}
  - {id: second_look, kind: judgment, role: second, foreach: claims.json, does: Look again at each claim.}
  - {id: report, kind: tool, does: Write findings and the report.}
edges:
  - {from: list_claims, rel: LEADS_TO, to: judge_claims, condition: Always., guidance: One ask per claim., pitfalls: [Judging all claims at once.], source: proposed}
  - {from: judge_claims, rel: LEADS_TO, to: second_look, condition: Always., guidance: A different model., pitfalls: [The same model twice.], source: proposed}
  - {from: second_look, rel: CONVERGES_TO, to: report, condition: Always., guidance: Report every claim., pitfalls: [Dropping a claim.], source: proposed}
"""

JUDGED_CONTRACT = """list_claims:
  reads: [draft.md, claims_rules.yaml]
  reads_optional: ["source_*.txt", notes.yaml]
  produces:
    claims.json: {items: {id: str}}
judge_claims:
  reads: [claims.json]
  produces:
    judge_claims.json: {items: {item_id: str}}
second_look:
  reads: [claims.json, judge_claims.json]
  produces:
    second_look.json: {items: {item_id: str}}
report:
  reads_optional: ["findings_*.json"]
  reads: [judge_claims.json, second_look.json, steps.json]
  produces:
    report.md: {headings: [Summary]}
"""

# A registry in the form the reconciliation fixes (item 7), naming judged.yaml.
REGISTRY = """registry_version: 1
procedures:
  - id: claims
    stream: claims
    name: Claims
    procedure: Claim review
    graph: graphs/judged.yaml
    triggers:
      events: [ai_edit, turn_end]
      phrases: [check the claims, claim review]
      files: ["*.md"]
    quick_steps: [list_claims]
"""

PROCEDURE_FILES = {
    "graphs/two_steps.yaml": TWO_STEPS_GRAPH,
    "contracts/two_steps.yaml": TWO_STEPS_CONTRACT,
    "graphs/judged.yaml": JUDGED_GRAPH,
    "contracts/judged.yaml": JUDGED_CONTRACT,
}


@pytest.fixture
def make_procedures(tmp_path):
    counter = itertools.count(1)

    def make(overrides=None):
        procedures = tmp_path / "procedures_{}".format(next(counter))
        files = dict(PROCEDURE_FILES)
        files.update(overrides or {})
        for rel, text in files.items():
            if text is None:
                continue
            path = procedures / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        procedures.mkdir(parents=True, exist_ok=True)
        return procedures

    return make
