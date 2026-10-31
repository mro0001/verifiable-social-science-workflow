"""Steps F2 and S1. Software detection, with every lookup faked except one interpreter check."""
import json
import os
import platform

import pytest

from features.setup import detect

WORD = "/Applications/Microsoft Word.app"
ZOTERO = "/Applications/Zotero.app"


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and the homes at temporary folders, and leave the model key unset."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "env_connections_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    monkeypatch.delenv("WORKFLOW_MODEL_KEY", raising=False)
    return home

COMMANDS = {
    "pandoc": "/fake/bin/pandoc",
    "make": "/fake/bin/make",
    "git": "/fake/bin/git",
    "gh": "/fake/bin/gh",
    "quarto": "/fake/bin/quarto",
    "Rscript": "/fake/bin/Rscript",
    "claude": "/fake/bin/claude",
    "forge": "/fake/bin/forge",
}

VERSIONS = {
    "pandoc": (0, "pandoc 3.9.0.2\nFeatures: +server +lua\n", ""),
    "make": (0, "GNU Make 3.81\n", ""),
    "git": (0, "git version 2.39.5\n", ""),
    "gh": (0, "gh version 2.40.1 (2023-12-13)\n", ""),
    "quarto": (0, "1.5.57\n", ""),
    "Rscript": (0, "", "Rscript (R) version 4.3.1 (2023-06-16)\n"),
    "claude": (0, "2.1.0 (Claude Code)\n", ""),
    "forge": (0, "forge 0.98.0\n", ""),
}

PACKAGES = {"PyYAML": "6.0.3", "python-docx": "1.2.0", "pytest": "8.4.2"}


class Fakes(object):
    """Every lookup detect makes, answered from dicts the test can change."""

    def __init__(self):
        self.commands = dict(COMMANDS)
        self.versions = dict(VERSIONS)
        self.packages = dict(PACKAGES)
        self.folders = {WORD, ZOTERO, os.path.expanduser("~/Zotero")}
        self.python = (3, 9, 5, "final", 0)
        self.ran = []

    def which(self, name):
        return self.commands.get(name)

    def run_version(self, argv):
        self.ran.append(list(argv))
        answer = self.versions[os.path.basename(argv[0])]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def path_exists(self, path):
        return path in self.folders

    def package_version(self, name):
        return self.packages.get(name)

    def detect(self):
        return detect.detect(
            which=self.which, run_version=self.run_version,
            path_exists=self.path_exists, package_version=self.package_version,
            python_version=self.python)


def by_name(found):
    return {item.name: item for item in found}


def test_the_fixed_list_names_each_tool_with_its_kind():
    rows = [(tool.name, tool.kind, tool.required) for tool in detect.SOFTWARE]
    assert rows == [
        ("python", "language", True),
        ("pyyaml", "package", True),
        ("python-docx", "package", True),
        ("pytest", "package", True),
        ("pandoc", "build", True),
        ("make", "build", True),
        ("git", "version_control", False),
        ("gh", "version_control", False),
        ("quarto", "build", False),
        ("rscript", "statistics", False),
        ("word", "editor", False),
        ("zotero", "citations", False),
        ("zotero_data", "citations", False),
        ("claude_code", "harness", False),
        ("forgecode", "harness", False),
    ]


def test_everything_present_is_ok():
    fakes = Fakes()
    found = by_name(fakes.detect())
    assert list(found) == [tool.name for tool in detect.SOFTWARE]
    assert all(item.found and item.ok for item in found.values())
    assert detect.missing_required(list(found.values())) == []
    assert found["python"].version == "3.9.5"
    assert found["python-docx"].version == "1.2.0"
    assert found["pandoc"].path == "/fake/bin/pandoc"
    assert found["pandoc"].version == "pandoc 3.9.0.2"
    assert found["pandoc"].note == ""
    assert found["claude_code"].version == "2.1.0 (Claude Code)"
    assert ["/fake/bin/forge", "--version"] in fakes.ran


def test_rscript_version_is_read_from_standard_error():
    found = by_name(Fakes().detect())
    assert found["rscript"].version == "Rscript (R) version 4.3.1 (2023-06-16)"


def test_missing_pandoc_is_listed_with_its_hint():
    fakes = Fakes()
    del fakes.commands["pandoc"]
    found = fakes.detect()
    pandoc = by_name(found)["pandoc"]
    assert not pandoc.found and not pandoc.ok
    assert pandoc.path == "" and pandoc.version == ""
    assert [item.name for item in detect.missing_required(found)] == ["pandoc"]
    assert "Pandoc" in detect.install_hint("pandoc")


def test_python_38_is_not_ok():
    fakes = Fakes()
    fakes.python = (3, 8, 10, "final", 0)
    found = fakes.detect()
    python = by_name(found)["python"]
    assert python.found and not python.ok
    assert python.version == "3.8.10"
    assert "3.9" in python.note
    assert [item.name for item in detect.missing_required(found)] == ["python"]


def test_python_docx_11_is_not_ok():
    fakes = Fakes()
    fakes.packages["python-docx"] = "1.1.2"
    found = fakes.detect()
    docx = by_name(found)["python-docx"]
    assert docx.found and not docx.ok
    assert "1.2" in docx.note
    assert [item.name for item in detect.missing_required(found)] == ["python-docx"]


def test_a_missing_package_is_not_found():
    fakes = Fakes()
    del fakes.packages["PyYAML"]
    pyyaml = by_name(fakes.detect())["pyyaml"]
    assert not pyyaml.found and not pyyaml.ok and pyyaml.version == ""


def test_neither_harness_found_is_no_error():
    fakes = Fakes()
    del fakes.commands["claude"]
    del fakes.commands["forge"]
    found = fakes.detect()
    names = by_name(found)
    for name in ("claude_code", "forgecode"):
        assert not names[name].found and not names[name].ok
    assert detect.missing_required(found) == []


@pytest.mark.parametrize("answer", [(1, "", "error\n"), OSError("cannot run")])
def test_a_failing_version_command_is_found_with_a_note(answer):
    fakes = Fakes()
    fakes.versions["git"] = answer
    git = by_name(fakes.detect())["git"]
    assert git.found
    assert git.path == "/fake/bin/git"
    assert git.version == ""
    assert git.note != ""


def test_pandoc_364_gets_the_note_on_the_stored_builds():
    fakes = Fakes()
    fakes.versions["pandoc"] = (0, "pandoc 3.6.4\n", "")
    pandoc = by_name(fakes.detect())["pandoc"]
    assert pandoc.ok
    assert pandoc.version == "pandoc 3.6.4"
    assert "3.9.0.2" in pandoc.note


@pytest.mark.parametrize("present", [True, False])
def test_word_is_found_by_its_folder_alone(present):
    fakes = Fakes()
    if not present:
        fakes.folders = set()
    word = by_name(fakes.detect())["word"]
    assert word.found is present
    assert word.ok is present
    assert word.version == ""
    assert word.path == (WORD if present else "")
    assert not any("Word" in " ".join(argv) for argv in fakes.ran)


def test_each_tool_has_one_plain_install_line():
    for tool in detect.SOFTWARE:
        hint = detect.install_hint(tool.name)
        assert hint and "\n" not in hint
    line = 'python3 -m pip install pyyaml "python-docx>=1.2" pytest'
    for name in ("pyyaml", "python-docx", "pytest"):
        assert detect.install_hint(name) == line


def test_an_unknown_tool_has_no_hint():
    with pytest.raises(ValueError):
        detect.install_hint("excel")


def test_the_real_interpreter_check():
    nothing = Fakes()
    nothing.commands = {}
    nothing.packages = {}
    nothing.folders = set()
    found = by_name(detect.detect(
        which=nothing.which, run_version=nothing.run_version,
        path_exists=nothing.path_exists, package_version=nothing.package_version))
    python = found["python"]
    assert python.found and python.ok
    assert python.version == platform.python_version()
    assert nothing.ran == []


# Step S1. Make is required, and Zotero and the GitHub command line are looked for.


def test_missing_make_is_a_missing_required_tool():
    fakes = Fakes()
    del fakes.commands["make"]
    found = fakes.detect()
    assert [item.name for item in detect.missing_required(found)] == ["make"]
    assert "make" in detect.install_hint("make")


@pytest.mark.parametrize("present", [set(), {ZOTERO}, {"data"}, {ZOTERO, "data"}])
def test_zotero_is_found_by_its_application_and_data_folder_existing_alone(present, private_home):
    fakes = Fakes()
    data = str(private_home / "Zotero")
    fakes.folders = {WORD} | {data if name == "data" else name for name in present}
    asked = []

    def path_exists(path):
        asked.append(path)
        return path in fakes.folders

    found = by_name(detect.detect(
        which=fakes.which, run_version=fakes.run_version, path_exists=path_exists,
        package_version=fakes.package_version, python_version=fakes.python))
    assert found["zotero"].found is (ZOTERO in present)
    assert found["zotero_data"].found is ("data" in present)
    assert found["zotero_data"].path == (data if "data" in present else "")
    assert ZOTERO in asked and data in asked
    assert not any("otero" in " ".join(argv) for argv in fakes.ran)


@pytest.mark.parametrize("present", [True, False])
def test_the_github_command_line_is_found_by_its_version(present):
    fakes = Fakes()
    if not present:
        del fakes.commands["gh"]
    gh = by_name(fakes.detect())["gh"]
    assert gh.found is present
    assert gh.version == ("gh version 2.40.1 (2023-12-13)" if present else "")
    assert detect.install_hint("gh")


# Step S1. Every outside program is reached through the one runner function.


class StandIn(object):
    """Stands in for run_program, answering by the program's name and recording each call."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        key = tuple([os.path.basename(argv[0])] + list(argv[1:]))
        for length in range(len(key), 0, -1):
            if key[:length] in self.answers:
                answer = self.answers[key[:length]]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return (0, "%s 1.0\n" % key[0], "")


def stand_ins(monkeypatch, programs=("claude", "forge", "git", "gh", "make", "pandoc"),
              folders=(), answers=None):
    runner = StandIn(answers)
    paths = {name: "/fake/bin/" + name for name in programs}
    monkeypatch.setattr(detect, "run_program", runner)
    monkeypatch.setattr(detect, "find_program", paths.get)
    monkeypatch.setattr(detect, "folder_exists", lambda path: path in folders)
    return runner


def test_detect_runs_each_program_through_the_runner_function(monkeypatch):
    runner = stand_ins(monkeypatch)
    found = by_name(detect.detect(package_version=lambda name: "1.2.0"))
    assert found["claude_code"].found and found["forgecode"].found
    assert ["/fake/bin/claude", "--version"] in runner.calls
    assert ["/fake/bin/forge", "--version"] in runner.calls
    assert ["/fake/bin/git", "--version"] in runner.calls
    assert not found["word"].found


def state(tmp_path, monkeypatch, **given):
    given.setdefault("audit_home", str(tmp_path / "audit_home"))
    return detect.detect_state(**given)


def test_gits_user_name_is_read_through_the_runner(tmp_path, monkeypatch):
    runner = stand_ins(monkeypatch, answers={
        ("git", "config", "--global", "--get", "user.name"): (0, "Test Scholar\n", "")})
    found = state(tmp_path, monkeypatch)
    assert found.git_name == "Test Scholar"
    assert ["/fake/bin/git", "config", "--global", "--get", "user.name"] in runner.calls


@pytest.mark.parametrize("answer", [(1, "", ""), (0, "\n", ""), OSError("cannot run")])
def test_no_git_name_gives_an_empty_name(tmp_path, monkeypatch, answer):
    stand_ins(monkeypatch, answers={("git", "config"): answer})
    assert state(tmp_path, monkeypatch).git_name == ""


def test_without_git_no_name_is_looked_for(tmp_path, monkeypatch):
    runner = stand_ins(monkeypatch, programs=("claude",))
    assert state(tmp_path, monkeypatch).git_name == ""
    assert not [call for call in runner.calls if "git" in call[0]]


def test_the_model_key_is_reported_as_set_and_its_value_never_kept(tmp_path, monkeypatch):
    stand_ins(monkeypatch)
    secret = "sk-test-secret-0123456789"
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", secret)
    found = state(tmp_path, monkeypatch)
    assert found.model_key_set is True
    assert secret not in repr(found)
    monkeypatch.setenv("WORKFLOW_MODEL_KEY", "")
    assert state(tmp_path, monkeypatch).model_key_set is False
    monkeypatch.delenv("WORKFLOW_MODEL_KEY")
    assert state(tmp_path, monkeypatch).model_key_set is False


def test_the_folders_already_excluded_are_read_from_the_audit_settings(tmp_path, monkeypatch):
    stand_ins(monkeypatch)
    audit = tmp_path / "audit_home"
    assert state(tmp_path, monkeypatch).excluded_folders is None
    audit.mkdir()
    (audit / "settings.yaml").write_text(
        "excluded_folders:\n  - /records\n  - /advising\n", encoding="utf-8")
    assert state(tmp_path, monkeypatch).excluded_folders == ["/records", "/advising"]
    (audit / "settings.yaml").write_text("excluded_folders: [/unclosed\n", encoding="utf-8")
    found = state(tmp_path, monkeypatch)
    assert found.excluded_folders is None
    assert any(str(audit / "settings.yaml") in note for note in found.notes)


def test_detection_never_looks_inside_an_excluded_folder(tmp_path, monkeypatch):
    stand_ins(monkeypatch)
    audit = tmp_path / "audit_home"
    audit.mkdir()
    records = tmp_path / "records"
    records.mkdir()
    (records / "student.txt").write_text("private", encoding="utf-8")
    (audit / "settings.yaml").write_text("excluded_folders:\n  - %s\n" % records,
                                         encoding="utf-8")
    opened = []
    real_listdir, real_scandir = os.listdir, os.scandir
    monkeypatch.setattr(os, "listdir", lambda path=".": opened.append(str(path))
                        or real_listdir(path))
    monkeypatch.setattr(os, "scandir", lambda path=".": opened.append(str(path))
                        or real_scandir(path))
    state(tmp_path, monkeypatch)
    assert not [path for path in opened if str(records) in path]


def write_settings_json(home, hooks):
    folder = home / ".claude"
    folder.mkdir(exist_ok=True)
    (folder / "settings.json").write_text(json.dumps({"hooks": hooks}), encoding="utf-8")


def command_entry(*commands, matcher=None):
    entry = {"hooks": [{"type": "command", "command": text} for text in commands]}
    if matcher:
        entry["matcher"] = matcher
    return [entry]


CAPTURE = "/usr/bin/python3 /repo/audit_layer/hooks/claude_code_hook.py"
TRIGGER = "PYTHONPATH=/repo python3 -m connections trigger hook"


def test_the_workflows_hooks_are_found_among_the_scholars_own(tmp_path, monkeypatch,
                                                             private_home):
    stand_ins(monkeypatch)
    assert state(tmp_path, monkeypatch).hooks == {"capture": [], "trigger": []}
    write_settings_json(private_home, {
        "Stop": command_entry("echo mine", CAPTURE, TRIGGER),
        "SubagentStop": command_entry(CAPTURE),
        "PostToolUse": command_entry(TRIGGER, matcher="Edit|Write"),
        "Notification": command_entry("echo other"),
    })
    found = state(tmp_path, monkeypatch)
    assert found.hooks == {"capture": ["Stop", "SubagentStop"], "trigger": ["PostToolUse", "Stop"]}


def test_a_settings_json_that_cannot_be_read_is_named(tmp_path, monkeypatch, private_home):
    stand_ins(monkeypatch)
    (private_home / ".claude").mkdir()
    path = private_home / ".claude" / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    before = path.read_bytes()
    found = state(tmp_path, monkeypatch)
    assert found.hooks == {"capture": [], "trigger": []}
    assert any(str(path) in note for note in found.notes)
    assert path.read_bytes() == before


MCP_LIST = (
    "Checking MCP server health...\n\n"
    "workflow-kb: python3 -m connections serve kb --index /x/kb_index.json - ✓ Connected\n"
    "workflow-events: python3 -m connections serve events - ✗ Failed to connect\n"
    "other-server: npx other - ✓ Connected\n"
)


def test_the_workflows_servers_are_read_from_claude_mcp_list_through_the_runner(
        tmp_path, monkeypatch):
    runner = stand_ins(monkeypatch, answers={("claude", "mcp", "list"): (0, MCP_LIST, "")})
    found = state(tmp_path, monkeypatch)
    assert found.servers == ["workflow-kb", "workflow-events"]
    assert ["/fake/bin/claude", "mcp", "list"] in runner.calls


@pytest.mark.parametrize("answer", [(1, "", "failed\n"), OSError("cannot run")])
def test_a_failing_server_list_is_not_known_and_named(tmp_path, monkeypatch, answer):
    stand_ins(monkeypatch, answers={("claude", "mcp", "list"): answer})
    found = state(tmp_path, monkeypatch)
    assert found.servers is None
    assert any("claude mcp list" in note for note in found.notes)


def test_without_claude_code_no_server_list_is_run(tmp_path, monkeypatch):
    runner = stand_ins(monkeypatch, programs=("git", "forge"))
    found = state(tmp_path, monkeypatch)
    assert found.servers is None
    assert not [call for call in runner.calls if call[0].endswith("claude")]
