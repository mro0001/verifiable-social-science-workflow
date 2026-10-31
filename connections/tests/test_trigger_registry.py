"""Tests for the procedure registry and the trigger settings (Track D, step D9).

The proposal says events in the harness, such as an AI edit or the end of a
turn, start the verification procedures, and names harness triggers as
designed but not built (Status paragraph 2). Table A6 lists the procedure
registry and triggers as specified. The triggers read the verification
layer's registry, verification_procedures/registry.yaml, read only
(reconciliation item 4), to learn which procedure an edited file makes due.
The command that starts a procedure for a project is the scholar's own, one
per procedure, in <connections home>/triggers.yaml with {project} filled in
(Track D choice 19).

Every test runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a
temporary folder. Run from the repository root with python3 -m pytest -q
connections/tests.
"""
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections.triggers.registry import (  # noqa: E402
    RegistryError,
    load_registry,
    load_trigger_settings,
    matching,
    start_command,
)

LIST_REGISTRY = """\
- id: prose
  graph: graphs/prose.yaml
  triggers:
    files: ["*.md"]
- id: citations
  graph: graphs/citations.yaml
  triggers:
    files: ["*.md", refs.yaml]
- id: build
  graph: graphs/build.yaml
"""

MAPPING_REGISTRY = """\
registry_version: 1
procedures:
  - id: prose
    stream: prose
    graph: graphs/prose.yaml
    triggers:
      events: [ai_edit, turn_end]
      files: ["*.md"]
  - id: citations
    stream: citations
    graph: graphs/citations.yaml
    triggers:
      files: ["*.md", refs.yaml]
  - id: build
    stream: build
    graph: graphs/build.yaml
    triggers:
      events: [build]
"""


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


@pytest.fixture
def project(homes):
    folder = homes / "project"
    (folder / "drafts").mkdir(parents=True)
    return folder


def write_registry(folder, text):
    path = folder / "registry.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def write_settings(text):
    import os

    home = Path(os.environ["CONNECTIONS_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "triggers.yaml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("text", [LIST_REGISTRY, MAPPING_REGISTRY], ids=["list", "mapping"])
def test_both_shapes_load_as_id_graph_and_files(homes, text):
    registry = load_registry(write_registry(homes, text))
    assert registry == [
        {"id": "prose", "graph": "graphs/prose.yaml", "files": ["*.md"]},
        {"id": "citations", "graph": "graphs/citations.yaml", "files": ["*.md", "refs.yaml"]},
        {"id": "build", "graph": "graphs/build.yaml", "files": []},
    ]


@pytest.mark.parametrize("text", [LIST_REGISTRY, MAPPING_REGISTRY], ids=["list", "mapping"])
def test_patterns_match_the_relative_path_or_the_base_name(homes, project, text):
    registry = load_registry(write_registry(homes, text))
    assert matching(registry, project / "manuscript.md", project) == ["prose", "citations"]
    assert matching(registry, project / "drafts" / "x.md", project) == ["prose", "citations"]
    assert matching(registry, project / "refs.yaml", project) == ["citations"]
    assert matching(registry, project / "drafts" / "refs.yaml", project) == ["citations"]
    assert matching(registry, project / "myrefs.yaml", project) == []
    assert matching(registry, project / "refs.yaml.bak", project) == []
    assert matching(registry, project / "data.csv", project) == []


def test_a_relative_path_is_taken_from_the_project(homes, project):
    registry = load_registry(write_registry(homes, MAPPING_REGISTRY))
    assert matching(registry, "drafts/x.md", project) == ["prose", "citations"]


def test_a_file_outside_the_project_matches_nothing(homes, project):
    registry = load_registry(write_registry(homes, MAPPING_REGISTRY))
    elsewhere = homes / "elsewhere"
    elsewhere.mkdir()
    assert matching(registry, elsewhere / "manuscript.md", project) == []
    assert matching(registry, homes / "project_old" / "manuscript.md", project) == []
    assert matching(registry, project / ".." / "manuscript.md", project) == []


def test_an_entry_without_file_patterns_never_matches(homes, project):
    registry = load_registry(write_registry(homes, MAPPING_REGISTRY))
    for name in ("Makefile", "BUILDS.md", "manuscript.md", "x.py"):
        assert "build" not in matching(registry, project / name, project)


@pytest.mark.parametrize(
    "text",
    [
        "just text\n",
        "procedures: nothing\n",
        "- id: prose\n  triggers:\n    files: '*.md'\n",
        "- graph: graphs/prose.yaml\n",
        "- [not, a, mapping]\n",
        "- id: prose\n  triggers: [files]\n",
        "a: [unclosed\n",
    ],
)
def test_a_registry_that_cannot_be_read_is_refused(homes, text):
    with pytest.raises(RegistryError):
        load_registry(write_registry(homes, text))


def test_a_missing_registry_is_refused(homes):
    with pytest.raises(RegistryError):
        load_registry(homes / "no_registry.yaml")


def test_missing_settings_give_no_command(homes, project):
    settings = load_trigger_settings()
    assert settings == {"start": {}, "registry": None}
    assert start_command(settings, "prose", project) is None


def test_settings_that_cannot_be_read_give_empty_settings(homes, project):
    for text in ("a: [unclosed\n", "just text\n", "start: [a, b]\n", "start:\n  prose: 3\n"):
        write_settings(text)
        assert load_trigger_settings() == {"start": {}, "registry": None}


def test_a_command_is_filled_with_the_project(homes, project):
    write_settings("start:\n  prose: run-prose --project {project} --again {project}\n")
    settings = load_trigger_settings()
    assert settings["start"] == {"prose": "run-prose --project {project} --again {project}"}
    command = start_command(settings, "prose", project)
    assert command == f"run-prose --project {project} --again {project}"
    assert start_command(settings, "citations", project) is None


def test_a_project_path_with_a_space_comes_back_quoted(homes):
    folder = homes / "my project"
    folder.mkdir()
    settings = {"start": {"data": "run-data {project}"}, "registry": None}
    command = start_command(settings, "data", folder)
    assert command == "run-data " + shlex.quote(str(folder))
    assert shlex.split(command) == ["run-data", str(folder)]


def test_the_settings_may_name_a_registry(homes):
    write_settings("registry: ~/my_registry.yaml\nstart: {}\n")
    settings = load_trigger_settings()
    assert settings["registry"] == str(Path(homes / "user" / "my_registry.yaml"))


def test_a_relative_registry_is_taken_from_the_connections_home(homes):
    write_settings("registry: regs/registry.yaml\n")
    settings = load_trigger_settings()
    assert settings["registry"] == str(homes / "connections_home" / "regs" / "registry.yaml")


def test_the_repository_registry_loads_with_the_four_streams():
    registry = load_registry()
    ids = [entry["id"] for entry in registry]
    assert ids == ["prose", "citations", "data", "build"]
    for entry in registry:
        assert (ROOT / "verification_procedures" / entry["graph"]).is_file()
    # The report names any stream without file patterns, as a question for
    # the authors. At this commit every stream has them.
    without = [entry["id"] for entry in registry if not entry["files"]]
    assert without == []


def test_the_repository_registry_marks_the_manuscript_for_three_streams(project):
    registry = load_registry()
    assert matching(registry, project / "manuscript.md", project) == ["prose", "citations", "build"]
    assert matching(registry, project / "numbers.yml", project) == ["data"]
    assert matching(registry, project / "data.csv", project) == []


def test_the_registry_module_imports_no_other_layer():
    text = (ROOT / "connections" / "triggers" / "registry.py").read_text(encoding="utf-8")
    for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
        assert f"import {layer}" not in text
        assert f"from {layer}" not in text
