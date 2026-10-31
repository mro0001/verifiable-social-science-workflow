"""Tests for the excluded-folder command (Track S, step S2).

python3 -m audit_layer excluded add PATH ... [--home DIR] adds each folder to
excluded_folders in the audit home's settings.yaml, creating the home as init
does when it has none. It never removes a folder, keeps the ones already
there, and prints the list. excluded list prints it. A folder is stored as
the full path the scholar typed, with ~ expanded, so setup can list the
folders before anything records (stuck points 1 and 6 of the scope report).

Every test runs with HOME and AUDIT_HOME inside a temporary folder. Nothing
here calls a model or the network. Run from the repository root with
python3 -m pytest -q audit_layer.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from audit_layer.cli import main  # noqa: E402
from audit_layer.settings import read_settings  # noqa: E402


@pytest.fixture(autouse=True)
def private_homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "env_audit_home"))
    return user


@pytest.fixture
def home(tmp_path):
    return tmp_path / "audit_home"


def listed(home):
    return yaml.safe_load((home / "settings.yaml").read_text(encoding="utf-8"))["excluded_folders"]


def test_add_on_a_home_with_none_creates_it_as_init_does_and_lists_the_folders(home, capsys):
    assert main(["excluded", "add", "--home", str(home), "/srv/records", "/srv/advising"]) == 0
    assert (home / "audit.sqlite").is_file()
    assert listed(home) == ["/srv/records", "/srv/advising"]
    assert read_settings(home) == {"excluded_folders": ["/srv/records", "/srv/advising"]}
    out = capsys.readouterr().out
    assert "/srv/records" in out and "/srv/advising" in out
    assert str(home / "settings.yaml") in out


def test_add_keeps_the_folders_already_listed_and_lists_each_once(home):
    assert main(["excluded", "add", "--home", str(home), "/srv/records"]) == 0
    assert main(["excluded", "add", "--home", str(home), "/srv/advising", "/srv/records"]) == 0
    assert listed(home) == ["/srv/records", "/srv/advising"]


def test_add_keeps_a_folder_the_scholar_wrote_by_hand_and_the_files_comments(home):
    assert main(["init", "--home", str(home)]) == 0
    settings = home / "settings.yaml"
    text = settings.read_text(encoding="utf-8").replace(
        "excluded_folders: []", "excluded_folders:\n  - ~/Courses")
    settings.write_text(text, encoding="utf-8")
    assert main(["excluded", "add", "--home", str(home), "/srv/records"]) == 0
    assert listed(home) == ["~/Courses", "/srv/records"]
    assert settings.read_text(encoding="utf-8").startswith("# Settings for the audit layer")


def test_a_folder_already_listed_with_a_tilde_is_not_added_again(home, private_homes):
    assert main(["excluded", "add", "--home", str(home), "~/Courses"]) == 0
    before = (home / "settings.yaml").read_bytes()
    assert main(["excluded", "add", "--home", str(home), str(private_homes / "Courses")]) == 0
    assert (home / "settings.yaml").read_bytes() == before


def test_a_tilde_is_expanded_from_the_home_folder(home, private_homes):
    assert main(["excluded", "add", "--home", str(home), "~/private_records"]) == 0
    assert listed(home) == [str(private_homes / "private_records")]


def test_the_folder_is_stored_as_typed_and_not_made_real(home, tmp_path):
    target = tmp_path / "real_records"
    target.mkdir()
    link = tmp_path / "records_link"
    link.symlink_to(target)
    assert main(["excluded", "add", "--home", str(home), str(link)]) == 0
    assert listed(home) == [str(link)]


@pytest.mark.parametrize("given", ["records", "./records", "Documents/Courses"])
def test_a_path_that_is_not_full_is_refused_and_nothing_is_written(home, capsys, given):
    assert main(["excluded", "add", "--home", str(home), "/srv/records", given]) == 1
    err = capsys.readouterr().err
    assert given in err and "full path" in err
    assert not home.exists()


def test_a_refused_path_leaves_an_existing_list_as_it_was(home):
    assert main(["excluded", "add", "--home", str(home), "/srv/records"]) == 0
    before = (home / "settings.yaml").read_bytes()
    assert main(["excluded", "add", "--home", str(home), "records"]) == 1
    assert (home / "settings.yaml").read_bytes() == before


def test_a_settings_file_capture_would_refuse_is_left_as_it_is(home, capsys):
    home.mkdir()
    settings = home / "settings.yaml"
    settings.write_text("excluded_folder:\n  - /srv/typo\n", encoding="utf-8")
    assert main(["excluded", "add", "--home", str(home), "/srv/records"]) == 1
    assert "excluded_folder" in capsys.readouterr().err
    assert settings.read_text(encoding="utf-8") == "excluded_folder:\n  - /srv/typo\n"


def test_add_needs_at_least_one_folder(home):
    with pytest.raises(SystemExit) as stopped:
        main(["excluded", "add", "--home", str(home)])
    assert stopped.value.code == 2


def test_list_prints_each_folder(home, capsys):
    main(["excluded", "add", "--home", str(home), "/srv/records", "/srv/advising"])
    capsys.readouterr()
    assert main(["excluded", "list", "--home", str(home)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[1:] == ["  /srv/records", "  /srv/advising"]


def test_list_says_none_for_an_empty_list(home, capsys):
    main(["init", "--home", str(home)])
    capsys.readouterr()
    assert main(["excluded", "list", "--home", str(home)]) == 0
    assert capsys.readouterr().out.splitlines()[1:] == ["  none"]


def test_list_without_a_settings_file_names_init_and_writes_nothing(home, capsys):
    assert main(["excluded", "list", "--home", str(home)]) == 1
    assert "audit_layer init" in capsys.readouterr().err
    assert not home.exists()


def test_the_command_finds_the_home_from_the_variable(tmp_path):
    env = dict(os.environ)
    env["AUDIT_HOME"] = str(tmp_path / "from_variable")
    env["HOME"] = str(tmp_path / "user")
    done = subprocess.run(
        [sys.executable, "-m", "audit_layer", "excluded", "add", "/srv/records"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert listed(tmp_path / "from_variable") == ["/srv/records"]


def test_capture_skips_a_session_in_a_folder_the_command_listed(home, tmp_path):
    story = ROOT / "examples" / "test_story" / "sessions" / "claude_code" / "excluded_session.jsonl"
    project = tmp_path / "project"
    (project / "excluded_folder").mkdir(parents=True)
    session = tmp_path / "excluded_session.jsonl"
    session.write_text(story.read_text(encoding="utf-8").replace("{{PROJECT}}", str(project)),
                       encoding="utf-8")
    assert main(["excluded", "add", "--home", str(home), str(project / "excluded_folder")]) == 0
    assert main(["capture", "--home", str(home), "--harness", "claude_code", str(session)]) == 0
    import sqlite3
    db = sqlite3.connect(str(home / "audit.sqlite"))
    try:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        db.close()
