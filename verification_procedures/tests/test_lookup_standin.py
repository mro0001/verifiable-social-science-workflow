"""The live bibliographic lookup, tested offline against a stand-in service on the
local machine (appendix Table A6 row "Live bibliographic lookup"). The seeded
citations fixture runs with an empty metadata cache, so every DOI an AI citation names
goes to the stand-in, which serves the original cache's records in Crossref's shape, and
a DOI Crossref lacks goes on to the stand-in's DataCite service (Track C2 plan choice 3).
Both addresses point at the stand-in, so nothing reaches the network."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from standin_crossref import StandIn  # noqa: E402

ROOT = HERE.parent
VG = [sys.executable, str(ROOT / "vg.py")]
SEEDED = ROOT / "fixtures" / "citations" / "seeded"
CACHE = json.loads((SEEDED / "metadata_cache.json").read_text())
FABRICATED = "10.5555/nmr.2021.0388"
FAILING = "10.5555/jca.2019.0142"
# sorensen2022's DOI, held by no service in the offline fixture, here held by DataCite only.
PREPRINT = "10.5555/jca.2022.0301"
PREPRINT_RECORD = {"title": "Coordinator turnover and volunteer exit", "issued": 2022, "type": "Preprint",
                   "author": [{"family": "Sorensen", "given": "Mikkel"}], "container-title": "Zenodo"}


def vg(env, *args):
    return subprocess.run(VG + [str(a) for a in args], cwd=ROOT, capture_output=True, text=True, env=env)


def live_env(standin):
    env = dict(os.environ, VG_CROSSREF_URL=standin.url, VG_DATACITE_URL=standin.datacite_url,
               NO_PROXY="127.0.0.1,localhost")
    env.pop("VG_OFFLINE", None)
    return env


def citations_run(env, rd, inputs):
    p = vg(env, "run", "graphs/citations.yaml", "--run", rd, "--inputs", inputs,
           "--judge", "recorded:" + str(SEEDED / "recorded_judge.json"))
    assert p.returncode == 0, p.stdout + p.stderr
    return rd


def empty_cache_copy(dest):
    shutil.copytree(str(SEEDED), str(dest))
    (dest / "metadata_cache.json").write_text("{}\n")
    return dest


def files(rd, name):
    return json.loads((rd / "files" / name).read_text())


@pytest.fixture(scope="module")
def offline(tmp_path_factory):
    env = dict(os.environ, VG_OFFLINE="1")
    return citations_run(env, tmp_path_factory.mktemp("offline") / "run", SEEDED)


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    base = tmp_path_factory.mktemp("live")
    inputs = empty_cache_copy(base / "inputs")
    with StandIn(CACHE) as standin:
        rd = citations_run(live_env(standin), base / "run", inputs)
        requests = list(standin.requests)
    return rd, requests


@pytest.fixture(scope="module")
def with_datacite(tmp_path_factory):
    base = tmp_path_factory.mktemp("datacite")
    inputs = empty_cache_copy(base / "inputs")
    with StandIn(CACHE, datacite={PREPRINT: PREPRINT_RECORD}) as standin:
        rd = citations_run(live_env(standin), base / "run", inputs)
        requests = list(standin.requests)
    return rd, requests


def test_every_cached_doi_comes_from_crossref_and_the_fabricated_one_is_not_found(live):
    rd, _ = live
    lookups = {lk["doi"]: lk for lk in files(rd, "lookups.json")}
    held = [d for d in lookups if d in CACHE]
    assert held
    for doi in held:
        assert lookups[doi]["via"] == "crossref", doi
        assert lookups[doi]["found"] is True
        assert lookups[doi]["record"] == CACHE[doi]
    assert lookups[FABRICATED]["via"] == "not_found"
    assert lookups[FABRICATED]["found"] is False
    notes = [f for f in files(rd, "findings_check_existence.json") if f["item"] == "ferrante2021"]
    assert [(f["severity"], f["message"]) for f in notes] == [
        ("info", "@ferrante2021 was not found, since neither Crossref nor DataCite holds DOI " + FABRICATED)]


def test_the_live_run_notes_the_same_works_as_the_offline_run(live, offline):
    rd, _ = live
    assert [f["item"] for f in files(rd, "findings_check_existence.json")] == [
        f["item"] for f in files(offline, "findings_check_existence.json")]
    assert {lk["id"]: lk["found"] for lk in files(rd, "lookups.json")} == {
        lk["id"]: lk["found"] for lk in files(offline, "lookups.json")}


def test_seeded_recall_is_complete(live):
    rd, _ = live
    p = vg(dict(os.environ), "score", "--run", rd, "--truth", SEEDED / "truth.yaml")
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads((rd / "score.json").read_text())["recall"] == 1.0


def test_verify_hashes_the_lookup_and_does_not_replay_it(live):
    rd, _ = live
    p = vg(dict(os.environ, VG_OFFLINE="1"), "verify", "--run", rd)
    assert p.returncode == 0, p.stdout + p.stderr
    steps = json.loads((rd / "verify.json").read_text())["steps"]
    verdict = next(s["verdict"] for s in steps if s["node"] == "fetch_metadata")
    assert verdict == "network step: outputs hashed, not replayed"


def test_crossref_is_asked_for_each_doi_and_datacite_only_for_those_crossref_lacks(live):
    rd, requests = live
    looked_up = [lk["doi"] for lk in files(rd, "lookups.json")]
    lacking = [lk["doi"] for lk in files(rd, "lookups.json") if lk["via"] == "not_found"]
    assert sorted(lacking) == sorted([FABRICATED, PREPRINT])
    assert sorted(r["path"] for r in requests) == sorted(
        ["/works/" + d for d in looked_up] + ["/dois/" + d for d in lacking])
    assert all(r["user_agent"] == "vg-citations/0.2" for r in requests)


def test_a_doi_only_datacite_holds_is_found_in_datacite(with_datacite):
    rd, requests = with_datacite
    lookups = {lk["doi"]: lk for lk in files(rd, "lookups.json")}
    assert lookups[PREPRINT]["via"] == "datacite" and lookups[PREPRINT]["found"] is True
    assert lookups[PREPRINT]["record"] == PREPRINT_RECORD
    assert "/dois/" + PREPRINT in [r["path"] for r in requests]
    verified = {r["id"]: r for r in files(rd, "refs_verified.json")}
    assert verified["sorensen2022"]["lookup"] == "found"
    assert verified["sorensen2022"]["existence"] == "found in DataCite (DOI %s)" % PREPRINT
    assert verified["sorensen2022"]["record"] == (
        "Sorensen, M. (2022). Coordinator turnover and volunteer exit. Zenodo. Type Preprint.")
    assert not [f for f in files(rd, "findings_check_existence.json") if f["item"] == "sorensen2022"]


def test_a_failing_lookup_is_a_note_that_the_work_was_not_looked_up(tmp_path):
    inputs = empty_cache_copy(tmp_path / "inputs")
    with StandIn(CACHE, failing=[FAILING]) as standin:
        rd = citations_run(live_env(standin), tmp_path / "run", inputs)
    lookups = {lk["doi"]: lk for lk in files(rd, "lookups.json")}
    assert lookups[FAILING]["via"] == "crossref_error"
    key = lookups[FAILING]["id"]
    mine = [f for f in files(rd, "findings_check_existence.json") if f["item"] == key]
    assert [f["severity"] for f in mine] == ["info"]
    assert "lookup of DOI %s failed" % FAILING in mine[0]["message"]
    assert {r["id"]: r for r in files(rd, "refs_verified.json")}[key]["lookup"] == "not_looked_up"
