"""The October 8 live run records (live_runs_2026-10-08/).

Appendix A5 describes seven runs made with live models on October 8, 2026, and
the proposal says the research artifact holds their records. The folders are
committed as recorded, apart from the changes for blind review their README
gives. Each one must still verify under this commit's runtime.

vg.py verify writes verify.json and appends to trail.jsonl in the folder it
checks, so every test copies the folder into tmp_path first and leaves the
committed records unchanged. The run uses VG_OFFLINE=1 and points every home
at tmp_path. verify asks no model and reads no home folder.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
LIVE = ROOT / "live_runs_2026-10-08"

# Run folder, then tool steps replayed, lookup steps hashed, and judgment steps
# listed, as the October 8 records give them.
RUNS = {
    "cit_live_clean": (13, 1, 3),
    "cit_live_seeded": (13, 1, 4),
    "data_live_clean": (8, 0, 1),
    "data_live_seeded": (8, 0, 1),
    "prose_clean_live": (6, 0, 1),
    "prose_live": (6, 0, 1),
    "prose_live2": (6, 0, 1),
}


def test_the_folder_holds_the_seven_live_runs_and_no_other():
    assert LIVE.is_dir()
    folders = sorted(p.name for p in LIVE.iterdir() if p.is_dir())
    assert folders == sorted(RUNS)
    assert (LIVE / "README.md").is_file()


@pytest.mark.parametrize("name", sorted(RUNS))
def test_a_copy_of_each_live_run_verifies(name, tmp_path):
    run = tmp_path / name
    shutil.copytree(str(LIVE / name), str(run))
    homes = tmp_path / "homes"
    env = dict(os.environ, VG_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
    for var in ("HOME", "AUDIT_HOME", "CONNECTIONS_HOME", "FEATURES_HOME",
                "OBSERVABILITY_HOME", "TMPDIR"):
        env[var] = str(homes / var.lower())
        os.makedirs(env[var])
    env.pop("WORKFLOW_MODEL_KEY", None)
    p = subprocess.run(VG + ["verify", "--run", str(run)], cwd=str(ROOT),
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stdout + p.stderr
    verdicts = [s["verdict"] for s in json.loads((run / "verify.json").read_text())["steps"]]
    assert not [v for v in verdicts if v.startswith("FAIL")]
    tools, lookups, judged = RUNS[name]
    assert verdicts.count("replay matches") == tools
    assert sum(v.startswith("network step") for v in verdicts) == lookups
    assert sum(v.startswith("judgment") for v in verdicts) == judged
    assert len(verdicts) == tools + lookups + judged
