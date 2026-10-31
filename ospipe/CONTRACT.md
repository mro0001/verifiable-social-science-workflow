# ospipe Root Contract

Purpose. The reproducible pipeline. Turns a canonical markdown source file plus a numbers manifest into checked, numbered builds. It holds only the pipeline's modules. Built with the Recursive Modules Method.

## Produces

- The command line `python3 -m ospipe`. Its commands are listed in `ospipe/root/CONTRACT.md`.
- The module tree under `ospipe/`, one folder per module, each with CONTRACT.md, fixture, code, tests. `MODULES.md` lists them.

## Frozen

- The placeholder grammar and manifest semantics defined in `ospipe/foundation/CONTRACT.md`.
- Resolve is the hard gate. Nothing downstream consumes unresolved text.
- Python 3.9, stdlib plus PyYAML only. No new dependencies without a contract change.
- Real manuscript data never enters a fixture or test. Fixtures are synthetic (fake values, real shape).

## Soft

- CLI flag names beyond the four check flags of `ospipe/root/CONTRACT.md`, output formatting, internal wiring.

## Consumers

- `make` targets in a paper workspace (adoption-time). The MANUSCRIPT_WORKFLOW.md appendix mechanics.

## Fixture

- Each child module carries its own; the root composition test assembles them (`tests/test_root_composition.py`).

## Status

- realized
