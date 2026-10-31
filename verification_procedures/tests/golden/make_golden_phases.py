"""Make the golden copies of the three data phase reports (Track V, step V3).

Runs the data collection, cleaning, and analysis reports offline on their clean and seeded
test files (fixtures/data_phases/), with the recorded answers and VG_OFFLINE=1, each run
folder named data_<phase>_<fixture> so that run identifiers match. Each run's
files/report.md, files/findings.json, and results.json are copied into
tests/golden/data_<phase>_<fixture>/. Kept apart from make_golden.py, whose nine runs are
the four streams'.

Run once to make the copies, and again only by a step that says it changes these reports:
    python3 tests/golden/make_golden_phases.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # verification_procedures/
PHASES = ("collection", "cleaning", "analysis")
RUNS = [(p, f) for f in ("clean", "seeded") for p in PHASES]
COPIED = (("files", "report.md"), ("files", "findings.json"), ("", "results.json"))


def folder_name(phase, fixture):
    return "data_%s_%s" % (phase, fixture)


def run_phase(phase, fixture, run_dir):
    """Run one phase report offline into run_dir, its finding step answered from the test
    files' recorded_judge.json."""
    inputs = ROOT / "fixtures" / "data_phases" / fixture
    args = [sys.executable, str(ROOT / "vg.py"), "run", "graphs/data_%s.yaml" % phase,
            "--run", str(run_dir), "--inputs", str(inputs),
            "--judge", "recorded:" + str(inputs / "recorded_judge.json")]
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, env=env)


def outputs(run_dir):
    """The files of one run that the golden copies hold, by name."""
    run_dir = Path(run_dir)
    found = {}
    for sub, name in COPIED:
        path = run_dir / sub / name if sub else run_dir / name
        if path.is_file():
            found[name] = path
    return found


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for phase, fixture in RUNS:
            name = folder_name(phase, fixture)
            rd = Path(tmp) / name
            proc = run_phase(phase, fixture, rd)
            if proc.returncode:
                sys.exit("%s failed:\n%s%s" % (name, proc.stdout, proc.stderr))
            dest = HERE / name
            if dest.exists():
                shutil.rmtree(str(dest))
            dest.mkdir()
            for fname, path in sorted(outputs(rd).items()):
                shutil.copyfile(str(path), str(dest / fname))
            print("%-26s %s" % (name, ", ".join(sorted(outputs(rd)))))


if __name__ == "__main__":
    main()
