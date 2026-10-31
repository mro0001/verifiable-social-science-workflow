"""Adding a product to the build file. Synthetic sources written by the test, and a
temporary copy of the sample project for the Make case."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.layout import AddProductError, add_product, read_map  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
SAMPLE_PROJECT = OSPIPE_DIR.parent / "examples" / "sample_project"
# /usr/bin/make on this Mac is an xcrun shim that fails under an x86_64 python, so the
# real binary is called when it is there.
_REAL_MAKE = "/Library/Developer/CommandLineTools/usr/bin/make"
MAKE = _REAL_MAKE if os.path.exists(_REAL_MAKE) else shutil.which("make")

SOURCES = {
    "manuscript.md": "# Fake paper\n\nWidgets {{num:widgets}}.\n",
    "slides.md": "## Fake talk\n\nWidgets {{num:widgets}}.\n",
    "site/index.md": "# Fake site\n\nWidgets {{num:widgets}}.\n",
    "numbers.yml": 'numbers:\n  widgets: {value: "24", from: out.json, field: widgets}\n',
    "refs.bib": "@book{fake2020, title={Fake}, author={Nobody}, year={2020}}\n",
}


@pytest.fixture()
def project(tmp_path):
    folder = tmp_path / "project"
    for relative, text in SOURCES.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


def _three(makefile):
    """Add a manuscript, slides, and a website, and return the file's bytes after each."""
    steps = []
    add_product(makefile, "manuscript", "manuscript.md", bib="refs.bib", csl="style/apa.csl",
                reference_doc="style/ref.docx", tables_dir="tables")
    steps.append(makefile.read_bytes())
    add_product(makefile, "slides", "slides.md", to="revealjs", tables_dir="tables")
    steps.append(makefile.read_bytes())
    add_product(makefile, "site", "site/index.md", to="html", builds_dir="builds/website")
    steps.append(makefile.read_bytes())
    return steps


def _run_cli(args, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(OSPIPE_DIR)
    return subprocess.run(
        [sys.executable, "-m", "ospipe", "add-product"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd or OSPIPE_DIR),
        env=env,
    )


def _checksums(folder):
    sums = {}
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            sums[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return sums


class TestAdd:
    def test_three_products_read_back_with_their_options(self, project):
        makefile = project / "Makefile"
        _three(makefile)
        project_map = read_map(makefile)
        assert project_map.problems == []
        products = {p.name: p for p in project_map.products}
        assert list(products) == ["manuscript", "slides", "site"]

        manuscript = products["manuscript"]
        assert manuscript.source == "manuscript.md"
        assert manuscript.to == "docx"
        assert manuscript.builds_dir == "builds/manuscript"
        assert manuscript.manifest == "numbers.yml"
        assert manuscript.bib == "refs.bib"
        assert manuscript.csl == "style/apa.csl"
        assert manuscript.reference_doc == "style/ref.docx"
        assert manuscript.tables_dir == "tables"
        assert manuscript.purpose == "draft"
        assert manuscript.verification_dir == "verification"

        slides = products["slides"]
        assert (slides.source, slides.to, slides.builds_dir, slides.tables_dir) == (
            "slides.md", "revealjs", "builds/slides", "tables")
        assert (slides.bib, slides.csl, slides.reference_doc) == (None, None, None)

        site = products["site"]
        assert (site.source, site.to, site.builds_dir, site.verification_dir) == (
            "site/index.md", "html", "builds/website", "site/verification")

    def test_a_new_file_starts_with_the_header_variables_and_manifest_rule(self, project):
        makefile = project / "Makefile"
        add_product(makefile, "manuscript", "manuscript.md")
        text = makefile.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines[0].startswith("# ")
        assert "one rule per research product" in lines[0].lower()
        assert "one source file" in lines[0]
        home = str(OSPIPE_DIR)
        assert "OSPIPE ?= PYTHONPATH='{0}' python3 -m ospipe".format(home) in lines
        assert "MANIFEST ?= numbers.yml" in lines
        assert "PURPOSE ?= draft" in lines
        assert "manifest:\n\t$(OSPIPE) emit-manifest --manifest $(MANIFEST)\n" in text
        assert (
            ".PHONY: manuscript\nmanuscript: manuscript.md $(MANIFEST)\n"
            "\t$(OSPIPE) build --manuscript manuscript.md --manifest $(MANIFEST) "
            "--to docx --builds-dir builds/manuscript --purpose \"$(PURPOSE)\"\n"
        ) in text
        assert text.count("manifest:\n") == 1

    def test_the_options_come_in_order(self, project):
        makefile = project / "Makefile"
        add_product(makefile, "manuscript", "manuscript.md", bib="refs.bib", csl="a.csl",
                    reference_doc="ref.docx", tables_dir="tables")
        recipe = [ln for ln in makefile.read_text(encoding="utf-8").splitlines()
                  if ln.startswith("\t$(OSPIPE) build")][0]
        assert recipe == (
            "\t$(OSPIPE) build --manuscript manuscript.md --manifest $(MANIFEST) "
            "--tables-dir tables --bib refs.bib --csl a.csl --reference-doc ref.docx "
            "--to docx --builds-dir builds/manuscript --purpose \"$(PURPOSE)\""
        )

    def test_earlier_text_is_unchanged_byte_for_byte(self, project):
        makefile = project / "Makefile"
        steps = _three(makefile)
        assert steps[1].startswith(steps[0]) and len(steps[1]) > len(steps[0])
        assert steps[2].startswith(steps[1]) and len(steps[2]) > len(steps[1])

    def test_an_existing_file_without_a_manifest_rule_gets_one_once(self, project):
        makefile = project / "Makefile"
        before = "# Kept by hand.\nMANIFEST := numbers.yml\n\nnotes:\n\techo notes"
        makefile.write_text(before, encoding="utf-8")
        add_product(makefile, "manuscript", "manuscript.md")
        add_product(makefile, "slides", "slides.md", to="revealjs")
        text = makefile.read_text(encoding="utf-8")
        assert text.startswith(before)
        assert text.count("manifest:\n") == 1
        assert "MANIFEST ?=" not in text
        assert "OSPIPE ?= " in text and "PURPOSE ?= draft" in text
        assert [p.name for p in read_map(makefile).products] == ["manuscript", "slides"]

    def test_an_existing_manifest_rule_is_left_alone(self, project):
        makefile = project / "Makefile"
        before = (
            "OSPIPE ?= python3 -m ospipe\nMANIFEST ?= numbers.yml\nPURPOSE ?= draft\nPRODUCT ?=\n\n"
            "manifest:\n\t$(OSPIPE) emit-manifest --manifest $(MANIFEST)\n"
            "emit:\n\t$(OSPIPE) emit --map Makefile --product $(PRODUCT)\n"
        )
        makefile.write_text(before, encoding="utf-8")
        add_product(makefile, "manuscript", "manuscript.md")
        text = makefile.read_text(encoding="utf-8")
        assert text.startswith(before)
        assert text[len(before):].lstrip("\n").startswith(".PHONY: manuscript\n")


class TestEmitRule:
    EMIT_RULE = "emit:\n\t$(OSPIPE) emit --map Makefile --product $(PRODUCT)\n"

    def test_a_new_file_gets_the_product_variable_and_the_emit_rule_once(self, project):
        makefile = project / "Makefile"
        add_product(makefile, "manuscript", "manuscript.md")
        add_product(makefile, "slides", "slides.md", to="revealjs")
        text = makefile.read_text(encoding="utf-8")
        assert "PRODUCT ?=" in text.splitlines()
        assert text.count("PRODUCT ?=") == 1
        assert text.count(self.EMIT_RULE) == 1
        assert text.index(self.EMIT_RULE) < text.index(".PHONY: manuscript")
        assert [p.name for p in read_map(makefile).products] == ["manuscript", "slides"]

    def test_an_existing_file_without_an_emit_target_gets_one(self, project):
        makefile = project / "Makefile"
        before = "# Kept by hand.\nMANIFEST := numbers.yml\n\nmanifest:\n\techo by hand\n"
        makefile.write_text(before, encoding="utf-8")
        add_product(makefile, "manuscript", "manuscript.md")
        text = makefile.read_text(encoding="utf-8")
        assert text.startswith(before)
        assert text.count(self.EMIT_RULE) == 1
        assert "PRODUCT ?=" in text.splitlines()

    def test_an_existing_emit_target_gets_no_second_rule_or_variable(self, project):
        makefile = project / "Makefile"
        before = "emit:\n\techo shipped by hand\n"
        makefile.write_text(before, encoding="utf-8")
        add_product(makefile, "manuscript", "manuscript.md")
        text = makefile.read_text(encoding="utf-8")
        assert text.startswith(before)
        assert self.EMIT_RULE not in text
        assert "PRODUCT ?=" not in text
        assert text.count("emit:") == 1

    def test_a_defined_product_variable_is_left_alone(self, project):
        makefile = project / "Makefile"
        before = "PRODUCT := manuscript\n"
        makefile.write_text(before, encoding="utf-8")
        add_product(makefile, "manuscript", "manuscript.md")
        text = makefile.read_text(encoding="utf-8")
        assert "PRODUCT ?=" not in text
        assert text.count(self.EMIT_RULE) == 1

    def test_emit_is_not_a_product_name(self, project):
        makefile = project / "Makefile"
        with pytest.raises(AddProductError) as caught:
            add_product(makefile, "emit", "manuscript.md")
        assert any("already a target" in p for p in caught.value.problems)
        assert not makefile.exists()


class TestRefusals:
    @pytest.mark.parametrize(
        "kwargs, words",
        [
            ({"name": "manuscript", "source": "slides.md"}, "already a target"),
            ({"name": "manifest", "source": "slides.md"}, "already a target"),
            ({"name": "two words", "source": "slides.md"}, "letters, digits"),
            ({"name": "v1.2", "source": "slides.md"}, "letters, digits"),
            ({"name": "", "source": "slides.md"}, "letters, digits"),
            ({"name": "foo\n", "source": "slides.md"}, "letters, digits"),
            ({"name": "talk", "source": "absent.md"}, "absent.md does not exist"),
            ({"name": "talk", "source": "slides.md", "builds_dir": "builds/manuscript/"}, "builds/manuscript"),
            ({"name": "talk", "source": "slides.md", "to": "pdf"}, "pdf"),
        ],
    )
    def test_each_refusal_leaves_the_file_unchanged(self, project, kwargs, words):
        makefile = project / "Makefile"
        add_product(makefile, "manuscript", "manuscript.md")
        before = makefile.read_bytes()
        with pytest.raises(AddProductError) as caught:
            add_product(makefile, **kwargs)
        assert any(words in p for p in caught.value.problems), caught.value.problems
        assert makefile.read_bytes() == before

    def test_a_refusal_on_a_new_file_writes_nothing(self, project):
        makefile = project / "Makefile"
        with pytest.raises(AddProductError):
            add_product(makefile, "talk", "absent.md")
        assert not makefile.exists()

    def test_a_new_file_with_a_newline_in_the_name_writes_nothing(self, project):
        makefile = project / "Makefile"
        with pytest.raises(AddProductError):
            add_product(makefile, "foo\n", "slides.md")
        assert not makefile.exists()

    def test_a_rule_that_would_not_read_back_leaves_the_file_unchanged(self, project):
        makefile = project / "Makefile"
        makefile.write_text("OSPIPE = ./run.sh\n\nmanifest:\n\t$(OSPIPE) emit-manifest\n", encoding="utf-8")
        before = makefile.read_bytes()
        with pytest.raises(AddProductError) as caught:
            add_product(makefile, "talk", "slides.md")
        assert any("read back" in p for p in caught.value.problems), caught.value.problems
        assert makefile.read_bytes() == before
        with pytest.raises(AddProductError) as again:
            add_product(makefile, "talk", "slides.md")
        assert not any("already a target" in p for p in again.value.problems)

    def test_every_problem_is_listed_at_once(self, project):
        makefile = project / "Makefile"
        add_product(makefile, "manuscript", "manuscript.md")
        with pytest.raises(AddProductError) as caught:
            add_product(makefile, "manuscript", "absent.md", builds_dir="builds/manuscript")
        assert len(caught.value.problems) == 3


class TestCommand:
    def test_adds_a_product_and_exits_0(self, project):
        run = _run_cli(["--name", "slides", "--source", "slides.md", "--to", "revealjs"], cwd=project)
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines() == ["added slides to Makefile, slides.md -> builds/slides (revealjs)"]
        (product,) = read_map(project / "Makefile").products
        assert product.to == "revealjs"

    def test_every_option_reaches_the_rule(self, project):
        run = _run_cli([
            "--map", str(project / "Makefile"), "--name", "paper", "--source", "manuscript.md",
            "--builds-dir", "out/paper", "--bib", "refs.bib", "--csl", "a.csl",
            "--reference-doc", "ref.docx", "--tables-dir", "tables",
        ])
        assert run.returncode == 0, run.stderr
        (product,) = read_map(project / "Makefile").products
        assert (product.builds_dir, product.bib, product.csl, product.reference_doc, product.tables_dir) == (
            "out/paper", "refs.bib", "a.csl", "ref.docx", "tables")

    def test_a_refusal_exits_2_listing_each_problem(self, project):
        _run_cli(["--name", "manuscript", "--source", "manuscript.md"], cwd=project)
        before = (project / "Makefile").read_bytes()
        run = _run_cli(["--name", "manuscript", "--source", "absent.md"], cwd=project)
        assert run.returncode == 2
        assert "already a target" in run.stderr
        assert "absent.md does not exist" in run.stderr
        assert (project / "Makefile").read_bytes() == before

    def test_to_outside_the_three_is_a_usage_error(self, project):
        run = _run_cli(["--name", "x", "--source", "slides.md", "--to", "pdf"], cwd=project)
        assert run.returncode == 2
        assert "invalid choice" in run.stderr


@pytest.mark.skipif(MAKE is None, reason="make is not on the path")
class TestMake:
    def test_make_builds_the_sample_products(self, tmp_path):
        before = _checksums(SAMPLE_PROJECT)
        copy = tmp_path / "sample_project"
        shutil.copytree(str(SAMPLE_PROJECT), str(copy), ignore=shutil.ignore_patterns("__pycache__", "builds"))
        makefile = copy / "Makefile"
        add_product(makefile, "manuscript", "manuscript.md", bib="refs.bib", tables_dir=".")
        add_product(makefile, "slides", "slides.md", to="revealjs", tables_dir=".")
        numbers_before = (copy / "numbers.yml").read_bytes()

        for target in ("manuscript", "slides"):
            run = subprocess.run([MAKE, target], capture_output=True, text=True, cwd=str(copy))
            assert run.returncode == 0, run.stdout + run.stderr
        assert (copy / "builds" / "manuscript" / "v001.docx").is_file()
        assert (copy / "builds" / "slides" / "v001.html").is_file()
        assert "30.0" in (copy / "builds" / "manuscript" / "v001.md").read_text(encoding="utf-8")

        run = subprocess.run([MAKE, "manifest"], capture_output=True, text=True, cwd=str(copy))
        assert run.returncode == 0, run.stdout + run.stderr
        assert "numbers.yml unchanged" in run.stdout
        assert (copy / "numbers.yml").read_bytes() == numbers_before
        assert _checksums(SAMPLE_PROJECT) == before
