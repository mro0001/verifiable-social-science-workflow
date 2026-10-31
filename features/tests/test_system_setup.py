"""Steps F3 and S2. System setup, once per scholar.

Detection is faked, and the one runner function for outside programs,
detect.run_program, is a stand-in that runs nothing. The layers are run for
real through the layer runner, with every home in a temporary folder.
Setup lists the scholar's excluded folders in the audit settings through
audit_layer excluded add, adding and never removing, runs audit_layer init
when there are none and the settings file is absent, and records the
folders in system.yaml (step S2, stuck point 1).

Run from the repository root as python3 -m pytest -q features/tests.
"""
import datetime
import io
import os
import sqlite3
from pathlib import Path

import pytest
import yaml

from features import cli, layers
from features.setup import detect, system

ROOT = Path(__file__).resolve().parents[2]
STORY_SESSIONS = ROOT / "examples" / "test_story" / "sessions" / "claude_code"
EXCLUDED_SESSION = STORY_SESSIONS / "excluded_session.jsonl"
TOKEN = "{{PROJECT}}"

NOW = datetime.datetime(2026, 10, 29, 9, 30, 0, tzinfo=datetime.timezone.utc)

FIELDS = ("schema", "schema_version", "written_at", "workflow_root", "python",
          "scholar_name", "harness", "audit_home", "citation_export",
          "excluded_folders", "connect", "layers", "ready", "software")

COMMANDS = {
    "pandoc": "/fake/bin/pandoc",
    "make": "/fake/bin/make",
    "git": "/fake/bin/git",
    "quarto": "/fake/bin/quarto",
    "Rscript": "/fake/bin/Rscript",
    "claude": "/fake/bin/claude",
    "forge": "/fake/bin/forge",
}


def fake_detector(missing=()):
    """A detector that finds every tool except the commands named in missing."""
    commands = {name: path for name, path in COMMANDS.items() if name not in missing}

    def detector():
        return detect.detect(
            which=commands.get,
            run_version=lambda argv: (0, "%s 3.9.0.2\n" % os.path.basename(argv[0]), ""),
            path_exists=lambda path: True,
            package_version=lambda name: "1.2.0",
            python_version=(3, 9, 5))
    return detector


class SpyRunner(object):
    """Runs each layer command for real and records its arguments."""

    def __init__(self, fail=None, missing=()):
        self.calls = []
        self.fail = fail or {}
        self.missing = missing

    def __call__(self, layer, args, root=None, cwd=None, env=None, timeout=600):
        self.calls.append((layer, list(args), dict(env or {})))
        if layer in self.missing:
            raise layers.LayerMissing("the %s layer is missing" % layer)
        if (layer, tuple(args)) in self.fail:
            return layers.LayerResult([layer] + list(args), 1, "", self.fail[(layer, tuple(args))])
        return layers.run_layer(layer, args, root=root, cwd=cwd, env=env, timeout=timeout)

    def inits(self):
        return [call for call in self.calls if call[0] == "audit_layer" and call[1] == ["init"]]


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Point HOME and the three home variables at temporary folders, so nothing real is touched."""
    home = tmp_path / "user_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    monkeypatch.setenv("FEATURES_HOME", str(tmp_path / "env_features_home"))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "env_connections_home"))
    monkeypatch.delenv("WORKFLOW_MODEL_KEY", raising=False)
    monkeypatch.setattr(detect, "find_program", lambda name: None)
    monkeypatch.setattr(detect, "run_program", refuse_program)
    return home


def refuse_program(argv, timeout=30):
    raise AssertionError("a test started the outside program %s" % argv[0])


@pytest.fixture
def homes(tmp_path):
    return tmp_path / "features_home", tmp_path / "audit_home"


def answers(folders, **more):
    given = {"scholar_name": "Test Scholar", "excluded_folders": [str(f) for f in folders]}
    given.update(more)
    return given


def setup(homes, given, detector=None, runner=None):
    home, audit = homes
    return system.run_system_setup(
        str(home), str(audit), given, str(ROOT), NOW,
        detector=detector or fake_detector(), runner=runner or layers.run_layer,
        connections_home=str(home.parent / "connections_home"))


def read_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# Where the homes are.


def test_features_home_is_the_option_else_the_variable_else_the_default(tmp_path, monkeypatch,
                                                                         private_home):
    assert system.features_home(str(tmp_path / "given")) == str(tmp_path / "given")
    assert system.features_home(None) == str(tmp_path / "env_features_home")
    monkeypatch.delenv("FEATURES_HOME")
    assert system.features_home(None) == str(private_home / ".workflow_features")


def test_audit_home_is_the_option_else_the_variable_else_the_slice_default(tmp_path, monkeypatch,
                                                                           private_home):
    assert system.audit_home(str(tmp_path / "given")) == str(tmp_path / "given")
    assert system.audit_home(None) == str(tmp_path / "env_audit_home")
    monkeypatch.delenv("AUDIT_HOME")
    assert system.audit_home(None) == str(private_home / ".audit_layer")


# A first run.


def test_a_first_run_writes_system_yaml_with_every_field_and_creates_the_audit_home(homes, tmp_path):
    records = tmp_path / "records"
    result = setup(homes, answers([records]))
    home, audit = homes

    written = read_yaml(home / "system.yaml")
    assert tuple(written) == FIELDS
    assert written["schema"] == "features-system"
    assert written["schema_version"] == 1
    assert written["written_at"] == "2026-10-29T09:30:00+00:00"
    assert written["workflow_root"] == str(ROOT)
    assert written["scholar_name"] == "Test Scholar"
    assert written["harness"] == "claude_code"
    assert written["audit_home"] == str(audit)
    assert written["citation_export"] == ""
    assert written["excluded_folders"] == [str(records)]
    assert written["connect"] == "no"
    assert written["layers"] == {"ospipe": {"ok": True}, "audit_layer": {"ok": True},
                                 "vg": {"ok": True}}
    assert written["ready"] is True
    assert [row["name"] for row in written["software"]] == [tool.name for tool in detect.SOFTWARE]
    assert set(written["software"][0]) == set(detect.Found._fields)
    assert result.ready is True

    assert (audit / "settings.yaml").is_file()
    assert (audit / "audit.sqlite").is_file()


def test_the_python_recorded_is_the_running_interpreter(homes):
    import sys
    setup(homes, answers([]))
    assert read_yaml(homes[0] / "system.yaml")["python"] == sys.executable


# Excluded folders are listed in the audit settings and recorded in system.yaml (step S2).


def test_excluded_folders_are_recorded_absolute_with_the_home_folder_expanded(homes, private_home):
    setup(homes, answers(["~/Courses"]))
    written = read_yaml(homes[0] / "system.yaml")
    assert written["excluded_folders"] == [str(private_home / "Courses")]
    assert read_yaml(homes[1] / "settings.yaml")["excluded_folders"] == [
        str(private_home / "Courses")]


def test_a_folder_not_given_as_a_full_path_is_refused_before_anything_is_written(homes):
    with pytest.raises(system.SetupError) as caught:
        setup(homes, answers(["relative/advising"]))
    assert "relative/advising" in str(caught.value) and "full path" in str(caught.value)
    assert not homes[0].exists() and not homes[1].exists()


def test_setup_lists_the_folders_in_the_audit_settings(homes, tmp_path):
    setup(homes, answers([tmp_path / "records"]))
    settings = homes[1] / "settings.yaml"
    assert read_yaml(settings) == {"excluded_folders": [str(tmp_path / "records")]}
    setup(homes, answers([tmp_path / "advising"]))
    assert read_yaml(settings) == {"excluded_folders": [str(tmp_path / "records"),
                                                        str(tmp_path / "advising")]}


def test_a_run_with_no_folders_leaves_the_audit_settings_byte_for_byte(homes, tmp_path):
    setup(homes, answers([tmp_path / "records"]))
    settings = homes[1] / "settings.yaml"
    before = settings.read_bytes()
    setup((homes[0].parent / "other_features_home", homes[1]), answers([]))
    assert settings.read_bytes() == before


def test_a_settings_file_the_scholar_edited_keeps_its_folders_and_comment(homes, tmp_path):
    audit = homes[1]
    audit.mkdir()
    settings = audit / "settings.yaml"
    settings.write_text("# mine\nexcluded_folders:\n  - %s\n" % (tmp_path / "kept"), encoding="utf-8")
    setup(homes, answers([tmp_path / "records"]))
    assert settings.read_text(encoding="utf-8").startswith("# mine\n")
    assert read_yaml(settings)["excluded_folders"] == [str(tmp_path / "kept"),
                                                       str(tmp_path / "records")]


def test_a_second_run_adds_a_folder_and_keeps_the_first_and_lists_each_once(homes, tmp_path):
    first, second = tmp_path / "records", tmp_path / "advising"
    setup(homes, answers([first]))
    result = setup(homes, answers([second, first, second]))
    written = read_yaml(homes[0] / "system.yaml")
    assert written["excluded_folders"] == [str(first), str(second)]
    assert result.excluded_folders == [str(first), str(second)]


def test_the_audit_layer_skips_a_folder_setup_listed(homes, tmp_path):
    project = tmp_path / "project"
    (project / "excluded_folder").mkdir(parents=True)
    setup(homes, answers([project / "excluded_folder"]))
    audit = homes[1]

    session = tmp_path / "excluded_session.jsonl"
    text = EXCLUDED_SESSION.read_text(encoding="utf-8").replace(TOKEN, str(project))
    session.write_text(text, encoding="utf-8")
    done = layers.run_layer("audit_layer", ["capture", "--harness", "claude_code", str(session)],
                            env={"AUDIT_HOME": str(audit)})
    assert done.returncode == 0, done.stderr

    db = sqlite3.connect("file:%s?mode=ro" % (audit / "audit.sqlite"), uri=True)
    try:
        count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    finally:
        db.close()
    assert count == 0


# The audit home is initialized once.


def test_an_existing_audit_home_is_not_initialized_again(homes):
    spy = SpyRunner()
    setup(homes, answers([]), runner=spy)
    assert len(spy.inits()) == 1
    assert spy.inits()[0][2] == {"AUDIT_HOME": str(homes[1])}
    again = SpyRunner()
    setup(homes, answers([]), runner=again)
    assert again.inits() == []


def test_each_layer_is_checked_by_its_help(homes):
    spy = SpyRunner()
    setup(homes, answers([]), runner=spy)
    helps = [(layer, args) for layer, args, _ in spy.calls if args == ["--help"]]
    assert helps == [("ospipe", ["--help"]), ("audit_layer", ["--help"]), ("vg", ["--help"])]


def test_a_failing_init_stops_setup_with_the_commands_error(homes):
    spy = SpyRunner(fail={("audit_layer", ("init",)): "the disk is full"})
    with pytest.raises(system.SetupError) as caught:
        setup(homes, answers([]), runner=spy)
    assert "the disk is full" in str(caught.value)
    assert not (homes[0] / "system.yaml").exists()


def test_a_missing_layer_is_recorded_and_setup_is_not_ready(homes):
    spy = SpyRunner()
    setup(homes, answers([]), runner=spy)
    missing = SpyRunner(missing=("vg",))
    result = setup(homes, answers([]), runner=missing)
    written = read_yaml(homes[0] / "system.yaml")
    assert written["layers"]["vg"] == {"ok": False}
    assert written["ready"] is False
    assert result.ready is False


# The harness.


def test_the_harness_default_follows_which_program_is_found():
    assert system.default_harness(fake_detector()()) == "claude_code"
    assert system.default_harness(fake_detector(missing=("claude",))()) == "forgecode"
    assert system.default_harness(fake_detector(missing=("claude", "forge"))()) == ""


def test_a_run_without_a_harness_answer_takes_the_default(homes):
    setup(homes, answers([]), detector=fake_detector(missing=("claude",)))
    assert read_yaml(homes[0] / "system.yaml")["harness"] == "forgecode"


def test_a_harness_not_found_is_recorded_as_not_found_and_reported(homes, tmp_path, monkeypatch,
                                                                  capsys):
    home, audit = homes
    code, out, err = run_command(
        ["setup", "system", "--home", str(home), "--audit-home", str(audit),
         "--answers", write_answers(tmp_path, answers([]))], monkeypatch, capsys,
        detector=fake_detector(missing=("claude", "forge")))
    assert read_yaml(home / "system.yaml")["harness"] == ""
    assert "Harness not found" in out
    assert "Harness claude_code" not in out
    assert detect.install_hint("claude_code") in out
    assert detect.install_hint("forgecode") in out


def test_the_terminal_takes_an_empty_harness_when_none_is_found(tmp_path):
    replies = iter(["none", "Test Scholar", "", "", ""])
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return next(replies)

    given = system.ask_answers(fake_detector(missing=("claude", "forge"))(), ask=ask,
                               out=io.StringIO())
    assert given["harness"] == ""
    assert "claude_code]" not in asked[-1]


def test_ready_is_not_printed_without_make(homes, tmp_path, monkeypatch, capsys):
    home, audit = homes
    code, out, err = run_command(
        ["setup", "system", "--home", str(home), "--audit-home", str(audit),
         "--answers", write_answers(tmp_path, answers([]))], monkeypatch, capsys,
        detector=fake_detector(missing=("make",)))
    assert code == 1
    assert "Ready\n" not in out.replace("Not ready", "")
    assert "Not ready" in out
    assert detect.install_hint("make") in out
    assert read_yaml(home / "system.yaml")["ready"] is False


def test_the_harness_names_are_the_audit_layers_adapter_names():
    adapter = (ROOT / "audit_layer" / "capture" / "forgecode.py").read_text(encoding="utf-8")
    assert 'NAME = "forgecode"' in adapter
    assert system.HARNESSES == ("claude_code", "forgecode")


def test_an_unknown_harness_is_refused(homes):
    with pytest.raises(system.SetupError) as caught:
        setup(homes, answers([], harness="cursor"))
    assert "claude_code" in str(caught.value) and "forgecode" in str(caught.value)


# The citation export.


def test_a_citation_export_that_exists_is_recorded_without_a_message(homes, tmp_path):
    export = tmp_path / "library.bib"
    export.write_text("", encoding="utf-8")
    result = setup(homes, answers([], citation_export=str(export)))
    assert read_yaml(homes[0] / "system.yaml")["citation_export"] == str(export)
    assert not [m for m in result.messages if "citation export" in m]


def test_a_citation_export_that_does_not_exist_adds_a_message(homes, tmp_path):
    export = tmp_path / "missing.bib"
    result = setup(homes, answers([], citation_export=str(export)))
    assert read_yaml(homes[0] / "system.yaml")["citation_export"] == str(export)
    assert any(str(export) in m and "does not exist" in m for m in result.messages)


# Answers.


def test_an_answers_file_missing_a_field_or_with_an_unknown_one_is_refused(tmp_path):
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump({"scholar_name": "Test Scholar"}), encoding="utf-8")
    with pytest.raises(system.SetupError) as caught:
        system.read_answers(str(path))
    assert "excluded_folders" in str(caught.value)
    path.write_text(yaml.safe_dump(answers([], colour="blue")), encoding="utf-8")
    with pytest.raises(system.SetupError) as caught:
        system.read_answers(str(path))
    assert "colour" in str(caught.value)


def test_the_terminal_asks_each_question_one_at_a_time(tmp_path):
    replies = iter([str(tmp_path / "a"), str(tmp_path / "b"), "", "Test Scholar", "", ""])
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return next(replies)

    given = system.ask_answers(fake_detector()(), ask=ask, out=io.StringIO())
    assert given == {"scholar_name": "Test Scholar", "harness": "",
                     "excluded_folders": [str(tmp_path / "a"), str(tmp_path / "b")],
                     "citation_export": "", "model_service": "", "model": "",
                     "second_model": "", "token_limit": None, "token_limit_field": "",
                     "connect": "no"}
    assert len(asked) == 6


def test_the_terminal_asks_again_after_an_empty_name(tmp_path):
    replies = iter(["none", "", "Test Scholar", "", ""])
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return next(replies)

    out = io.StringIO()
    given = system.ask_answers(fake_detector()(), ask=ask, out=out)
    assert given["scholar_name"] == "Test Scholar"
    assert len(asked) == 5
    assert asked[1] == asked[2]
    assert "A name is needed" in out.getvalue()


# The command.


def no_state(audit):
    return detect.State(git_name="", model_key_set=False, excluded_folders=None,
                        hooks={"capture": [], "trigger": []}, servers=[], notes=[])


def run_command(argv, monkeypatch, capsys, detector=None, interactive=False):
    monkeypatch.setattr(system, "detect", detector or fake_detector())
    monkeypatch.setattr(system, "detect_state", no_state)
    monkeypatch.setattr(system, "_interactive", lambda: interactive)
    code = cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def write_answers(tmp_path, given):
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump(given), encoding="utf-8")
    return str(path)


def test_the_command_prints_the_tools_layers_harness_home_folders_and_later_connections(
        homes, tmp_path, monkeypatch, capsys):
    home, audit = homes
    records = tmp_path / "records"
    code, out, err = run_command(
        ["setup", "system", "--home", str(home), "--audit-home", str(audit),
         "--answers", write_answers(tmp_path, answers([records]))], monkeypatch, capsys)
    assert code == 0, err
    for tool in detect.SOFTWARE:
        assert tool.name in out
    assert "3.9.0.2" in out
    for layer in ("ospipe", "audit_layer", "vg"):
        assert layer in out
    assert "claude_code" in out
    assert str(audit) in out
    assert str(records) in out
    for line in system.LATER_CONNECTIONS:
        assert line in out
    assert len(system.LATER_CONNECTIONS) == 3
    joined = "\n".join(system.LATER_CONNECTIONS)
    assert "audit_layer/hooks/INSTALL.md" in joined and "connections/README.md" in joined
    assert "Excluded folders, listed in %s" % (audit / "settings.yaml") in out
    assert (home / "system.yaml").is_file()


def test_missing_pandoc_gives_not_ready_exit_one_and_its_hint(homes, tmp_path, monkeypatch, capsys):
    home, audit = homes
    code, out, err = run_command(
        ["setup", "system", "--home", str(home), "--audit-home", str(audit),
         "--answers", write_answers(tmp_path, answers([]))], monkeypatch, capsys,
        detector=fake_detector(missing=("pandoc",)))
    assert code == 1
    assert detect.install_hint("pandoc") in out
    assert read_yaml(home / "system.yaml")["ready"] is False


def test_no_answers_file_and_no_terminal_refuses_and_names_the_fields(homes, monkeypatch, capsys):
    home, audit = homes
    code, out, err = run_command(
        ["setup", "system", "--home", str(home), "--audit-home", str(audit)],
        monkeypatch, capsys)
    assert code == 2
    for field in system.FIELDS:
        assert field in err
    assert not home.exists()


def test_the_command_uses_the_home_variables_when_no_option_is_given(tmp_path, monkeypatch, capsys):
    code, out, err = run_command(
        ["setup", "system", "--answers", write_answers(tmp_path, answers([]))],
        monkeypatch, capsys)
    assert code == 0, err
    assert (tmp_path / "env_features_home" / "system.yaml").is_file()
    assert (tmp_path / "env_audit_home" / "settings.yaml").is_file()


# Reading system.yaml back.


def test_load_system_gives_back_what_setup_wrote(homes):
    setup(homes, answers([]))
    loaded = system.load_system(str(homes[0]))
    assert loaded["schema"] == "features-system"
    assert loaded["scholar_name"] == "Test Scholar"


def test_load_system_on_an_empty_home_names_the_setup_command(tmp_path):
    with pytest.raises(system.SetupError) as caught:
        system.load_system(str(tmp_path))
    assert "python3 -m features setup system" in str(caught.value)


@pytest.mark.parametrize("text", [
    "schema: something-else\nschema_version: 1\n",
    "schema: features-system\nschema_version: 2\n",
    "[not, a, mapping]\n",
    "schema: [unclosed\n",
])
def test_load_system_refuses_a_wrong_or_malformed_file(tmp_path, text):
    (tmp_path / "system.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(system.SetupError) as caught:
        system.load_system(str(tmp_path))
    assert "python3 -m features setup system" in str(caught.value)


# A system.yaml setup cannot read stops setup without telling the scholar to run setup.


BROKEN = [
    "excluded_folders: [/x\n",
    "[not, a, mapping]\n",
    "schema: something-else\nschema_version: 1\nexcluded_folders: []\n",
    "schema: features-system\nschema_version: 2\nexcluded_folders: []\n",
    "schema: features-system\nschema_version: 1\nexcluded_folders: []\n",
]


@pytest.mark.parametrize("text", BROKEN + [None])
def test_a_system_yaml_setup_cannot_read_stops_setup_and_is_left_unchanged(homes, text):
    home, audit = homes
    setup(homes, answers(["/kept"]))
    path = home / "system.yaml"
    if text is None:
        record = read_yaml(path)
        record["excluded_folders"] = "/kept"
        text = yaml.safe_dump(record)
    path.write_text(text, encoding="utf-8")
    before = path.read_bytes()
    spy = SpyRunner()
    with pytest.raises(system.SetupError) as caught:
        setup((home, audit / "fresh"), answers([]), runner=spy)
    message = str(caught.value)
    assert str(path) in message
    assert "repair" in message and "move it aside" in message
    assert "python3 -m features setup system" not in message
    assert path.read_bytes() == before
    assert spy.inits() == []
    assert not (audit / "fresh").exists()


def test_the_command_stops_on_a_broken_system_yaml_with_exit_one(homes, tmp_path, monkeypatch,
                                                                    capsys):
    home, audit = homes
    home.mkdir()
    path = home / "system.yaml"
    path.write_text(BROKEN[0], encoding="utf-8")
    code, out, err = run_command(
        ["setup", "system", "--home", str(home), "--audit-home", str(audit),
         "--answers", write_answers(tmp_path, answers([]))], monkeypatch, capsys)
    assert code == 1
    assert str(path) in err and "move it aside" in err
    assert "python3 -m features setup system" not in err
    assert path.read_text(encoding="utf-8") == BROKEN[0]


def test_the_terminal_path_detects_the_software_once(homes, monkeypatch, capsys):
    home, audit = homes
    calls = []
    found = fake_detector()

    def counting():
        calls.append(1)
        return found()

    replies = iter(["none", "Test Scholar", "", "", "no"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    code, out, err = run_command(
        ["setup", "system", "--home", str(home), "--audit-home", str(audit)],
        monkeypatch, capsys, detector=counting, interactive=True)
    assert code == 0, err
    assert len(calls) == 1
