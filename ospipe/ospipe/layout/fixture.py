"""Synthetic fixture for the layout contract. Fake products, real shape.

A build file with a manuscript (a Word document with a bibliography) and slides
(reveal.js), written with variables, a `?=` after an `=`, a variable used before
it is defined, a continuation line, and a `manifest` rule that is not a product.
A second build file holds one rule for each problem kind. Tests write the files
named in `FILES` beside a build file so that every source exists.
"""

MAP_MAKEFILE = """\
# Synthetic build file. One rule per research product.
OSPIPE = python3 -m ospipe
PAPER := paper/paper.md
TO_SLIDES = revealjs
TO_SLIDES ?= docx
BIB ?= refs.bib
MANIFEST = numbers.yml
PURPOSE ?= draft
OUT = $(BUILD_ROOT)
BUILD_ROOT := builds

.PHONY: manuscript slides manifest

manuscript: $(PAPER) $(MANIFEST)
\t$(OSPIPE) build --manuscript $(PAPER) --manifest $(MANIFEST) \\
\t  --tables-dir tables --bib $(BIB) --csl style/apa.csl --reference-doc style/ref.docx \\
\t  --builds-dir ${OUT}/manuscript --purpose "$(PURPOSE)"

slides: slides/talk.md $(MANIFEST)
\t@$(OSPIPE) build --manuscript=slides/talk.md --manifest $(MANIFEST) --overlay overlay.yml --to $(TO_SLIDES) --builds-dir $(OUT)/slides --verification-dir checks --purpose "fake talk"

manifest:
\t$(OSPIPE) emit-manifest --manifest $(MANIFEST)
"""

FILES = {
    "paper/paper.md": "# Fake paper\n\nWidgets {{num:widgets}}.\n",
    "slides/talk.md": "## Fake talk\n\nWidgets {{num:widgets}}.\n",
    "numbers.yml": 'numbers:\n  widgets: {value: "24", from: out.json, field: widgets}\n',
}

# Every field of the two products the map holds, as read_map gives them.
EXPECTED = {
    "manuscript": {
        "name": "manuscript",
        "source": "paper/paper.md",
        "builds_dir": "builds/manuscript",
        "to": "docx",
        "manifest": "numbers.yml",
        "overlay": None,
        "tables_dir": "tables",
        "bib": "refs.bib",
        "csl": "style/apa.csl",
        "reference_doc": "style/ref.docx",
        "verification_dir": "paper/verification",
        "purpose": "draft",
    },
    "slides": {
        "name": "slides",
        "source": "slides/talk.md",
        "builds_dir": "builds/slides",
        "to": "revealjs",
        "manifest": "numbers.yml",
        "overlay": "overlay.yml",
        "tables_dir": None,
        "bib": None,
        "csl": None,
        "reference_doc": None,
        "verification_dir": "checks",
        "purpose": "fake talk",
    },
}

# One rule for each problem kind, and two products from one source, which is fine.
PROBLEM_MAKEFILE = """\
OSPIPE = python3 -m ospipe

no_source:
\t$(OSPIPE) build --manifest numbers.yml --builds-dir builds/a --purpose x

two_sources:
\t$(OSPIPE) build --manuscript paper/paper.md --manuscript slides/talk.md --manifest numbers.yml --builds-dir builds/b --purpose x

missing_source:
\t$(OSPIPE) build --manuscript paper/absent.md --manifest numbers.yml --builds-dir builds/c --purpose x

no_manifest:
\t$(OSPIPE) build --manuscript paper/paper.md --builds-dir builds/d --purpose x

no_builds_dir:
\t$(OSPIPE) build --manuscript paper/paper.md --manifest numbers.yml --purpose x

first_sharer:
\t$(OSPIPE) build --manuscript paper/paper.md --manifest numbers.yml --builds-dir builds/shared --purpose x

second_sharer:
\t$(OSPIPE) build --manuscript slides/talk.md --manifest numbers.yml --builds-dir builds/shared/ --purpose x

same_source_one:
\t$(OSPIPE) build --manuscript paper/paper.md --manifest numbers.yml --builds-dir builds/one --purpose x

same_source_two:
\t$(OSPIPE) build --manuscript paper/paper.md --manifest numbers.yml --to html --builds-dir builds/two --purpose x
"""

# The words each problem's message holds, by the rule it is about.
PROBLEM_WORDS = (
    ("no_source", "no --manuscript"),
    ("two_sources", "more than one --manuscript"),
    ("missing_source", "paper/absent.md does not exist"),
    ("no_manifest", "no --manifest"),
    ("no_builds_dir", "no --builds-dir"),
    ("second_sharer", "builds/shared"),
)
