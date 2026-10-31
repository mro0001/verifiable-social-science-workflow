# The story project's build file. Each rule builds one research product from its
# one source with ospipe's build, using the arguments the project README gives.
# Before running make, set PYTHONPATH to the repository's ospipe/ folder, as the
# project README does, for example PYTHONPATH=../../../ospipe make manuscript.

OSPIPE ?= python3 -m ospipe
PURPOSE ?= draft

.PHONY: manuscript slides

manuscript: manuscript.md numbers.yml refs.bib top_words.md
	$(OSPIPE) build --manuscript manuscript.md --manifest numbers.yml --tables-dir . --bib refs.bib --builds-dir builds/manuscript --purpose "$(PURPOSE)"

slides: slides.md numbers.yml top_words.md
	$(OSPIPE) build --manuscript slides.md --manifest numbers.yml --tables-dir . --to revealjs --builds-dir builds/slides --purpose "$(PURPOSE)"
