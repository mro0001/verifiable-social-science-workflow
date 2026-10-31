"""Tests for the connections home and the excluded folders (Track D, step D1).

Appendix A2.2 says the connectors sit outside any single project, so one setup
serves every project. A2.6 and A6 say sessions in folders the scholar excludes
are never recorded, and the reconciliation's item 3 gives the connectors the
same check capture makes, recording nothing while the audit settings file is
missing. Every test runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a
temporary folder, so no test reaches the scholar's real folders. Run from the
repository root with python3 -m pytest -q connections/tests.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections import home  # noqa: E402
from connections.cli import main  # noqa: E402


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    """A home folder, a connections home, and an audit home, all temporary."""
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def write_settings(text):
    path = Path(os.environ["AUDIT_HOME"]) / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def exclude(*folders):
    lines = "".join(f"  - {folder}\n" for folder in folders)
    return write_settings("excluded_folders:\n" + lines if folders else "excluded_folders: []\n")


# The connections home.


def test_connections_home_variable_wins_over_the_default(homes, monkeypatch):
    chosen = homes / "elsewhere"
    monkeypatch.setenv("CONNECTIONS_HOME", str(chosen))
    assert home.connections_home() == chosen


def test_connections_home_default_is_in_the_home_folder(homes, monkeypatch):
    monkeypatch.delenv("CONNECTIONS_HOME")
    assert home.connections_home() == homes / "user" / ".workflow_connections"


def test_connections_home_set_to_nothing_counts_as_not_set(homes, monkeypatch):
    monkeypatch.setenv("CONNECTIONS_HOME", "")
    assert home.connections_home() == homes / "user" / ".workflow_connections"


def test_connections_home_is_expanded(homes, monkeypatch):
    monkeypatch.setenv("CONNECTIONS_HOME", "~/conn")
    assert home.connections_home() == homes / "user" / "conn"


def test_connections_home_is_never_created(homes, monkeypatch):
    found = home.connections_home()
    assert not found.exists()
    monkeypatch.delenv("CONNECTIONS_HOME")
    found = home.connections_home()
    assert not found.exists()


# The audit layer's settings file.


def test_audit_settings_path_follows_audit_home(homes):
    assert home.audit_settings_path() == homes / "audit_home" / "settings.yaml"


def test_audit_settings_path_default_is_in_the_home_folder(homes, monkeypatch):
    monkeypatch.delenv("AUDIT_HOME")
    assert home.audit_settings_path() == homes / "user" / ".audit_layer" / "settings.yaml"


def test_audit_settings_path_set_to_nothing_counts_as_not_set(homes, monkeypatch):
    monkeypatch.setenv("AUDIT_HOME", "")
    assert home.audit_settings_path() == homes / "user" / ".audit_layer" / "settings.yaml"


# The excluded folders.


def test_missing_settings_file_gives_none_and_allows_nothing(homes):
    folder = homes / "project"
    folder.mkdir()
    assert home.excluded_folders() is None
    assert home.recording_allowed(folder) is False


def test_missing_audit_home_allows_nothing(homes, monkeypatch):
    monkeypatch.setenv("AUDIT_HOME", str(homes / "no_such_home"))
    assert home.excluded_folders() is None
    assert home.recording_allowed(homes) is False


@pytest.mark.parametrize(
    "text",
    [
        "excluded_folders: [\n",
        "excluded_folders:\n  - a\n - b\n",
        "\tbad: yaml\n",
    ],
)
def test_settings_file_that_does_not_parse_gives_none(homes, text):
    write_settings(text)
    assert home.excluded_folders() is None
    assert home.recording_allowed(homes) is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        "- /a\n",
        "just words\n",
        "other: 1\n",
        "excluded_folder:\n  - /a\n",
        "excluded_folders:\n",
        "excluded_folders: /a\n",
        "excluded_folders:\n  - relative/folder\n",
        "excluded_folders:\n  - ''\n",
        "excluded_folders:\n  - 3\n",
    ],
)
def test_settings_that_do_not_clearly_list_folders_give_none(homes, text):
    write_settings(text)
    assert home.excluded_folders() is None
    assert home.recording_allowed(homes) is False


def test_settings_file_that_cannot_be_read_gives_none(homes):
    write_settings("excluded_folders: []\n").write_bytes(b"\xff\xfe\x00bad")
    assert home.excluded_folders() is None


def test_settings_path_that_is_a_folder_gives_none(homes):
    (homes / "audit_home" / "settings.yaml").mkdir(parents=True)
    assert home.excluded_folders() is None


def test_empty_list_excludes_nothing_and_allows_recording(homes):
    exclude()
    folder = homes / "project"
    folder.mkdir()
    assert home.excluded_folders() == []
    assert home.recording_allowed(folder) is True


def test_excluded_folders_are_real_paths(homes):
    target = homes / "records"
    target.mkdir()
    link = homes / "records_link"
    link.symlink_to(target)
    exclude(str(link), "~/courses")
    assert home.excluded_folders() == [
        os.path.realpath(str(target)),
        os.path.realpath(str(homes / "user" / "courses")),
    ]


def test_other_settings_beside_the_list_make_the_file_unclear(homes):
    # The slice's audit_layer/settings.py refuses a file holding any setting
    # besides excluded_folders, so the connectors do too.
    write_settings("excluded_folders:\n  - /a\nsomething_else: 1\n")
    assert home.excluded_folders() is None


def test_misspelled_list_name_records_nothing(homes):
    records = homes / "records"
    records.mkdir()
    write_settings(f"excluded_folders: []\nexcluded_folder:\n  - {records}\n")
    assert home.excluded_folders() is None
    assert home.recording_allowed(records) is False
    assert home.recording_allowed(homes) is False


# Whether recording is allowed in a folder.


def test_excluded_folder_itself_is_refused(homes):
    records = homes / "records"
    records.mkdir()
    exclude(str(records))
    assert home.recording_allowed(records) is False


def test_folder_inside_an_excluded_folder_is_refused(homes):
    records = homes / "records"
    inner = records / "spring" / "grades"
    inner.mkdir(parents=True)
    exclude(str(records))
    assert home.recording_allowed(inner) is False


def test_folder_inside_not_yet_made_is_refused(homes):
    records = homes / "records"
    exclude(str(records))
    assert home.recording_allowed(records / "later") is False


def test_link_into_an_excluded_folder_is_refused(homes):
    records = homes / "records"
    inner = records / "spring"
    inner.mkdir(parents=True)
    link = homes / "work" / "looks_harmless"
    link.parent.mkdir()
    link.symlink_to(inner)
    exclude(str(records))
    assert home.recording_allowed(link) is False


def test_folder_listed_through_a_link_is_refused(homes):
    records = homes / "records"
    records.mkdir()
    link = homes / "records_link"
    link.symlink_to(records)
    exclude(str(link))
    assert home.recording_allowed(records) is False


def test_folder_listed_with_tilde_is_refused(homes):
    courses = homes / "user" / "courses"
    courses.mkdir()
    exclude("~/courses")
    assert home.recording_allowed(courses / "x") is False


def test_sibling_whose_name_begins_with_the_excluded_name_is_allowed(homes):
    records = homes / "records"
    records.mkdir()
    sibling = homes / "records_old"
    sibling.mkdir()
    exclude(str(records))
    assert home.recording_allowed(sibling) is True


def test_folder_outside_every_excluded_folder_is_allowed(homes):
    records = homes / "records"
    records.mkdir()
    project = homes / "project"
    project.mkdir()
    exclude(str(records))
    assert home.recording_allowed(project) is True


def test_parent_of_an_excluded_folder_is_allowed(homes):
    records = homes / "work" / "records"
    records.mkdir(parents=True)
    exclude(str(records))
    assert home.recording_allowed(homes / "work") is True


def test_root_listed_excludes_everything(homes):
    exclude("/")
    assert home.recording_allowed(homes) is False


def test_recording_allowed_takes_text_paths(homes):
    records = homes / "records"
    records.mkdir()
    exclude(str(records))
    assert home.recording_allowed(str(records / "a")) is False
    assert home.recording_allowed(str(homes)) is True


# Letter case in a listed folder (Track L, Step L4, decision 51). Whether the
# disk ignores case is found by checking the disk, and a stand-in for that
# check plays each kind of disk here.


def disk(monkeypatch, ignores):
    """Stand in for the disk check, and keep the folders it was asked about."""
    asked = []

    def check(path):
        asked.append(str(path))
        return ignores

    monkeypatch.setattr(home, "ignores_case", check)
    return asked


@pytest.mark.parametrize("ignores, allowed", [(True, False), (False, True)])
@pytest.mark.parametrize(
    "listed, where",
    [("Records", "records"), ("records", "RECORDS"), ("Records", "rEcOrDs/spring/grades")],
)
def test_a_folder_listed_in_another_case_is_refused_only_on_a_disk_that_ignores_case(
    homes, monkeypatch, listed, where, ignores, allowed
):
    (homes / "records" / "spring" / "grades").mkdir(parents=True)
    disk(monkeypatch, ignores)
    exclude(str(homes / listed))
    assert home.recording_allowed(homes / where) is allowed


@pytest.mark.parametrize("ignores", [True, False])
def test_the_same_case_is_refused_on_either_disk(homes, monkeypatch, ignores):
    (homes / "records" / "spring").mkdir(parents=True)
    disk(monkeypatch, ignores)
    exclude(str(homes / "records"))
    assert home.recording_allowed(homes / "records" / "spring") is False


@pytest.mark.parametrize("where", ["RECORDS_old", "Recordsx/spring", "Other/records", "."])
def test_ignoring_case_still_compares_whole_folders(homes, monkeypatch, where):
    disk(monkeypatch, True)
    exclude(str(homes / "Records"))
    assert home.recording_allowed(homes / where) is True


def test_the_disk_checked_is_the_listed_folders_own(homes, monkeypatch):
    asked = disk(monkeypatch, True)
    exclude(str(homes / "Records"))
    home.recording_allowed(homes / "elsewhere")
    assert asked == [os.path.realpath(str(homes / "Records"))]


def test_the_disk_check_agrees_with_the_disk(homes):
    # The check runs on this machine's own disk, compared with what the disk
    # does with a name written in another case.
    probe = homes / "Probe"
    probe.mkdir()
    expected = (homes / "pROBE").exists()
    assert home.ignores_case(probe) is expected
    # A folder not yet made is judged by the nearest folder above it.
    assert home.ignores_case(probe / "not" / "made") is expected
    # A name with no letter is passed over for one above it.
    (probe / "2026").mkdir()
    assert home.ignores_case(probe / "2026") is expected


# The folder key.


def test_folder_key_is_twelve_hex_characters_of_the_real_path(homes):
    folder = homes / "project"
    folder.mkdir()
    real = os.path.realpath(str(folder))
    expected = hashlib.sha256(real.encode("utf-8")).hexdigest()[:12]
    assert home.folder_key(folder) == expected
    assert len(expected) == 12


def test_folder_and_link_to_it_get_the_same_key(homes):
    folder = homes / "project"
    folder.mkdir()
    link = homes / "project_link"
    link.symlink_to(folder)
    assert home.folder_key(link) == home.folder_key(folder)
    assert home.folder_key(str(link)) == home.folder_key(folder)


def test_different_folders_get_different_keys(homes):
    one = homes / "one"
    two = homes / "two"
    one.mkdir()
    two.mkdir()
    assert home.folder_key(one) != home.folder_key(two)


# The command line.


def test_no_command_prints_the_usage_and_exits_2(capsys):
    assert main([]) == 2
    captured = capsys.readouterr()
    assert "usage" in captured.out + captured.err


def test_module_with_no_command_exits_2(homes):
    result = subprocess.run(
        [sys.executable, "-m", "connections"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "usage" in result.stdout + result.stderr
