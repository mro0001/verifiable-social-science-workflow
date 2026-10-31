"""Step F6. The organizer's inventory of files and the project map.

Each test copies the fixture features/tests/fixtures/organizer_project/ to a
temporary folder. By the reconciliation (Track F), the map's products come
from ospipe products --json run through the layer runner, author_draft.md is
protected, and the organizer refuses and prunes no folder for being excluded
(reconciliation item 3), so the scan reads no audit settings.

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import hashlib
import io
import json
import os
import shutil
from pathlib import Path

import pytest

from features import cli, layers
from features.organizer import inventory
from features.setup import system
from features.tests.test_system_setup import fake_detector

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "features" / "tests" / "fixtures" / "organizer_project"
NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)
LATER = datetime.datetime(2026, 10, 30, 14, 0, 0, tzinfo=datetime.timezone.utc)

# Each fixture file with its kind, its protected flag, and the canonical it reads as.
EXPECTED = {
    "Makefile": ("build_input", True, None),
    "manuscript.md": ("canonical", True, None),
    "drafts/manuscript_old.md": ("lookalike", False, "manuscript.md"),
    "drafts/retention_full.md": ("lookalike", False, "manuscript.md"),
    "drafts/early.md": ("archived", False, "manuscript.md"),
    "numbers.yml": ("build_input", True, None),
    "refs.bib": ("build_input", True, None),
    "pipeline.yaml": ("build_input", True, None),
    "s1.py": ("declared", True, None),
    "raw.csv": ("declared", True, None),
    "notes/writing.md": ("notes", False, None),
    "stray.txt": ("other", False, None),
    "verification/README.md": ("verification", True, None),
}


class SpyRunner(object):
    """Runs each layer command for real and records its arguments."""

    def __init__(self):
        self.calls = []

    def __call__(self, layer, args, root=None, cwd=None, env=None, timeout=600):
        self.calls.append((layer, list(args), cwd))
        return layers.run_layer(layer, args, root=root, cwd=cwd, env=env, timeout=timeout)


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and both home variables at temporary folders, so nothing real is touched."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    return home


def copy_fixture(tmp_path, name="project"):
    target = tmp_path / name
    shutil.copytree(str(FIXTURE), str(target))
    return target


def make_home(tmp_path, excluded=()):
    """A features home written by system setup with fake detection."""
    home = tmp_path / "features_home"
    given = {"scholar_name": "Test Scholar", "excluded_folders": [str(f) for f in excluded],
             "citation_export": ""}
    result = system.run_system_setup(str(home), str(tmp_path / "audit_home"), given,
                                     str(ROOT), NOW, detector=fake_detector())
    assert result.ready
    return home


def scan(project):
    project_map = inventory.read_map(str(project), root=str(ROOT))
    declared = inventory.read_declared(str(project))
    return {entry.path: entry for entry in inventory.scan_files(str(project), project_map, declared)}


def snapshot(folder):
    found = {}
    for here, dirs, files in os.walk(str(folder)):
        dirs[:] = [name for name in dirs if name != ".organizer"]
        for name in files:
            path = os.path.join(here, name)
            found[os.path.relpath(path, str(folder))] = Path(path).read_bytes()
    return found


def run_command(argv):
    out = io.StringIO()
    err = io.StringIO()
    parser, _ = cli._parser()
    options = parser.parse_args(argv)
    code = options.run(options, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# The project map, from ospipe products --json.

def test_read_map_takes_the_products_from_ospipe_products_json(tmp_path):
    project = copy_fixture(tmp_path)
    spy = SpyRunner()
    project_map = inventory.read_map(str(project), root=str(ROOT), runner=spy)
    assert [(layer, args) for layer, args, _ in spy.calls] == [("ospipe", ["products", "--json"])]
    assert os.path.realpath(spy.calls[0][2]) == os.path.realpath(str(project))
    assert [item["name"] for item in project_map.products] == ["manuscript"]
    product = project_map.products[0]
    assert product["source"] == "manuscript.md"
    assert product["builds_dir"] == "builds/manuscript"
    assert project_map.problems == []


def test_referenced_holds_the_manifest_and_the_bibliography(tmp_path):
    project = copy_fixture(tmp_path)
    project_map = inventory.read_map(str(project), root=str(ROOT))
    assert project_map.referenced == ["numbers.yml", "refs.bib"]


def test_referenced_also_holds_a_csl_and_a_reference_doc(tmp_path):
    project = copy_fixture(tmp_path)
    makefile = project / "Makefile"
    makefile.write_text(makefile.read_text(encoding="utf-8").replace(
        "--bib refs.bib", "--bib refs.bib --csl style.csl --reference-doc styles/ref.docx"),
        encoding="utf-8")
    project_map = inventory.read_map(str(project), root=str(ROOT))
    assert project_map.referenced == ["numbers.yml", "refs.bib", "style.csl", "styles/ref.docx"]


def test_a_missing_makefile_is_a_problem_and_not_an_error(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "Makefile").unlink()
    spy = SpyRunner()
    project_map = inventory.read_map(str(project), root=str(ROOT), runner=spy)
    assert project_map.products == []
    assert project_map.referenced == []
    assert len(project_map.problems) == 1
    assert "Makefile" in project_map.problems[0]


def test_a_problem_ospipe_finds_in_the_build_file_is_kept(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "manuscript.md").rename(project / "renamed.md")
    project_map = inventory.read_map(str(project), root=str(ROOT))
    assert [item["name"] for item in project_map.products] == ["manuscript"]
    assert project_map.problems == ["manuscript: source manuscript.md does not exist"]


def test_output_that_is_not_json_is_a_problem(tmp_path):
    project = copy_fixture(tmp_path)

    def broken(layer, args, root=None, cwd=None, env=None, timeout=600):
        return layers.LayerResult(["ospipe"] + list(args), 1, "", "the stand-in failure\n")

    project_map = inventory.read_map(str(project), root=str(ROOT), runner=broken)
    assert project_map.products == []
    assert len(project_map.problems) == 1
    assert "exit 1" in project_map.problems[0]
    assert "the stand-in failure" in project_map.problems[0]


def test_a_build_file_in_the_build_procedures_source_form_names_no_product(tmp_path):
    # The map is ospipe's (reconciliation, Track F), and ospipe's reader finds a
    # product by its ospipe build command, so a rule in the build procedure's
    # --source form with a Pandoc command after -- is no product.
    project = copy_fixture(tmp_path)
    (project / "Makefile").write_text(
        "manuscript: manuscript.md\n"
        "\tpython3 build.py --source manuscript.md --manifest numbers.yml"
        " --builds-dir builds/manuscript -- pandoc -o out.docx\n", encoding="utf-8")
    project_map = inventory.read_map(str(project), root=str(ROOT))
    assert project_map.products == []
    entries = scan(project)
    assert entries["manuscript.md"].kind != "canonical"
    assert entries["Makefile"].kind == "build_input"


# The files a pipeline, the acquisition record, and the numbers file declare.

def test_read_declared_names_the_pipeline_and_numbers_files(tmp_path):
    project = copy_fixture(tmp_path)
    assert inventory.read_declared(str(project)) == {"s1.py", "raw.csv", "results.json"}


def test_read_declared_names_helpers_and_the_acquisition_records_raw_files(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "pipeline.yaml").write_text(
        "helpers: [lib/io.py]\n"
        "steps:\n"
        "  - id: s1\n    script: s1.py\n    inputs: [raw.csv]\n    outputs: [out/results.json]\n",
        encoding="utf-8")
    (project / "acquisition.yaml").write_text(
        "raw:\n  - file: data/survey.csv\n    sha256: sha256:00\n", encoding="utf-8")
    (project / "numbers.yml").write_text("numbers: {}\n", encoding="utf-8")
    assert inventory.read_declared(str(project)) == {
        "lib/io.py", "s1.py", "raw.csv", "out/results.json", "data/survey.csv"}


def test_read_declared_with_no_files_is_empty(tmp_path):
    project = tmp_path / "bare"
    project.mkdir()
    assert inventory.read_declared(str(project)) == set()


def test_read_declared_skips_a_file_that_is_not_yaml(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "pipeline.yaml").write_text("steps: [\n", encoding="utf-8")
    assert inventory.read_declared(str(project)) == {"results.json"}


# The files, their kinds, and their protected flags.

def test_each_fixture_file_gets_its_kind_and_protected_flag(tmp_path):
    project = copy_fixture(tmp_path)
    entries = scan(project)
    assert sorted(entries) == sorted(EXPECTED)
    for path, (kind, protected, claims) in EXPECTED.items():
        entry = entries[path]
        assert (entry.kind, entry.protected, entry.claims) == (kind, protected, claims), path


def test_each_entry_has_its_size_and_checksum(tmp_path):
    project = copy_fixture(tmp_path)
    for path, entry in scan(project).items():
        data = (project / path).read_bytes()
        assert entry.size == len(data)
        assert entry.sha256 == hashlib.sha256(data).hexdigest()


def test_the_archive_line_is_kept_on_the_archived_file(tmp_path):
    project = copy_fixture(tmp_path)
    entries = scan(project)
    assert entries["drafts/early.md"].archive_line == "> ARCHIVE 2026-09-01: superseded by manuscript.md"
    assert entries["drafts/manuscript_old.md"].archive_line is None
    assert entries["manuscript.md"].archive_line is None


def test_files_are_listed_in_path_order(tmp_path):
    project = copy_fixture(tmp_path)
    project_map = inventory.read_map(str(project), root=str(ROOT))
    entries = inventory.scan_files(str(project), project_map, inventory.read_declared(str(project)))
    paths = [entry.path for entry in entries]
    assert paths == sorted(paths)


def test_a_file_under_the_builds_folder_is_not_listed(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "builds" / "manuscript").mkdir(parents=True)
    (project / "builds" / "manuscript" / "v001.md").write_text("# Retention in Small Agencies\n",
                                                               encoding="utf-8")
    (project / "builds" / "manuscript" / "v001.docx").write_bytes(b"docx")
    entries = scan(project)
    assert not [path for path in entries if path.startswith("builds/")]


@pytest.mark.parametrize("folder", [".git", ".organizer", "__pycache__", "ship", "drafts/__pycache__"])
def test_the_walk_skips_its_fixed_folders(tmp_path, folder):
    project = copy_fixture(tmp_path)
    (project / folder).mkdir(parents=True, exist_ok=True)
    (project / folder / "manuscript_copy.md").write_text("# Retention in Small Agencies\n",
                                                         encoding="utf-8")
    entries = scan(project)
    assert sorted(entries) == sorted(EXPECTED)


def test_a_notes_file_that_reads_as_the_manuscript_is_a_lookalike(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "notes" / "retention.md").write_text("# Retention in Small Agencies\n\nNotes.\n",
                                                    encoding="utf-8")
    entry = scan(project)["notes/retention.md"]
    assert (entry.kind, entry.protected, entry.claims) == ("lookalike", False, "manuscript.md")


def test_author_draft_is_protected_and_never_a_lookalike(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "author_draft.md").write_text(
        "---\ntitle: \"Retention in Small Agencies\"\n---\n\nThe author's earlier text.\n",
        encoding="utf-8")
    (project / "drafts" / "author_draft.md").write_text("# Retention in Small Agencies\n",
                                                        encoding="utf-8")
    entries = scan(project)
    for path in ("author_draft.md", "drafts/author_draft.md"):
        assert entries[path].kind != "lookalike", path
        assert entries[path].protected, path
        assert entries[path].claims is None, path


def test_a_referenced_file_and_a_declared_file_are_protected(tmp_path):
    project = copy_fixture(tmp_path)
    makefile = project / "Makefile"
    makefile.write_text(makefile.read_text(encoding="utf-8").replace(
        "--bib refs.bib", "--bib refs.bib --csl style.csl"), encoding="utf-8")
    (project / "style.csl").write_text("<style/>\n", encoding="utf-8")
    (project / "results.json").write_text("{}\n", encoding="utf-8")
    entries = scan(project)
    assert (entries["style.csl"].kind, entries["style.csl"].protected) == ("build_input", True)
    assert (entries["results.json"].kind, entries["results.json"].protected) == ("declared", True)


def test_a_markdown_file_with_an_archive_line_and_no_claim_is_archived(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "drafts" / "aside.md").write_text(
        "> ARCHIVE 2026-08-01: superseded by manuscript.md\n\n# Something else\n", encoding="utf-8")
    entry = scan(project)["drafts/aside.md"]
    assert (entry.kind, entry.claims) == ("archived", None)


def test_a_link_to_nothing_is_skipped_with_a_message(tmp_path):
    project = copy_fixture(tmp_path)
    os.symlink(str(tmp_path / "nowhere.md"), str(project / "gone.md"))
    found = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    assert "gone.md" not in [entry["path"] for entry in found["files"]]
    assert any("gone.md" in message for message in found["messages"])


def test_a_scan_changes_no_project_file(tmp_path):
    project = copy_fixture(tmp_path)
    before = snapshot(project)
    found = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    inventory.write_inventory(str(project), found)
    assert snapshot(project) == before


# The inventory record.

def test_build_inventory_has_every_field(tmp_path):
    project = copy_fixture(tmp_path)
    found = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    assert list(found) == ["schema", "schema_version", "inventory_id", "project", "scanned_at",
                           "map", "files", "builds", "build_problems", "sessions", "messages"]
    assert found["schema"] == "organizer-inventory"
    assert found["schema_version"] == 1
    assert found["project"] == os.path.realpath(str(project))
    assert found["scanned_at"] == "2026-10-29T09:30:00+00:00"
    assert sorted(found["map"]) == ["problems", "products", "referenced"]
    assert [entry["path"] for entry in found["files"]] == sorted(EXPECTED)
    assert sorted(found["files"][0]) == sorted(
        ["path", "size", "sha256", "kind", "claims", "archive_line", "protected", "sessions"])
    assert found["messages"] == []
    assert len(found["inventory_id"]) == 64


def test_two_scans_of_an_unchanged_project_give_the_same_id(tmp_path):
    project = copy_fixture(tmp_path)
    first = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    inventory.write_inventory(str(project), first)
    second = inventory.build_inventory(str(project), LATER, root=str(ROOT))
    assert second["inventory_id"] == first["inventory_id"]


def test_the_id_holds_no_absolute_path(tmp_path):
    one = copy_fixture(tmp_path, "one")
    other = copy_fixture(tmp_path, "other")
    first = inventory.build_inventory(str(one), NOW, root=str(ROOT))
    second = inventory.build_inventory(str(other), LATER, root=str(ROOT))
    assert first["inventory_id"] == second["inventory_id"]


def test_one_changed_byte_changes_the_id(tmp_path):
    project = copy_fixture(tmp_path)
    first = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    stray = project / "stray.txt"
    data = bytearray(stray.read_bytes())
    data[0] = ord("a") if data[0] != ord("a") else ord("b")
    stray.write_bytes(bytes(data))
    second = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    assert second["inventory_id"] != first["inventory_id"]


def test_a_changed_kind_changes_the_id(tmp_path):
    project = copy_fixture(tmp_path)
    first = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    (project / "pipeline.yaml").write_text(
        (project / "pipeline.yaml").read_text(encoding="utf-8").replace(
            "inputs: [raw.csv]", "inputs: [raw.csv, stray.txt]"), encoding="utf-8")
    second = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    assert second["inventory_id"] != first["inventory_id"]


def test_write_inventory_writes_the_organizers_file(tmp_path):
    project = copy_fixture(tmp_path)
    found = inventory.build_inventory(str(project), NOW, root=str(ROOT))
    path = inventory.write_inventory(str(project), found)
    assert Path(path) == project / ".organizer" / "inventory.json"
    assert json.loads(Path(path).read_text(encoding="utf-8")) == found


# The command.

def test_scan_refuses_without_system_yaml_naming_the_setup_command(tmp_path):
    project = copy_fixture(tmp_path)
    code, out, err = run_command(["organize", "scan", str(project),
                                  "--home", str(tmp_path / "empty_home")])
    assert code == 1
    assert system.COMMAND in err
    assert not (project / ".organizer").exists()


def test_scan_refuses_a_folder_that_does_not_exist(tmp_path):
    home = make_home(tmp_path)
    code, out, err = run_command(["organize", "scan", str(tmp_path / "absent"), "--home", str(home)])
    assert code == 1
    assert "absent" in err
    assert not (tmp_path / "absent").exists()


def test_scan_writes_the_inventory_and_prints_counts_and_lookalikes(tmp_path):
    project = copy_fixture(tmp_path)
    home = make_home(tmp_path)
    code, out, err = run_command(["organize", "scan", str(project), "--home", str(home)])
    assert code == 0, err
    written = json.loads((project / ".organizer" / "inventory.json").read_text(encoding="utf-8"))
    assert written["schema"] == "organizer-inventory"
    assert "canonical 1" in out
    assert "build_input 4" in out
    assert "lookalike 2" in out
    assert "drafts/manuscript_old.md reads as manuscript.md" in out
    assert "drafts/retention_full.md reads as manuscript.md" in out
    assert written["inventory_id"] in out


def test_scan_prints_the_build_files_problems(tmp_path):
    project = copy_fixture(tmp_path)
    (project / "Makefile").unlink()
    home = make_home(tmp_path)
    code, out, err = run_command(["organize", "scan", str(project), "--home", str(home)])
    assert code == 0, err
    assert "Makefile" in out
    assert (project / ".organizer" / "inventory.json").is_file()


def test_scan_refuses_no_folder_for_being_excluded_and_reads_no_audit_settings(tmp_path):
    # Reconciliation item 3 drops the organizer's refusals and pruning.
    outer = tmp_path / "excluded"
    outer.mkdir()
    project = copy_fixture(outer)
    home = make_home(tmp_path, excluded=[outer])
    (tmp_path / "audit_home" / "settings.yaml").unlink()
    code, out, err = run_command(["organize", "scan", str(project), "--home", str(home)])
    assert code == 0, err
    written = json.loads((project / ".organizer" / "inventory.json").read_text(encoding="utf-8"))
    assert sorted(entry["path"] for entry in written["files"]) == sorted(EXPECTED)


def test_the_organize_group_lists_scan(tmp_path):
    parser, helps = cli._parser()
    assert "scan" in helps["organize"].format_help()
