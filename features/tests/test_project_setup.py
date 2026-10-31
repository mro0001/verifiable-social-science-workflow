"""Step F5. Project setup, once per project.

Each test makes a features home with run_system_setup and fake detection.
The layers run for real through the runner. By the reconciliation (Track F),
project setup lays out the skeleton, installs the notes with ospipe
install-notes, adds each product's rule with ospipe add-product, appends
only the rule that copies the citation export to refs.bib, runs no git init,
refuses no folder for being excluded, and prints the run command of the
GitHub procedure from the procedures-ops-github entry when it exists.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import io
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from features import cli, layers
from features.setup import project, system
from features.setup.skeleton import Product
from features.tests.test_system_setup import fake_detector

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "features" / "setup" / "GUIDE.md"
GITHUB_ENTRY = ROOT / "audit_layer" / "kb" / "corpus" / "procedures" / "procedures-ops-github.md"
NOTES = sorted(path.name for path in (ROOT / "templates" / "notes").glob("*.md"))

NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)
MANUSCRIPT = Product("manuscript", "manuscript.md", "docx")
SLIDES = Product("slides", "slides.md", "revealjs")

SKELETON_FILES = ["README.md", "acquisition.yaml", "manuscript.md", "numbers.yml",
                  "params.yaml", "pipeline.yaml", "refs.bib", "verification/README.md"]

# /usr/bin/make on this Mac is an xcrun shim that fails under an x86_64 python,
# so the tools' own make is used when it is there (as in ospipe's own tests).
_REAL_MAKE = "/Library/Developer/CommandLineTools/usr/bin/make"
MAKE = _REAL_MAKE if os.path.exists(_REAL_MAKE) else shutil.which("make")
needs_make = pytest.mark.skipif(MAKE is None or shutil.which("pandoc") is None,
                                reason="make or pandoc is not on the path")


class SpyRunner(object):
    """Runs each layer command for real and records its arguments."""

    def __init__(self):
        self.calls = []

    def __call__(self, layer, args, root=None, cwd=None, env=None, timeout=600):
        self.calls.append((layer, list(args)))
        return layers.run_layer(layer, args, root=root, cwd=cwd, env=env, timeout=timeout)

    def commands(self):
        return [args[0] for layer, args in self.calls if layer == "ospipe"]


class FailingRunner(SpyRunner):
    """Runs each layer command for real, except one ospipe command, which exits 1."""

    def __init__(self, failing):
        SpyRunner.__init__(self)
        self.failing = failing

    def __call__(self, layer, args, root=None, cwd=None, env=None, timeout=600):
        if layer == "ospipe" and args[0] == self.failing:
            self.calls.append((layer, list(args)))
            return layers.LayerResult(["ospipe"] + list(args), 1, "", "the stand-in failure\n")
        return SpyRunner.__call__(self, layer, args, root=root, cwd=cwd, env=env, timeout=timeout)


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and both home variables at temporary folders, so nothing real is touched."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    monkeypatch.setattr(project, "_interactive", lambda: False)
    return home


def make_home(tmp_path, citation_export="", excluded=()):
    """A features home written by system setup with fake detection."""
    home = tmp_path / "features_home"
    given = {"scholar_name": "Test Scholar", "excluded_folders": [str(f) for f in excluded],
             "citation_export": str(citation_export) if citation_export else ""}
    result = system.run_system_setup(str(home), str(tmp_path / "audit_home"), given,
                                     str(ROOT), NOW, detector=fake_detector())
    assert result.ready
    return home


def set_up(folder, home, answers=None, runner=None):
    return project.run_project_setup(str(folder), str(home), answers or {}, NOW,
                                     runner=runner or layers.run_layer)


def written(folder):
    found = []
    for here, _, files in os.walk(str(folder)):
        for name in files:
            found.append(os.path.relpath(os.path.join(here, name), str(folder)).replace(os.sep, "/"))
    return sorted(found)


def snapshot(folder):
    return {path: (Path(folder) / path).read_bytes() for path in written(folder)}


def products_of(folder):
    result = layers.run_layer("ospipe", ["products", "--json"], root=ROOT, cwd=str(folder))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_command(argv):
    out = io.StringIO()
    err = io.StringIO()
    parser, _ = cli._parser()
    options = parser.parse_args(argv)
    code = project.command(options, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# Refusals.

def test_no_system_yaml_refuses_naming_the_system_setup_command(tmp_path):
    folder = tmp_path / "survey"
    with pytest.raises(system.SetupError) as raised:
        set_up(folder, tmp_path / "empty_home")
    assert system.COMMAND in str(raised.value)
    assert not folder.exists()


def test_the_command_without_system_yaml_exits_one_and_names_the_command(tmp_path):
    folder = tmp_path / "survey"
    code, out, err = run_command(["setup", "project", str(folder), "--home", str(tmp_path / "none")])
    assert code == 1
    assert system.COMMAND in err
    assert not folder.exists()


def test_bad_products_are_refused_with_nothing_created(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    with pytest.raises(system.SetupError) as raised:
        set_up(folder, home, {"products": [
            {"name": "Paper", "source": "paper.md", "to": "docx"},
            {"name": "talk", "source": "talk.md", "to": "pptx"}]})
    assert "Paper" in str(raised.value) and "pptx" in str(raised.value)
    assert not folder.exists()


def test_a_folder_that_is_a_file_is_refused(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    folder.write_text("not a folder\n", encoding="utf-8")
    with pytest.raises(system.SetupError):
        set_up(folder, home)
    assert folder.read_text(encoding="utf-8") == "not a folder\n"


# A new project.

def test_a_new_folder_gets_the_skeleton_the_notes_and_the_build_file(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    result = set_up(folder, home)
    expected = sorted(SKELETON_FILES + ["Makefile"] + ["notes/" + name for name in NOTES])
    assert written(folder) == expected
    assert sorted(result.created) == sorted(SKELETON_FILES)
    assert result.kept == []
    assert result.notes_written == ["notes/" + name for name in NOTES]
    for name in NOTES:
        assert (folder / "notes" / name).read_bytes() == (ROOT / "templates" / "notes" / name).read_bytes()
    assert result.ok


def test_ospipe_check_returns_zero_on_each_product_source(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    result = set_up(folder, home, {"products": [
        {"name": "manuscript", "source": "manuscript.md", "to": "docx"},
        {"name": "slides", "source": "slides.md", "to": "revealjs"}]})
    assert [(check.source, check.returncode) for check in result.checks] == [
        ("manuscript.md", 0), ("slides.md", 0)]
    assert result.ok


def test_the_build_file_comes_from_add_product_with_no_check_rule(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    runner = SpyRunner()
    set_up(folder, home, {"products": [
        {"name": "manuscript", "source": "manuscript.md", "to": "docx"},
        {"name": "slides", "source": "slides.md", "to": "revealjs"}]}, runner=runner)
    assert runner.commands() == ["install-notes", "add-product", "add-product", "products",
                                 "check", "check"]
    found = products_of(folder)
    assert found["problems"] == []
    assert [(p["name"], p["source"], p["to"], p["builds_dir"]) for p in found["products"]] == [
        ("manuscript", "manuscript.md", "docx", "builds/manuscript"),
        ("slides", "slides.md", "revealjs", "builds/slides")]
    text = (folder / "Makefile").read_text(encoding="utf-8")
    assert not re.search(r"^check:", text, re.MULTILINE)
    assert "refs.bib:" not in text


def test_the_export_from_system_yaml_gets_the_refs_bib_rule(tmp_path):
    export = tmp_path / "library.bib"
    export.write_bytes(b"@book{healy2020,}\n")
    home = make_home(tmp_path, citation_export=export)
    folder = tmp_path / "survey"
    result = set_up(folder, home)
    assert (folder / "refs.bib").read_bytes() == export.read_bytes()
    text = (folder / "Makefile").read_text(encoding="utf-8")
    assert "refs.bib: {0}".format(export) in text
    assert re.search(r"^manuscript: refs\.bib$", text, re.MULTILINE)
    assert result.rule_appended
    assert products_of(folder)["problems"] == []


def test_an_answered_empty_export_gives_no_rule(tmp_path):
    export = tmp_path / "library.bib"
    export.write_bytes(b"@book{healy2020,}\n")
    home = make_home(tmp_path, citation_export=export)
    folder = tmp_path / "survey"
    result = set_up(folder, home, {"citation_export": ""})
    assert (folder / "refs.bib").read_bytes() == b""
    assert "refs.bib:" not in (folder / "Makefile").read_text(encoding="utf-8")
    assert not result.rule_appended


def test_the_title_defaults_to_the_folder_name(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey_study"
    set_up(folder, home)
    text = (folder / "manuscript.md").read_text(encoding="utf-8")
    assert yaml.safe_load(text.split("---\n", 2)[1])["title"] == "survey_study"


def test_setup_runs_no_git(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    result = set_up(folder, home)
    assert not (folder / ".git").exists()
    assert not hasattr(result, "git")


def test_an_excluded_folder_is_not_refused(tmp_path):
    excluded = tmp_path / "private"
    home = make_home(tmp_path, excluded=[excluded])
    folder = excluded / "survey"
    result = set_up(folder, home)
    assert result.ok
    assert (folder / "manuscript.md").is_file()


# Running again and existing files.

def test_a_second_run_creates_nothing_and_changes_no_file(tmp_path):
    export = tmp_path / "library.bib"
    export.write_bytes(b"@book{healy2020,}\n")
    home = make_home(tmp_path, citation_export=export)
    folder = tmp_path / "survey"
    set_up(folder, home)
    before = snapshot(folder)
    runner = SpyRunner()
    again = set_up(folder, home, runner=runner)
    assert snapshot(folder) == before
    assert again.created == []
    assert sorted(again.kept) == sorted(SKELETON_FILES)
    assert again.notes_written == []
    assert again.notes_kept == ["notes/" + name for name in NOTES]
    assert again.makefile_kept
    assert not again.rule_appended
    assert "add-product" not in runner.commands()
    assert again.ok


def test_an_existing_manuscript_and_makefile_are_unchanged(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    folder.mkdir()
    manuscript = b"---\ntitle: Mine\n---\n\nMy own words.\n"
    makefile = b"# my own build file\nall:\n\techo hand made\n"
    (folder / "manuscript.md").write_bytes(manuscript)
    (folder / "Makefile").write_bytes(makefile)
    result = set_up(folder, home)
    assert (folder / "manuscript.md").read_bytes() == manuscript
    assert (folder / "Makefile").read_bytes() == makefile
    assert "manuscript.md" in result.kept
    assert result.makefile_kept
    assert result.built == []
    assert result.missing == [MANUSCRIPT]
    assert not result.ok


def test_a_rerun_with_an_added_product_on_a_kept_makefile_names_the_missing_rule(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    set_up(folder, home)
    before = (folder / "Makefile").read_bytes()
    again = set_up(folder, home, {"products": [
        {"name": "manuscript", "source": "manuscript.md", "to": "docx"},
        {"name": "slides", "source": "slides.md", "to": "revealjs"}]})
    assert (folder / "Makefile").read_bytes() == before
    assert again.built == ["manuscript"]
    assert again.missing == [SLIDES]
    assert not again.ok


def test_the_command_on_a_rerun_prints_make_only_for_the_rules_the_build_file_has(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    code, out, err = run_command(["setup", "project", str(folder), "--home", str(home)])
    assert code == 0, err
    code, out, err = run_command([
        "setup", "project", str(folder), "--home", str(home),
        "--product", "manuscript:manuscript.md:docx", "--product", "slides:slides.md:revealjs"])
    assert code == 1
    lines = out.splitlines()
    assert "  make manuscript" in lines
    assert "  make slides" not in lines
    assert any(line.endswith("python3 -m ospipe add-product --name slides --source slides.md"
                             " --to revealjs --bib refs.bib --tables-dir .") for line in lines), out
    assert "Ready" not in lines
    assert any(line.startswith("Not ready") and "slides" in line for line in lines)


def test_the_printed_add_product_line_adds_the_missing_rule(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    set_up(folder, home)
    code, out, err = run_command([
        "setup", "project", str(folder), "--home", str(home),
        "--product", "manuscript:manuscript.md:docx", "--product", "slides:slides.md:revealjs"])
    line = [text for text in out.splitlines() if "ospipe add-product" in text][0].strip()
    done = subprocess.run(line, shell=True, cwd=str(folder), capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert [p["name"] for p in products_of(folder)["products"]] == ["manuscript", "slides"]
    code, out, err = run_command([
        "setup", "project", str(folder), "--home", str(home),
        "--product", "manuscript:manuscript.md:docx", "--product", "slides:slides.md:revealjs"])
    assert code == 0, out + err
    assert "Ready" in out.splitlines()


def _rename_the_manuscript_source(folder, new_name):
    """Point the kept build file's manuscript rule at another source, as a scholar's edit might."""
    path = folder / "Makefile"
    path.write_text(path.read_text(encoding="utf-8").replace("manuscript.md", new_name),
                    encoding="utf-8")


def test_a_kept_build_file_with_a_problem_is_not_ready(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    set_up(folder, home)
    _rename_the_manuscript_source(folder, "gone.md")
    before = (folder / "Makefile").read_bytes()
    again = set_up(folder, home)
    assert (folder / "Makefile").read_bytes() == before
    assert "manuscript: source gone.md does not exist" in again.build_problems
    assert "manuscript" not in again.built
    assert again.missing == []
    assert not again.ok


def test_the_command_prints_each_build_file_problem_and_no_make_for_it(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    run_command(["setup", "project", str(folder), "--home", str(home)])
    _rename_the_manuscript_source(folder, "gone.md")
    code, out, err = run_command(["setup", "project", str(folder), "--home", str(home)])
    assert code == 1
    lines = out.splitlines()
    assert "  make manuscript" not in lines
    assert "  manuscript: source gone.md does not exist" in lines
    assert "Ready" not in lines
    assert any(line.startswith("Not ready") and "problem" in line for line in lines), out


def test_a_problem_on_another_rule_leaves_the_project_not_ready(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    set_up(folder, home)
    with open(str(folder / "Makefile"), "a", encoding="utf-8") as handle:
        handle.write("\nother: manuscript.md\n\t$(OSPIPE) build --manuscript manuscript.md"
                     " --manifest $(MANIFEST) --builds-dir builds/manuscript\n")
    again = set_up(folder, home)
    assert any(problem.startswith("other: shares the builds dir") for problem in again.build_problems)
    assert again.built == ["manuscript"]
    assert not again.ok


class ProductsExitRunner(SpyRunner):
    """Runs each layer command for real, except ospipe products, which keeps its JSON but exits 2."""

    def __call__(self, layer, args, root=None, cwd=None, env=None, timeout=600):
        done = SpyRunner.__call__(self, layer, args, root=root, cwd=cwd, env=env, timeout=timeout)
        if layer == "ospipe" and args[0] == "products":
            return layers.LayerResult(done.argv, 2, done.stdout, done.stderr)
        return done


def test_a_nonzero_exit_from_ospipe_products_is_not_ready(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    result = set_up(folder, home, runner=ProductsExitRunner())
    assert result.build_problems == ["ospipe products exited 2"]
    assert not result.ok


def test_a_product_the_build_file_builds_from_another_source_is_not_ready(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    set_up(folder, home)
    again = set_up(folder, home, {"products": [
        {"name": "manuscript", "source": "paper.md", "to": "docx"}]})
    assert again.built == []
    assert again.missing == []
    assert again.add_lines == []
    assert [product.name for product, found in again.differs] == ["manuscript"]
    assert again.differs[0][1]["source"] == "manuscript.md"
    assert not again.ok


def test_a_product_the_build_file_builds_as_another_format_is_not_ready(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    set_up(folder, home)
    again = set_up(folder, home, {"products": [
        {"name": "manuscript", "source": "manuscript.md", "to": "revealjs"}]})
    assert again.built == []
    assert [product.name for product, found in again.differs] == ["manuscript"]
    assert not again.ok


def test_the_command_names_how_the_build_file_builds_a_product_that_differs(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    run_command(["setup", "project", str(folder), "--home", str(home)])
    code, out, err = run_command(["setup", "project", str(folder), "--home", str(home),
                                  "--product", "manuscript:paper.md:docx"])
    assert code == 1
    lines = out.splitlines()
    assert "  make manuscript" not in lines
    assert not any("ospipe add-product" in line for line in lines)
    assert ("  manuscript is built from manuscript.md as docx, not from paper.md as docx"
            in lines), out
    assert "Ready" not in lines
    assert any(line.startswith("Not ready") and "manuscript" in line for line in lines), out


def test_a_second_run_lists_each_kept_file_once(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    run_command(["setup", "project", str(folder), "--home", str(home)])
    code, out, err = run_command(["setup", "project", str(folder), "--home", str(home)])
    assert code == 0, err
    assert "as it was, since setup never changes" not in out
    assert out.splitlines().count("  manuscript.md") == 1


def test_a_failing_check_is_reported_and_not_ok(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    folder.mkdir()
    (folder / "manuscript.md").write_text(
        "---\ntitle: Mine\n---\n\nThe sample held {{num:respondents}} people.\n", encoding="utf-8")
    result = set_up(folder, home)
    assert [check.returncode != 0 for check in result.checks] == [True]
    assert result.checks[0].problem
    assert not result.ok


# Stops.

def test_a_stale_workflow_root_stops_before_anything_is_written(tmp_path):
    home = make_home(tmp_path)
    path = home / "system.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["workflow_root"] = str(tmp_path / "moved_away")
    path.write_text(yaml.safe_dump(record), encoding="utf-8")
    folder = tmp_path / "survey"
    with pytest.raises(system.SetupError) as raised:
        set_up(folder, home)
    assert "moved_away" in str(raised.value)
    assert system.COMMAND in str(raised.value)
    assert not folder.exists()


@pytest.mark.parametrize("failing", ["install-notes", "add-product"])
def test_a_failed_ospipe_command_stops_setup_with_its_error(tmp_path, failing):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    runner = FailingRunner(failing)
    with pytest.raises(system.SetupError) as raised:
        set_up(folder, home, runner=runner)
    assert "ospipe " + failing in str(raised.value)
    assert "the stand-in failure" in str(raised.value)
    assert runner.commands()[-1] == failing
    assert "check" not in runner.commands()


def test_the_command_exits_one_when_a_check_fails(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    folder.mkdir()
    (folder / "manuscript.md").write_text(
        "---\ntitle: Mine\n---\n\nThe sample held {{num:respondents}} people.\n", encoding="utf-8")
    code, out, err = run_command(["setup", "project", str(folder), "--home", str(home)])
    assert code == 1
    lines = out.splitlines()
    assert "Ready" not in lines
    assert any(line.startswith("Not ready") and "check" in line for line in lines)


# The GitHub procedure.

def test_the_github_run_command_comes_from_its_entry():
    line = project.github_run_command(str(ROOT))
    wanted = [text for text in GITHUB_ENTRY.read_text(encoding="utf-8").splitlines()
              if text.startswith("4. Run command. ")][0]
    assert line == wanted[len("4. Run command. "):]
    assert "vg.py run graphs/ops_github.yaml" in line


def test_no_github_entry_gives_no_line(tmp_path):
    assert project.github_run_command(str(tmp_path)) == ""


# The command.

def test_the_command_sets_up_a_project_and_prints_what_it_did(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    code, out, err = run_command([
        "setup", "project", str(folder), "--home", str(home), "--title", "The Survey",
        "--product", "manuscript:manuscript.md:docx", "--product", "slides:slides.md:revealjs"])
    assert code == 0, err
    assert (folder / "slides.md").is_file()
    for path in SKELETON_FILES + ["slides.md"]:
        assert path in out
    assert "make manuscript" in out
    assert "make slides" in out
    assert "manuscript.md passed" in out
    assert project.github_run_command(str(ROOT)) in out
    for line in system.LATER_CONNECTIONS:
        assert line in out
    assert "git init" not in out


def test_the_command_reads_an_answers_file_and_flags_win(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    answers = tmp_path / "project_answers.yaml"
    answers.write_text(yaml.safe_dump({
        "title": "From the file",
        "products": [{"name": "paper", "source": "paper.md", "to": "docx"}],
        "citation_export": ""}), encoding="utf-8")
    code, out, err = run_command(["setup", "project", str(folder), "--home", str(home),
                                  "--answers", str(answers), "--title", "From the flag"])
    assert code == 0, err
    text = (folder / "paper.md").read_text(encoding="utf-8")
    assert yaml.safe_load(text.split("---\n", 2)[1])["title"] == "From the flag"
    assert not (folder / "manuscript.md").exists()


def test_an_answers_file_with_an_unknown_field_is_refused(tmp_path):
    home = make_home(tmp_path)
    answers = tmp_path / "project_answers.yaml"
    answers.write_text("title: Survey\ngit: true\n", encoding="utf-8")
    code, out, err = run_command(["setup", "project", str(tmp_path / "survey"), "--home", str(home),
                                  "--answers", str(answers)])
    assert code == 1
    assert "git" in err
    assert not (tmp_path / "survey").exists()


def test_a_bad_product_flag_is_refused(tmp_path):
    home = make_home(tmp_path)
    code, out, err = run_command(["setup", "project", str(tmp_path / "survey"), "--home", str(home),
                                  "--product", "manuscript.md"])
    assert code == 1
    assert "NAME:SOURCE:FORMAT" in err


def test_the_command_has_no_git_option():
    parser, _ = cli._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["setup", "project", "survey", "--git"])


def test_questions_are_asked_for_what_the_flags_did_not_give():
    asked = []
    replies = iter(["", "paper:paper.md:docx", "talk:talk.md:revealjs", "", "none"])

    def ask(prompt):
        asked.append(prompt)
        return next(replies)

    given = project.ask_answers("survey", {"citation_export": "/lib.bib"}, {}, ask=ask,
                                out=io.StringIO())
    assert given == {"title": "survey",
                     "products": [{"name": "paper", "source": "paper.md", "to": "docx"},
                                  {"name": "talk", "source": "talk.md", "to": "revealjs"}],
                     "citation_export": ""}
    assert len(asked) == 5


def test_a_bad_product_answer_is_asked_again():
    replies = iter(["Survey", "bad", "", ""])
    out = io.StringIO()
    given = project.ask_answers("survey", {"citation_export": ""}, {"title": "Given"},
                                ask=lambda prompt: next(replies), out=out)
    assert given["title"] == "Given"
    assert "NAME:SOURCE:FORMAT" in out.getvalue()


# make on the new project.

@needs_make
def test_make_builds_the_manuscript_unverified_for_every_stream(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    set_up(folder, home)
    done = subprocess.run([MAKE, "manuscript"], cwd=str(folder), capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (folder / "builds" / "manuscript" / "v001.docx").is_file()
    ledger = (folder / "builds" / "manuscript" / "BUILDS.md").read_text(encoding="utf-8")
    rows = [line for line in ledger.splitlines() if line.startswith("| v001 ")]
    assert len(rows) == 1
    assert "unverified: prose, citations, data, build" in rows[0]


@needs_make
def test_make_builds_an_added_slides_product(tmp_path):
    home = make_home(tmp_path)
    folder = tmp_path / "survey"
    set_up(folder, home, {"products": [
        {"name": "manuscript", "source": "manuscript.md", "to": "docx"},
        {"name": "slides", "source": "slides.md", "to": "revealjs"}]})
    done = subprocess.run([MAKE, "slides"], cwd=str(folder), capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (folder / "builds" / "slides" / "v001.html").is_file()


# The guide.

def guide_commands():
    """Each setup command line in the guide, leaving out the answers examples' first lines."""
    lines = [line for line in GUIDE.read_text(encoding="utf-8").splitlines()
             if not line.startswith("# answers for ")]
    return re.findall(r"python3 -m features (setup [^`\n]*)", "\n".join(lines))


def guide_answers():
    text = GUIDE.read_text(encoding="utf-8")
    return re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)


def test_every_setup_line_in_the_guide_parses_with_the_command():
    commands = guide_commands()
    assert any(line.startswith("setup system") for line in commands)
    assert any(line.startswith("setup project") for line in commands)
    parser, _ = cli._parser()
    for line in commands:
        options = parser.parse_args(shlex.split(line))
        assert options.command in ("system", "project"), line


def test_each_example_answers_file_matches_its_command(tmp_path):
    blocks = guide_answers()
    seen = set()
    for number, block in enumerate(blocks):
        first = block.splitlines()[0]
        path = tmp_path / "answers_{0}.yaml".format(number)
        path.write_text(block, encoding="utf-8")
        if first == "# answers for python3 -m features setup system":
            assert set(yaml.safe_load(block)) <= set(system.FIELDS)
            system.read_answers(str(path))
            seen.add("system")
        elif first == "# answers for python3 -m features setup project":
            assert set(yaml.safe_load(block)) <= set(project.FIELDS)
            project.read_answers(str(path))
            seen.add("project")
        else:
            pytest.fail("an answers example must start with the line naming its command: " + first)
    assert seen == {"system", "project"}


def test_the_guide_names_every_answers_field_and_what_setup_never_does():
    text = GUIDE.read_text(encoding="utf-8")
    for field in tuple(system.FIELDS) + tuple(project.FIELDS):
        assert "`{0}`".format(field) in text, field
    for words in ("install", "overwrite", "excluded folder", "commit", "PYTHONPATH"):
        assert words in text, words
    assert "—" not in text
