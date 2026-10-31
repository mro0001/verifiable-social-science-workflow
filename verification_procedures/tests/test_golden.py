"""Golden copies of today's reports.

tests/golden/<stream>_<fixture>/ holds report.md, findings.json, and results.json from
nine offline runs, the four streams on their clean and seeded fixtures and the data
procedure on the sample project. Each test runs the same procedure the same way, through
make_golden.py, into a folder of the same name, and compares the three files byte for
byte. The golden copies change only when a later step says it changes a report and
reruns make_golden.py. Judgment steps use recorded answers and lookups stay offline
(VG_OFFLINE=1), so nothing here calls a model or the network.
"""
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"

spec = importlib.util.spec_from_file_location("make_golden", str(GOLDEN / "make_golden.py"))
make_golden = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_golden)

COMPARED = ("report.md", "findings.json", "results.json")


def test_nine_runs_are_named():
    names = [make_golden.folder_name(stream, fixture) for stream, fixture in make_golden.RUNS]
    assert names == ["prose_clean", "prose_seeded", "citations_clean", "citations_seeded",
                     "data_clean", "data_seeded", "build_clean", "build_seeded", "data_sample"]


@pytest.mark.parametrize("stream,fixture", make_golden.RUNS,
                         ids=[make_golden.folder_name(s, f) for s, f in make_golden.RUNS])
def test_run_reproduces_golden_copy(tmp_path, stream, fixture):
    name = make_golden.folder_name(stream, fixture)
    rd = tmp_path / name
    proc = make_golden.run_procedure(stream, fixture, rd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    got = make_golden.outputs(rd)
    assert sorted(got) == sorted(COMPARED)
    for fname in COMPARED:
        want = GOLDEN / name / fname
        assert want.is_file(), "no golden copy %s/%s" % (name, fname)
        assert got[fname].read_bytes() == want.read_bytes(), "%s/%s differs" % (name, fname)
