"""Publish design A.2, A.4 to A.6, R4 to R7, R10, R12, and R16. Planning and building a repository.

Each test builds a small project in tmp_path and a features home whose
system.yaml is written by hand with every field system setup writes. A
stand-in runner gives the product map that ospipe products --json would give
and writes a session index as the audit layer's write-out session-index
would. The commands run in-process. One test runs the ops_publish check on
what the build wrote, through the layer runner, and one parses every publish
command line of the guide.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import hashlib
import io
import json
import os
import re
import shlex
import tarfile
import tempfile
from pathlib import Path

import pytest
import yaml

from features import cli, layers
from features.publish import assemble, collect, commands, model
from features.setup import system

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "features" / "publish" / "GUIDE.md"
NOW = datetime.datetime(2026, 10, 31, 12, 0, 0, tzinfo=datetime.timezone.utc)

PUBLIC = "S0123456789ab"
OTHER = "Sba9876543210"
MANUSCRIPT = {"name": "manuscript", "source": "manuscript.md", "builds_dir": "builds/manuscript",
              "verification_dir": "verification/manuscript", "to": "docx",
              "manifest": "numbers.yml", "bib": "refs.bib"}
SLIDES = {"name": "slides", "source": "slides.md", "builds_dir": "builds/slides",
          "verification_dir": "verification/slides", "to": "revealjs",
          "manifest": "numbers.yml", "bib": "refs.bib"}
MAKEFILE = ("WORKFLOW ?= ../workflow\n"
            "OSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe\n"
            "\n"
            "manuscript: manuscript.md\n"
            "\t$(OSPIPE) build --manuscript manuscript.md --builds-dir builds/manuscript\n"
            "\n"
            "slides: slides.md\n"
            "\t$(OSPIPE) build --manuscript slides.md --builds-dir builds/slides\n")
LEDGER = ("# Builds\n\n| version | date | git | sha256 | purpose | baseline | reviewed |"
          " verification | runs |\n|---|---|---|---|---|---|---|---|---|\n"
          "| v001 | 2026-10-31 | - | abc | first | - | no |"
          " unverified: prose, citations, data, build | - |\n")
CHECK_KEYS = ["workflow_root", "terms", "allow", "max_file_mb", "warn_file_mb", "rebuild",
              "excluded_folders", "excluded_paths"]
# The scholar's name in the hand-written system.yaml. Neither of its words
# is one the pages use, so the check, which looks for both, finds neither.
SCHOLAR = "Avery Quill"
NAME_TERMS = ["Avery Quill", "Avery", "Quill"]
GITHUB = {"repo_name": "survey-verification", "remote_url": "git@github.example.invalid:a/b.git"}


class Runner(object):
    """Gives the product map and writes a session index, recording every call.

    fail makes the session index exit 1, extra adds a file it would never write,
    and stdout is printed before its last line.
    """

    def __init__(self, products=(MANUSCRIPT,), fail=False, extra=None, stdout=""):
        self.products = [dict(product) for product in products]
        self.fail = fail
        self.extra = extra
        self.stdout = stdout
        self.calls = []
        self.lists = {}

    def __call__(self, layer, args, root=None, cwd=None, env=None, timeout=600):
        self.calls.append((layer, list(args), root, cwd))
        if layer == "ospipe":
            assert list(args) == ["products", "--json"]
            text = json.dumps({"products": self.products, "problems": []})
            return layers.LayerResult(["ospipe"] + list(args), 0, text, "")
        assert layer == "audit_layer" and list(args[:2]) == ["write-out", "session-index"]
        for flag in ("--withhold", "--scrub"):
            if flag in args:
                self.lists[flag] = Path(args[args.index(flag) + 1]).read_text(encoding="utf-8")
        if self.fail:
            return layers.LayerResult(list(args), 1, "", "write-out refused, the stand-in"
                                                         " failure\n")
        out = Path(args[args.index("--out") + 1])
        out.mkdir(parents=True)
        (out / "sessions.csv").write_text(
            "public_id,started_at,harness,contributions\n"
            "%s,2026-10-01T09:00:00Z,claude_code,3\n"
            "%s,2026-10-02T09:00:00Z,forgecode,0\n" % (PUBLIC, OTHER), encoding="utf-8")
        (out / "README.md").write_text("# The AI sessions behind the reports\n", encoding="utf-8")
        (out / "index.html").write_text("<!doctype html>\n<title>Sessions</title>\n",
                                        encoding="utf-8")
        for public_id in (PUBLIC, OTHER):
            (out / (public_id + ".md")).write_text("# %s\n" % public_id, encoding="utf-8")
        if self.extra:
            (out / self.extra).write_text("not part of the index\n", encoding="utf-8")
        return layers.LayerResult(list(args), 0, self.stdout + "wrote the index, 2 sessions\n", "")

    def index_calls(self):
        return [args for layer, args, _, _ in self.calls if layer == "audit_layer"]


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME, the home variables, and the temporary folders at tmp_path."""
    home = tmp_path / "user_home"
    home.mkdir()
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    monkeypatch.delenv("CONNECTIONS_HOME", raising=False)
    monkeypatch.delenv("OBSERVABILITY_HOME", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    return home


def write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def write_json(path, value):
    return write(path, json.dumps(value, indent=2) + "\n")


def make_home(tmp_path, excluded=(), audit_excluded=()):
    """A features home with a system.yaml written by hand, and its audit home."""
    audit = tmp_path / "audit_home"
    write(audit / "settings.yaml", yaml.safe_dump({"excluded_folders": list(audit_excluded)}))
    write(audit / "audit.sqlite", b"")
    record = {
        "schema": system.SCHEMA, "schema_version": system.SCHEMA_VERSION,
        "written_at": "2026-10-31T12:00:00+00:00", "workflow_root": str(ROOT),
        "python": "3.9.5", "scholar_name": SCHOLAR, "harness": "claude_code",
        "audit_home": str(audit), "citation_export": "", "excluded_folders": list(excluded),
        "connect": False, "layers": {"ospipe": {"ok": True}, "audit_layer": {"ok": True},
                                     "vg": {"ok": True}},
        "ready": True, "software": [],
    }
    assert set(system.SYSTEM_FIELDS) <= set(record)
    home = tmp_path / "features_home"
    write(home / "system.yaml", yaml.safe_dump(record, sort_keys=False))
    return home


def results(stream, run_id, items, decisions=()):
    return {"schema": "verification-results", "schema_version": 1, "stream": stream,
            "run_id": run_id, "procedure_version": 0.1, "inputs": {"manuscript.md": "sha256:00"},
            "items": list(items), "decisions": list(decisions)}


def finding(check, severity, message):
    return {"check": check, "severity": severity, "message": message, "evidence": ""}


PROSE = [
    {"id": "c1", "kind": "change", "needs_decision": True, "sessions": [PUBLIC],
     "findings": [finding("rationale_coverage", "blocking", "No reason is on record.")]},
    {"id": "c2", "kind": "change", "needs_decision": True, "sessions": [PUBLIC], "findings": []},
    {"id": "c3", "kind": "change", "needs_decision": False, "findings": []},
]
CITATIONS = [
    {"id": "r1", "citekey": "smith2020", "origin": "ai", "lookup": "found",
     "quote_in_source": "yes", "reason": "It supports the claim.", "sentence": "As shown.",
     "needs_decision": True, "sessions": [PUBLIC], "findings": []},
    {"id": "r2", "citekey": "jones2019", "origin": "scholar", "lookup": "found",
     "needs_decision": False, "findings": []},
]
DATA = [
    {"id": "n1", "kind": "number", "needs_decision": False, "findings": []},
    {"id": "n2", "kind": "number", "needs_decision": False, "findings": []},
]


def build_items(names):
    return [{"id": name, "kind": "deliverable", "needs_decision": False,
             "findings": [finding("check_hardcoding", "blocking", "A number is typed in.")]}
            for name in names]


def write_results(project, verification_dir, prefix, names, streams=("prose", "citations",
                                                                     "data", "build")):
    items = {"prose": PROSE, "citations": CITATIONS, "data": DATA, "build": build_items(names)}
    for stream in streams:
        write_json(project / verification_dir / (stream + ".json"),
                   results(stream, "%s_%s" % (prefix, stream), items[stream]))


def make_project(tmp_path, products=(MANUSCRIPT,), built=("manuscript",), name="study"):
    """A small verified project: each product's results in its verification folder."""
    project = tmp_path / name
    write(project / "Makefile", MAKEFILE)
    write(project / "manuscript.md", "# A survey\n\nThe text.\n")
    write(project / "slides.md", "# Slides\n")
    write(project / "README.md", "# Project guide\n")
    write(project / "numbers.yml", "numbers:\n  n: 3\n  m: 4\n")
    write(project / "refs.bib", "@article{smith2020,\n}\n@book{jones2019,\n}\n")
    write(project / "data.csv", "a,b\n1,2\n")
    write(project / "private.csv", "name\nsomeone\n")
    write(project / ".gitignore", "private.csv\n")
    write(project / "notes" / "ideas.md", "An idea.\n")
    write(project / "sources" / "smith2020.txt", "The source text.\n")
    for product in built:
        write(project / "builds" / product / "BUILDS.md", LEDGER)
        write(project / "builds" / product / "v001.md", "# Built\n")
    seen = {}
    for product in products:
        seen.setdefault(product["verification_dir"], []).append(product["name"])
    for verification_dir, names in seen.items():
        write_results(project, verification_dir, "+".join(names) if len(names) > 1 else names[0],
                      names)
    return project


def write_answers(tmp_path, given):
    return write(tmp_path / "answers.yaml", yaml.safe_dump(given, sort_keys=False))


def publish(tmp_path, project, out=None, answers=None, runner=None, write_files=True,
            home=None, runs=None):
    home = home or make_home(tmp_path)
    path = str(write_answers(tmp_path, answers)) if answers is not None else None
    return assemble.run_publish(str(project), str(out) if out is not None else None, path,
                                str(runs or tmp_path / "runs"), str(home), NOW,
                                runner=runner or Runner(), write=write_files)


def files_in(folder):
    folder = Path(folder)
    return sorted(str(path.relative_to(folder)).replace(os.sep, "/")
                  for path in folder.rglob("*") if path.is_file())


def snapshot(folder):
    return dict((path, (Path(folder) / path).read_bytes()) for path in files_in(folder))


def members(data):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return archive.getmembers()


def tar_files(data):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return dict((member.name, archive.extractfile(member).read())
                    for member in archive.getmembers())


def run_command(argv, monkeypatch, runner=None):
    monkeypatch.setattr(commands, "run_layer", runner or Runner())
    out = io.StringIO()
    err = io.StringIO()
    parser, _ = cli._parser()
    options = parser.parse_args(argv)
    code = options.run(options, out=out, err=err, now=NOW)
    return code, out.getvalue(), err.getvalue()


# publish plan.


def test_plan_writes_nothing_and_runs_no_session_index(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    home = make_home(tmp_path)
    before = snapshot(tmp_path)
    runner = Runner()
    code, out, err = run_command(["publish", "plan", str(project), "--home", str(home),
                                  "--runs", str(tmp_path / "runs")], monkeypatch, runner)
    assert code == 0, err
    assert snapshot(tmp_path) == before
    assert runner.index_calls() == []
    assert "Products\n  manuscript, latest v001 of 2026-10-31, unverified: prose, citations," \
           " data, build\n" in out
    assert "  manuscript/prose: run manuscript_prose, no report whose results match" in out
    assert "Missing\n  none\n" in out
    assert "Left out\n" in out and "  notes/: the scholar's notes\n" in out
    assert "  private.csv: matched by private.csv in .gitignore\n" in out
    assert "Session index\n  will be written from the record in %s\n" % (tmp_path / "audit_home") \
        in out


def test_plan_json_is_one_object_with_the_same_content(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    home = make_home(tmp_path)
    code, out, err = run_command(["publish", "plan", str(project), "--home", str(home),
                                  "--runs", str(tmp_path / "runs"), "--json"], monkeypatch)
    assert code == 0, err
    found = json.loads(out)
    assert list(found) == ["project", "products", "reports", "missing", "copied", "left_out",
                           "session_index", "notes", "counts"]
    assert found["products"][0]["name"] == "manuscript"
    assert [(r["group"], r["stream"]) for r in found["reports"]] == [
        ("manuscript", stream) for stream in model.STREAMS]
    assert found["counts"]["prose.changes"] == 3
    assert "sessions.indexed" not in found["counts"]


def test_a_stop_prints_one_line_and_exits_1(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    code, out, err = run_command(["publish", "plan", str(project), "--home",
                                  str(tmp_path / "no_home")], monkeypatch)
    assert code == 1 and out == ""
    assert err.startswith("publish plan stopped, there is no ")
    assert system.COMMAND in err
    home = make_home(tmp_path)
    answers = write_answers(tmp_path, {"title": 3})
    code, out, err = run_command(["publish", "build", str(project), "--out",
                                  str(tmp_path / "public"), "--home", str(home), "--answers",
                                  str(answers)], monkeypatch)
    assert code == 1 and out == ""
    assert err == "publish build stopped, the answers file's title must be text\n"
    assert not (tmp_path / "public").exists()


# publish build.


def test_build_writes_the_repository_and_both_inputs_folders(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    result = publish(tmp_path, project, out, answers={
        "check": {"terms": ["Jordan Doe", "test scholar"], "allow": [{"path": "project/*.tar:*"}],
                  "rebuild": False},
        "github": GITHUB})
    assert files_in(out) == sorted(result.plan)
    for path in assemble.GENERATED:
        assert (out / path).is_file(), path
    assert (out / "project" / "Makefile").read_text(encoding="utf-8").startswith(
        "WORKFLOW ?= ../../verifiable-social-science-workflow\n")
    for path in ("prose", "citations", "data", "build"):
        assert (out / "project" / "verification" / "manuscript" / path / "results.json").read_bytes() \
            == (project / "verification" / "manuscript" / (path + ".json")).read_bytes()
    assert files_in(out / "project" / "sessions") == sorted(
        ["README.md", "index.html", "sessions.csv", PUBLIC + ".md", OTHER + ".md"])
    for gone in ("notes/ideas.md", "sources/smith2020.txt", "private.csv"):
        assert not (out / "project" / gone).exists(), gone

    check = Path(str(out) + ".check")
    assert sorted(os.listdir(str(check))) == ["left_out.json", "publish_check.yaml", "repo.tar"]
    settings = yaml.safe_load((check / "publish_check.yaml").read_text(encoding="utf-8"))
    assert list(settings) == CHECK_KEYS
    assert settings["workflow_root"] == str(ROOT)
    assert settings["terms"] == ["Jordan Doe", "test scholar"] + NAME_TERMS
    assert settings["allow"] == [{"path": "project/*.tar:*"}]
    assert settings["rebuild"] is False and settings["excluded_folders"] == []
    assert sorted(tar_files((check / "repo.tar").read_bytes())) == files_in(out)
    record = json.loads((check / "left_out.json").read_text(encoding="utf-8"))
    assert record["schema"] == "publish-left-out" and record["schema_version"] == 1
    assert {"path": "private.csv", "rule": "gitignore",
            "why": "matched by private.csv in .gitignore"} in record["left_out"]

    github = Path(str(out) + ".github")
    assert sorted(os.listdir(str(github))) == ["github.yaml", "project.tar"]
    settings = yaml.safe_load((github / "github.yaml").read_text(encoding="utf-8"))
    assert settings["project_dir"] == str(out)
    assert settings["apply"] is False
    assert settings["repo_name"] == "survey-verification"
    assert settings["visibility"] == "private" and settings["create_with"] == "none"
    assert settings["remote_url"] == GITHUB["remote_url"]
    assert "schema" not in settings
    assert (github / "project.tar").read_bytes() == (check / "repo.tar").read_bytes()


def check_settings_of(out):
    return yaml.safe_load(Path(str(out) + ".check", "publish_check.yaml").read_text(
        encoding="utf-8"))


def manifest_of(out):
    return json.loads((Path(out) / "docs" / "publish_manifest.json").read_text(encoding="utf-8"))


def test_an_anonymous_build_scrubs_and_checks_the_name_and_its_words(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    runner = Runner()
    result = publish(tmp_path, project, out, runner=runner,
                     answers={"check": {"terms": ["avery", "Jordan Doe"]}})
    assert result.collected.answers.anonymous is True
    assert runner.lists == {"--scrub": "Avery Quill\nAvery\nQuill\n"}
    settings = check_settings_of(out)
    assert settings["terms"] == ["avery", "Jordan Doe", "Avery Quill", "Quill"]
    assert settings["rebuild"] is True
    assert manifest_of(out)["anonymous"] is True
    assert not Path(str(out) + ".github").exists()


def test_a_build_that_is_not_anonymous_neither_scrubs_nor_checks_the_name(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    runner = Runner()
    publish(tmp_path, project, out, runner=runner,
            answers={"anonymous": False, "check": {"terms": ["Jordan Doe"]}})
    assert "--scrub" not in runner.index_calls()[0] and runner.lists == {}
    assert check_settings_of(out)["terms"] == ["Jordan Doe"]
    manifest = manifest_of(out)
    assert manifest["anonymous"] is False
    assert list(manifest)[:7] == ["schema", "schema_version", "assembled_on", "workflow",
                                  "make_style", "anonymous", "harness_names"]

    # Scrub terms the answers give still reach the session index, but not the check.
    out = tmp_path / "public2"
    runner = Runner()
    publish(tmp_path, project, out, runner=runner,
            answers={"anonymous": False, "sessions": {"scrub_terms": ["Avery"]}})
    assert runner.lists == {"--scrub": "Avery\n"}
    assert check_settings_of(out)["terms"] == []


def test_walked_files_that_a_page_or_a_report_replaces_are_left_out(tmp_path):
    project = make_project(tmp_path)
    folder = project / "verification" / "manuscript" / "prose"
    write(folder / "report.md", "# An older prose report\n")
    write_json(folder / "results.json", results("prose", "manuscript_prose", PROSE[:1]))
    run = tmp_path / "runs" / "manuscript_prose"
    write_json(run / "results.json", results("prose", "manuscript_prose", PROSE))
    write(run / "files" / "report.md", "# The prose report\n")
    out = tmp_path / "public"
    result = publish(tmp_path, project, out)
    assert (out / "project" / "verification" / "manuscript" / "prose" / "report.md").read_text(
        encoding="utf-8") == "# The prose report\n"
    replaced = dict((path, why) for path, rule, why in result.left_out_local
                    if rule == "replaced")
    assert replaced == {
        "README.md": "replaced by the generated file table",
        "verification/manuscript/prose/report.md": "replaced by the report of run manuscript_prose",
        "verification/manuscript/prose/results.json":
            "replaced by verification/manuscript/prose.json, the project's results file, which"
            " every count reads",
    }
    assert (out / "project" / "README.md").read_text(encoding="utf-8").startswith(
        "# The project folder\n")


def test_nothing_is_written_when_the_github_block_lacks_a_remote(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, out, answers={"github": {"repo_name": "r"}})
    assert "the github block needs remote_url when create_with is none" in str(raised.value)
    assert not out.exists()
    assert not Path(str(out) + ".check").exists()


@pytest.mark.parametrize("case, words", [
    ("index_fails", "the session index could not be written, write-out refused, the stand-in"
                    " failure; set sessions: {skip: true}"),
    ("index_extra", "the session index wrote secret.txt, a file publish does not publish"),
    ("foreign_file", "holds files this command did not write, such as notes.txt"),
    ("out_in_project", "lies inside the project folder"),
    ("bad_answers", "the answers file's exclude must be"),
])
def test_nothing_is_written_when_the_build_stops(tmp_path, case, words):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    runner = Runner(fail=case == "index_fails", extra="secret.txt" if case == "index_extra"
                    else None)
    answers = {"exclude": ["../x"]} if case == "bad_answers" else None
    if case == "foreign_file":
        write(out / "notes.txt", "The scholar's own file.\n")
    if case == "out_in_project":
        out = project / "public"
    home = make_home(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, out, answers=answers, runner=runner, home=home)
    assert words in str(raised.value)
    after = snapshot(tmp_path)
    after.pop("answers.yaml", None)
    before.pop("answers.yaml", None)
    assert after == before
    assert os.listdir(str(tmp_path / "temporary")) == []


def test_an_excluded_folder_in_the_audit_settings_stops_the_build(tmp_path, private_home):
    study = private_home / "private_records" / "study"
    project = make_project(study.parent, name="study")
    home = make_home(tmp_path, excluded=(), audit_excluded=["~/private_records"])
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, tmp_path / "public", home=home)
    assert "the project folder lies inside a folder the scholar excluded" in str(raised.value)
    assert not (tmp_path / "public").exists()


def test_an_out_folder_inside_an_excluded_folder_is_never_opened(tmp_path, private_home,
                                                                 monkeypatch):
    project = make_project(tmp_path)
    out = private_home / "Teaching" / "public"
    write(out / "grades.csv", "a student record\n")
    home = make_home(tmp_path, audit_excluded=["~/Teaching"])

    def never(folder):
        raise AssertionError("an excluded folder was opened: %s" % folder)
    monkeypatch.setattr(assemble, "owned_out", never)
    monkeypatch.setattr(assemble, "owned_inputs", lambda folder, names: never(folder))
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, out, home=home)
    assert "lies inside a folder the scholar excluded" in str(raised.value)
    assert files_in(out) == ["grades.csv"]


def test_a_changed_file_in_out_stops_the_next_build(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    home = make_home(tmp_path)
    publish(tmp_path, project, out, home=home)
    write(out / "README.md", "# A README typed by hand\n")
    before = snapshot(tmp_path)
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, out, home=home)
    assert str(raised.value).endswith("holds a file changed since it was written: README.md")
    assert snapshot(tmp_path) == before


def test_an_out_folder_whose_manifest_names_a_path_outside_it_is_refused(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    write_json(out / "docs" / "publish_manifest.json",
               {"schema": "publish-repo", "schema_version": 1, "files": {"../x": "sha256:0"}})
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, out)
    assert "lists ../x, a path outside it" in str(raised.value)


def test_a_second_build_replaces_the_first_and_an_added_exclude_removes_a_file(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    first = publish(tmp_path, project, out)
    assert (out / "project" / "data.csv").is_file()
    assert "project/data.csv" in tar_files(first.check_plan["repo.tar"])
    write(out / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(out / "project" / ".DS_Store", b"\0")
    second = publish(tmp_path, project, out, answers={"exclude": ["data.csv"]})
    assert not (out / "project" / "data.csv").exists()
    assert "project/data.csv" not in tar_files(Path(str(out) + ".check", "repo.tar").read_bytes())
    assert (out / ".git" / "HEAD").is_file()
    manifest = json.loads((out / "docs" / "publish_manifest.json").read_text(encoding="utf-8"))
    assert "project/data.csv" not in manifest["files"]
    kept = [path for path in files_in(out) if not path.startswith(".git/")
            and not path.endswith(".DS_Store")]
    assert kept == sorted(second.plan)
    assert {"rule": "exclude", "count": 1} in manifest["left_out"]["rules"]
    third = publish(tmp_path, project, out, answers={"exclude": ["data.csv"]})
    assert third.plan == second.plan


def test_an_out_folder_holding_only_git_is_written_and_its_git_is_kept(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    write(out / ".git" / "HEAD", "ref: refs/heads/main\n")
    result = publish(tmp_path, project, out)
    assert (out / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    assert [path for path in files_in(out) if not path.startswith(".git/")] == sorted(result.plan)


def test_a_foreign_file_in_the_check_folder_stops_the_build(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    write(Path(str(out) + ".check") / "mine.txt", "The scholar's own file.\n")
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, out)
    assert "holds files this command did not write, such as mine.txt" in str(raised.value)
    assert not out.exists()


def test_a_long_dash_in_the_answers_gives_a_note(tmp_path):
    project = make_project(tmp_path)
    result = publish(tmp_path, project, answers={"summary": u"The summary \u2014 with a dash."})
    assert "README.md holds a long or en dash from the answers' own text, which the page keeps" \
           " as given" in result.notes


def test_the_plan_says_when_the_audit_home_has_no_store(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    home = make_home(tmp_path)
    (tmp_path / "audit_home" / "audit.sqlite").unlink()
    code, out, err = run_command(["publish", "plan", str(project), "--home", str(home)],
                                 monkeypatch)
    assert code == 0, err
    assert "  the audit home holds no audit.sqlite, so publish build would stop; set sessions:" \
           " {skip: true} in the answers file to publish without the index\n" in out


def test_the_plan_says_when_system_yaml_gives_no_audit_home(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    home = name_home(tmp_path, SCHOLAR)
    path = home / "system.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["audit_home"] = ""
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    code, out, err = run_command(["publish", "plan", str(project), "--home", str(home)],
                                 monkeypatch)
    assert code == 0, err
    assert "None" not in out
    assert "  system.yaml gives no audit_home, so publish build would stop; set sessions:" \
           " {skip: true} in the answers file to publish without the index\n" in out


def test_advice_for_this_machine_is_printed_but_not_published(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    result = publish(tmp_path, project, out)
    advice = [note for note in result.notes if note.startswith("the answers give no repo_url")]
    assert advice
    assert not [note for note in manifest_of(out)["notes"] if "repo_url" in note]


def test_repo_tar_is_the_same_every_time(tmp_path):
    project = make_project(tmp_path)
    first = publish(tmp_path, project, tmp_path / "one")
    second = publish(tmp_path, project, tmp_path / "two")
    data = Path(str(tmp_path / "one") + ".check", "repo.tar").read_bytes()
    assert data == Path(str(tmp_path / "two") + ".check", "repo.tar").read_bytes()
    assert first.check_plan["repo.tar"] == second.check_plan["repo.tar"] == data
    assert data[257:265] == b"ustar\x0000"
    found = members(data)
    assert [member.name for member in found] == sorted(member.name for member in found)
    for member in found:
        assert member.isfile()
        assert (member.mtime, member.mode, member.uid, member.gid, member.uname, member.gname) \
            == (0, 0o644, 0, 0, "", "")
    assert assemble.pack({"b": b"2", "a": b"1"}) == assemble.pack({"a": b"1", "b": b"2"})


def test_the_manifest_lists_every_file_by_a_relative_path(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    publish(tmp_path, project, out, answers={"exclude": ["data.csv"]})
    text = (out / "docs" / "publish_manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(text)
    assert manifest["schema"] == "publish-repo" and manifest["schema_version"] == 1
    assert manifest["assembled_on"] == "2026-10-31"
    on_disk = set(files_in(out)) - {"docs/publish_manifest.json"}
    assert set(manifest["files"]) == on_disk
    for path, sha in manifest["files"].items():
        assert not path.startswith("/") and ".." not in path.split("/")
        assert sha == "sha256:" + hashlib.sha256((out / path).read_bytes()).hexdigest()
    assert list(manifest["generated"]) == list(assemble.GENERATED)
    assert str(tmp_path) not in text and os.path.realpath(str(tmp_path)) not in text
    assert "private.csv" not in text and "data.csv" not in text
    assert manifest["left_out"]["fixed"] == ["sources/", "notes/"]
    assert {"rule": "gitignore", "count": 1} in manifest["left_out"]["rules"]
    assert {"rule": "exclude", "count": 1} in manifest["left_out"]["rules"]
    assert manifest["rewritten"][0]["path"] == "project/Makefile"
    assert [(r["group"], r["stream"], r["results"]) for r in manifest["reports"]] == [
        ("manuscript", stream, "project/verification/manuscript/%s/results.json" % stream)
        for stream in model.STREAMS]
    product = manifest["products"][0]
    assert product["bib"] == "refs.bib" and product["numbers"] == "numbers.yml"
    assert product["latest"] == {"version": "v001", "date": "2026-10-31", "sha256": "abc",
                                 "epoch": 1793404800}
    assert manifest["counts"]["prose.changes"] == 3
    assert manifest["counts"]["sessions.indexed"] == 2


def test_products_that_share_a_verification_folder_count_and_link_once(tmp_path):
    shared_manuscript = dict(MANUSCRIPT, verification_dir="verification")
    shared_slides = dict(SLIDES, verification_dir="verification")
    project = make_project(tmp_path, products=(shared_manuscript, shared_slides),
                           built=("manuscript", "slides"))
    runner = Runner(products=(shared_manuscript, shared_slides))
    out = tmp_path / "public"
    result = publish(tmp_path, project, out, runner=runner)
    assert result.counts["prose.changes"] == 3
    assert result.counts["citations.rows"] == 2
    assert result.counts["decisions.undecided"] == 3
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert readme.count("(project/verification/prose/report.md)") == 0
    assert readme.count("(project/verification/prose/results.json)") == 1
    manifest = json.loads((out / "docs" / "publish_manifest.json").read_text(encoding="utf-8"))
    assert [group["products"] for group in manifest["groups"]] == [["manuscript", "slides"]]
    assert manifest["groups"][0]["label"] == "manuscript and slides"
    assert len(manifest["reports"]) == 4
    given = runner.index_calls()[0]
    found = given[given.index("--results") + 1:given.index("--scrub")]
    assert found == [str(project / "verification" / (stream + ".json"))
                     for stream in model.STREAMS]


def test_a_product_with_no_build_has_no_build_keys(tmp_path):
    project = make_project(tmp_path, products=(MANUSCRIPT, SLIDES), built=("manuscript",))
    out = tmp_path / "public"
    result = publish(tmp_path, project, out, runner=Runner(products=(MANUSCRIPT, SLIDES)))
    assert not [key for key in result.counts if key.startswith("builds.slides.")]
    assert result.counts["builds.manuscript.latest"] == "v001"
    manifest = json.loads((out / "docs" / "publish_manifest.json").read_text(encoding="utf-8"))
    slides = [product for product in manifest["products"] if product["name"] == "slides"][0]
    assert slides["latest"] is None and slides["verification"] is None
    # No ledger row marks it, so its state says it has no build, not that it waits.
    assert slides["state"] == assemble.UNBUILT_STATE == "no numbered build yet"
    states = dict((product["name"], product["state"]) for product in manifest["products"])
    assert states["manuscript"] == "unverified until the scholar decides"
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "`slides` has no numbered build yet." in readme
    assert "SOURCE_DATE_EPOCH=1793404800 make manuscript" in readme
    assert "make slides" not in readme


def test_sessions_skip_publishes_no_index(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    runner = Runner()
    result = publish(tmp_path, project, out, answers={"sessions": {"skip": True}}, runner=runner)
    assert runner.index_calls() == []
    assert not (out / "project" / "sessions").exists()
    assert not [key for key in result.counts if key.startswith("sessions.")]
    assert "sessions/sessions.csv" not in (out / "README.md").read_text(encoding="utf-8")
    assert "The session index is not published" in (out / "docs" / "record.md").read_text(
        encoding="utf-8")


def test_the_session_index_gets_absolute_paths_and_only_the_flags_with_values(tmp_path):
    project = make_project(tmp_path)
    runner = Runner()
    publish(tmp_path, project, tmp_path / "public", runner=runner)
    given = runner.index_calls()[0]
    assert given[:4] == ["write-out", "session-index", "--home", str(tmp_path / "audit_home")]
    assert given[given.index("--project") + 1] == str(project)
    assert os.path.isabs(given[given.index("--out") + 1])
    assert given[given.index("--results") + 1:given.index("--results") + 5] == [
        "manuscript=%s" % (project / "verification" / "manuscript" / (stream + ".json"))
        for stream in model.STREAMS]
    for flag in ("--also-folder", "--withhold", "--no-summaries"):
        assert flag not in given
    assert runner.lists == {"--scrub": "".join(term + "\n" for term in NAME_TERMS)}
    assert os.listdir(str(tmp_path / "temporary")) == []

    earlier = tmp_path / "earlier_folder"
    earlier.mkdir()
    runner = Runner(stdout="set aside %s, since a later results file of its stream was given\n"
                           "the results files name session Sffffffffffff, which the index does"
                           " not list\n" % (project / "verification" / "manuscript"
                                            / "prose.json"))
    result = publish(tmp_path, project, tmp_path / "public2", runner=runner, answers={
        "sessions": {"also_folders": [str(earlier)], "no_summaries": True, "withhold": [PUBLIC],
                     "scrub_terms": []}})
    given = runner.index_calls()[0]
    assert given[given.index("--also-folder") + 1] == str(earlier)
    # An empty scrub list still withholds the scholar's full name in an anonymous build.
    assert "--no-summaries" in given and "--scrub" in given
    assert runner.lists == {"--withhold": PUBLIC + "\n", "--scrub": SCHOLAR + "\n"}
    assert "the session index set aside verification/manuscript/prose.json, since a later" \
           " results file of its stream was given" in result.notes
    assert "the results files name session Sffffffffffff, which the index does not list" \
        in result.notes
    assert os.listdir(str(tmp_path / "temporary")) == []


def test_the_build_prints_both_run_commands_read_from_the_knowledge_base(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    home = make_home(tmp_path)
    out = tmp_path / "public"
    answers = write_answers(tmp_path, {"github": GITHUB})
    code, printed, err = run_command(["publish", "build", str(project), "--out", str(out),
                                      "--home", str(home), "--answers", str(answers),
                                      "--runs", str(tmp_path / "runs")], monkeypatch)
    assert code == 0, err
    lines = printed.splitlines()
    assert lines[0] == "Wrote %s" % out
    check = lines[lines.index("Check it before it goes public") + 1]
    assert "vg.py run graphs/ops_publish.yaml" in check
    assert "--inputs %s`" % shlex.quote(str(out) + ".check") in check
    assert commands.run_command(ROOT, commands.PUBLISH_ENTRY) in check.replace(
        shlex.quote(str(out) + ".check"), "<inputs folder>")
    github = lines[lines.index("Put it on GitHub") + 1]
    assert "vg.py run graphs/ops_github.yaml" in github
    assert shlex.quote(str(out) + ".github") in github
    assert github.endswith("only plans until github.yaml sets apply: true.")

    code, printed, err = run_command(["publish", "build", str(project), "--out",
                                      str(tmp_path / "public2"), "--home", str(home), "--runs",
                                      str(tmp_path / "runs")], monkeypatch)
    assert code == 0, err
    assert "Put it on GitHub\n  Add a github block to the answers file to write its inputs\n" \
        in printed


def test_a_missing_knowledge_base_entry_gives_the_fixed_command(tmp_path):
    assert commands.run_command(tmp_path, commands.PUBLISH_ENTRY) == ""
    line = commands.check_command(str(tmp_path), "/x/out.check")
    assert "vg.py run graphs/ops_publish.yaml" in line and "--inputs /x/out.check`" in line
    line = commands.github_command(str(tmp_path), "/x/out.github")
    assert "vg.py run graphs/ops_github.yaml" in line and "--inputs /x/out.github`" in line


def run_check(out, run):
    """The findings of the real ops_publish check on what a build wrote."""
    done = layers.run_layer("vg", ["run", "graphs/ops_publish.yaml", "--run", str(run),
                                   "--inputs", str(out) + ".check"], root=str(ROOT),
                            env={"PYTHONDONTWRITEBYTECODE": "1"})
    assert done.returncode == 0, done.stdout + done.stderr
    found = json.loads((Path(run) / "files" / "findings.json").read_text(encoding="utf-8"))
    return found if isinstance(found, list) else found["items"]


def test_the_ops_publish_check_finds_no_problem_in_a_build(tmp_path):
    project = make_project(tmp_path)
    # The scholar decides as the guide says, by "the scholar", which is not a term,
    # so the anonymous build's check, which looks for the scholar's name, passes.
    write_json(project / "verification" / "manuscript" / "prose.json",
               results("prose", "manuscript_prose", PROSE, decisions=[
                   {"item": "c1", "decision": "approved", "by": "the scholar",
                    "at": "2026-10-31", "run_id": "manuscript_prose"}]))
    out = tmp_path / "public"
    publish(tmp_path, project, out, answers={"repo_url": "https://example.org/a/b",
                                             "check": {"rebuild": False}})
    run = tmp_path / "check_run"
    items = run_check(out, run)
    problems = [(item["check"], item["item"], item["message"]) for item in items
                if item["severity"] != "info"]
    assert problems == []
    recount = json.loads((run / "files" / "counts.json").read_text(encoding="utf-8"))
    assert recount["differ"] == 0 and recount["checked"] > 40
    assert recount["files_unlisted"] == 0 and recount["files_changed"] == 0


def test_a_decision_signed_with_the_scholars_name_blocks_an_anonymous_build(tmp_path):
    project = make_project(tmp_path)
    write_json(project / "verification" / "manuscript" / "prose.json",
               results("prose", "manuscript_prose", PROSE, decisions=[
                   {"item": "c1", "decision": "approved", "by": SCHOLAR, "at": "2026-10-31",
                    "run_id": "manuscript_prose"}]))
    out = tmp_path / "public"
    publish(tmp_path, project, out, answers={"repo_url": "https://example.org/a/b",
                                             "check": {"rebuild": False}})
    items = run_check(out, tmp_path / "check_run")
    blocked = sorted(item["item"] for item in items
                     if item["severity"] == "blocking" and item["evidence"] == "term 1")
    assert blocked == ["project/verification/manuscript/prose.json",
                       "project/verification/manuscript/prose/results.json"]


def test_the_repository_gets_its_own_gitignore_listed_as_generated(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    result = publish(tmp_path, project, out)
    assert (out / ".gitignore").read_bytes() == b".DS_Store\n"
    assert result.plan[".gitignore"] == b".DS_Store\n"
    manifest = manifest_of(out)
    sha = "sha256:" + hashlib.sha256(b".DS_Store\n").hexdigest()
    assert manifest["generated"][".gitignore"] == sha
    assert manifest["files"][".gitignore"] == sha
    assert ".gitignore" in tar_files(result.check_plan["repo.tar"])
    # The project's own .gitignore is copied byte for byte, as before.
    assert (out / "project" / ".gitignore").read_bytes() == (project / ".gitignore").read_bytes()


def test_an_excluded_folder_inside_the_project_stops_the_build_unopened(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    write(project / "class" / "grades.csv", "a student record\n")
    home = make_home(tmp_path, audit_excluded=[str(project / "class")])
    runner = Runner()
    before = snapshot(tmp_path)
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, tmp_path / "public", runner=runner, home=home)
    assert str(raised.value) == (
        "an excluded folder lies inside the project, so the session index could name its"
        " files; move it out or leave the project out of the index with sessions: {skip: true}")
    assert runner.calls == []
    assert snapshot(tmp_path) == before

    # With the index skipped, the folder is left out unopened and the build goes on.
    result = publish(tmp_path, project, tmp_path / "public", runner=runner, home=home,
                     answers={"sessions": {"skip": True}})
    assert not (tmp_path / "public" / "project" / "class").exists()
    assert not [path for path in result.collected.project_files if path.startswith("class")]
    assert ("class/", "excluded_folder") in [(path, rule) for path, rule, _ in
                                             result.left_out_local]
    assert runner.index_calls() == []


def test_an_excluded_folder_inside_the_output_folder_is_never_walked(tmp_path, monkeypatch):
    project = make_project(tmp_path)
    out = tmp_path / "docs_folder"
    write(out / "Restricted" / "a_student_record.csv", "a student record\n")
    home = make_home(tmp_path, excluded=[str(out / "Restricted")])
    walked = []
    real_walk = os.walk

    def watched(folder, *args, **kwargs):
        walked.append(str(folder))
        return real_walk(folder, *args, **kwargs)
    monkeypatch.setattr(assemble.os, "walk", watched)
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, out, home=home)
    assert "holds a folder the scholar excluded" in str(raised.value)
    assert "a_student_record" not in str(raised.value) and "Restricted" not in str(raised.value)
    assert not [folder for folder in walked if folder.startswith(str(out))]
    assert files_in(out) == ["Restricted/a_student_record.csv"]


def test_the_check_settings_name_each_excluded_folder_inside_the_project(tmp_path):
    project = make_project(tmp_path)
    write(project / "class" / "grades.csv", "a student record\n")
    home = make_home(tmp_path, audit_excluded=[str(project / "class")])
    out = tmp_path / "public"
    publish(tmp_path, project, out, home=home, answers={"sessions": {"skip": True}})
    assert check_settings_of(out)["excluded_paths"] == ["project/class"]


def name_home(tmp_path, name):
    home = make_home(tmp_path)
    path = home / "system.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["scholar_name"] = name
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    return home


def test_a_word_of_the_name_in_a_page_publish_writes_stops_the_build(tmp_path):
    # A surname that is an ordinary word, such as Read, is in the pages publish writes,
    # so the check would block them; the build stops and says how to choose the words.
    project = make_project(tmp_path)
    home = name_home(tmp_path, "Ann Read")
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, tmp_path / "public", home=home)
    assert str(raised.value).startswith("the word 'Read' of the scholar's name, which the check looks"
                                        " for in an anonymous build, is in README.md")
    assert "give sessions scrub_terms that leave it out" in str(raised.value)
    assert not (tmp_path / "public").exists()
    out = tmp_path / "public"
    result = publish(tmp_path, project, out, home=home, answers={"sessions": {"scrub_terms": ["Ann"]}})
    assert check_settings_of(out)["terms"] == ["Ann Read", "Ann"]
    assert collect.WORDS_LEFT_NOTE % (1, "word", "it", "it") in result.notes


def test_a_project_gitignore_that_would_hide_a_published_file_stops_the_build(tmp_path):
    project = make_project(tmp_path)
    write(project / ".gitignore", "private.csv\n*.html\n")
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, tmp_path / "public")
    assert str(raised.value).startswith("the line '*.html' of project/.gitignore would hide"
                                        " project/sessions/index.html, which publish writes, from git")
    write(project / ".gitignore", "private.csv\nreport.md\n")
    write_json(tmp_path / "runs" / "manuscript_prose" / "results.json",
               results("prose", "manuscript_prose", PROSE))
    write(tmp_path / "runs" / "manuscript_prose" / "files" / "report.md", "# The prose report\n")
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, tmp_path / "public")
    assert "project/verification/manuscript/prose/report.md" in str(raised.value)
    assert not (tmp_path / "public").exists()


def test_a_run_decided_after_its_results_reached_the_project_stops_the_build(tmp_path):
    project = make_project(tmp_path)
    decided = [{"item": "c1", "decision": "approved", "by": "the scholar", "at": "2026-10-31",
                "run_id": "manuscript_prose"}]
    run = tmp_path / "runs" / "manuscript_prose"
    write_json(run / "results.json", results("prose", "manuscript_prose", PROSE, decisions=decided))
    write(run / "report_decided.md", "# The prose report, 1 approved\n")
    with pytest.raises(model.PublishError) as raised:
        publish(tmp_path, project, tmp_path / "public")
    assert str(raised.value) == (
        "run manuscript_prose was decided after its results reached the project, so the README"
        " would count other decisions than its report shows; run handoffs/results_to_pipeline.py"
        " again to hand the decided results to the project, then build again")
    assert not (tmp_path / "public").exists()


def test_a_file_in_out_that_cannot_be_read_stops_the_next_build(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    home = make_home(tmp_path)
    publish(tmp_path, project, out, home=home)
    os.chmod(str(out / "README.md"), 0)
    try:
        with pytest.raises(model.PublishError) as raised:
            publish(tmp_path, project, out, home=home)
    finally:
        os.chmod(str(out / "README.md"), 0o644)
    assert "holds a file that cannot be read, README.md (" in str(raised.value)


def test_an_ssh_repository_address_gives_a_web_clone_line_the_check_passes(tmp_path):
    project = make_project(tmp_path)
    out = tmp_path / "public"
    publish(tmp_path, project, out, answers={
        "repo_url": "git@github.com:example-scholar/story-verification.git",
        "sessions": {"skip": True}, "check": {"rebuild": False}})
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "git clone https://github.com/example-scholar/story-verification\n" in readme
    assert "git@" not in readme
    items = run_check(out, tmp_path / "check_run")
    assert [item for item in items if item["severity"] == "blocking"] == []


def test_phase_decisions_and_a_state_that_waits_for_a_build_are_rechecked(tmp_path):
    project = make_project(tmp_path)
    items = {"prose": PROSE, "citations": CITATIONS, "data": DATA, "build": build_items(["manuscript"])}
    for stream in ("prose", "citations", "data", "build"):
        run_id = "manuscript_%s" % stream
        decided = [{"item": item["id"], "decision": "approved", "by": "the scholar",
                    "at": "2026-10-31", "run_id": run_id}
                   for item in items[stream] if item.get("needs_decision")]
        write_json(project / "verification" / "manuscript" / (stream + ".json"),
                   results(stream, run_id, items[stream], decisions=decided))
    phase = results("data_phases", "manuscript_data_analysis", [
        {"id": "d01", "kind": "description", "needs_decision": True, "findings": []}])
    write_json(project / "verification" / "manuscript" / "data_analysis" / "results.json", phase)
    out = tmp_path / "public"
    result = publish(tmp_path, project, out, answers={"repo_url": "https://example.org/a/b",
                                                      "check": {"rebuild": False}})
    assert result.counts["phases.decisions.undecided"] == 1
    assert result.counts["builds.manuscript.state"] == "unverified until it is built again"
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "Every item of the four stream reports is approved" in readme
    assert "Of the 1 item of the data phase reports, 0 are approved, 0 held, and 1 not yet decided." \
        in readme
    run = tmp_path / "check_run"
    found = run_check(out, run)
    assert [(item["check"], item["item"]) for item in found
            if item["severity"] != "info" and item["check"] == "publish_counts"] == []
    recount = json.loads((run / "files" / "counts.json").read_text(encoding="utf-8"))
    assert recount["differ"] == 0 and recount["not_rechecked"] == 0


# The guide.


def guide_text():
    return GUIDE.read_text(encoding="utf-8")


def test_the_docs_say_publishing_runs_git_only_to_ask_what_it_ignores():
    contract = (ROOT / "features" / "CONTRACT.md").read_text(encoding="utf-8")
    commands_doc = (ROOT / "features" / "publish" / "commands.py").read_text(encoding="utf-8")
    assert "never runs git" not in guide_text()
    assert "It runs git only to ask, read only, which project files git ignores." in guide_text()
    assert "no graph and no git" not in contract
    assert "Neither command runs a graph or git." not in commands_doc


def test_the_guide_says_what_an_anonymous_build_withholds_and_the_common_word_hazard():
    text = guide_text()
    assert "no file in the repository may hold the scholar's full name" in text
    assert "such as Read, Young, or Scholar, would block ordinary text" in text
    assert "even inside a longer word" not in text


def test_every_publish_line_in_the_guide_parses_with_the_command():
    lines = re.findall(r"python3 -m features (publish [^`\n]*)", guide_text())
    parser, _ = cli._parser()
    seen = set()
    for line in lines:
        options = parser.parse_args(shlex.split(line))
        assert options.group == "publish", line
        seen.add(options.command)
    assert seen == {"plan", "build"}


def test_the_guide_example_names_every_answers_field_and_reads(tmp_path):
    blocks = re.findall(r"```yaml\n(.*?)```", guide_text(), re.DOTALL)
    assert len(blocks) == 1
    given = yaml.safe_load(blocks[0])
    assert list(given) == list(collect.ANSWER_FIELDS)
    assert set(given["sessions"]) == set(collect.SESSION_DEFAULTS)
    assert set(given["check"]) == set(collect.CHECK_DEFAULTS)
    assert set(given["github"]) == set(collect.GITHUB_DEFAULTS)
    path = write(tmp_path / "answers.yaml", blocks[0])
    answers = collect.read_answers(str(path), str(tmp_path / "survey_study"),
                                   {"workflow_root": str(ROOT), "scholar_name": "A. Scholar"})
    assert answers.unknown_keys == []
    assert answers.github["remote_url"].startswith("git@github.com:")


def test_the_guide_names_every_field_and_what_publishing_never_does():
    text = guide_text()
    fields = (tuple(collect.ANSWER_FIELDS) + tuple(collect.SESSION_DEFAULTS)
              + tuple(collect.CHECK_DEFAULTS) + tuple(collect.GITHUB_DEFAULTS)
              + tuple(collect.ALLOW_KEYS))
    for field in fields:
        assert "`%s`" % field in text, field
    for words in ("vg.py run graphs/ops_publish.yaml", "vg.py run graphs/ops_github.yaml",
                  "before making anything public", "only plans until", "`apply: true`",
                  "excluded folder", "never calls a model", "## What publishing never does",
                  "## For an AI session", "`anonymous: false`", "### An anonymous repository",
                  "`.gitignore`", "unless `sessions: {skip: true}` leaves the index out"):
        assert words in text, words
    # An anonymous repository's decisions are signed with a label that is not a term.
    decide = re.findall(r"^python3 vg\.py decide .*$", text, re.M)
    assert decide == ['python3 vg.py decide --run runs/survey_prose --item c01 --approve --by'
                      ' "the scholar"']
    assert u"\u2014" not in text and u"\u2013" not in text


def test_no_long_or_en_dash_in_the_publish_files():
    for name in ("assemble.py", "commands.py", "model.py", "GUIDE.md"):
        text = (ROOT / "features" / "publish" / name).read_text(encoding="utf-8")
        assert u"\u2014" not in text and u"\u2013" not in text, name
