"""Runtime self-test: walk, branch skip, per-item judgment, replay, score, trail."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]


def run(*args):
    return subprocess.run(VG + list(args), cwd=ROOT, capture_output=True, text=True)


def test_selftest_end_to_end(tmp_path):
    rd = tmp_path / "run"
    p = run("run", "graphs/selftest.yaml", "--run", str(rd), "--inputs", "fixtures/selftest",
            "--judge", "recorded:fixtures/selftest/recorded_judge.json")
    assert p.returncode == 0, p.stdout + p.stderr
    events = [json.loads(l) for l in (rd / "trail.jsonl").read_text().splitlines()]
    assert {"event": "step_skipped", "node": "skipped_branch"}.items() <= next(
        e for e in events if e["event"] == "step_skipped").items()
    assert len([e for e in events if e["event"] == "judgment_item"]) == 4
    assert not (rd / "files" / "truth.yaml").exists()
    assert run("verify", "--run", str(rd)).returncode == 0
    p = run("score", "--run", str(rd), "--truth", "fixtures/selftest/truth.yaml")
    assert p.returncode == 0 and '"recall": 1.0' in p.stdout


def test_step_that_overwrites_fails(tmp_path):
    import shutil
    rd = tmp_path / "run"
    assert run("run", "graphs/selftest.yaml", "--run", str(rd), "--inputs", "fixtures/selftest",
               "--judge", "recorded:fixtures/selftest/recorded_judge.json").returncode == 0
    # a rerun that would change items.json must be refused (identical bytes are harmless)
    (rd / "files" / "words.txt").write_text("purple chair\n")
    p = run("step", "--run", str(rd), "--node", "list_items")
    assert p.returncode == 1
    rec = sorted((rd / "records").iterdir())[-1]
    assert "overwrote" in json.loads(rec.read_text())["checks"]["problems"][0]
    shutil.rmtree(rd)


def test_unparseable_answer_is_not_judged_not_a_crash(tmp_path):
    book = json.loads((ROOT / "fixtures/selftest/recorded_judge.json").read_text())
    book["judge_items:w2"] = 'sure! {"is_color": tru'
    rec = tmp_path / "recorded_bad.json"
    rec.write_text(json.dumps(book))
    rd = tmp_path / "run"
    p = run("run", "graphs/selftest.yaml", "--run", str(rd), "--inputs", "fixtures/selftest",
            "--judge", f"recorded:{rec}")
    assert p.returncode == 0, p.stdout + p.stderr
    findings = json.loads((rd / "files" / "findings.json").read_text())
    assert any(f["item"] == "w2" and f["message"].startswith("not judged") for f in findings)
    assert (rd / "responses" / "02_judge_items" / "w2.retry.txt").exists()
    assert run("verify", "--run", str(rd)).returncode == 0
