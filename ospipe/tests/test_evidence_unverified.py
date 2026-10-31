"""The list of unverified claims.

Each stream's results file is read by the build's own rule, and every stream that is not
verified and every item still open is listed. The verification folders here are
synthetic, written in the shape of the build status tests' results files
(`ospipe/evidence/fixture.py`). Nothing here calls a model or the network.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.build.verification import (  # noqa: E402
    STREAMS,
    latest_decision,
    stream_detail,
    stream_status,
)
from ospipe.evidence import SUMMARY_FIELDS, Unverified, unverified_claims  # noqa: E402
from ospipe.evidence import fixture  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def project(tmp_path):
    source, numbers = fixture.write_project(tmp_path / "project")
    return {"source": source, "numbers": numbers, "folder": tmp_path / "project" / "verification"}


def claims(project):
    return unverified_claims(project["folder"], project["source"], project["numbers"])


def details(project):
    return stream_detail(project["folder"], project["source"], project["numbers"])


def flags(project):
    return stream_status(project["folder"], project["source"], project["numbers"])[0]


def not_verified(project):
    return [s for s, d in details(project).items() if d.state != "verified"]


def make_case(project, case):
    """Write the verification folder for one named case."""
    folder = project["folder"]
    fixture.write_all_four(folder)
    if case == "held_and_undecided":
        decisions = [fixture.decision("r01"), fixture.decision("r02", "held")]
        fixture.write_results(folder, "citations", fixture.citations_results(decisions=decisions))
    elif case == "missing_data":
        (folder / "data.json").unlink()
    elif case == "out_of_date_build":
        fixture.write_results(folder, "build", fixture.stream_results("build", "an older text\n"))
    elif case == "unreadable_prose":
        (folder / "prose.json").write_text("{not json", encoding="utf-8")
    elif case == "older_run_approval":
        decisions = [fixture.decision(r[0]) for r in fixture.CITATION_ROWS[:2]]
        decisions.append(fixture.decision("r03", run_id=fixture.OLDER_RUN_ID))
        fixture.write_results(folder, "citations", fixture.citations_results(decisions=decisions))
    elif case == "no_folder":
        for stream in STREAMS:
            (folder / (stream + ".json")).unlink()
        folder.rmdir()
    elif case == "changed_numbers":
        project["numbers"].write_text(fixture.NUMBERS_TEXT + "\n", encoding="utf-8")
    elif case == "out_of_date_and_open":
        decisions = [fixture.decision("r01")]
        data = fixture.citations_results(source_text="an older text\n", decisions=decisions)
        fixture.write_results(folder, "citations", data)
    elif case == "malformed_shape":
        data = fixture.citations_results()
        del data["items"][0]["needs_decision"]
        fixture.write_results(folder, "citations", data)
    else:
        assert case == "all_verified"


CASES = [
    "all_verified",
    "held_and_undecided",
    "missing_data",
    "out_of_date_build",
    "unreadable_prose",
    "older_run_approval",
    "no_folder",
    "changed_numbers",
    "out_of_date_and_open",
    "malformed_shape",
]


class TestUnverifiedClaims:
    def test_four_verified_streams_give_none(self, project):
        make_case(project, "all_verified")
        assert claims(project) == []

    def test_a_held_and_an_undecided_citation_give_two_entries(self, project):
        make_case(project, "held_and_undecided")
        found = claims(project)
        assert [(u.stream, u.item, u.state) for u in found] == [
            ("citations", "r02", "held"),
            ("citations", "r03", "undecided"),
        ]
        assert found[0].summary == "The rise was steady."
        assert found[1].summary == "The source reports a rise, not a fall."

    @pytest.mark.parametrize(
        "case, entry",
        [
            ("missing_data", ("data", "-", "missing")),
            ("out_of_date_build", ("build", "-", "out_of_date")),
            ("unreadable_prose", ("prose", "-", "unreadable")),
        ],
    )
    def test_a_stream_not_verified_as_a_whole_gives_one_entry(self, project, case, entry):
        make_case(project, case)
        found = claims(project)
        assert [(u.stream, u.item, u.state) for u in found] == [entry]
        assert found[0].summary == ""

    def test_an_approval_on_an_older_run_leaves_the_item_undecided(self, project):
        make_case(project, "older_run_approval")
        assert [(u.stream, u.item, u.state) for u in claims(project)] == [("citations", "r03", "undecided")]

    def test_no_folder_lists_every_stream_as_missing(self, project):
        make_case(project, "no_folder")
        assert [(u.stream, u.item, u.state) for u in claims(project)] == [
            (s, "-", "missing") for s in STREAMS
        ]
        assert not project["folder"].exists()

    def test_an_out_of_date_stream_also_lists_its_open_items(self, project):
        make_case(project, "out_of_date_and_open")
        assert [(u.stream, u.item, u.state) for u in claims(project)] == [
            ("citations", "-", "out_of_date"),
            ("citations", "r02", "undecided"),
            ("citations", "r03", "undecided"),
        ]

    def test_entries_are_unverified_tuples(self, project):
        make_case(project, "held_and_undecided")
        entry = claims(project)[0]
        assert isinstance(entry, Unverified)
        assert entry._fields == ("stream", "item", "state", "summary")

    @pytest.mark.parametrize("case", CASES)
    def test_streams_not_verified_are_exactly_the_build_flags(self, project, case):
        make_case(project, case)
        assert not_verified(project) == flags(project)
        assert sorted(set(u.stream for u in claims(project)), key=STREAMS.index) == flags(project)


class TestSummary:
    def test_the_summary_fields_name_every_stream(self):
        assert sorted(SUMMARY_FIELDS) == sorted(STREAMS)
        assert SUMMARY_FIELDS["citations"] == ("summary", "reason", "sentence")
        for stream in ("prose", "data", "build"):
            assert SUMMARY_FIELDS[stream] == ("summary",)

    def test_the_first_non_empty_field_is_the_summary(self, project):
        fixture.write_all_four(project["folder"])
        item = fixture.citation_item("r04", "delta2021", "problem", "A reason.", "A sentence.")
        item["summary"] = "  "
        data = fixture.citations_results(extra_items=[item])
        fixture.write_results(project["folder"], "citations", data)
        assert [(u.item, u.summary) for u in claims(project)] == [("r04", "A reason.")]

    def test_a_long_summary_is_cut_to_120_characters_on_one_line(self, project):
        fixture.write_all_four(project["folder"])
        long_text = "word\nnext " * 40
        data = fixture.stream_results("prose", fixture.SOURCE_TEXT, decisions=[], summary=long_text)
        fixture.write_results(project["folder"], "prose", data)
        found = claims(project)
        assert [(u.stream, u.item, u.state) for u in found] == [("prose", "i1", "undecided")]
        assert len(found[0].summary) == 120
        assert "\n" not in found[0].summary
        assert found[0].summary.startswith("word next word next")

    def test_an_item_with_no_summary_field_gives_an_empty_summary(self, project):
        fixture.write_all_four(project["folder"])
        data = fixture.stream_results("data", fixture.NUMBERS_TEXT, decisions=[])
        del data["items"][0]["summary"]
        fixture.write_results(project["folder"], "data", data)
        assert [(u.stream, u.item, u.summary) for u in claims(project)] == [("data", "i1", "")]


class TestStreamDetail:
    def test_every_stream_in_order(self, project):
        make_case(project, "all_verified")
        found = details(project)
        assert list(found) == list(STREAMS)
        assert [d.state for d in found.values()] == ["verified"] * 4
        assert found["citations"].run_id == fixture.RUN_ID
        assert found["prose"].run_id == "fake_prose_1"
        assert all(d.open_items == [] for d in found.values())

    def test_open_items_carry_the_item(self, project):
        make_case(project, "held_and_undecided")
        found = details(project)["citations"]
        assert found.state == "open"
        assert found._fields == ("state", "run_id", "open_items")
        assert [(i, s) for i, s, _ in found.open_items] == [("r02", "held"), ("r03", "undecided")]
        assert found.open_items[0][2]["citekey"] == "beta2014"

    def test_missing_and_unreadable_name_no_run(self, project):
        make_case(project, "missing_data")
        assert details(project)["data"] == ("missing", None, [])
        make_case(project, "unreadable_prose")
        assert details(project)["prose"] == ("unreadable", None, [])

    def test_a_malformed_file_is_unreadable(self, project):
        make_case(project, "malformed_shape")
        assert details(project)["citations"].state == "unreadable"

    def test_out_of_date_names_its_run(self, project):
        make_case(project, "out_of_date_build")
        assert details(project)["build"][:2] == ("out_of_date", "fake_build_1")


class TestLatestDecision:
    def results(self, decisions):
        return fixture.citations_results(decisions=decisions)

    def test_approved_on_this_run(self):
        word, entry = latest_decision(self.results([fixture.decision("r01")]), "r01")
        assert word == "approved"
        assert entry == fixture.decision("r01")

    def test_held_on_this_run(self):
        held = fixture.decision("r01", "held", by="another scholar")
        assert latest_decision(self.results([held]), "r01") == ("held", held)

    def test_no_decision_is_undecided(self):
        assert latest_decision(self.results([]), "r01") == ("undecided", None)

    def test_a_decision_on_an_older_run_does_not_count(self):
        older = fixture.decision("r01", run_id=fixture.OLDER_RUN_ID)
        assert latest_decision(self.results([older]), "r01") == ("undecided", None)

    def test_the_latest_decision_counts(self):
        both = [fixture.decision("r01"), fixture.decision("r01", "held")]
        assert latest_decision(self.results(both), "r01")[0] == "held"
        both.reverse()
        assert latest_decision(self.results(both), "r01")[0] == "approved"

    def test_a_later_decision_on_an_older_run_undoes_an_approval(self):
        # stream_status reads the last decision listed, so the item counts as not approved
        both = [fixture.decision("r01"), fixture.decision("r01", run_id=fixture.OLDER_RUN_ID)]
        assert latest_decision(self.results(both), "r01") == ("undecided", None)


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "ospipe", "unverified"] + [str(a) for a in args],
        capture_output=True,
        text=True,
        cwd=str(OSPIPE_DIR),
    )


class TestCommandLine:
    def test_four_verified_streams_print_zero(self, project):
        make_case(project, "all_verified")
        run = run_cli("--source", project["source"], "--manifest", project["numbers"])
        assert run.returncode == 0, run.stderr
        assert run.stdout == "0 unverified\n"

    def test_one_line_per_entry_then_the_count(self, project):
        make_case(project, "held_and_undecided")
        (project["folder"] / "data.json").unlink()
        run = run_cli("--source", project["source"], "--manifest", project["numbers"])
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines() == [
            "citations r02 held, The rise was steady.",
            "citations r03 undecided, The source reports a rise, not a fall.",
            "data - missing",
            "3 unverified",
        ]

    def test_out_writes_the_same_as_a_markdown_list(self, project, tmp_path):
        make_case(project, "held_and_undecided")
        out = tmp_path / "unverified.md"
        run = run_cli("--source", project["source"], "--manifest", project["numbers"], "--out", out)
        assert run.returncode == 0, run.stderr
        assert out.read_text(encoding="utf-8") == (
            "- citations r02 held, The rise was steady.\n"
            "- citations r03 undecided, The source reports a rise, not a fall.\n"
            "\n"
            "2 unverified\n"
        )
        assert run.stdout.splitlines()[-1] == "2 unverified"

    def test_the_verification_dir_option_names_another_folder(self, project, tmp_path):
        make_case(project, "held_and_undecided")
        elsewhere = tmp_path / "handed_over"
        fixture.write_all_four(elsewhere)
        run = run_cli(
            "--source", project["source"], "--manifest", project["numbers"], "--verification-dir", elsewhere
        )
        assert run.returncode == 0, run.stderr
        assert run.stdout == "0 unverified\n"

    def test_it_always_exits_zero(self, project, tmp_path):
        run = run_cli("--source", tmp_path / "no_such.md", "--manifest", tmp_path / "no_such.yml")
        assert run.returncode == 0, run.stderr
        assert run.stdout.splitlines() == ["{0} - missing".format(s) for s in STREAMS] + ["4 unverified"]

    def test_the_json_files_are_left_as_they_were(self, project):
        make_case(project, "held_and_undecided")
        before = {p.name: p.read_bytes() for p in project["folder"].iterdir()}
        run_cli("--source", project["source"], "--manifest", project["numbers"])
        assert {p.name: p.read_bytes() for p in project["folder"].iterdir()} == before
        assert json.loads(before["citations.json"])["run_id"] == fixture.RUN_ID
