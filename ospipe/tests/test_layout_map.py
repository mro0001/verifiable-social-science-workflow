"""Reading the build file. Makefiles from the layout fixture, written into a temporary
project folder with every source the map names."""
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.layout import Product, ProjectMap, fixture, read_map  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
# /usr/bin/make on this Mac is an xcrun shim that fails under an x86_64 python, so the
# real binary is called when it is there.
_REAL_MAKE = "/Library/Developer/CommandLineTools/usr/bin/make"
MAKE = _REAL_MAKE if os.path.exists(_REAL_MAKE) else shutil.which("make")


def _project(folder, makefile_text):
    folder.mkdir(parents=True, exist_ok=True)
    for relative, text in fixture.FILES.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    makefile = folder / "Makefile"
    makefile.write_text(makefile_text, encoding="utf-8")
    return makefile


@pytest.fixture()
def map_file(tmp_path):
    return _project(tmp_path / "project", fixture.MAP_MAKEFILE)


@pytest.fixture()
def problem_file(tmp_path):
    return _project(tmp_path / "project", fixture.PROBLEM_MAKEFILE)


def _run_cli(args, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(OSPIPE_DIR)
    return subprocess.run(
        [sys.executable, "-m", "ospipe", "products"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd or OSPIPE_DIR),
        env=env,
    )


class TestReadMap:
    def test_two_products_with_every_field(self, map_file):
        project_map = read_map(map_file)
        assert isinstance(project_map, ProjectMap)
        assert project_map.problems == []
        assert Path(project_map.project_dir) == map_file.parent.resolve()
        assert [p.name for p in project_map.products] == ["manuscript", "slides"]
        for product in project_map.products:
            assert isinstance(product, Product)
            assert product._asdict() == fixture.EXPECTED[product.name]

    def test_question_mark_assignment_keeps_an_earlier_value(self, map_file):
        slides = read_map(map_file).products[1]
        assert slides.to == "revealjs"

    def test_question_mark_assignment_sets_an_undefined_name(self, map_file):
        text = fixture.MAP_MAKEFILE.replace("TO_SLIDES = revealjs\n", "")
        map_file.write_text(text, encoding="utf-8")
        slides = read_map(map_file).products[1]
        assert slides.to == "docx"

    def test_a_rule_without_an_ospipe_build_is_not_a_product(self, map_file):
        names = [p.name for p in read_map(map_file).products]
        assert "manifest" not in names

    def test_paths_are_relative_to_the_project_folder(self, map_file):
        absolute = str((map_file.parent / "paper" / "paper.md").resolve())
        text = fixture.MAP_MAKEFILE.replace("PAPER := paper/paper.md", "PAPER := " + absolute)
        map_file.write_text(text, encoding="utf-8")
        manuscript = read_map(map_file).products[0]
        assert manuscript.source == "paper/paper.md"
        assert read_map(map_file).problems == []

    def test_to_and_verification_dir_defaults(self, tmp_path):
        makefile = _project(
            tmp_path / "project",
            "paper:\n\tpython3 -m ospipe build --manuscript paper/paper.md --manifest numbers.yml "
            "--builds-dir builds/paper --purpose x\n",
        )
        (product,) = read_map(makefile).products
        assert product.to == "docx"
        assert product.verification_dir == "paper/verification"

    def test_an_option_does_not_take_the_next_option_as_its_value(self, tmp_path):
        makefile = _project(
            tmp_path / "project",
            "paper: paper/paper.md\n\tpython3 -m ospipe build --manuscript $< --manifest numbers.yml "
            "--builds-dir builds/paper --purpose x\n",
        )
        project_map = read_map(makefile)
        (product,) = project_map.products
        assert product.source is None
        assert product.manifest == "numbers.yml"
        assert project_map.problems == ["paper: no --manuscript"]

    def test_source_at_the_project_root_has_verification_beside_it(self, tmp_path):
        makefile = _project(
            tmp_path / "project",
            "top:\n\tpython3 -m ospipe build --manuscript numbers.yml --manifest numbers.yml "
            "--builds-dir builds/top --purpose x\n",
        )
        (product,) = read_map(makefile).products
        assert product.verification_dir == "verification"


class TestProblems:
    def test_each_problem_kind_is_reported(self, problem_file):
        project_map = read_map(problem_file)
        for rule, words in fixture.PROBLEM_WORDS:
            assert any(rule in p and words in p for p in project_map.problems), (rule, project_map.problems)
        assert len(project_map.problems) == len(fixture.PROBLEM_WORDS)

    def test_two_products_from_one_source_is_no_problem(self, problem_file):
        project_map = read_map(problem_file)
        assert not any("same_source" in p for p in project_map.problems)
        names = [p.name for p in project_map.products]
        assert "same_source_one" in names and "same_source_two" in names

    def test_rules_with_problems_are_still_products(self, problem_file):
        products = {p.name: p for p in read_map(problem_file).products}
        assert products["no_source"].source is None
        assert products["two_sources"].source is None
        assert products["no_manifest"].manifest is None
        assert products["no_builds_dir"].builds_dir is None


@pytest.mark.skipif(MAKE is None, reason="make is not on the path")
class TestMake:
    @pytest.mark.parametrize("name", ["manuscript", "slides"])
    def test_make_dry_run_shows_the_source_the_reader_found(self, map_file, name):
        run = subprocess.run(
            [MAKE, "-n", name], capture_output=True, text=True, cwd=str(map_file.parent)
        )
        assert run.returncode == 0, run.stderr
        words = shlex.split(run.stdout.replace("\\\n", " "))
        if "--manuscript" in words:
            shown = words[words.index("--manuscript") + 1]
        else:
            shown = [w for w in words if w.startswith("--manuscript=")][0].split("=", 1)[1]
        product = [p for p in read_map(map_file).products if p.name == name][0]
        assert shown == product.source


class TestCommand:
    def test_lists_each_product_and_exits_0(self, map_file):
        run = _run_cli(["--map", str(map_file)])
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines() == [
            "manuscript: paper/paper.md -> builds/manuscript (docx)",
            "slides: slides/talk.md -> builds/slides (revealjs)",
        ]

    def test_map_defaults_to_the_makefile_here(self, map_file):
        run = _run_cli([], cwd=map_file.parent)
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines()[0] == "manuscript: paper/paper.md -> builds/manuscript (docx)"

    def test_problems_exit_2_after_the_products(self, problem_file):
        run = _run_cli(["--map", str(problem_file)])
        assert run.returncode == 2
        lines = run.stdout.splitlines()
        assert lines[0].startswith("no_source: ")
        for rule, words in fixture.PROBLEM_WORDS:
            assert any(rule in ln and words in ln for ln in lines[len(read_map(problem_file).products):])

    def test_json_gives_the_whole_map(self, map_file):
        run = _run_cli(["--map", str(map_file), "--json"])
        assert run.returncode == 0, run.stderr
        data = json.loads(run.stdout)
        assert Path(data["project_dir"]) == map_file.parent.resolve()
        assert data["problems"] == []
        assert data["products"] == [fixture.EXPECTED["manuscript"], fixture.EXPECTED["slides"]]

    def test_json_with_problems_exits_2(self, problem_file):
        run = _run_cli(["--map", str(problem_file), "--json"])
        assert run.returncode == 2
        assert len(json.loads(run.stdout)["problems"]) == len(fixture.PROBLEM_WORDS)

    def test_missing_build_file_exits_2(self, tmp_path):
        run = _run_cli(["--map", str(tmp_path / "Makefile")])
        assert run.returncode == 2
        assert "no build file" in run.stderr
