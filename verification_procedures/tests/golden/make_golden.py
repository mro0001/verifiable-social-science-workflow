"""Make the golden copies of today's reports.

Runs nine procedure runs offline in a temporary folder, with recorded answers and
VG_OFFLINE=1, each run folder named <stream>_<fixture> so that run identifiers match. The
nine are prose, citations, data, and build on their clean and seeded fixtures, and the
data procedure on examples/sample_project (folder data_sample). Each run's
files/report.md, files/findings.json, and results.json (where the run writes one) are
copied into tests/golden/<stream>_<fixture>/.

Run once to make the copies, and again only by a step that says it changes a report:
    python3 tests/golden/make_golden.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # verification_procedures/
SAMPLE = ROOT.parent / "examples" / "sample_project"

RUNS = [("prose", "clean"), ("prose", "seeded"), ("citations", "clean"), ("citations", "seeded"),
        ("data", "clean"), ("data", "seeded"), ("build", "clean"), ("build", "seeded"),
        ("data", "sample")]
COPIED = (("files", "report.md"), ("files", "findings.json"), ("", "results.json"))


def folder_name(stream, fixture):
    return "%s_%s" % (stream, fixture)


def flat_copy(project, folder):
    """Copy the project's top-level regular files into folder, as the data handoff copies
    a flat project. A run of the data procedure carries its inputs' subfolders, so a
    sample project built in place, with its builds/ folder, is read through this copy."""
    folder = Path(folder)
    folder.mkdir(parents=True)
    for path in sorted(Path(project).iterdir()):
        if path.is_file() and not path.is_symlink():
            shutil.copyfile(str(path), str(folder / path.name))
    return folder


def inputs_of(stream, fixture, staging=None):
    if (stream, fixture) == ("data", "sample"):
        return flat_copy(SAMPLE, staging or tempfile.mkdtemp(prefix="sample_inputs_") + "/inputs")
    return ROOT / "fixtures" / stream / fixture


def run_procedure(stream, fixture, run_dir):
    """Run one procedure offline into run_dir with its recorded answers. The judge reads
    recorded_judge.json from the inputs folder. The build procedure has no judgment step."""
    inputs = inputs_of(stream, fixture, Path(str(run_dir) + "_inputs"))
    args = [sys.executable, str(ROOT / "vg.py"), "run", "graphs/%s.yaml" % stream,
            "--run", str(run_dir), "--inputs", str(inputs)]
    if stream != "build":
        args += ["--judge", "recorded:" + str(inputs / "recorded_judge.json")]
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
        for stream, fixture in RUNS:
            name = folder_name(stream, fixture)
            rd = Path(tmp) / name
            proc = run_procedure(stream, fixture, rd)
            if proc.returncode:
                sys.exit("%s failed:\n%s%s" % (name, proc.stdout, proc.stderr))
            dest = HERE / name
            if dest.exists():
                shutil.rmtree(str(dest))
            dest.mkdir()
            for fname, path in sorted(outputs(rd).items()):
                shutil.copyfile(str(path), str(dest / fname))
            print("%-18s %s" % (name, ", ".join(sorted(outputs(rd)))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
