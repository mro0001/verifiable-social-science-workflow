"""Step F4. The project skeleton.

The skeleton lays out a new project in the sample project's flat layout and
never changes a file that exists. By the reconciliation (Track F), it writes
no .gitignore, no Makefile, and no notes. Project setup (step F5) adds each
product's rule with ospipe add-product, installs the notes with ospipe
install-notes, and appends only the rule that copies the citation manager's
export to refs.bib, whose text makefile_text gives here. The tests that run
ospipe and make play that part of step F5 through the layer runner.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from features import layers
from features.setup import skeleton
from features.setup.skeleton import Product

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "features" / "setup" / "project_template"

NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)
TITLE = 'Who Answers "Yes" to the Survey'
MANUSCRIPT = Product("manuscript", "manuscript.md", "docx")
SLIDES = Product("slides", "slides.md", "revealjs")

BASE_FILES = ["README.md", "acquisition.yaml", "manuscript.md", "numbers.yml",
              "params.yaml", "pipeline.yaml", "refs.bib", "verification/README.md"]

# /usr/bin/make on this Mac is an xcrun shim that fails under an x86_64 python,
# so the tools' own make is used when it is there (as in ospipe's own tests).
_REAL_MAKE = "/Library/Developer/CommandLineTools/usr/bin/make"
MAKE = _REAL_MAKE if os.path.exists(_REAL_MAKE) else shutil.which("make")
needs_make = pytest.mark.skipif(MAKE is None, reason="make is not on the path")


def lay_out(project, products=(MANUSCRIPT,), title=TITLE, citation_export=None):
    planned = skeleton.plan_skeleton(str(project), title, list(products), citation_export, NOW)
    return skeleton.write_skeleton(str(project), planned)


def written(project):
    """Every file under the project, as paths relative to it."""
    found = []
    for folder, _, files in os.walk(str(project)):
        for name in files:
            found.append(os.path.relpath(os.path.join(folder, name), str(project)).replace(os.sep, "/"))
    return sorted(found)


def front_matter(path):
    text = Path(path).read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n", 2)[1])


def add_products(project, products):
    """Step F5's part, played here, adding each product's rule with ospipe add-product."""
    for product in products:
        result = layers.run_layer(
            "ospipe", ["add-product", "--name", product.name, "--source", product.source,
                       "--to", product.to, "--bib", "refs.bib", "--tables-dir", "."],
            root=ROOT, cwd=str(project))
        assert result.returncode == 0, result.stderr


def append_rule(project, products, citation_export):
    addition = skeleton.makefile_text(products, citation_export, str(project))
    with open(str(project / "Makefile"), "a", encoding="utf-8") as handle:
        handle.write(addition.text)
    return addition


def make_dry(project, target):
    return subprocess.run([MAKE, "-n", target], cwd=str(project),
                          capture_output=True, text=True, timeout=120)


# The templates.

def test_the_template_folder_holds_the_eight_templates_and_no_gitignore():
    names = sorted(os.listdir(str(TEMPLATES)))
    assert names == ["README.md", "acquisition.yaml", "manuscript.md", "numbers.yml",
                     "params.yaml", "pipeline.yaml", "slides.md", "verification_README.md"]


def test_templates_use_only_the_two_tokens_and_hold_no_placeholder_or_numeral():
    for path in TEMPLATES.iterdir():
        text = path.read_text(encoding="utf-8")
        tokens = set(re.findall(r"@@[A-Z_]*@@", text))
        assert tokens <= {"@@TITLE@@", "@@DATE@@"}, path.name
        assert text.count("@@") == 2 * len(re.findall(r"@@[A-Z_]*@@", text)), path.name
        assert "{{" not in text, path.name
        assert not re.search(r"[0-9]", text), path.name


# The layout.

def test_an_empty_folder_gets_every_planned_file(tmp_path):
    project = tmp_path / "survey"
    result = lay_out(project)
    assert sorted(result.created) == BASE_FILES
    assert result.kept == []
    assert written(project) == BASE_FILES


def test_a_slides_product_gets_its_source_from_the_slides_template(tmp_path):
    project = tmp_path / "survey"
    result = lay_out(project, products=(MANUSCRIPT, SLIDES))
    assert sorted(result.created) == sorted(BASE_FILES + ["slides.md"])
    slides = (project / "slides.md").read_text(encoding="utf-8")
    manuscript = (project / "manuscript.md").read_text(encoding="utf-8")
    assert "## References" in manuscript
    assert "## References" not in slides
    assert re.search(r"^## ", slides, re.MULTILINE)
    assert front_matter(project / "slides.md")["title"] == TITLE


def test_a_source_in_a_subfolder_gets_its_folder(tmp_path):
    project = tmp_path / "survey"
    lay_out(project, products=(Product("paper", "paper/main.md", "docx"),))
    assert (project / "paper" / "main.md").is_file()
    assert not (project / "manuscript.md").exists()


def test_the_skeleton_writes_no_gitignore_makefile_or_notes(tmp_path):
    project = tmp_path / "survey"
    lay_out(project, products=(MANUSCRIPT, SLIDES), citation_export=None)
    assert not (project / ".gitignore").exists()
    assert not (project / "Makefile").exists()
    assert not (project / "notes").exists()


def test_the_title_is_a_quoted_yaml_string_with_its_quotes_escaped(tmp_path):
    project = tmp_path / "survey"
    title = 'A "quoted" title: with a colon and a back\\slash'
    lay_out(project, title=title)
    assert front_matter(project / "manuscript.md")["title"] == title
    first = (project / "manuscript.md").read_text(encoding="utf-8").splitlines()[1]
    assert first.startswith('title: "') and first.endswith('"')


def test_an_empty_title_takes_the_folder_name(tmp_path):
    project = tmp_path / "survey_of_voters"
    lay_out(project, title="")
    assert front_matter(project / "manuscript.md")["title"] == "survey_of_voters"


def test_a_title_that_cannot_be_written_is_refused(tmp_path):
    for title in ("two\nlines", "a {{num:x}} title", "a @@TITLE@@ title", "Project guide",
                  "  verification   RESULTS "):
        with pytest.raises(skeleton.SkeletonError):
            skeleton.plan_skeleton(str(tmp_path / "p"), title, [MANUSCRIPT], None, NOW)


def test_no_written_file_holds_a_token_or_a_placeholder(tmp_path):
    project = tmp_path / "survey"
    lay_out(project, products=(MANUSCRIPT, SLIDES))
    for name in written(project):
        text = (project / name).read_text(encoding="utf-8")
        assert "@@" not in text, name
        assert "{{" not in text, name


def test_product_sources_hold_no_numeral(tmp_path):
    project = tmp_path / "survey"
    lay_out(project, products=(MANUSCRIPT, SLIDES))
    for name in ("manuscript.md", "slides.md"):
        assert not re.search(r"[0-9]", (project / name).read_text(encoding="utf-8")), name


def test_the_yaml_files_keep_the_forms_other_parts_read(tmp_path):
    project = tmp_path / "survey"
    lay_out(project)
    assert yaml.safe_load((project / "numbers.yml").read_text(encoding="utf-8")) == {"numbers": {}}
    assert yaml.safe_load((project / "pipeline.yaml").read_text(encoding="utf-8")) == {
        "helpers": [], "steps": []}
    assert yaml.safe_load((project / "params.yaml").read_text(encoding="utf-8")) == {}
    assert yaml.safe_load((project / "acquisition.yaml").read_text(encoding="utf-8")) == {"raw": []}
    for name in ("numbers.yml", "pipeline.yaml", "params.yaml", "acquisition.yaml"):
        assert (project / name).read_text(encoding="utf-8").startswith("# "), name


def test_the_readme_is_a_project_guide_naming_each_product(tmp_path):
    project = tmp_path / "survey"
    lay_out(project, products=(MANUSCRIPT, SLIDES))
    text = (project / "README.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "# Project guide"
    assert lines[0][2:].lower() != TITLE.lower()
    for product in (MANUSCRIPT, SLIDES):
        assert "`{0}`".format(product.source) in text
        assert "`make {0}`".format(product.name) in text
    for place in ("numbers.yml", "refs.bib", "acquisition.yaml", "pipeline.yaml",
                  "params.yaml", "notes/", "verification/"):
        assert place in text, place
    assert "make check" not in text
    assert "2026-10-29" in text
    assert text.index("`make manuscript`") < text.index("numbers.yml")


def test_the_verification_readme_names_the_results_files(tmp_path):
    project = tmp_path / "survey"
    lay_out(project)
    text = (project / "verification" / "README.md").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "# Verification results"
    assert "<stream>.json" in text
    assert "unverified" in text


# Never changing a file.

def test_a_second_run_creates_nothing_and_keeps_every_file(tmp_path):
    project = tmp_path / "survey"
    first = lay_out(project, products=(MANUSCRIPT, SLIDES))
    before = {name: (project / name).read_bytes() for name in written(project)}
    second = lay_out(project, products=(MANUSCRIPT, SLIDES), title="Another title")
    assert second.created == []
    assert sorted(second.kept) == sorted(first.created)
    assert {name: (project / name).read_bytes() for name in written(project)} == before
    assert len(second.messages) == len(second.kept)


def test_an_existing_manuscript_is_unchanged_byte_for_byte(tmp_path):
    project = tmp_path / "survey"
    project.mkdir()
    mine = b"---\ntitle: Mine\n---\r\n\r\nMy own words, kept.\r\n"
    (project / "manuscript.md").write_bytes(mine)
    result = lay_out(project)
    assert (project / "manuscript.md").read_bytes() == mine
    assert "manuscript.md" in result.kept
    assert "manuscript.md" not in result.created


def test_a_link_at_a_planned_path_is_kept_and_not_written_through(tmp_path):
    project = tmp_path / "survey"
    project.mkdir()
    elsewhere = tmp_path / "elsewhere.yml"
    elsewhere.write_bytes(b"mine: true\n")
    os.symlink(str(elsewhere), str(project / "numbers.yml"))
    result = lay_out(project)
    assert "numbers.yml" in result.kept
    assert elsewhere.read_bytes() == b"mine: true\n"


# Products.

def test_the_default_product_is_the_manuscript():
    assert skeleton.DEFAULT_PRODUCTS == [Product("manuscript", "manuscript.md", "docx")]


def test_products_that_cannot_be_built_are_refused_before_anything_is_written(tmp_path):
    cases = [
        [MANUSCRIPT, Product("manuscript", "other.md", "docx")],
        [MANUSCRIPT, Product("paper", "manuscript.md", "docx")],
        [Product("Paper", "paper.md", "docx")],
        [Product("1paper", "paper.md", "docx")],
        [Product("paper-two", "paper.md", "docx")],
        [Product("paper", "paper.md", "pdf")],
        [Product("manifest", "paper.md", "docx")],
        [Product("emit", "paper.md", "docx")],
        [Product("paper", "README.md", "docx")],
        [Product("paper", "refs.bib", "docx")],
        [Product("paper", "verification/README.md", "docx")],
        [Product("paper", "/tmp/paper.md", "docx")],
        [Product("paper", "../paper.md", "docx")],
        [],
    ]
    for products in cases:
        project = tmp_path / "p"
        with pytest.raises(skeleton.SkeletonError):
            skeleton.plan_skeleton(str(project), TITLE, products, None, NOW)
        assert not project.exists()


def test_every_problem_is_named_at_once(tmp_path):
    with pytest.raises(skeleton.SkeletonError) as caught:
        skeleton.plan_skeleton(str(tmp_path / "p"), TITLE,
                               [Product("Bad", "a.md", "docx"), Product("good", "b.md", "pdf")],
                               None, NOW)
    assert len(caught.value.problems) == 2


# The references and the citation manager's export.

def test_refs_bib_is_empty_without_an_export(tmp_path):
    project = tmp_path / "survey"
    lay_out(project)
    assert (project / "refs.bib").read_bytes() == b""


def test_refs_bib_is_a_copy_of_the_export(tmp_path):
    export = tmp_path / "library.bib"
    export.write_bytes(b"@book{healy2020,\n  title = {Plain Text},\n}\n")
    project = tmp_path / "survey"
    lay_out(project, citation_export=str(export))
    assert (project / "refs.bib").read_bytes() == export.read_bytes()


def test_without_an_export_there_is_no_rule(tmp_path):
    project = tmp_path / "survey"
    lay_out(project)
    addition = skeleton.makefile_text([MANUSCRIPT], None, str(project))
    assert addition.text == ""
    assert addition.messages == []
    assert skeleton.makefile_text([MANUSCRIPT], "", str(project)).text == ""


def test_with_an_export_the_rule_copies_it_and_each_product_needs_it(tmp_path):
    export = tmp_path / "library.bib"
    export.write_bytes(b"@book{healy2020,}\n")
    project = tmp_path / "survey"
    lay_out(project, products=(MANUSCRIPT, SLIDES), citation_export=str(export))
    addition = skeleton.makefile_text([MANUSCRIPT, SLIDES], str(export), str(project))
    lines = addition.text.splitlines()
    assert "refs.bib: {0}".format(export) in lines
    assert "\tcp '{0}' refs.bib".format(export) in lines
    assert "manuscript slides: refs.bib" in lines
    assert addition.messages == []


def test_a_different_existing_refs_bib_leaves_the_rule_out_with_a_message(tmp_path):
    export = tmp_path / "library.bib"
    export.write_bytes(b"@book{healy2020,}\n")
    project = tmp_path / "survey"
    project.mkdir()
    (project / "refs.bib").write_bytes(b"@book{mine,}\n")
    result = lay_out(project, citation_export=str(export))
    assert "refs.bib" in result.kept
    assert (project / "refs.bib").read_bytes() == b"@book{mine,}\n"
    addition = skeleton.makefile_text([MANUSCRIPT], str(export), str(project))
    assert addition.text == ""
    assert len(addition.messages) == 1
    assert "refs.bib" in addition.messages[0]


def test_a_missing_export_leaves_the_rule_out_with_a_message(tmp_path):
    project = tmp_path / "survey"
    lay_out(project, citation_export=str(tmp_path / "gone.bib"))
    assert (project / "refs.bib").read_bytes() == b""
    addition = skeleton.makefile_text([MANUSCRIPT], str(tmp_path / "gone.bib"), str(project))
    assert addition.text == ""
    assert len(addition.messages) == 1


def test_an_export_path_make_cannot_name_is_left_out_with_a_message(tmp_path):
    folder = tmp_path / "a:b"
    folder.mkdir()
    export = folder / "library.bib"
    export.write_bytes(b"@book{x,}\n")
    project = tmp_path / "survey"
    lay_out(project, citation_export=str(export))
    addition = skeleton.makefile_text([MANUSCRIPT], str(export), str(project))
    assert addition.text == ""
    assert len(addition.messages) == 1


# With ospipe, as step F5 will run it.

def test_the_sources_pass_ospipe_check(tmp_path):
    project = tmp_path / "survey"
    lay_out(project, products=(MANUSCRIPT, SLIDES))
    for product in (MANUSCRIPT, SLIDES):
        result = layers.run_layer(
            "ospipe", ["check", "--manuscript", product.source, "--manifest", "numbers.yml",
                       "--tables-dir", "."], root=ROOT, cwd=str(project))
        assert result.returncode == 0, result.stderr


def test_the_build_file_reads_back_each_product_after_the_rule_is_appended(tmp_path):
    export = tmp_path / "library.bib"
    export.write_bytes(b"@book{healy2020,}\n")
    project = tmp_path / "survey"
    lay_out(project, products=(MANUSCRIPT, SLIDES), citation_export=str(export))
    add_products(project, [MANUSCRIPT, SLIDES])
    append_rule(project, [MANUSCRIPT, SLIDES], str(export))
    result = layers.run_layer("ospipe", ["products", "--json"], root=ROOT, cwd=str(project))
    assert result.returncode == 0, result.stderr
    project_map = json.loads(result.stdout)
    assert project_map["problems"] == []
    assert [(p["name"], p["source"], p["to"], p["builds_dir"]) for p in project_map["products"]] == [
        ("manuscript", "manuscript.md", "docx", "builds/manuscript"),
        ("slides", "slides.md", "revealjs", "builds/slides")]


@needs_make
def test_make_dry_runs_each_product_with_the_rule_appended(tmp_path):
    export = tmp_path / "my library.bib"
    export.write_bytes(b"@book{healy2020,}\n")
    project = tmp_path / "survey"
    lay_out(project, products=(MANUSCRIPT, SLIDES), citation_export=str(export))
    add_products(project, [MANUSCRIPT, SLIDES])
    append_rule(project, [MANUSCRIPT, SLIDES], str(export))
    manuscript = make_dry(project, "manuscript")
    assert manuscript.returncode == 0, manuscript.stderr
    assert "--manuscript manuscript.md" in manuscript.stdout
    assert "--builds-dir builds/manuscript" in manuscript.stdout
    assert "cp " not in manuscript.stdout
    slides = make_dry(project, "slides")
    assert slides.returncode == 0, slides.stderr
    assert "--to revealjs" in slides.stdout
    later = (project / "refs.bib").stat().st_mtime + 60
    os.utime(str(export), (later, later))
    refreshed = make_dry(project, "manuscript")
    assert refreshed.returncode == 0, refreshed.stderr
    assert "cp '{0}' refs.bib".format(export) in refreshed.stdout


@needs_make
def test_make_dry_runs_each_product_without_an_export(tmp_path):
    project = tmp_path / "survey"
    lay_out(project)
    add_products(project, [MANUSCRIPT])
    append_rule(project, [MANUSCRIPT], None)
    manuscript = make_dry(project, "manuscript")
    assert manuscript.returncode == 0, manuscript.stderr
    assert "--manuscript manuscript.md" in manuscript.stdout
