# Implement the workflow

This page gives the commands that set the workflow up and then try it on the sample project with no network and no model. Go back to [the portal's home](home.md), or read how to [critique the workflow](critique.md).

## Get the workflow

Clone the repository and change into the folder the clone makes. Replace `<repository address>` with the repository's address.

```
git clone <repository address>
```

Run every command from the workflow's folder, the folder that holds `features/`, `ospipe/`, and `audit_layer/`, unless a step says to change folder.

## Set up once

System setup runs once per scholar. It checks the software the workflow needs, prints a line to install anything missing, and records the scholar's choices. Project setup runs once per project and lays out a project that builds with `make` on the first try.

```
python3 -m features setup system --answers system_answers.yaml
python3 -m features setup project ~/research/my_study --answers project_answers.yaml
```

The [pipeline setup guide](../../setup/GUIDE.md) gives the fields of each answers file and what setup never does. The [project organizer guide](../../organizer/GUIDE.md) shows how an AI session proposes changes to a project's files and how the scholar applies and undoes them.

## Build the sample project

The [sample project](../../../examples/sample_project/README.md) is a small project with a manuscript and slides built from one set of computed results. These commands rerun its analysis and build the manuscript. Nothing here uses the network or calls a model.

```
cd examples/sample_project
python3 s1_results.py
PYTHONPATH=../../ospipe python3 -m ospipe build --manuscript manuscript.md --manifest numbers.yml --tables-dir . --bib refs.bib --builds-dir builds/manuscript --purpose "sample manuscript"
```

The build writes `builds/manuscript/v001.docx` and a row in `builds/manuscript/BUILDS.md` that marks the build unverified for all four streams.

## Run the four procedures

Each procedure runs from the `verification_procedures` folder. The data procedure checks the sample project's numbers against a rerun of its analysis. The other three run on their seeded test inputs, which hold faults the procedure should catch. Recorded answers stand in for the model at each judgment step, and `VG_OFFLINE=1` keeps the references procedure from looking up sources on the web.

```
cd verification_procedures
python3 vg.py run graphs/data.yaml --run runs/demo_sample --inputs ../examples/sample_project --judge recorded:../examples/sample_project/recorded_judge.json
python3 vg.py run graphs/prose.yaml --run runs/demo_prose --inputs fixtures/prose/seeded --judge recorded:fixtures/prose/seeded/recorded_judge.json
VG_OFFLINE=1 python3 vg.py run graphs/citations.yaml --run runs/demo_citations --inputs fixtures/citations/seeded --judge recorded:fixtures/citations/seeded/recorded_judge.json
python3 vg.py run graphs/build.yaml --run runs/demo_build --inputs fixtures/build/seeded
```

Each run writes its report to `runs/<name>/files/report.md` and its items to `runs/<name>/results.json`. The scholar approves or holds each item that needs a decision, naming the item from `results.json`, as in `python3 vg.py decide --run runs/demo_citations --item ITEM --approve --by "A. Scholar"`.

## Build this portal

```
python3 -m features portal build
```

The site goes to `features/portal/_site/` and opens from disk. Open its `index.html` in a browser.
