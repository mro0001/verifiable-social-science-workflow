"""Evaluating LLM runs, written as a procedural graph (graphs/llm_runs.yaml).

The graph reads a finished run of any procedure that put questions to a model,
packed as run.tar, and reports which model answered and what the run kept. The
module fixture runs the references procedure on the test story offline with its
recorded answers, the way examples/test_story/test_story.py arranges it, replays
it with vg.py verify, and packs the run folder the same way every time.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
VG = [sys.executable, str(ROOT / "vg.py")]
GRAPH = "graphs/llm_runs.yaml"
STORY = REPO / "examples" / "test_story"
PROJECT = STORY / "project"
REFERENCES = STORY / "references"
# The slice writes results.json for the four streams, and these tests never read
# it, so the archive leaves it out.
NOT_ARCHIVED = ("results.json",)


def vg(*args, **kw):
    env = dict(os.environ, VG_OFFLINE="1")
    return subprocess.run(VG + list(args), cwd=str(ROOT), capture_output=True, text=True, env=env, **kw)


def pack(run_dir):
    """The run folder as tar bytes, names led by './', sorted, with no times or owners."""
    run_dir = Path(run_dir)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
            rel = path.relative_to(run_dir).as_posix()
            if rel in NOT_ARCHIVED:
                continue
            data = path.read_bytes()
            info = tarfile.TarInfo("./" + rel)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def tar_of(files):
    """A tar of the given {name: bytes}, packed the same way."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(files[name]), 0, 0o644
            tf.addfile(info, io.BytesIO(files[name]))
    return buf.getvalue()


def evaluate(tmp, tar_bytes, reference=None):
    """Run the evaluation graph on one run.tar, with reference.json when a
    reference answer book is given, and return its run folder."""
    tmp = Path(tmp)
    inputs = tmp / "eval_inputs"
    inputs.mkdir()
    (inputs / "run.tar").write_bytes(tar_bytes)
    if reference is not None:
        (inputs / "reference.json").write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    run = tmp / "eval_run"
    p = vg("run", GRAPH, "--run", str(run), "--inputs", str(inputs))
    assert p.returncode == 0, p.stdout + p.stderr
    return run


def read(run, name):
    return json.loads((Path(run) / "files" / name).read_text(encoding="utf-8"))


def problems(run):
    return [f for f in read(run, "findings.json") if f["severity"] in ("blocking", "warning")]


def run_story(tmp):
    """The references procedure run on the test story offline with its recorded
    answers, then verified. Returns the run folder and its inputs folder."""
    tmp = Path(tmp)
    inputs = tmp / "inputs"
    inputs.mkdir()
    shutil.copyfile(str(PROJECT / "manuscript.md"), str(inputs / "draft.md"))
    shutil.copyfile(str(REFERENCES / "expected_citation_provenance.yaml"),
                    str(inputs / "citation_provenance.yaml"))
    for src in sorted(REFERENCES.iterdir()):
        if not src.name.startswith("expected_"):
            shutil.copyfile(str(src), str(inputs / src.name))
    run = tmp / "run"
    p = vg("run", "graphs/citations.yaml", "--run", str(run), "--inputs", str(inputs),
           "--judge", "recorded:" + str(inputs / "recorded_judge.json"))
    assert p.returncode == 0, p.stdout + p.stderr
    p = vg("verify", "--run", str(run))
    assert p.returncode == 0, p.stdout + p.stderr
    return run, inputs


@pytest.fixture(scope="module")
def story(tmp_path_factory):
    """The references procedure run on the test story, verified and packed."""
    tmp = tmp_path_factory.mktemp("llm_runs_story")
    run, inputs = run_story(tmp)
    tar_bytes = pack(run)
    assert pack(run) == tar_bytes
    (tmp / "eval").mkdir()
    return {"run": run, "inputs": inputs, "tar": tar_bytes, "eval": evaluate(tmp / "eval", tar_bytes)}


# ---------------------------------------------------------------- the graph

def test_graph_passes_check():
    p = vg("check", GRAPH)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.startswith("OK: ")


def test_graph_names_its_stream_title_trigger_and_pitfalls():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert graph["stream"] == "llm_runs"
    assert graph["version"] == 0.3
    assert graph["title"] == "Evaluate an LLM run"
    assert graph["contracts"] == "contracts/llm_runs.yaml"
    assert len(graph["triggers"]) == 2 and all(t.endswith(".") for t in graph["triggers"])
    assert "compares two runs of the same procedure on the same files" in graph["triggers"][1]
    assert (graph["entry"], graph["exit"]) == ("read_run", "report")
    assert all(n["kind"] == "tool" for n in graph["nodes"])
    pitfalls = " ".join(p for e in graph["edges"] for p in e["pitfalls"]).lower()
    for words in ("asking a model again", "executor as the model's version",
                  "not judged as a pass", "same model as the first",
                  "difference in wording as a different verdict", "missing replay as a pass"):
        assert words in pitfalls, words
    assert [n["id"] for n in graph["nodes"]] == [
        "read_run", "check_record", "check_models", "compare_reference", "skip_reference",
        "check_replay", "report"]
    assert [(e["from"], e["rel"], e["to"], e.get("check")) for e in graph["edges"]] == [
        ("read_run", "LEADS_TO", "check_record", "run_index.json:is_run == true"),
        ("read_run", "PROVIDES_INPUT_FOR", "check_models", "run_index.json:is_run == true"),
        ("read_run", "CONVERGES_TO", "report", "run_index.json:is_run == false"),
        ("check_record", "CONVERGES_TO", "report", None),
        ("check_models", "CONVERGES_TO", "report", None),
        ("check_record", "LEADS_TO", "compare_reference", "run_index.json:has_reference == true"),
        ("check_record", "LEADS_TO", "skip_reference", "run_index.json:has_reference == false"),
        ("check_record", "LEADS_TO", "check_replay", None),
        ("compare_reference", "CONVERGES_TO", "report", None),
        ("skip_reference", "CONVERGES_TO", "report", None),
        ("check_replay", "CONVERGES_TO", "report", None)]


# ---------------------------------------------------------------- reading a run

def test_story_run_index_names_the_graph_executors_and_judgment_steps(story):
    index = read(story["eval"], "run_index.json")
    citations = yaml.safe_load((ROOT / "graphs" / "citations.yaml").read_text(encoding="utf-8"))
    assert index["is_run"] is True
    assert index["graph"] == "graphs/citations.yaml"
    assert index["graph_version"] == str(citations["version"])
    assert index["stream"] == "citations"
    assert index["judge"] == "recorded:" + str(story["inputs"] / "recorded_judge.json")
    assert index["second"] == ""
    assert index["finished"] is True
    assert index["stopped_at"] == ""
    assert index["has_verify"] is True
    assert index["has_score"] is False
    steps = index["judgment_steps"]
    assert [s["node"] for s in steps] == ["locate_passage"]
    book = json.loads((REFERENCES / "recorded_judge.json").read_text(encoding="utf-8"))
    per_step = [sum(1 for key in book if key.startswith(s["node"] + ":")) for s in steps]
    assert per_step == [2]
    assert [s["items"] for s in steps] == per_step
    assert [s["role"] for s in steps] == ["judge"]
    for s in steps:
        assert s["unjudged"] == []
        assert re.fullmatch(r"prompts/\d\d_" + s["node"], s["prompts"])
        assert re.fullmatch(r"responses/\d\d_" + s["node"], s["responses"])
        assert s["executor"] == ["recorded:recorded_judge.json"]
    records = sorted((story["run"] / "records").iterdir())
    assert index["tool_steps"] == len(records) - 1


def test_answer_book_holds_the_story_answers_in_the_recorded_form(story):
    answers = read(story["eval"], "answer_book.json")
    book = json.loads((REFERENCES / "recorded_judge.json").read_text(encoding="utf-8"))
    assert answers
    for key, answer in answers.items():
        assert key in book, key
        assert answer == book[key], key
    assert answers == book


def test_story_report_has_its_sections(story):
    report = (story["eval"] / "files" / "report.md").read_text(encoding="utf-8")
    for heading in ("## Summary", "## Problems", "## Models and settings", "## Judgment steps"):
        assert heading in report, heading
    assert "| Role | Executor |" in report
    assert "| judge | recorded:" in report
    assert ("| Step | Role | Items asked | Answered | Items not judged | Retries | Prompt mismatches |"
            in report)
    assert "| locate_passage | judge | 2 | 2 | 0 | 0 | 0 |" in report


def test_a_tar_without_a_manifest_is_blocking(tmp_path):
    run = evaluate(tmp_path, tar_of({"notes.txt": b"not a run\n"}))
    index = read(run, "run_index.json")
    assert index["is_run"] is False
    assert index["graph"] == "" and index["stream"] == "" and index["judgment_steps"] == []
    assert index["finished"] is False and index["tool_steps"] == 0
    assert read(run, "answer_book.json") == {}
    blocking = [f for f in read(run, "findings.json") if f["severity"] == "blocking"]
    assert len(blocking) == 1 and blocking[0]["check"] == "read_run"
    # Neither check runs on an archive that holds no run.
    ran = sorted(r.name for r in (run / "records").iterdir())
    assert ran == ["01_read_run.json", "02_report.json"]
    events = [json.loads(line) for line in (run / "trail.jsonl").read_text().splitlines()]
    assert sorted(e["node"] for e in events if e["event"] == "step_skipped") == [
        "check_models", "check_record", "check_replay", "compare_reference", "skip_reference"]
    assert index["has_reference"] is False
    assert not (run / "files" / "agreement.json").exists()
    assert not (run / "files" / "record_check.json").exists()
    p = vg("verify", "--run", str(run))
    assert p.returncode == 0 and p.stdout.count("replay matches") == 2, p.stdout + p.stderr


def test_verify_replays_every_step_of_the_evaluation(story):
    p = vg("verify", "--run", str(story["eval"]))
    assert p.returncode == 0, p.stdout + p.stderr
    lines = p.stdout.strip().splitlines()
    assert len(lines) == len(list((story["eval"] / "records").iterdir()))
    assert all(line.endswith("replay matches") for line in lines), p.stdout


# ---------------------------------------------------------------- the record and the models

def copied_run(story, tmp_path):
    """A copy of the story's finished run, to edit before packing."""
    run = Path(tmp_path) / "copied_run"
    shutil.copytree(str(story["run"]), str(run))
    return run


def edit_manifest(run, **changes):
    path = run / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(changes)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def step_folder(run, top, node):
    return next(p for p in sorted((run / top).iterdir()) if p.name.endswith("_" + node))


def test_story_run_gives_no_problem_and_every_step_all_answered(story):
    assert problems(story["eval"]) == []
    rows = read(story["eval"], "record_check.json")
    assert [r["node"] for r in rows] == ["locate_passage"]
    for r in rows:
        assert r["answered"] == r["items"] > 0
        assert (r["unjudged"], r["retries"], r["prompt_mismatches"], r["missing_responses"]) == (0, 0, 0, 0)
    notes = [f for f in read(story["eval"], "findings.json")
             if f["check"] == "check_record" and f["severity"] == "info"]
    assert sorted(n["item"] for n in notes) == sorted(r["node"] for r in rows)
    assert any(n["item"] == "locate_passage" and "2 of 2" in n["message"] for n in notes)
    assert read(story["eval"], "run_index.json")["provider"] == {}


def test_a_saved_prompt_edited_before_archiving_is_blocking_on_that_item(story, tmp_path):
    run = copied_run(story, tmp_path)
    prompt = step_folder(run, "prompts", "locate_passage") / "r02.txt"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "One more line.\n", encoding="utf-8")
    evaluated = evaluate(tmp_path, pack(run))
    blocking = [f for f in read(evaluated, "findings.json") if f["severity"] == "blocking"]
    assert [(f["check"], f["item"]) for f in blocking] == [("check_record", "locate_passage:r02")]
    row = read(evaluated, "record_check.json")[0]
    assert row["node"] == "locate_passage" and row["prompt_mismatches"] == 1
    report = (evaluated / "files" / "report.md").read_text(encoding="utf-8")
    assert "| locate_passage | judge | 2 | 2 | 0 | 0 | 1 |" in report


def test_a_missing_response_is_a_warning(story, tmp_path):
    run = copied_run(story, tmp_path)
    (step_folder(run, "responses", "locate_passage") / "r03.txt").unlink()
    evaluated = evaluate(tmp_path, pack(run))
    assert [(f["check"], f["severity"], f["item"]) for f in problems(evaluated)] == [
        ("check_record", "warning", "locate_passage:r03")]
    row = read(evaluated, "record_check.json")[0]
    assert row["node"] == "locate_passage" and row["missing_responses"] == 1


def test_an_unparseable_answer_gives_a_not_judged_warning_and_one_retry(tmp_path):
    book = json.loads((ROOT / "fixtures/selftest/recorded_judge.json").read_text())
    book["judge_items:w2"] = 'sure! {"is_color": tru'
    rec = tmp_path / "recorded_bad.json"
    rec.write_text(json.dumps(book))
    run = tmp_path / "selftest_run"
    p = vg("run", "graphs/selftest.yaml", "--run", str(run), "--inputs", "fixtures/selftest",
           "--judge", "recorded:" + str(rec))
    assert p.returncode == 0, p.stdout + p.stderr
    evaluated = evaluate(tmp_path, pack(run))
    warnings = [f for f in problems(evaluated) if f["check"] == "check_record"]
    assert [(f["severity"], f["item"]) for f in warnings] == [("warning", "judge_items:w2")]
    assert "not judged" in warnings[0]["message"]
    assert read(evaluated, "record_check.json") == [
        {"node": "judge_items", "items": 4, "answered": 3, "unjudged": 1, "retries": 1,
         "prompt_mismatches": 0, "missing_responses": 0}]
    assert "judge_items:w2" not in read(evaluated, "answer_book.json")


def test_one_executor_for_both_roles_gives_the_same_model_warning(story, tmp_path):
    run = copied_run(story, tmp_path)
    merged = "recorded:" + str(tmp_path / "recorded_merged.json")
    edit_manifest(run, executors={"judge": merged, "second": merged})
    evaluated = evaluate(tmp_path, pack(run))
    same = [f for f in problems(evaluated) if f["check"] == "check_models"]
    assert len(same) == 1 and same[0]["severity"] == "warning"
    assert "same" in same[0]["message"]
    assert problems(story["eval"]) == []


def test_models_notes_name_each_executor_and_what_the_run_does_not_record(story):
    notes = [f for f in read(story["eval"], "findings.json") if f["check"] == "check_models"]
    assert all(n["severity"] == "info" for n in notes)
    by_item = {n["item"]: n["message"] for n in notes}
    assert set(by_item) == {"judge", "second", "run"}
    assert "recorded_judge.json" in by_item["judge"] and "recorded file" in by_item["judge"]
    assert by_item["second"] == "No executor was set for the second checker."
    for words in ("name", "version", "settings", "token counts", "finish reasons", "seeds", "reasoning"):
        assert words in by_item["run"], words


def test_the_provider_block_names_the_live_model_and_resolves_live(story, tmp_path):
    provider = {"base_url": "http://127.0.0.1:9/v1", "model": "story-model"}
    first = tmp_path / "different"
    first.mkdir()
    run = copied_run(story, first)
    edit_manifest(run, executors={"judge": "live", "second": "live:other-model"}, provider=provider)
    evaluated = evaluate(first, pack(run))
    assert read(evaluated, "run_index.json")["provider"] == provider
    by_item = {f["item"]: f for f in read(evaluated, "findings.json") if f["check"] == "check_models"}
    assert by_item["judge"]["severity"] == "info"
    assert "story-model" in by_item["judge"]["message"] and "127.0.0.1:9" in by_item["judge"]["message"]
    assert "other-model" in by_item["second"]["message"]
    assert [f for f in problems(evaluated) if f["check"] == "check_models"] == []
    second = tmp_path / "same"
    second.mkdir()
    run = copied_run(story, second)
    edit_manifest(run, executors={"judge": "live", "second": "live:story-model"}, provider=provider)
    evaluated = evaluate(second, pack(run))
    same = [f for f in problems(evaluated) if f["check"] == "check_models"]
    assert len(same) == 1 and same[0]["severity"] == "warning"


# ---------------------------------------------------------------- agreement, replay, and score

def story_book():
    """The story's recorded answer file, the form a reference takes."""
    return json.loads((REFERENCES / "recorded_judge.json").read_text(encoding="utf-8"))


def ran_nodes(run):
    return [json.loads(r.read_text())["node"] for r in sorted((Path(run) / "records").iterdir())]


def notes_of(run, check):
    return [f for f in read(run, "findings.json") if f["check"] == check and f["severity"] == "info"]


@pytest.fixture(scope="module")
def referenced(story, tmp_path_factory):
    """The story run evaluated with the story's recorded answers as the reference."""
    return evaluate(tmp_path_factory.mktemp("llm_runs_reference"), story["tar"], story_book())


def test_read_run_says_whether_a_reference_was_given(story, referenced):
    assert read(story["eval"], "run_index.json")["has_reference"] is False
    assert read(referenced, "run_index.json")["has_reference"] is True


def test_the_story_answers_as_reference_agree_on_every_compared_item(referenced):
    assert problems(referenced) == []
    assert ran_nodes(referenced) == ["read_run", "check_record", "check_models", "compare_reference",
                                     "check_replay", "report"]
    agreement = read(referenced, "agreement.json")
    assert agreement["compared"] is True
    assert agreement["total"] == agreement["agreed"] == 2
    assert agreement["steps"] == [{"node": "locate_passage", "compared": 2, "agreed": 2}]
    notes = {n["item"]: n["message"] for n in notes_of(referenced, "compare_reference")}
    assert set(notes) == {"locate_passage"}
    assert "2 of 2" in notes["locate_passage"]
    report = (referenced / "files" / "report.md").read_text(encoding="utf-8")
    assert "## Agreement" in report and "## Replay and score" in report
    assert "| Step | Compared | Agreed |" in report
    assert "| locate_passage | 2 | 2 |" in report


def test_a_changed_kind_of_answer_in_the_reference_is_one_warning(story, tmp_path):
    reference = story_book()
    reference["locate_passage:r03"] = dict(reference["locate_passage:r03"], kind="paraphrase")
    evaluated = evaluate(tmp_path, story["tar"], reference)
    warnings = problems(evaluated)
    assert [(f["check"], f["severity"], f["item"]) for f in warnings] == [
        ("compare_reference", "warning", "locate_passage:r03")]
    assert "kind" in warnings[0]["message"]
    agreement = read(evaluated, "agreement.json")
    assert agreement["agreed"] == agreement["total"] - 1
    step = next(st for st in agreement["steps"] if st["node"] == "locate_passage")
    assert (step["compared"], step["agreed"]) == (2, 1)


def test_long_text_and_spaced_text_are_not_compared(story, tmp_path):
    reference = story_book()
    reference["locate_passage:r02"] = dict(reference["locate_passage:r02"], text="Worded another way.")
    reference["locate_passage:r03"] = dict(reference["locate_passage:r03"], location="page 2")
    evaluated = evaluate(tmp_path, story["tar"], reference)
    assert problems(evaluated) == []
    assert read(evaluated, "agreement.json")["agreed"] == 2


def test_keys_in_only_one_book_get_one_note(story, tmp_path):
    reference = story_book()
    del reference["locate_passage:r02"]
    reference["locate_passage:r09"] = {"found": True}
    evaluated = evaluate(tmp_path, story["tar"], reference)
    assert problems(evaluated) == []
    only = [n for n in notes_of(evaluated, "compare_reference") if n["item"] == "reference"]
    assert len(only) == 1
    assert "locate_passage:r02" in only[0]["evidence"] and "locate_passage:r09" in only[0]["evidence"]
    assert read(evaluated, "agreement.json")["total"] == 1


def test_two_story_runs_compared_agree_fully(story, tmp_path):
    (tmp_path / "second_story").mkdir()
    (tmp_path / "second_eval").mkdir()
    second_run, _ = run_story(tmp_path / "second_story")
    reference = read(story["eval"], "answer_book.json")
    evaluated = evaluate(tmp_path / "second_eval", pack(second_run), reference)
    assert problems(evaluated) == []
    agreement = read(evaluated, "agreement.json")
    assert agreement["compared"] is True and agreement["total"] == agreement["agreed"] == 2
    assert not [n for n in notes_of(evaluated, "compare_reference") if n["item"] == "reference"]


def test_no_reference_takes_the_skip_branch(story):
    assert ran_nodes(story["eval"]) == ["read_run", "check_record", "check_models", "skip_reference",
                                        "check_replay", "report"]
    events = [json.loads(line) for line in (story["eval"] / "trail.jsonl").read_text().splitlines()]
    assert [e["node"] for e in events if e["event"] == "step_skipped"] == ["compare_reference"]
    assert read(story["eval"], "agreement.json") == {"compared": False, "total": 0, "agreed": 0, "steps": []}
    notes = notes_of(story["eval"], "skip_reference")
    assert len(notes) == 1 and "no reference" in notes[0]["message"].lower()
    report = (story["eval"] / "files" / "report.md").read_text(encoding="utf-8")
    assert "No reference was given." in report


def test_the_story_run_replay_passes_and_its_missing_score_is_a_note(story):
    notes = notes_of(story["eval"], "check_replay")
    assert [n["item"] for n in notes] == ["score.json"]
    assert [f for f in read(story["eval"], "findings.json")
            if f["check"] == "check_replay" and f["severity"] != "info"] == []


def test_a_run_archived_before_verify_gives_a_warning(story, tmp_path):
    run = copied_run(story, tmp_path)
    (run / "verify.json").unlink()
    evaluated = evaluate(tmp_path, pack(run))
    assert [(f["check"], f["severity"], f["item"]) for f in problems(evaluated)] == [
        ("check_replay", "warning", "verify.json")]
    report = (evaluated / "files" / "report.md").read_text(encoding="utf-8")
    assert "holds no verify.json" in report


def test_a_verify_json_with_a_fail_line_is_blocking(story, tmp_path):
    run = copied_run(story, tmp_path)
    first_tool = next(json.loads(r.read_text()) for r in sorted((run / "records").iterdir())
                      if json.loads(r.read_text())["execution"]["type"] == "script")
    output = run / "files" / sorted(first_tool["outputs"])[0]
    output.write_text(output.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    p = vg("verify", "--run", str(run))
    assert p.returncode == 1, p.stdout + p.stderr
    failed = [st for st in json.loads((run / "verify.json").read_text())["steps"]
              if st["verdict"].startswith("FAIL")]
    assert failed
    evaluated = evaluate(tmp_path, pack(run))
    blocking = [f for f in read(evaluated, "findings.json") if f["severity"] == "blocking"]
    assert all(f["check"] == "check_replay" for f in blocking)
    assert sorted(f["item"] for f in blocking) == sorted(
        "{:02d}_{}".format(st["seq"], st["node"]) for st in failed)
    assert {f["evidence"] for f in blocking} == {st["verdict"] for st in failed}


def test_a_missed_fault_in_the_score_is_a_warning(tmp_path):
    run = tmp_path / "selftest_run"
    p = vg("run", "graphs/selftest.yaml", "--run", str(run), "--inputs", "fixtures/selftest",
           "--judge", "recorded:fixtures/selftest/recorded_judge.json")
    assert p.returncode == 0, p.stdout + p.stderr
    truth = yaml.safe_load((ROOT / "fixtures/selftest/truth.yaml").read_text())
    truth["faults"].append({"id": "F2", "check": "judge_items", "item": "w1"})
    truth_path = tmp_path / "truth_extra.yaml"
    truth_path.write_text(yaml.safe_dump(truth))
    assert vg("verify", "--run", str(run)).returncode == 0
    p = vg("score", "--run", str(run), "--truth", str(truth_path))
    assert p.returncode == 1, p.stdout + p.stderr
    evaluated = evaluate(tmp_path, pack(run))
    replay = [f for f in read(evaluated, "findings.json") if f["check"] == "check_replay"]
    assert [(f["severity"], f["item"]) for f in replay if f["severity"] != "info"] == [("warning", "F2")]
    notes = [f for f in replay if f["severity"] == "info"]
    assert len(notes) == 1 and notes[0]["item"] == "score.json"
    assert "0.5" in notes[0]["message"] and "1 of 2" in notes[0]["message"]
    report = (evaluated / "files" / "report.md").read_text(encoding="utf-8")
    assert "holds score.json" in report


def test_verify_replays_every_step_of_the_evaluation_with_a_reference(referenced):
    p = vg("verify", "--run", str(referenced))
    assert p.returncode == 0, p.stdout + p.stderr
    lines = p.stdout.strip().splitlines()
    assert len(lines) == len(list((referenced / "records").iterdir())) == 6
    assert all(line.endswith("replay matches") for line in lines), p.stdout


def test_no_code_imports_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(audit_layer|ospipe|vg)\b")
    files = sorted((ROOT / "implementations" / "llm_runs").glob("*.py"))
    assert files
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)
