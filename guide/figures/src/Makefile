# The repository map and its highlighted copies, one for each folder's README and each
# stream page. Each copy fades everything outside one region of the map (see workflow_map.tex).
# Needs pdflatex (TeX Live) and pdftoppm (Poppler). Run make from this folder.
DPI ?= 150
OUT := ..

# name = the region kept bright, as a TikZ rectangle in the map's coordinates
HOLE_features      := (-0.15,2.3) rectangle (10.45,3.4)
HOLE_observability := (-0.15,0.6) rectangle (13.75,2.1)
HOLE_connections   := (5.15,-0.75) rectangle (11.05,0.75)
HOLE_audit         := (13.85,2.1) rectangle (16.25,-3.7)
HOLE_verification  := (-0.15,-3.85) rectangle (13.75,-2.3)
HOLE_pipeline      := (-0.15,-5.25) rectangle (16.25,-3.88)
HOLE_prose         := (2.62,-5.17) rectangle (5.28,-0.92)
HOLE_references    := (5.37,-5.17) rectangle (8.03,-0.92)
HOLE_data          := (8.12,-5.17) rectangle (10.78,-0.92)
HOLE_build         := (10.87,-5.17) rectangle (13.53,-0.92)

VARIANTS := features observability connections audit verification pipeline prose references data build

all: $(OUT)/map.png $(addprefix $(OUT)/map_,$(addsuffix .png,$(VARIANTS)))

map.pdf: workflow_map.tex appendixstyle.tex figstyle.tex
	pdflatex -interaction=nonstopmode -halt-on-error -jobname=map workflow_map.tex > map.log.txt 2>&1 || (grep -A4 '^!' map.log.txt; exit 1)

map_%.pdf: workflow_map.tex appendixstyle.tex figstyle.tex
	pdflatex -interaction=nonstopmode -halt-on-error -jobname=map_$* "\def\hole{$(HOLE_$*)}\input{workflow_map.tex}" > map_$*.log.txt 2>&1 || (grep -A4 '^!' map_$*.log.txt; exit 1)

$(OUT)/%.png: %.pdf
	pdftoppm -png -r $(DPI) -singlefile $< $(OUT)/$*

clean:
	rm -f *.aux *.log *.log.txt *.pdf

.PHONY: all clean
