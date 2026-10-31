"""The second checker must be a different model from the judge (appendix A2.4, A2.5,
Table A6 row "Second checker"). The run refuses to start, before it makes the run
folder, when a graph with a second role is given the same model for both roles.
Recorded executors are the same model when they name the same file.

No procedure of the four streams has a second role since the references procedure 0.2
(Track C2), so the rule is tested on a copy of the self-test graph, written in the
test's temp folder, whose judgment step takes the second role."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vg  # noqa: E402

VG = [sys.executable, str(ROOT / "vg.py")]
SELFTEST = ROOT / "fixtures" / "selftest"
SEEDED = ROOT / "fixtures" / "citations" / "seeded"
PROSE = ROOT / "fixtures" / "prose" / "seeded"
REFUSAL = "the second checker must be a different model from the judge"
ANSWERS = SELFTEST / "recorded_judge.json"
OTHER = SEEDED / "recorded_judge.json"


def run(*args, home=None):
    env = dict(os.environ, VG_OFFLINE="1")
    env.pop("WORKFLOW_MODEL_KEY", None)
    if home is not None:
        env["CONNECTIONS_HOME"] = str(home)
    return subprocess.run(VG + [str(a) for a in args], cwd=ROOT, capture_output=True, text=True, env=env)


def second_graph(tmp_path):
    """The self-test graph with its judgment step in the second role."""
    text = (ROOT / "graphs" / "selftest.yaml").read_text(encoding="utf-8")
    old = "{id: judge_items, kind: judgment,"
    assert text.count(old) == 1
    path = tmp_path / "selftest_second.yaml"
    path.write_text(text.replace(old, "{id: judge_items, kind: judgment, role: second,"), encoding="utf-8")
    return path


def with_second(tmp_path, rd, judge, second, home=None):
    return run("run", second_graph(tmp_path), "--run", rd, "--inputs", SELFTEST,
               "--judge", judge, "--second", second, home=home)


def provider_home(tmp_path, model="qwen/qwen3.5-122b"):
    home = tmp_path / "connections"
    home.mkdir()
    (home / "provider.yaml").write_text(
        "base_url: http://127.0.0.1:9/v1\nmodel: %s\n" % model, encoding="utf-8")
    return home


def test_one_recorded_file_for_both_roles_is_refused(tmp_path):
    rd = tmp_path / "run"
    spec = "recorded:" + str(ANSWERS)
    p = with_second(tmp_path, rd, spec, spec)
    assert p.returncode != 0
    assert REFUSAL in p.stderr
    assert spec in p.stderr
    assert not rd.exists()


def test_same_live_model_is_refused_before_any_call(tmp_path):
    rd = tmp_path / "run"
    home = provider_home(tmp_path)
    p = with_second(tmp_path, rd, "live:qwen/qwen3.5-122b", "live:qwen/qwen3.5-122b", home=home)
    assert p.returncode != 0
    assert REFUSAL + " (live:qwen/qwen3.5-122b)" in p.stderr
    assert "WORKFLOW_MODEL_KEY" not in p.stdout + p.stderr
    assert not rd.exists()


def test_live_and_the_providers_own_model_by_name_are_refused(tmp_path):
    rd = tmp_path / "run"
    home = provider_home(tmp_path)
    p = with_second(tmp_path, rd, "live", "live:Qwen/Qwen3.5-122b", home=home)
    assert p.returncode != 0
    assert REFUSAL + " (live:Qwen/Qwen3.5-122b)" in p.stderr
    assert not rd.exists()


def test_one_file_by_relative_and_absolute_path_is_refused(tmp_path):
    rd = tmp_path / "run"
    rel = "recorded:fixtures/selftest/recorded_judge.json"
    absolute = "recorded:" + str(ANSWERS)
    p = with_second(tmp_path, rd, rel, absolute)
    assert p.returncode != 0
    assert REFUSAL in p.stderr
    assert not rd.exists()


def test_different_recorded_files_run_as_before(tmp_path):
    rd = tmp_path / "run"
    p = with_second(tmp_path, rd, "recorded:" + str(OTHER), "recorded:" + str(ANSWERS))
    assert p.returncode == 0, p.stdout + p.stderr
    s = run("score", "--run", rd, "--truth", SELFTEST / "truth.yaml")
    assert s.returncode == 0, s.stdout + s.stderr


def test_the_references_procedure_has_no_second_role_and_runs_with_any_second(tmp_path):
    rd = tmp_path / "run"
    spec = "recorded:" + str(OTHER)
    p = run("run", "graphs/citations.yaml", "--run", rd, "--inputs", SEEDED, "--judge", spec, "--second", spec)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (rd / "results.json").exists()


def test_prose_graph_has_no_second_role_and_runs_with_any_second(tmp_path):
    rd = tmp_path / "run"
    spec = "recorded:" + str(PROSE / "recorded_judge.json")
    p = run("run", "graphs/prose.yaml", "--run", rd, "--inputs", PROSE, "--judge", spec, "--second", spec)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (rd / "results.json").exists()


def test_same_model_compares_the_part_after_the_first_colon(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert vg.same_model("live:Qwen/Qwen3.5-122b ", "live: qwen/qwen3.5-122b")
    assert not vg.same_model("live:qwen/qwen3.5-122b", "live:openai/gpt-oss-120b")
    assert vg.same_model("recorded:fixtures/citations/seeded/recorded_judge.json",
                         "recorded:" + str(SEEDED / "recorded_judge.json"))
    assert not vg.same_model("recorded:" + str(SEEDED / "recorded_judge.json"),
                             "recorded:" + str(ANSWERS))
