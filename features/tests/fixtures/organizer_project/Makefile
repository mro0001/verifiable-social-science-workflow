# The organizer fixture's build file, one rule for the manuscript.

OSPIPE ?= python3 -m ospipe
PURPOSE ?= draft

.PHONY: manuscript

manuscript: manuscript.md numbers.yml refs.bib
	$(OSPIPE) build --manuscript manuscript.md --manifest numbers.yml --tables-dir . --bib refs.bib --builds-dir builds/manuscript --purpose "$(PURPOSE)"
