"""Verification status tests. The build reads each stream's results file and marks the product.

The results files here are synthetic, cut from the test story in examples/test_story.
The citations file carries the story's three reference rows (r01 castellanos2017, r02
dumont2014, r03 nakamura2020, none of them the author's warrant, so each needs a
decision), and its inputs carry the checksums of the story's files with the project's
manuscript as draft.md, the way the references run records them. Every test works on a
copy of the story project. Nothing here calls a model or the network.
"""
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.build import BuildError, build, verify_ledger  # noqa: E402
from ospipe.build import fixture  # noqa: E402
from ospipe.build.verification import STREAMS, stream_status  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]
STORY = OSPIPE_DIR.parent / "examples" / "test_story"
RUN_ID = "story_citations_2"
OLDER_RUN_ID = "story_citations_1"
ALL_FLAGS = ["prose", "citations", "data", "build"]
NEW_HEADER = "| version | date | git | sha256 | purpose | baseline | reviewed | verification | runs |"

# The story's reference rows as its references run reports them (id, citekey, category).
STORY_ROWS = [
    ("r01", "castellanos2017", "verified"),
    ("r02", "dumont2014", "verified"),
    ("r03", "nakamura2020", "problem"),
]


def checksum(path):
    """The checksum form the verification runtime writes in a run's inputs."""
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture()
def project(tmp_path):
    """A copy of the story project, so a test can change its source text."""
    dest = tmp_path / "project"
    shutil.copytree(
        str(STORY / "project"), str(dest), ignore=shutil.ignore_patterns("builds", "verification")
    )
    return dest


def story_inputs(source):
    """The story references run's inputs, with the manuscript at `source` as draft.md."""
    refs = STORY / "references"
    inputs = {
        "draft.md": checksum(source),
        "author_draft.md": checksum(STORY / "project" / "author_draft.md"),
        "citation_log.yaml": checksum(refs / "expected_citation_log.yaml"),
    }
    for path in sorted(refs.iterdir()):
        if path.name == "expected_citation_log.yaml" or path.name.startswith("recorded_"):
            continue  # recorded answers never enter a run
        inputs[path.name] = checksum(path)
    return inputs


def decision(item, verdict="approved", run_id=RUN_ID):
    return {
        "item": item,
        "decision": verdict,
        "by": "scholar",
        "at": "2026-10-29T09:00:00-07:00",
        "run_id": run_id,
    }


def citations_results(source, decisions=None, extra_items=()):
    """The story's citations results file, every row approved unless decisions are given."""
    items = [
        {"id": row_id, "citekey": key, "category": category, "needs_decision": True}
        for row_id, key, category in STORY_ROWS
    ]
    items.extend(extra_items)
    if decisions is None:
        decisions = [decision(row_id) for row_id, _, _ in STORY_ROWS]
    return {
        "schema": "verification-results",
        "schema_version": 1,
        "stream": "citations",
        "run_id": RUN_ID,
        "procedure_version": 0.1,
        "inputs": story_inputs(source),
        "items": items,
        "decisions": decisions,
    }


def stream_results(stream, inputs):
    """A results file for another stream, with one item, approved on its run."""
    run_id = "story_{0}_1".format(stream)
    return {
        "schema": "verification-results",
        "schema_version": 1,
        "stream": stream,
        "run_id": run_id,
        "procedure_version": 0.1,
        "inputs": inputs,
        "items": [{"id": "i1", "needs_decision": True}],
        "decisions": [decision("i1", run_id=run_id)],
    }


def write(folder, stream, data):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (stream + ".json")).write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_all_four(folder, project):
    source, numbers = project / "manuscript.md", project / "numbers.yml"
    write(folder, "citations", citations_results(source))
    write(folder, "prose", stream_results("prose", {"revised.md": checksum(source)}))
    write(folder, "data", stream_results("data", {"numbers.yml": checksum(numbers)}))
    write(folder, "build", stream_results("build", {"manuscript.md": checksum(source)}))


def status(folder, project):
    return stream_status(folder, project / "manuscript.md", project / "numbers.yml")


def ledger_row(builds, version):
    ledger = (Path(builds) / "BUILDS.md").read_text(encoding="utf-8")
    line = [ln for ln in ledger.splitlines() if ln.startswith("| " + version + " ")][0]
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def build_with_status(project, folder, builds, text=fixture.RESOLVED_MD, **kwargs):
    return build(
        text,
        builds,
        purpose=kwargs.pop("purpose", "story build"),
        verification_dir=folder,
        source_path=project / "manuscript.md",
        numbers_path=project / "numbers.yml",
        **kwargs
    )


class TestStreamStatus:
    def test_the_four_streams_in_order(self):
        assert list(STREAMS) == ALL_FLAGS

    def test_no_file_gives_the_flag(self, project, tmp_path):
        folder = tmp_path / "verification"
        folder.mkdir()
        assert status(folder, project) == (ALL_FLAGS, {})

    def test_a_missing_folder_flags_every_stream_and_is_not_made(self, project, tmp_path):
        folder = tmp_path / "never_handed_over"
        assert status(folder, project) == (ALL_FLAGS, {})
        assert not folder.exists()

    def test_approved_items_and_current_inputs_give_no_flag(self, project, tmp_path):
        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(project / "manuscript.md"))
        flags, runs = status(folder, project)
        assert flags == ["prose", "data", "build"]
        assert runs == {"citations": RUN_ID}

    @pytest.mark.parametrize("case", ["held", "undecided", "older_run"])
    def test_an_item_not_approved_on_this_run_gives_the_flag(self, project, tmp_path, case):
        decisions = [decision("r01"), decision("r02")]
        if case == "held":
            decisions.append(decision("r03", "held"))
        elif case == "older_run":
            decisions.append(decision("r03", run_id=OLDER_RUN_ID))
        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(project / "manuscript.md", decisions))
        flags, runs = status(folder, project)
        assert flags == ALL_FLAGS
        assert runs == {"citations": RUN_ID}  # the file was read, and its run is named

    def test_every_decision_on_an_older_run_gives_the_flag(self, project, tmp_path):
        decisions = [decision(row_id, run_id=OLDER_RUN_ID) for row_id, _, _ in STORY_ROWS]
        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(project / "manuscript.md", decisions))
        assert "citations" in status(folder, project)[0]

    def test_the_latest_decision_for_an_item_counts(self, project, tmp_path):
        source = project / "manuscript.md"
        folder = tmp_path / "verification"
        approved_then_held = [decision(r) for r, _, _ in STORY_ROWS] + [decision("r03", "held")]
        write(folder, "citations", citations_results(source, approved_then_held))
        assert "citations" in status(folder, project)[0]
        held_then_approved = [decision("r03", "held")] + [decision(r) for r, _, _ in STORY_ROWS]
        write(folder, "citations", citations_results(source, held_then_approved))
        assert "citations" not in status(folder, project)[0]

    def test_an_item_that_needs_no_decision_needs_no_approval(self, project, tmp_path):
        warrant = {"id": "r04", "citekey": "author2019", "category": "author", "needs_decision": False}
        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(project / "manuscript.md", extra_items=[warrant]))
        assert status(folder, project) == (["prose", "data", "build"], {"citations": RUN_ID})

    def test_a_changed_source_text_gives_the_flag(self, project, tmp_path):
        source = project / "manuscript.md"
        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(source))
        assert "citations" not in status(folder, project)[0]
        source.write_text(source.read_text(encoding="utf-8") + "\nOne more sentence.\n", encoding="utf-8")
        flags, runs = status(folder, project)
        assert flags == ALL_FLAGS
        assert runs == {"citations": RUN_ID}

    def test_no_source_path_gives_the_flag(self, project, tmp_path):
        folder = tmp_path / "verification"
        write_all_four(folder, project)
        flags, runs = stream_status(folder, None, None)
        assert flags == ALL_FLAGS
        assert list(runs) == ALL_FLAGS

    def test_the_data_stream_covers_the_numbers_file(self, project, tmp_path):
        source, numbers = project / "manuscript.md", project / "numbers.yml"
        folder = tmp_path / "verification"
        write(folder, "data", stream_results("data", {"numbers.yml": checksum(numbers)}))
        write(folder, "prose", stream_results("prose", {"numbers.yml": checksum(numbers)}))
        flags, _ = status(folder, project)
        assert "data" not in flags
        assert "prose" in flags  # prose covers the source text, not the numbers file
        write(folder, "data", stream_results("data", {"draft.md": checksum(source)}))
        assert "data" in status(folder, project)[0]

    def test_a_changed_numbers_file_flags_only_data(self, project, tmp_path):
        folder = tmp_path / "verification"
        write_all_four(folder, project)
        assert status(folder, project)[0] == []
        numbers = project / "numbers.yml"
        numbers.write_text(numbers.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        assert status(folder, project)[0] == ["data"]

    def test_every_stream_verified_gives_no_flag_and_names_every_run(self, project, tmp_path):
        folder = tmp_path / "verification"
        write_all_four(folder, project)
        flags, runs = status(folder, project)
        assert flags == []
        assert runs == {
            "prose": "story_prose_1",
            "citations": RUN_ID,
            "data": "story_data_1",
            "build": "story_build_1",
        }

    @pytest.mark.parametrize(
        "damage",
        [
            "not_json",
            "empty",
            "not_utf8",
            "a_list",
            "wrong_schema",
            "schema_version_2",
            "schema_version_text",
            "schema_version_true",
            "no_run_id",
            "inputs_a_list",
            "no_items",
            "item_not_an_object",
            "item_without_needs_decision",
            "item_without_id",
            "decisions_not_a_list",
            "decision_not_an_object",
            "decision_item_a_list",
        ],
    )
    def test_a_malformed_file_gives_the_flag(self, project, tmp_path, damage):
        folder = tmp_path / "verification"
        folder.mkdir()
        path = folder / "citations.json"
        good = citations_results(project / "manuscript.md")
        if damage == "not_json":
            path.write_text("{not json", encoding="utf-8")
        elif damage == "empty":
            path.write_text("", encoding="utf-8")
        elif damage == "not_utf8":
            path.write_bytes(b"\xff\xfe" + json.dumps(good).encode("utf-16-le"))
        elif damage == "a_list":
            path.write_text(json.dumps([good]), encoding="utf-8")
        else:
            if damage == "wrong_schema":
                good["schema"] = "verification-report"
            elif damage == "schema_version_2":
                good["schema_version"] = 2
            elif damage == "schema_version_text":
                good["schema_version"] = "1"
            elif damage == "schema_version_true":
                good["schema_version"] = True
            elif damage == "no_run_id":
                del good["run_id"]
            elif damage == "inputs_a_list":
                good["inputs"] = sorted(good["inputs"].values())
            elif damage == "no_items":
                del good["items"]
            elif damage == "item_not_an_object":
                good["items"].append("r04")
            elif damage == "item_without_needs_decision":
                del good["items"][0]["needs_decision"]
            elif damage == "item_without_id":
                del good["items"][0]["id"]
            elif damage == "decisions_not_a_list":
                good["decisions"] = {"r01": "approved"}
            elif damage == "decision_not_an_object":
                good["decisions"].append("approved")
            elif damage == "decision_item_a_list":
                good["decisions"].append(decision(["r01", "r02"]))
            write(folder, "citations", good)
        flags, runs = status(folder, project)
        assert flags == ALL_FLAGS
        assert runs == {}  # a malformed file names no run


class TestBuildMarksTheProduct:
    def test_the_ledger_holds_both_new_columns(self, project, tmp_path):
        builds = tmp_path / "builds"
        result = build_with_status(project, tmp_path / "verification", builds)
        assert result.version == "v001"
        ledger = (builds / "BUILDS.md").read_text(encoding="utf-8")
        assert NEW_HEADER in ledger
        cells = ledger_row(builds, "v001")
        assert len(cells) == 9
        assert cells[3] == result.sha256
        assert cells[6] == "no"
        assert cells[7:] == ["unverified: prose, citations, data, build", "-"]
        assert verify_ledger(builds) is None

    def test_an_approved_stream_drops_from_the_mark_and_names_its_run(self, project, tmp_path):
        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(project / "manuscript.md"))
        build_with_status(project, folder, tmp_path / "builds")
        cells = ledger_row(tmp_path / "builds", "v001")
        assert cells[7:] == ["unverified: prose, data, build", "citations=" + RUN_ID]

    def test_every_stream_verified_marks_the_build_verified(self, project, tmp_path):
        folder = tmp_path / "verification"
        write_all_four(folder, project)
        build_with_status(project, folder, tmp_path / "builds")
        cells = ledger_row(tmp_path / "builds", "v001")
        assert cells[7] == "verified"
        assert cells[8] == (
            "prose=story_prose_1; citations=" + RUN_ID + "; data=story_data_1; build=story_build_1"
        )

    def test_a_held_item_marks_the_build_unverified(self, project, tmp_path):
        decisions = [decision("r01"), decision("r02"), decision("r03", "held")]
        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(project / "manuscript.md", decisions))
        build_with_status(project, folder, tmp_path / "builds")
        cells = ledger_row(tmp_path / "builds", "v001")
        assert cells[7:] == ["unverified: prose, citations, data, build", "citations=" + RUN_ID]

    def test_without_a_verification_folder_no_status_is_read(self, project, tmp_path):
        folder = tmp_path / "verification"
        write_all_four(folder, project)
        builds = tmp_path / "builds"
        build(fixture.RESOLVED_MD, builds, purpose="no status asked for")
        assert NEW_HEADER in (builds / "BUILDS.md").read_text(encoding="utf-8")
        assert ledger_row(builds, "v001")[7:] == ["-", "-"]

    def test_the_status_never_stops_a_build(self, project, tmp_path):
        folder = tmp_path / "verification"
        folder.mkdir()
        for stream in ALL_FLAGS:
            (folder / (stream + ".json")).write_text("{broken", encoding="utf-8")
        first = build_with_status(project, folder, tmp_path / "builds")
        assert first.version == "v001"
        not_a_folder = tmp_path / "a_file"
        not_a_folder.write_text("not a folder", encoding="utf-8")
        second = build_with_status(project, not_a_folder, tmp_path / "builds", purpose="odd path")
        assert second.version == "v002"
        assert verify_ledger(tmp_path / "builds") is None
        for version in ("v001", "v002"):
            assert ledger_row(tmp_path / "builds", version)[7:] == [
                "unverified: prose, citations, data, build",
                "-",
            ]

    def test_an_old_seven_column_ledger_still_verifies(self, project, tmp_path):
        builds = tmp_path / "builds"
        first = build(fixture.RESOLVED_MD, builds, purpose="before the columns")
        old_header = "| version | date | git | sha256 | purpose | baseline | reviewed |\n"
        (builds / "BUILDS.md").write_text(
            "# Builds\n\n" + old_header + "|---|---|---|---|---|---|---|\n"
            "| v001 | 2026-10-01 | - | " + first.sha256 + " | before the columns | - | no |\n",
            encoding="utf-8",
        )
        assert verify_ledger(builds) is None

        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(project / "manuscript.md"))
        second = build_with_status(project, folder, builds, text=fixture.RESOLVED_MD_NEXT, baseline="v001")
        assert second.version == "v002"
        assert verify_ledger(builds) is None
        assert len(ledger_row(builds, "v001")) == 7
        assert ledger_row(builds, "v002")[5:] == [
            "v001",
            "no",
            "unverified: prose, data, build",
            "citations=" + RUN_ID,
        ]
        third = build(fixture.RESOLVED_MD, builds, purpose="numbering continues")
        assert third.version == "v003"
        assert verify_ledger(builds) is None

    def test_a_ledger_row_of_another_width_is_still_refused(self, tmp_path):
        builds = tmp_path / "builds"
        build(fixture.RESOLVED_MD, builds, purpose="one")
        with open(builds / "BUILDS.md", "a", encoding="utf-8") as fh:
            fh.write("| v002 | 2026-10-29 | - | " + fixture.FAKE_SHA256 + " | eight cells | - | no | x |\n")
        with pytest.raises(BuildError, match="line 6"):
            verify_ledger(builds)

    def test_an_altered_earlier_build_is_still_refused(self, project, tmp_path):
        folder = tmp_path / "verification"
        write_all_four(folder, project)
        builds = tmp_path / "builds"
        first = build_with_status(project, folder, builds)
        with open(first.docx_path, "ab") as fh:
            fh.write(fixture.TAMPER_BYTES)
        with pytest.raises(BuildError, match="sha256 mismatch"):
            build_with_status(project, folder, builds, text=fixture.RESOLVED_MD_NEXT)
        assert not (builds / "v002.md").exists()
        assert not (builds / "v002.docx").exists()
        assert "| v002 " not in (builds / "BUILDS.md").read_text(encoding="utf-8")

    def test_no_network_call_is_made(self, project, tmp_path, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("a network call was attempted")

        monkeypatch.setattr(socket, "create_connection", refuse)
        monkeypatch.setattr(socket, "getaddrinfo", refuse)
        monkeypatch.setattr(socket.socket, "connect", refuse)
        folder = tmp_path / "verification"
        write(folder, "citations", citations_results(project / "manuscript.md"))
        assert status(folder, project) == (["prose", "data", "build"], {"citations": RUN_ID})
        result = build_with_status(project, folder, tmp_path / "builds")
        assert result.version == "v001"


def run_cli(project, *extra):
    """python3 -m ospipe build on the story project, as its README runs it."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ospipe",
            "build",
            "--manuscript",
            str(project / "manuscript.md"),
            "--manifest",
            str(project / "numbers.yml"),
            "--tables-dir",
            str(project),
            "--bib",
            str(project / "refs.bib"),
            "--builds-dir",
            str(project / "builds" / "manuscript"),
            "--purpose",
            "story manuscript",
        ]
        + list(extra),
        capture_output=True,
        text=True,
        cwd=str(OSPIPE_DIR),
    )


class TestCommandLine:
    def test_build_prints_the_flags_and_a_changed_manuscript_is_flagged_again(self, project):
        builds = project / "builds" / "manuscript"
        first = run_cli(project)
        assert first.returncode == 0, first.stderr
        lines = first.stdout.splitlines()
        assert lines[0].startswith("v001 -> ")
        assert lines[1] == "unverified: prose, citations, data, build"
        assert ledger_row(builds, "v001")[7:] == ["unverified: prose, citations, data, build", "-"]

        # the results file handed over beside the manuscript, every item approved
        write(project / "verification", "citations", citations_results(project / "manuscript.md"))
        second = run_cli(project)
        assert second.returncode == 0, second.stderr
        assert second.stdout.splitlines()[1] == "unverified: prose, data, build"
        assert ledger_row(builds, "v002")[7:] == ["unverified: prose, data, build", "citations=" + RUN_ID]

        manuscript = project / "manuscript.md"
        manuscript.write_text(
            manuscript.read_text(encoding="utf-8") + "\nA sentence added after the run.\n",
            encoding="utf-8",
        )
        third = run_cli(project)
        assert third.returncode == 0, third.stderr
        assert third.stdout.splitlines()[1] == "unverified: prose, citations, data, build"
        assert ledger_row(builds, "v003")[7:] == [
            "unverified: prose, citations, data, build",
            "citations=" + RUN_ID,
        ]

    def test_every_stream_verified_prints_and_records_verified(self, project):
        write_all_four(project / "verification", project)
        run = run_cli(project)
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines()[1] == "verified"
        assert ledger_row(project / "builds" / "manuscript", "v001")[7] == "verified"

    def test_the_verification_dir_option_names_another_folder(self, project, tmp_path):
        elsewhere = tmp_path / "handed_over"
        write(elsewhere, "citations", citations_results(project / "manuscript.md"))
        beside = project / "verification"
        write(beside, "citations", citations_results(project / "manuscript.md", decisions=[]))
        run = run_cli(project, "--verification-dir", str(elsewhere))
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines()[1] == "unverified: prose, data, build"

    def test_an_unfilled_placeholder_still_stops_the_build(self, project):
        write(project / "verification", "citations", citations_results(project / "manuscript.md"))
        manuscript = project / "manuscript.md"
        manuscript.write_text(
            manuscript.read_text(encoding="utf-8") + "\nA value with no entry, {{num:not_in_numbers}}.\n",
            encoding="utf-8",
        )
        run = run_cli(project)
        assert run.returncode == 2
        assert "not_in_numbers" in run.stderr
        assert not (project / "builds").exists()
