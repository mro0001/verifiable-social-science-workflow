# The map. One rule per deliverable: the rule names the canonical file
# (--source), where its builds go (--builds-dir), and the pandoc render
# (everything after `--`). tools/build.py resolves {{num:key}} from the
# manifest, freezes the snapshot vNNN.md, renders vNNN.html, and appends a
# ledger row to BUILDS.md. Builds are numbered and never edited.
PANDOC ?= pandoc
MANIFEST := numbers.yml
ALLOW := allowlist.txt
BIB := refs.bib
CSL := style/mini-author-date.csl
PURPOSE ?= draft

.PHONY: paper slides

paper: paper/paper.md paper/template.html $(MANIFEST)
	python3 tools/build.py --source paper/paper.md --manifest $(MANIFEST) --builds-dir builds/paper --ext html --purpose "$(PURPOSE)" -- \
	  $(PANDOC) --standalone --template paper/template.html --citeproc --bibliography $(BIB) --csl $(CSL) --toc --number-sections --to html5

slides: slides/slides.md $(MANIFEST)
	python3 tools/build.py --source slides/slides.md --manifest $(MANIFEST) --builds-dir builds/slides --ext html --purpose "$(PURPOSE)" -- \
	  $(PANDOC) --standalone --citeproc --bibliography $(BIB) --csl $(CSL) --to revealjs
