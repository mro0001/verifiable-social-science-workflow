# Project guide

This project was set up on @@DATE@@. Each research product has one source file, and the `Makefile` names it, so it is always clear which draft is current.

## Products

## Build

Run `make <product>` in this folder to build a product. Each build fills every placeholder from `numbers.yml`, stops if one is missing, and writes the next numbered build in `builds/<product>/` with a ledger row in its `BUILDS.md`. `make manifest` fills each value in `numbers.yml` from the pipeline's outputs, and `make emit PRODUCT=<product>` writes that product's replication folder.

## Where things go

- Computed results. Each value the text cites is listed in `numbers.yml` with the output it comes from. The text cites it through a num placeholder that holds its key, as the sample project in the workflow's `examples/sample_project/` shows. Tables the text cites are markdown files in this folder.
- References. `refs.bib` holds the references the text cites. When the scholar's citation manager exports a BibTeX file, `make` copies that export to `refs.bib` whenever the export is newer, so the build uses the current library and the project keeps its own copy.
- Data. Raw data files are never edited, and `acquisition.yaml` lists each one with its checksum. `pipeline.yaml` declares each analysis step and the outputs it writes, and `params.yaml` sets each analytic choice once.
- Notes. The `notes/` folder holds the project's notes, started from the workflow's notes templates.
- Verification results. The `verification/` folder holds each stream's results file, and its own `README.md` says how the build reads them.
