"""Tests for the event writer (Track D, step D2).

Appendix A2.2 says wrappers turn what happens in the scholar's software into
events in a schema that fits the audit layer's databases, and Table A4 gives
the fixed verbs, action or observation, and the file roles. Every event a
connector writes is one JSON line in <connections home>/events/, one file per
day and working folder (Track D choice 2), and nothing is written in an
excluded folder or while the audit settings file is missing (choice 3). Every
test runs with HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary
folder. Run from the repository root with python3 -m pytest -q
connections/tests.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections import events  # noqa: E402
from connections.events import (  # noqa: E402
    KINDS,
    ROLES,
    VERBS,
    append_event,
    event_path,
    make_event,
)
from connections import home  # noqa: E402
from connections.home import folder_key  # noqa: E402

# The one event schema's fields, as the slice's audit_layer/events.py names them.
SCHEMA_FIELDS = (
    "harness",
    "harness_session_id",
    "source_id",
    "verb",
    "kind",
    "object",
    "rationale",
    "role",
)
FIXED = datetime(2026, 10, 29, 9, 30, 15, 987654)


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def exclude(*folders):
    path = Path(os.environ["AUDIT_HOME"]) / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"  - {folder}\n" for folder in folders)
    path.write_text("excluded_folders:\n" + lines if folders else "excluded_folders: []\n")


@pytest.fixture
def project(homes):
    folder = homes / "project"
    folder.mkdir()
    exclude(str(homes / "records"))
    return folder


def events_dir():
    return Path(os.environ["CONNECTIONS_HOME"]) / "events"


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# The fixed lists, copied from the slice.


def test_lists_match_the_slice_schema():
    assert VERBS == ("wrote", "edited", "ran", "searched", "verified", "committed")
    assert KINDS == ("action", "decision", "observation", "blocker")
    assert ROLES == ("produced", "edited", "read", "cited")


def test_lists_are_copied_not_imported():
    source = Path(events.__file__).read_text(encoding="utf-8")
    assert "audit_layer/events.py" in source
    assert not re.search(r"^\s*(from|import)\s+audit_layer", source, re.MULTILINE)


# Making an event.


def test_event_holds_every_schema_field_and_at_cwd_and_program(project):
    event = make_event(project, "ran", "action", "make all", program="make", now=FIXED)
    for name in SCHEMA_FIELDS + ("at", "cwd", "program"):
        assert name in event
    assert set(event) == set(SCHEMA_FIELDS + ("at", "cwd", "program"))
    assert event["harness"] == "wrappers"
    assert event["verb"] == "ran"
    assert event["kind"] == "action"
    assert event["object"] == "make all"
    assert event["rationale"] == ""
    assert event["role"] == ""
    assert event["program"] == "make"
    assert event["cwd"] == str(project)


def test_every_value_is_text(project):
    event = make_event(project, "wrote", "action", "/x/out.txt", role="produced", now=FIXED)
    assert all(isinstance(value, str) for value in event.values())


def test_session_id_is_the_day_and_the_folder_key(project):
    event = make_event(project, "ran", "action", "make", now=FIXED)
    assert event["harness_session_id"] == f"2026-10-29_{folder_key(project)}"


def test_source_id_is_a_new_uuid4_hex(project):
    one = make_event(project, "ran", "action", "make", now=FIXED)
    two = make_event(project, "ran", "action", "make", now=FIXED)
    assert re.fullmatch(r"[0-9a-f]{32}", one["source_id"])
    assert one["source_id"][12] == "4"
    assert one["source_id"] != two["source_id"]


def test_at_is_local_time_to_the_second(project):
    event = make_event(project, "ran", "action", "make", now=FIXED)
    expected = FIXED.replace(microsecond=0).astimezone().isoformat()
    assert event["at"] == expected
    assert event["at"].startswith("2026-10-29T09:30:15")


@pytest.fixture
def local_zone(monkeypatch):
    """Sets the machine's local zone for one test, so it holds on any machine."""

    def choose(name):
        monkeypatch.setenv("TZ", name)
        time.tzset()

    yield choose
    monkeypatch.undo()
    time.tzset()


def test_at_is_a_given_time_in_local_time_with_its_day(project, local_zone):
    local_zone("UTC")
    mountain = timezone(timedelta(hours=-7))
    late = datetime(2026, 10, 29, 23, 59, 59, 500000, tzinfo=mountain)
    event = make_event(project, "ran", "action", "make", now=late)
    assert event["at"] == "2026-10-30T06:59:59+00:00"
    assert event["harness_session_id"].startswith("2026-10-30_")


def test_at_keeps_a_given_time_already_in_local_time(project, local_zone):
    local_zone("Etc/GMT+7")
    mountain = timezone(timedelta(hours=-7))
    late = datetime(2026, 10, 29, 23, 59, 59, 500000, tzinfo=mountain)
    event = make_event(project, "ran", "action", "make", now=late)
    assert event["at"] == "2026-10-29T23:59:59-07:00"
    assert event["harness_session_id"].startswith("2026-10-29_")


def test_at_without_a_given_clock_is_now(project):
    before = datetime.now().astimezone().replace(microsecond=0)
    event = make_event(project, "ran", "action", "make")
    after = datetime.now().astimezone()
    at = datetime.fromisoformat(event["at"])
    assert before <= at <= after
    assert "." not in event["at"]
    assert event["harness_session_id"].startswith(at.strftime("%Y-%m-%d") + "_")


def test_rationale_role_and_extras_are_kept(project):
    event = make_event(
        project,
        "committed",
        "action",
        "git commit -m fix",
        rationale="fix",
        role="",
        program="git",
        extra={"exit_code": "0", "duration_s": "0.2"},
        now=FIXED,
    )
    assert event["rationale"] == "fix"
    assert event["exit_code"] == "0"
    assert event["duration_s"] == "0.2"


def test_relative_working_folder_is_made_absolute(project, monkeypatch):
    monkeypatch.chdir(project)
    event = make_event(".", "ran", "action", "make", now=FIXED)
    assert event["cwd"] == os.path.abspath(".")
    assert event["harness_session_id"].endswith(folder_key(project))


@pytest.mark.parametrize(
    "field, kwargs",
    [
        ("verb", {"verb": "deleted"}),
        ("verb", {"verb": ""}),
        ("kind", {"kind": "note"}),
        ("kind", {"kind": "Action"}),
        ("role", {"role": "owned"}),
        ("object", {"obj": ""}),
        ("object", {"obj": "   "}),
    ],
)
def test_wrong_field_raises_and_names_it(project, field, kwargs):
    arguments = {"verb": "ran", "kind": "action", "obj": "make"}
    arguments.update(kwargs)
    with pytest.raises(ValueError) as raised:
        make_event(
            project,
            arguments["verb"],
            arguments["kind"],
            arguments["obj"],
            role=kwargs.get("role", ""),
            now=FIXED,
        )
    assert field in str(raised.value)


@pytest.mark.parametrize(
    "field,kwargs",
    [
        ("extra", {"extra": ["not", "a", "mapping"]}),
        ("extra", {"extra": "text"}),
        ("rationale", {"rationale": 3}),
        ("rationale", {"rationale": None}),
        ("program", {"program": 3}),
        ("program", {"program": ["make"]}),
    ],
)
def test_wrong_type_raises_and_names_it(project, field, kwargs):
    with pytest.raises(ValueError) as raised:
        make_event(project, "ran", "action", "make", now=FIXED, **kwargs)
    assert field in str(raised.value)


def test_extra_that_would_replace_a_field_raises_and_names_it(project):
    with pytest.raises(ValueError) as raised:
        make_event(project, "ran", "action", "make", extra={"verb": "wrote"}, now=FIXED)
    assert "verb" in str(raised.value)


# Where events land.


def test_event_path_is_the_session_file_in_the_events_folder(project):
    event = make_event(project, "ran", "action", "make", now=FIXED)
    expected = events_dir() / f"2026-10-29_{folder_key(project)}.jsonl"
    assert event_path(event) == expected


def test_append_writes_one_line_and_returns_true(project):
    event = make_event(project, "ran", "action", "make", program="make", now=FIXED)
    assert append_event(event) is True
    path = event_path(event)
    assert read_lines(path) == [event]
    assert path.read_bytes().endswith(b"\n")


def test_two_events_from_one_folder_on_one_day_share_a_file_in_order(project):
    first = make_event(project, "ran", "action", "make", now=FIXED)
    second = make_event(
        project, "wrote", "action", str(project / "out.txt"), role="produced", now=FIXED
    )
    assert append_event(first) and append_event(second)
    files = sorted(events_dir().iterdir())
    assert len(files) == 1
    assert [line["source_id"] for line in read_lines(files[0])] == [
        first["source_id"],
        second["source_id"],
    ]


def test_two_folders_land_in_two_files(project, homes):
    other = homes / "other"
    other.mkdir()
    assert append_event(make_event(project, "ran", "action", "make", now=FIXED))
    assert append_event(make_event(other, "ran", "action", "make", now=FIXED))
    files = sorted(path.name for path in events_dir().iterdir())
    assert files == sorted(
        [f"2026-10-29_{folder_key(project)}.jsonl", f"2026-10-29_{folder_key(other)}.jsonl"]
    )


def test_two_days_land_in_two_files(project):
    assert append_event(make_event(project, "ran", "action", "make", now=FIXED))
    later = FIXED + timedelta(days=1)
    assert append_event(make_event(project, "ran", "action", "make", now=later))
    assert len(list(events_dir().iterdir())) == 2


def test_every_line_parses_as_json(project):
    awkward = 'say "hi"\nand\tthen é中 \\ done'
    for index in range(3):
        event = make_event(
            project, "ran", "action", f"{awkward} {index}", rationale=awkward, now=FIXED
        )
        assert append_event(event)
    (path,) = list(events_dir().iterdir())
    raw = path.read_text(encoding="utf-8")
    assert raw.count("\n") == 3
    lines = read_lines(path)
    assert [line["object"] for line in lines] == [f"{awkward} {index}" for index in range(3)]
    assert all(line["rationale"] == awkward for line in lines)


def test_excluded_folder_writes_nothing_and_returns_false(homes):
    records = homes / "records" / "spring"
    records.mkdir(parents=True)
    exclude(str(homes / "records"))
    event = make_event(records, "ran", "action", "make", now=FIXED)
    assert append_event(event) is False
    assert not Path(os.environ["CONNECTIONS_HOME"]).exists()


@pytest.mark.parametrize("ignores, written", [(True, False), (False, True)])
def test_a_folder_listed_in_another_case_writes_nothing_only_on_a_disk_that_ignores_case(
    homes, monkeypatch, ignores, written
):
    # Track L, Step L4, decision 51, with a stand-in for the disk check.
    records = homes / "records" / "spring"
    records.mkdir(parents=True)
    exclude(str(homes / "Records"))
    monkeypatch.setattr(home, "ignores_case", lambda path: ignores)
    event = make_event(records, "ran", "action", "make", now=FIXED)
    assert append_event(event) is written


def test_missing_settings_file_writes_nothing_and_returns_false(homes):
    folder = homes / "project"
    folder.mkdir()
    event = make_event(folder, "ran", "action", "make", now=FIXED)
    assert append_event(event) is False
    assert not Path(os.environ["CONNECTIONS_HOME"]).exists()


def test_connections_home_that_is_a_file_returns_false(project):
    Path(os.environ["CONNECTIONS_HOME"]).write_text("not a folder")
    event = make_event(project, "ran", "action", "make", now=FIXED)
    assert append_event(event) is False
    assert Path(os.environ["CONNECTIONS_HOME"]).read_text() == "not a folder"


def test_events_folder_that_cannot_be_written_returns_false(project):
    folder = events_dir()
    folder.mkdir(parents=True)
    folder.chmod(0o500)
    try:
        event = make_event(project, "ran", "action", "make", now=FIXED)
        assert append_event(event) is False
    finally:
        folder.chmod(0o700)


@pytest.mark.parametrize(
    "event",
    [
        None,
        "not an event",
        {},
        {"cwd": "/tmp"},
        {"cwd": "/tmp", "harness_session_id": "../escape"},
        {"cwd": "/tmp", "harness_session_id": ""},
    ],
)
def test_broken_event_returns_false_without_an_exception(project, event):
    if isinstance(event, dict) and "cwd" in event:
        event = dict(event, cwd=str(project))
    assert append_event(event) is False
    assert not (Path(os.environ["CONNECTIONS_HOME"]) / "escape.jsonl").exists()


def test_event_that_cannot_be_written_as_json_returns_false(project):
    event = make_event(project, "ran", "action", "make", now=FIXED)
    event["bad"] = object()
    assert append_event(event) is False
