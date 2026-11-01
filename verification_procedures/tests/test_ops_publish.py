"""Checking a verification repository before it is published, written as a procedural
graph (graphs/ops_publish.yaml).

The run reads the repository that python3 -m features publish build writes, packed as
repo.tar, and the settings it writes beside it, publish_check.yaml. The fixtures are made
by fixtures/ops_publish/make_fixtures.py: a small synthetic repository with two
products, whose manifest's counts are written out by hand, and a seeded copy holding
the faults its truth.yaml names. The term the settings name is Jordan Doe, and every
address and host is an example one.

The rebuild tests build a tiny real project once with make and pandoc, and are skipped
when this machine has no make that runs from this Python or no pandoc.
"""
import collections
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tokenize
import unicodedata
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
VG = [sys.executable, str(ROOT / "vg.py")]
FIX = ROOT / "fixtures" / "ops_publish"
GRAPH = "graphs/ops_publish.yaml"
TITLE = "Check a verification repository before it is published"
STEPS = ("publish_settings", "publish_files", "publish_counts", "publish_rebuild", "publish_report")
SETTINGS_FIELDS = ("task", "valid", "workflow_root", "terms", "allow", "max_file_mb", "warn_file_mb", "rebuild",
                   "excluded_folders", "excluded_paths")
HEADINGS = ["Summary", "Problems", "Settings", "Files", "Counts", "Rebuild", "Notes"]
MACHINE_PATHS = ("/Users/", "/home/", "/tmp/", "/private/tmp/", "/var/folders/")
ALLOWED_IMPORTS = {"_lib", "yaml", "base64", "collections", "csv", "datetime", "fnmatch", "hashlib", "html", "io",
                   "json", "os", "posixpath", "re", "shutil", "subprocess", "tarfile", "tempfile", "unicodedata",
                   "zipfile", "zlib"}


def load_maker():
    spec = importlib.util.spec_from_file_location("ops_publish_make_fixtures", str(FIX / "make_fixtures.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAKER = load_maker()


def vg(*args, env=None):
    return subprocess.run(VG + list(args), cwd=ROOT, capture_output=True, text=True, env=env)


def run_on(tmp_path, inputs, name="run"):
    run = tmp_path / name
    p = vg("run", GRAPH, "--run", str(run), "--inputs", str(inputs))
    assert p.returncode == 0, p.stdout + p.stderr
    return run


def settings(**over):
    base = yaml.safe_load(MAKER.SETTINGS)
    base.update(over)
    return base


def inputs_with(tmp_path, cfg=None, files=None, raw_settings=None, name="inputs"):
    """An inputs folder holding publish_check.yaml and repo.tar, by default the clean
    repository, else a tar of the given {name: bytes}."""
    inputs = tmp_path / name
    inputs.mkdir()
    text = raw_settings if raw_settings is not None else yaml.safe_dump(cfg or settings(), sort_keys=True)
    (inputs / "publish_check.yaml").write_text(text, encoding="utf-8")
    data = (FIX / "clean" / "repo.tar").read_bytes() if files is None else MAKER.pack_files(files)
    (inputs / "repo.tar").write_bytes(data)
    return inputs


def clean_files():
    return MAKER.finish(MAKER.repository())


def read(run, name):
    return json.loads((run / "files" / name).read_text(encoding="utf-8"))


def findings(run, severity=None, check=None):
    return [f for f in read(run, "findings.json")
            if (severity is None or f["severity"] == severity) and (check is None or f["check"] == check)]


def problems(run, check=None):
    return [f for f in findings(run, check=check) if f["severity"] in ("blocking", "warning")]


def pairs(found):
    return sorted((f["severity"], f["item"]) for f in found)


def skipped(run):
    lines = (run / "trail.jsonl").read_text(encoding="utf-8").splitlines()
    return [e["node"] for e in map(json.loads, lines) if e["event"] == "step_skipped"]


def ran(run):
    return [json.loads(p.read_text())["node"] for p in sorted((run / "records").glob("*.json"))]


def report(run):
    return (run / "files" / "report.md").read_text(encoding="utf-8")


def section(text, heading):
    return text.split("## " + heading + "\n")[1].split("\n## ")[0].strip()


def scan(tmp_path, extra, name="case", **over):
    """The file findings for the clean repository with extra files added and the
    manifest written again, so only the scan's own findings appear."""
    sub = tmp_path / name
    sub.mkdir()
    files = MAKER.repository()
    files.update(extra)
    run = run_on(sub, inputs_with(sub, settings(**over), MAKER.finish(files)))
    return [f for f in read(run, "findings.json") if f["check"] == "publish_files"]


def blocked(found):
    return sorted(set(f["item"] for f in found if f["severity"] == "blocking"))


# ---------------------------------------------------------------- the graph

def test_graph_passes_check():
    p = vg("check", GRAPH)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.startswith("OK: ")


def test_graph_names_its_stream_title_triggers_and_ends():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert (graph["stream"], graph["version"], graph["title"]) == ("ops", 0.1, TITLE)
    assert graph["contracts"] == "contracts/ops_publish.yaml"
    assert len(graph["triggers"]) == 2 and all(t.endswith(".") for t in graph["triggers"])
    assert (graph["entry"], graph["exit"]) == ("publish_settings", "publish_report")
    nodes = [n["id"] for n in graph["nodes"]]
    assert nodes == list(STEPS)
    assert all(n["kind"] == "tool" and "replay" not in n for n in graph["nodes"])


def test_graph_edges_checks_and_pitfalls():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    edges = {(e["from"], e["to"]): e for e in graph["edges"]}
    assert sorted(edges) == sorted([
        ("publish_settings", "publish_files"), ("publish_settings", "publish_report"),
        ("publish_files", "publish_counts"), ("publish_counts", "publish_rebuild"),
        ("publish_counts", "publish_report"), ("publish_rebuild", "publish_report")])
    assert edges[("publish_settings", "publish_files")]["check"] == "settings.json:valid == true"
    assert edges[("publish_settings", "publish_report")]["check"] == "settings.json:valid == false"
    assert "check" not in edges[("publish_files", "publish_counts")]
    assert edges[("publish_counts", "publish_rebuild")]["check"] == "settings.json:rebuild == true"
    assert edges[("publish_counts", "publish_report")]["check"] == "settings.json:rebuild == false"
    assert "check" not in edges[("publish_rebuild", "publish_report")]
    assert all(e["source"] == "proposed" and e["pitfalls"] for e in graph["edges"])
    text = " ".join(p for e in graph["edges"] for p in e["pitfalls"]).lower()
    for words in ("allow entry", "archive", "pandoc version", "by hand", "a key or a term"):
        assert words in text, words


def test_graph_text_names_no_machine_path_and_no_long_dash():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    texts = [graph["goal"], graph["title"]] + graph["triggers"] + [n["does"] for n in graph["nodes"]]
    for e in graph["edges"]:
        texts += [e["condition"], e["guidance"]] + e["pitfalls"]
    for text in texts:
        for path in MACHINE_PATHS:
            assert path not in text, (path, text)
    for path in ("graphs/ops_publish.yaml", "contracts/ops_publish.yaml"):
        raw = (ROOT / path).read_text(encoding="utf-8")
        assert "\u2014" not in raw and "\u2013" not in raw, path
        for machine in MACHINE_PATHS:
            assert machine not in raw, (path, machine)


def test_contract_report_headings():
    contract = yaml.safe_load((ROOT / "contracts" / "ops_publish.yaml").read_text(encoding="utf-8"))
    assert contract["publish_report"]["produces"]["report.md"]["headings"] == HEADINGS
    assert set(contract) == set(STEPS)


# ---------------------------------------------------------------- the fixtures

def test_fixture_tars_are_packed_the_same_way_every_time():
    clean = MAKER.pack_files(clean_files())
    assert clean == MAKER.pack_files(clean_files())
    assert clean == (FIX / "clean" / "repo.tar").read_bytes()
    assert MAKER.pack_files(MAKER.seeded()) == (FIX / "seeded" / "repo.tar").read_bytes()
    with tarfile.open(fileobj=io.BytesIO(clean)) as tf:
        members = tf.getmembers()
    assert [m.name for m in members] == sorted(m.name for m in members)
    assert all(m.mtime == 0 and m.mode == 0o644 and m.uid == 0 and m.uname == "" for m in members)
    assert clean[257:263] == b"ustar\x00"


def test_fixture_settings_and_truth_are_written_from_the_maker():
    for name in ("clean", "seeded"):
        assert (FIX / name / "publish_check.yaml").read_text(encoding="utf-8") == MAKER.SETTINGS
    assert (FIX / "seeded" / "truth.yaml").read_text(encoding="utf-8") == MAKER.TRUTH
    assert not (FIX / "clean" / "truth.yaml").exists()


def test_the_clean_fixture_is_synthetic():
    files = clean_files()
    text = b"\n".join(files.values()).decode("utf-8", "replace")
    for path in MACHINE_PATHS:
        assert path not in text
    assert "Jordan" not in text and "@university" not in text
    manifest = json.loads(files[MAKER.MANIFEST])
    assert manifest["counts"]["builds.paper.sha256"] == hashlib.sha256(
        files["project/builds/paper/v002.docx"]).hexdigest()


# ---------------------------------------------------------------- settings

def test_clean_settings_are_valid_with_every_field(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    s = read(run, "settings.json")
    assert set(s) == set(SETTINGS_FIELDS)
    assert s["valid"] is True and s["task"] == TITLE
    assert (s["workflow_root"], s["terms"], s["allow"]) == ("/scholar/workflow", ["Jordan Doe"], [])
    assert (s["max_file_mb"], s["warn_file_mb"], s["rebuild"]) == (100, 50, False)
    assert s["excluded_folders"] == ["/scholar/private_records"]


def test_defaults_fill_an_empty_settings_file(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, raw_settings="workflow_root: /scholar/workflow\n"))
    s = read(run, "settings.json")
    assert (s["terms"], s["allow"], s["excluded_folders"]) == ([], [], [])
    assert (s["max_file_mb"], s["warn_file_mb"], s["rebuild"]) == (100, 50, True)
    assert findings(run, check="publish_settings") == []


def test_each_settings_problem_is_blocking(tmp_path):
    cases = [
        ({"workflow_root": "relative/workflow"}, "workflow_root"),
        ({"workflow_root": 3}, "workflow_root"),
        ({"terms": "Jordan Doe"}, "terms"),
        ({"terms": ["Jordan Doe", ""]}, "terms"),
        ({"allow": [{"text": "x", "colour": "blue"}]}, "allow"),
        ({"allow": [{}]}, "allow"),
        ({"allow": [3]}, "allow"),
        ({"allow": [{"path": ""}]}, "allow"),
        ({"max_file_mb": "big"}, "max_file_mb"),
        ({"warn_file_mb": -1}, "warn_file_mb"),
        ({"rebuild": "yes"}, "rebuild"),
        ({"excluded_folders": ["relative/folder"]}, "excluded_folders"),
        ({"excluded_folders": "/scholar/private"}, "excluded_folders"),
        ({"excluded_paths": ["/project/records"]}, "excluded_paths"),
        ({"excluded_paths": ["project/../records"]}, "excluded_paths"),
    ]
    for n, (over, item) in enumerate(cases):
        sub = tmp_path / ("case%d" % n)
        sub.mkdir()
        run = run_on(sub, inputs_with(sub, settings(**over)))
        blocking = findings(run, "blocking")
        assert [(f["check"], f["item"]) for f in blocking] == [("publish_settings", item)], (over, blocking)
        s = read(run, "settings.json")
        assert set(s) == set(SETTINGS_FIELDS) and s["valid"] is False, over
        assert ran(run) == ["publish_settings", "publish_report"], over


def test_a_bad_term_is_named_by_its_place_and_never_shown(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, settings(terms=["Jordan Doe", 7])))
    blocking = findings(run, "blocking")
    assert [f["evidence"] for f in blocking] == ["entry 2 is int"]
    assert "Jordan" not in report(run)


def test_unknown_key_is_a_warning(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, settings(colour="blue")))
    assert [(f["check"], f["item"]) for f in findings(run, "warning")] == [("publish_settings", "colour")]
    assert read(run, "settings.json")["valid"] is True


def test_unreadable_settings_file_is_blocking_and_skips_the_scan(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, raw_settings="- just\n- a list\n"))
    assert [(f["check"], f["item"]) for f in findings(run, "blocking")] == [("publish_settings", "publish_check.yaml")]
    assert "publish_files" in skipped(run)
    text = report(run)
    for heading in ("Files", "Counts", "Rebuild"):
        assert section(text, heading) == "Not run."


def test_an_empty_workflow_folder_turns_the_rebuild_off_with_a_note(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, settings(workflow_root="", rebuild=True)))
    assert read(run, "settings.json")["rebuild"] is False
    assert ("publish_settings", "rebuild") in [(f["check"], f["item"]) for f in findings(run, "info")]
    assert "publish_rebuild" in skipped(run)


# ---------------------------------------------------------------- the clean and seeded runs

def test_clean_fixture_has_no_problem_and_rechecks_every_count(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    assert problems(run) == []
    counts = read(run, "counts.json")
    assert counts["checked"] == len(MAKER.COUNTS)
    assert (counts["differ"], counts["not_rechecked"], counts["generated_changed"]) == (0, 0, 0)
    assert (counts["files_changed"], counts["files_unlisted"], counts["reports_missing"]) == (0, 0, 0)
    want = MAKER.counts_for(clean_files())
    assert collections.OrderedDict((r["key"], r["recount"]) for r in counts["rows"]) == want
    assert all(r["same"] is True for r in counts["rows"])
    scan_out = read(run, "scan.json")
    assert scan_out["files"] == len(clean_files()) and scan_out["office_files"] == 2
    assert (scan_out["blocked"], scan_out["warned"], scan_out["accepted"]) == (0, 0, 0)
    assert ran(run) == ["publish_settings", "publish_files", "publish_counts", "publish_report"]
    assert "publish_rebuild" in skipped(run)
    assert section(report(run), "Rebuild") == "Not run."


def test_seeded_fixture_scores_recall_one(tmp_path):
    run = run_on(tmp_path, FIX / "seeded")
    p = vg("score", "--run", str(run), "--truth", str(FIX / "seeded" / "truth.yaml"))
    assert p.returncode == 0, p.stdout + p.stderr
    result = json.loads((run / "score.json").read_text())
    assert result["recall"] == 1.0 and result["extra_findings"] == []
    assert result["faults"] == 15


def test_seeded_count_changed_with_its_readme_is_caught_only_by_the_recount(tmp_path):
    run = run_on(tmp_path, FIX / "seeded")
    readme = [f for f in findings(run) if f["item"] == "README.md"]
    assert readme == []
    rows = {r["key"]: r for r in read(run, "counts.json")["rows"]}
    assert (rows["prose.changes"]["manifest"], rows["prose.changes"]["recount"]) == (8, 7)
    assert (rows["citations.ai"]["manifest"], rows["citations.ai"]["recount"]) == (6, 5)


def test_verify_reports_replay_matches(tmp_path):
    for name in ("clean", "seeded"):
        sub = tmp_path / name
        sub.mkdir()
        run = run_on(sub, FIX / name)
        p = vg("verify", "--run", str(run))
        assert p.returncode == 0, p.stdout + p.stderr
        lines = p.stdout.strip().splitlines()
        assert lines and all(line.endswith("replay matches") for line in lines), p.stdout


# ---------------------------------------------------------------- the file scan

def test_names_and_folders_that_must_not_be_published(tmp_path):
    extra = {name: b"This is not a real secret.\n" for name in (
        "project/.git/HEAD", "project/.homes/audit/settings.yaml", "project/store.sqlite", "project/a.db",
        "project/.ENV.local", "project/server.pem", "project/id_rsa.pub", "project/.netrc",
        "project/.git-credentials", "project/.pypirc", "project/Credentials.json", "project/my_secret.txt",
        "project/token", "project/github.token", "project/token.json", "project/oauth_access_token.txt",
        "project/my_api_key.txt", "project/apikey", "project/sources/a.txt", "project/notes/n.md")}
    extra["project/tokenizer.py"] = b"print('words')\n"
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted(n for n in extra if n != "project/tokenizer.py")
    assert all(f["evidence"] == f["item"] for f in found if f["severity"] == "blocking")


def test_editor_and_history_files_are_warnings(tmp_path):
    extra = {"project/.vscode/settings.json": b"{}\n", "project/__pycache__/x.cpython-39.pyc": b"\x00\x01",
             "project/.bash_history": b"ls\n", "project/.Rhistory": b"x <- 1\n"}
    found = scan(tmp_path, extra)
    assert pairs(f for f in found if f["severity"] != "info") == [("warning", n) for n in sorted(extra)]


def test_a_run_folder_blocks_at_the_top_and_warns_inside_a_tar(tmp_path):
    run_folder = {"manifest.json": b"{}\n", "trail.jsonl": b"{}\n"}
    extra = {"project/runs/r1/" + n: d for n, d in run_folder.items()}
    extra["project/inputs.tar"] = MAKER.pack_files(dict(("runs/r2/" + n, d) for n, d in run_folder.items()))
    found = scan(tmp_path, extra)
    assert pairs(f for f in found if f["severity"] != "info") == [
        ("blocking", "project/runs/r1"), ("warning", "project/inputs.tar:runs/r2")]


def test_tar_members_are_scanned_and_nested_or_compressed_archives_block(tmp_path):
    inner = {"notes/home.txt": b"Saved in /Users/jdoe/Documents.\n", "fixtures/project.tar": MAKER.pack_files({}),
             "data.zip": b"PK\x05\x06" + b"\x00" * 18, "keys/id_ed25519": b"not a key\n",
             "audit/session_writes.jsonl": b"{}\n", "project/audit/x.jsonl": b"{}\n", "fine.txt": b"fine\n"}
    extra = {"project/archive.tar": MAKER.pack_files(inner), "project/data.tar.gz": b"\x1f\x8b\x08\x00",
             "project/broken.tar": b"this is not a tar"}
    found = scan(tmp_path, extra)
    assert pairs(f for f in found if f["severity"] != "info") == sorted([
        ("blocking", "project/archive.tar:notes/home.txt"),
        ("blocking", "project/archive.tar:fixtures/project.tar"),
        ("blocking", "project/archive.tar:data.zip"),
        ("blocking", "project/archive.tar:keys/id_ed25519"),
        ("warning", "project/archive.tar:project/audit/x.jsonl"),
        ("blocking", "project/data.tar.gz"),
        ("blocking", "project/broken.tar"),
    ])


def test_size_limits_block_and_warn(tmp_path):
    extra = {"project/big.txt": b"x" * 400000, "project/mid.txt": b"x" * 200000}
    assert max(len(d) for d in clean_files().values()) < 100000
    found = scan(tmp_path, extra, max_file_mb=0.3, warn_file_mb=0.15)
    assert pairs(f for f in found if f["severity"] != "info") == [
        ("blocking", "project/big.txt"), ("warning", "project/mid.txt")]


def test_email_forms(tmp_path):
    allowed = b"a@example.com b@cluster.example.edu c@host.invalid d@x.test e@y.localhost f@z.example icon@2x.png"
    extra = {"project/ok.md": allowed,
             "project/at.md": b"Write to jdoe@university.edu.",
             "project/url.md": b"?mailto=jdoe%40uni.edu&x=1",
             "project/entity.html": b"jdoe&#64;uni.edu",
             "project/hex.html": b"jdoe&#x40;uni.edu"}
    found = scan(tmp_path, extra)
    assert blocked(found) == ["project/at.md", "project/entity.html", "project/hex.html", "project/url.md"]


def test_home_and_temporary_folder_forms(tmp_path):
    hits = ['"/Users/jdoe"', "cd /Users/jdoe && make", "/private/tmp/claude-504/-Users-jdoe-x/y",
            "~/.claude/projects/-Users-jdoe-p/x.jsonl", r"C:\\Users\\jdoe\\x", r"C:\Users\jdoe", "D:/Users/jdoe",
            "file = {:Users/jdoe/Documents/Mendeley Desktop/x.pdf:pdf}", "%2FUsers%2Fjdoe", "/home/jdoe/data",
            "/var/folders/ab/xyz/T/x", "/private/var/folders/ab/xyz"]
    misses = ["/Users/Shared/data", "/Users/<name>/x", "/Users/$USER/x", r"C:\Users\Public\x", "/home/<x>/",
              "https://example.com/home/page", "the Users/ folder"]
    extra = {"project/hit%02d.txt" % n: text.encode("utf-8") for n, text in enumerate(hits)}
    extra.update({"project/miss%02d.txt" % n: text.encode("utf-8") for n, text in enumerate(misses)})
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted("project/hit%02d.txt" % n for n in range(len(hits)))
    assert ("warning", "project/hit03.txt") in pairs(found)  # the tilde form warns too


def test_other_tilde_paths_are_warnings(tmp_path):
    found = scan(tmp_path, {"project/a.md": b"The settings live in ~/.config/tool/settings.yaml.\n",
                            "project/b.md": b"See https://example.org/~/x and a~/b.\n"})
    assert pairs(f for f in found if f["severity"] != "info") == [("warning", "project/a.md")]


def test_key_forms_are_blocking_and_never_shown(tmp_path):
    keys = ["sk-ant-api03-abc1defghijklmnopqrstu", "-----BEGIN RSA PRIVATE KEY-----",
            "-----BEGIN PGP PRIVATE KEY BLOCK-----", "ghp_" + "a1" * 18, "gho_" + "b2" * 18,
            "github_pat_" + "c3" * 11, "hf_" + "d4" * 15, "glpat-" + "e5" * 10, "sk_live_" + "f6" * 10,
            "https://hooks.slack.com/services/T000/B000/XXXX", "AKIA" + "ABCDEFGH12345678", "AIza" + "g7" * 17 + "h"]
    extra = {"project/k%02d.txt" % n: key.encode("utf-8") for n, key in enumerate(keys)}
    extra["project/prose.md"] = b"a task-specific-instruction-template and risk-adjusted-return-on-capital\n"
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted(extra)[:-1]
    for f in found:
        for key in keys:
            assert key[6:] not in f["evidence"]
    assert all(re.search(r"\(\d+ characters, sha256 [0-9a-f]{12}\)$", f["evidence"])
               for f in found if f["severity"] == "blocking")


def test_a_long_secret_assignment_is_a_warning(tmp_path):
    found = scan(tmp_path, {"project/conf.py": b"password = 'correct-horse-battery-staple'\n",
                            "project/short.py": b"token: abc\n"})
    assert pairs(f for f in found if f["severity"] != "info") == [("warning", "project/conf.py")]
    assert "staple" not in found[0]["evidence"]


def test_terms_match_across_spaces_and_underscores_but_not_inside_words(tmp_path):
    extra = {"project/a.md": b"Thanks to Jordan\n  Doe.", "project/b.md": b"see jordan doe_notes.md",
             "project/c.md": b"JORDAN DOE (2020)", "project/d.md": b"Jordan Doering and xJordan Doe",
             "project/e.html": b"Jordan&nbsp;Doe", "project/jordan_doe_cv.txt": b"a cv\n"}
    found = scan(tmp_path, extra)
    # The manifest lists the file named for the scholar, so it names the scholar too.
    assert blocked(found) == ["docs/publish_manifest.json", "project/a.md", "project/b.md", "project/c.md",
                              "project/e.html", "project/jordan_doe_cv.txt"]
    assert all("Jordan" not in f["evidence"] for f in found)
    assert [f["evidence"] for f in found if f["item"] == "project/a.md"] == ["term 1"]


def test_word_files_are_scanned_part_by_part(tmp_path):
    split_runs = MAKER.office({
        "word/document.xml": '<w:document %s><w:body><w:p><w:r><w:t>Jordan</w:t></w:r><w:r><w:t xml:space="preserve">'
                             ' Doe</w:t></w:r></w:p></w:body></w:document>' % MAKER.W})
    tracked = MAKER.office({
        "word/document.xml": '<w:document %s><w:body><w:p><w:ins w:id="1" w:author="A. Person"><w:r><w:t>x</w:t>'
                             '</w:r></w:ins></w:p></w:body></w:document>' % MAKER.W})
    props = MAKER.office({
        "docProps/app.xml": "<Properties><Company>A University</Company></Properties>",
        "docProps/custom.xml": '<Properties><property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" '
                               'name="affiliation"><vt:lpwstr>A lab</vt:lpwstr></property></Properties>'})
    people = MAKER.office({"word/people.xml": '<w15:people><w15:person w15:author="A. Person"/></w15:people>'})
    links = MAKER.office({"word/_rels/document.xml.rels": '<Relationships><Relationship Target='
                                                         '"mailto:jdoe@uni.edu"/></Relationships>'})
    extra = {"project/split.docx": split_runs, "project/tracked.docx": tracked, "project/props.docx": props,
             "project/people.docx": people, "project/links.docx": links,
             "project/creator.docx": MAKER.word("Text.", creator="A. Person"),
             "project/comment.docx": MAKER.word("Text.", comment=True),
             "project/broken.docx": b"not a zip"}
    found = scan(tmp_path, extra)
    assert pairs(f for f in found if f["severity"] != "info") == sorted([
        ("blocking", "project/broken.docx"), ("blocking", "project/creator.docx"),
        ("blocking", "project/links.docx"), ("blocking", "project/people.docx"),
        ("blocking", "project/props.docx"), ("blocking", "project/split.docx"),
        ("blocking", "project/tracked.docx"), ("warning", "project/comment.docx")])
    assert [f["evidence"] for f in found if f["item"] == "project/props.docx" and f["severity"] == "blocking"] == [
        "docProps/app.xml: Company"]
    infos = [f for f in found if f["item"] == "project/props.docx" and f["severity"] == "info"]
    # the custom property is one note, and the {GUID} of a custom property is not a UUID finding
    assert [f["evidence"] for f in infos] == ["custom property: affiliation"]


CUSTOM_NOTE = ("The Office file has custom properties, which are published with it. Their values are scanned like "
               "its other parts, and only a problem found in them blocks.")


def with_custom(properties, text="Text."):
    """A small Word file with a docProps/custom.xml part holding the given (name, value)
    pairs, written the way pandoc writes its options into a Word build."""
    book = zipfile.ZipFile(io.BytesIO(MAKER.word(text)))
    parts = dict((name, book.read(name).decode("utf-8")) for name in book.namelist())
    rows = "".join('<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="%d" name="%s"><vt:lpwstr>%s'
                   '</vt:lpwstr></property>' % (pid, name, value)
                   for pid, (name, value) in enumerate(properties, 2))
    parts["docProps/custom.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?><Properties '
        'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">' + rows + '</Properties>')
    return MAKER.office(parts)


def test_pandoc_custom_properties_alone_are_one_note(tmp_path):
    extra = {"project/builds/paper/v003.docx": with_custom([("bibliography", "refs.bib"),
                                                            ("csl", "styles/apa.csl")]),
             "project/builds/paper/v004.docx": with_custom([("bibliography", "refs.bib")])}
    found = scan(tmp_path, extra)
    mine = [(f["severity"], f["item"], f["message"], f["evidence"]) for f in found if f["item"] in extra]
    assert sorted(mine) == [
        ("info", "project/builds/paper/v003.docx", CUSTOM_NOTE, "custom properties: bibliography, csl"),
        ("info", "project/builds/paper/v004.docx", CUSTOM_NOTE, "custom property: bibliography")]
    assert blocked(found) == []


def test_a_custom_property_value_is_scanned_like_every_other_part(tmp_path):
    extra = {"project/builds/paper/term.docx": with_custom([("bibliography", "refs.bib"),
                                                            ("subtitle", "Notes by Jordan Doe")]),
             "project/builds/paper/email.docx": with_custom([("bibliography", "refs.bib"),
                                                             ("contact", "jdoe@uni.edu")]),
             "project/builds/paper/home.docx": with_custom([("bibliography", "/Users/jdoe/refs.bib")]),
             "project/builds/paper/named.docx": with_custom([("Jordan Doe", "x")])}
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted(extra)
    shown = dict((item, sorted((f["severity"], f["evidence"]) for f in found if f["item"] == item)) for item in extra)
    assert shown["project/builds/paper/term.docx"] == [
        ("blocking", "docProps/custom.xml: term 1"), ("info", "custom properties: bibliography, subtitle")]
    assert shown["project/builds/paper/email.docx"] == [
        ("blocking", "docProps/custom.xml: jdoe@uni.edu"), ("info", "custom properties: bibliography, contact")]
    assert ("blocking", "docProps/custom.xml: /Users/jdoe") in shown["project/builds/paper/home.docx"]
    assert shown["project/builds/paper/named.docx"] == [
        ("blocking", "docProps/custom.xml: term 1"), ("info", "custom property: term 1")]
    assert all("Jordan" not in f["evidence"] for f in found)
    # the allow entry that once accepted pandoc's option does not accept a problem in its value
    allow = [{"path": "project/builds/*/v*.docx", "text": "docProps/custom.xml: bibliography"},
             {"path": "project/builds/*.docx", "text": "custom properties: bibliography, subtitle"}]
    found = scan(tmp_path, {"project/builds/paper/v009.docx": extra["project/builds/paper/term.docx"]},
                 name="allowed", allow=allow)
    assert blocked(found) == ["project/builds/paper/v009.docx"]


def test_an_empty_comments_part_gives_no_warning(tmp_path):
    found = scan(tmp_path, {"project/plain.docx": MAKER.word("Text.")})
    assert [f for f in found if f["item"] == "project/plain.docx"] == []


def test_a_raw_id_of_an_indexed_session_blocks_and_other_uuids_are_one_note(tmp_path):
    other = "0f8fad5b-d9cb-469f-a165-70867728950e"
    extra = {"project/log.txt": ("ran %s/agent-a1b2c3\n" % MAKER.RAW_SESSION).encode("utf-8"),
             "project/upper.txt": MAKER.RAW_SESSION.upper().encode("utf-8"),
             "project/ids.txt": ("%s and %s and %s\n" % (other, other.replace("0f", "1f"), other)).encode("utf-8"),
             "project/transcript.md": b"Found in ~/.claude/projects/x/y.jsonl\n"}
    found = scan(tmp_path, extra)
    assert blocked(found) == ["project/log.txt", "project/transcript.md", "project/upper.txt"]
    notes = [f for f in found if f["item"] == "project/ids.txt"]
    assert [(f["severity"], f["message"]) for f in notes] == [
        ("info", "The text holds 3 UUIDs that name no indexed session, which may still be raw ids of other sessions.")]
    raw = [f for f in found if f["item"] == "project/log.txt" and f["severity"] == "blocking"]
    assert raw[0]["evidence"] == "raw id of " + MAKER.SESSION_IDS[0]


def test_an_excluded_folder_blocks_in_any_spelling(tmp_path):
    home = os.path.expanduser("~")
    folder = os.path.join(home, "Records_Private")
    spelled = {"project/abs.md": folder + "/grades.csv", "project/tilde.md": "~/Records_Private/grades.csv",
               "project/case.md": folder.upper() + "/x",
               "project/encoded.md": re.sub(r"[^A-Za-z0-9]", "-", folder) + "-sub/x",
               "project/other.md": folder + "_old/x"}
    found = scan(tmp_path, {k: v.encode("utf-8") for k, v in spelled.items()}, excluded_folders=[folder])
    excluded = sorted(set(f["item"] for f in found if "folder the settings exclude" in f["message"]))
    assert excluded == ["project/abs.md", "project/case.md", "project/encoded.md", "project/tilde.md"]


def test_base_url_hosts(tmp_path):
    extra = {"project/a.yaml": b"base_url: https://models.example.edu/v1\n",
             "project/b.yaml": b"base_url: https://api.provider.com/v1\n",
             "project/c.yaml": b'{"base_url": "http://%s/v1"}\n',
             "project/d.yaml": b"base_url: https://{host}/v1\n",
             "project/e.py": b"base_url: str = ''\n",
             "project/f.yaml": b"base_url: http://localhost:8000/v1\n",
             "project/g.yaml": b"base_url: http://gpu-box:8000/v1\n"}
    found = scan(tmp_path, extra)
    assert pairs(f for f in found if f["severity"] != "info") == [("warning", "project/b.yaml"),
                                                                ("warning", "project/g.yaml")]


def test_notebook_outputs_warn(tmp_path):
    with_out = json.dumps({"cells": [{"cell_type": "code", "outputs": [{"text": "4.2"}]}]}).encode("utf-8")
    without = json.dumps({"cells": [{"cell_type": "code", "outputs": []}]}).encode("utf-8")
    found = scan(tmp_path, {"project/a.ipynb": with_out, "project/b.ipynb": without})
    assert pairs(f for f in found if f["severity"] != "info") == [("warning", "project/a.ipynb")]


def test_text_in_other_encodings_is_scanned(tmp_path):
    extra = {"project/latin.bib": "file = {/Users/jdoe/Papers/M\u00fcller.pdf}".encode("latin-1"),
             "project/wide.csv": "name,email\nx,jdoe@uni.edu\n".encode("utf-16")}
    found = scan(tmp_path, extra)
    assert blocked(found) == ["project/latin.bib", "project/wide.csv"]


def png(*chunks):
    """A one-pixel PNG with the given (kind, data) chunks before its image data."""
    import struct

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib_crc(kind + data))
    body = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    for kind, data in chunks:
        body += chunk(kind, data)
    return b"\x89PNG\r\n\x1a\n" + body + chunk(b"IDAT", zlib_compress(b"\x00\x00")) + chunk(b"IEND", b"")


def zlib_crc(data):
    import zlib
    return zlib.crc32(data) & 0xffffffff


def zlib_compress(data):
    import zlib
    return zlib.compress(data)


def test_images_and_pdfs_have_their_text_and_metadata_scanned(tmp_path):
    pdf_info = (b"%PDF-1.4\n1 0 obj << /Author (Jordan Doe) /Creator (/Users/jdoepdf/Library/x) >> endobj\n"
                b"trailer << /Info 1 0 R >>\n%%EOF\n")
    packed = zlib_compress(b"BT (Write to jdoe.flate@uni.edu) Tj ET")
    pdf_stream = b"%PDF-1.4\n2 0 obj << /Filter /FlateDecode >> stream\n" + packed + b"\nendstream\nendobj\n%%EOF\n"
    pdf_wide = b"%PDF-1.4\n1 0 obj << /Author (\xfe\xff" + "Jordan Doe".encode("utf-16-be") + b") >> endobj\n%%EOF\n"
    extra = {"project/fig.png": png(),
             "project/meta.png": png((b"tEXt", b"Author\x00jdoe.png@uni.edu")),
             "project/packed.png": png((b"zTXt", b"Comment\x00\x00" + zlib_compress(b"/home/jdoepng/x"))),
             "project/info.pdf": pdf_info, "project/stream.pdf": pdf_stream, "project/wide.pdf": pdf_wide,
             "project/roster.png": b"student,email\nJane Roe,jroe@uni.edu\n",
             "project/paper.pdf": b"%PDF-1.4\nnothing here\n%%EOF\n"}
    found = scan(tmp_path, extra)
    assert blocked(found) == ["project/info.pdf", "project/meta.png", "project/packed.png", "project/roster.png",
                              "project/stream.pdf", "project/wide.pdf"]
    notes = sorted(f["item"] for f in found if f["severity"] == "info" and "what it shows" in f["message"])
    # Each real image or PDF gets the note that what it shows is not scanned; text named
    # like an image is read as text.
    assert notes == sorted(n for n in extra if n != "project/roster.png")


def test_allow_entries_turn_findings_into_notes(tmp_path):
    extra = {"project/styles/a.csl": b"<email>editor@styles.org</email>",
             "project/other.md": b"editor@styles.org",
             "project/byline.md": b"By Jordan Doe.",
             "project/vendor.tar": MAKER.pack_files({"docs/x.md": b"/Users/someone/x", "id_rsa": b"x"}),
             "project/keyed.txt": b"sk-test-0123456789abcdefghij"}
    key_evidence = None
    allow = [{"path": "project/styles/*.csl"}, {"text": "Jordan Doe", "path": "project/byline.md"},
             {"path": "project/vendor.tar:*"}]
    found = scan(tmp_path, extra, name="first", allow=allow)
    assert blocked(found) == ["project/keyed.txt", "project/other.md"]
    accepted = sorted(f["item"] for f in found if f["message"].startswith("Accepted by the settings. "))
    assert accepted == ["project/byline.md", "project/styles/a.csl", "project/vendor.tar:docs/x.md",
                        "project/vendor.tar:id_rsa"]
    assert all(f["severity"] == "info" for f in found if f["item"] in accepted)
    key_evidence = [f["evidence"] for f in found if f["item"] == "project/keyed.txt"][0]
    found = scan(tmp_path, extra, name="second", allow=allow + [key_evidence, "editor@styles.org"])
    assert blocked(found) == []


def test_symbolic_links_in_the_tar_are_warnings(tmp_path):
    buf = io.BytesIO()
    files = MAKER.finish(MAKER.repository())
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size = len(files[name])
            tf.addfile(info, io.BytesIO(files[name]))
        link = tarfile.TarInfo("project/link.md")
        link.type, link.linkname = tarfile.SYMTYPE, "manuscript.md"
        tf.addfile(link)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "publish_check.yaml").write_text(MAKER.SETTINGS, encoding="utf-8")
    (inputs / "repo.tar").write_bytes(buf.getvalue())
    run = run_on(tmp_path, inputs)
    assert pairs(problems(run, "publish_files")) == [("warning", "project/link.md")]


def test_home_paths_below_a_drive_a_volume_or_a_cluster_folder_and_in_file_urls(tmp_path):
    hits = ["/mnt/c/Users/jdoewsl/Documents/thesis/data.csv", "cd /c/Users/jdoegb/Documents/thesis",
            "/cygdrive/c/Users/jdoecyg/x", "/Volumes/Macintosh HD/Users/jdoevol/Desktop/x.txt",
            "/System/Volumes/Data/Users/jdoesys/x", "/gpfs/home/jdoehpc/project/run.sh",
            "<url>file://localhost/Users/jdoeurl/Documents/thesis.docx</url>", "file:///Users/jdoefile/x",
            r"\\fileserver\home$\jdoeunc\thesis\data.csv", "backup/Users/jdoebak/Documents/file.txt"]
    misses = ["https://example.com/home/page", "https://github.com/x/Users/y", "the Users/ folder"]
    extra = {"project/hit%02d.txt" % n: text.encode("utf-8") for n, text in enumerate(hits)}
    extra.update({"project/miss%02d.txt" % n: text.encode("utf-8") for n, text in enumerate(misses)})
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted("project/hit%02d.txt" % n for n in range(len(hits)))


def test_escaped_and_encoded_home_paths(tmp_path):
    bdsk = base64_text(b"bplist00 relativePath ../Papers/x.pdf alias /Users/jdoebib/Papers/x.pdf")
    extra = {"project/a.json": b'{"path": "\\/Users\\/jdoejson\\/Documents\\/x.csv"}\n',
             "project/b.json": b'{"p": "\\u002fUsers\\u002fjdoeuni\\u002fx"}\n',
             "project/c.html": b"<p>&#47;Users&#47;jdoeent&#47;notes.txt</p>\n",
             "project/d.txt": b"-users-jdoelow-documents-x\n",
             "project/e.txt": b"_Users_jdoeund_Documents_x\n",
             "project/f.bib": ("@article{a, Bdsk-File-1 = {%s}}\n" % bdsk).encode("utf-8"),
             "project/g.bib": b"@article{a, file = {:C\\:\\\\Users\\\\jdoejab\\\\Documents\\\\paper.pdf:PDF}}\n",
             "project/h.json": b'{"p": "C:\\\\Users\\\\jdoewin\\\\Documents\\\\x.csv"}\n',
             "project/ok.md": b"for-users-of-the-tool and _users_list_ = []\n"}
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted(n for n in extra if n != "project/ok.md")


def base64_text(data):
    import base64
    return base64.b64encode(data).decode("ascii")


def test_text_without_a_byte_order_mark_in_utf_16_is_scanned(tmp_path):
    extra = {"project/le.txt": "Contact jdoe.utf16@uni.edu at /Users/jdoeutf/".encode("utf-16-le"),
             "project/be.txt": "Contact jdoe.utf16@uni.edu".encode("utf-16-be")}
    found = scan(tmp_path, extra)
    assert blocked(found) == ["project/be.txt", "project/le.txt"]


def test_names_written_another_way_are_found(tmp_path):
    name = "Zo\u00eb Bront\u00eb"
    nfd = unicodedata.normalize("NFD", name)
    extra = {"project/nfd.md": ("Written by %s." % nfd).encode("utf-8"),
             "project/escaped.json": json.dumps({"author": name}).encode("utf-8"),
             "project/latin1.txt": ("Written by %s." % name).encode("latin-1"),
             ("project/%s_cv.md" % nfd.replace(" ", "_")): b"cv\n",
             "project/joined.md": ("handle %s." % name.replace(" ", "")).encode("utf-8"),
             "project/plain.md": b"Zoe and Bronte, unrelated words.\n"}
    found = scan(tmp_path, extra, terms=[name])
    assert sorted(set(blocked(found)) - {"docs/publish_manifest.json"}) == sorted(
        n for n in extra if n != "project/plain.md")
    assert all("Zo" not in f["evidence"] for f in found)


def test_compressed_files_are_found_by_their_first_bytes(tmp_path):
    import bz2
    import gzip
    import lzma
    private = b"jdoe.arch@uni.edu,Jordan Doe\n"
    extra = {"project/model.rds": gzip.compress(private), "project/.RData": gzip.compress(b"RDX3\n" + private),
             "project/figure.svgz": gzip.compress(b"<svg/>"), "project/data.tbz": bz2.compress(private),
             "project/data.txz": lzma.compress(private), "project/data.tar.lzma": lzma.compress(
                 private, format=lzma.FORMAT_ALONE),
             "project/data.tar.zst": b"\x28\xb5\x2f\xfd" + private, "project/bundle.bin": b"7z\xbc\xaf\x27\x1c" + private,
             "project/store.cache": b"SQLite format 3\x00" + private,
             "project/k01.sqlite3": b"x", "project/k02.sqlite-wal": b"x", "project/k03.duckdb": b"x"}
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted(extra)


def test_office_files_of_every_kind_and_older_ones(tmp_path):
    core = ('<cp:coreProperties xmlns:cp="x" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>A. Person'
            '</dc:creator></cp:coreProperties>')
    odf = {"mimetype": "application/vnd.oasis.opendocument.text",
           "meta.xml": "<office:meta><meta:initial-creator>A. Person</meta:initial-creator></office:meta>",
           "content.xml": "<office:text><text:p>Plain text.</text:p></office:text>"}
    extra = {"project/macro.docm": MAKER.office({"docProps/core.xml": core}),
             "project/template.dotx": MAKER.office({"docProps/core.xml": core}),
             "project/sheet.xlsm": MAKER.office({"docProps/core.xml": core}),
             "project/thesis.odt": MAKER.office(odf),
             "project/odt_text.odt": MAKER.office({"mimetype": "application/vnd.oasis.opendocument.text",
                                                   "content.xml": "<text:p>jdoe.odt@uni.edu</text:p>"}),
             "project/prefix.docx": MAKER.office({"docProps/core.xml": '<cp:coreProperties xmlns:cp="x" '
                                                  'xmlns:dcx="http://purl.org/dc/elements/1.1/"><dcx:creator>'
                                                  'A. Person</dcx:creator></cp:coreProperties>'}),
             "project/old.doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
             "project/renamed.docx": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
             "project/plain.odt": MAKER.office({"mimetype": "application/vnd.oasis.opendocument.text",
                                                "content.xml": "<text:p>Plain text.</text:p>"})}
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted(n for n in extra if n != "project/plain.odt")


def package(parts):
    """A zip of the given {part: text or bytes}, written the way MAKER.office writes one."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name in sorted(parts):
            data = parts[name]
            z.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)),
                       data if isinstance(data, bytes) else data.encode("utf-8"))
    return buf.getvalue()


def test_parts_inside_an_office_file_are_scanned_or_block(tmp_path):
    inner = package({"docProps/core.xml": '<cp:coreProperties xmlns:dc="x"><dc:creator>A. Person</dc:creator>'
                                               '</cp:coreProperties>'})
    extra = {"project/chart.docx": package({"word/embeddings/Microsoft_Excel_Worksheet.xlsx": inner}),
             "project/notes.docx": package({"word/embeddings/notes.txt": "jdoe.txtpart@uni.edu"}),
             "project/object.docx": package({"word/embeddings/oleObject1.bin":
                                             b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32}),
             "project/zipped.docx": package({"word/embeddings/bundle.zip": package({"a.txt": b"x"})}),
             "project/picture.docx": package({"word/media/image1.png": png()})}
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted(n for n in extra if n != "project/picture.docx")
    assert [f["evidence"] for f in found if f["item"] == "project/chart.docx" and f["severity"] == "blocking"] == [
        "word/embeddings/Microsoft_Excel_Worksheet.xlsx: docProps/core.xml: dc:creator"]
    assert [(f["severity"], f["evidence"]) for f in found if f["item"] == "project/picture.docx"] == [
        ("info", "1 image")]


def test_text_split_across_runs_is_read_joined(tmp_path):
    def paragraph(*runs):
        return "".join("<w:r><w:t xml:space=\"preserve\">%s</w:t></w:r>" % run for run in runs)
    def word_file(*runs):
        return MAKER.office({"word/document.xml": "<w:document %s><w:body><w:p>%s</w:p></w:body></w:document>"
                                                  % (MAKER.W, paragraph(*runs))})
    extra = {"project/email.docx": word_file("Write to jdoe.split@", "uni.edu today."),
             "project/path.docx": word_file("Files in /Users/", "jdoesplit/Documents/x"),
             "project/key.docx": word_file("key: sk-ant-api03-AbCdEf123456", "7890AbCdEf1234567890AbCdEf"),
             "project/slide.pptx": MAKER.office({"ppt/slides/slide1.xml": "<p:sld><a:p><a:r><a:t>jdoe.slide@</a:t>"
                                                 "</a:r><a:r><a:t>uni.edu</a:t></a:r></a:p></p:sld>"}),
             "project/cells.xlsx": MAKER.office({"xl/sharedStrings.xml": "<sst><si><r><t>Jor</t></r><r><t>dan D"
                                                 "</t></r><r><t>oe</t></r></si></sst>"}),
             "project/two.docx": word_file("refs.bib"), "project/apart.xlsx": MAKER.office({
                 "xl/sharedStrings.xml": "<sst><si><t>Jordan</t></si><si><t>Doering</t></si></sst>"})}
    found = scan(tmp_path, extra)
    assert blocked(found) == ["project/cells.xlsx", "project/email.docx", "project/key.docx", "project/path.docx",
                              "project/slide.pptx"]


def test_every_tracked_change_author_and_every_person_list_is_found(tmp_path):
    document = ('<w:document %s><w:body><w:p><w:pPr><w:pPrChange w:id="1" w:author="A. Person"/></w:pPr>'
                '<w:r><w:rPr><w:rPrChange w:id="2" w:author="A. Person"><w:rPr/></w:rPrChange></w:rPr>'
                '<w:t>x</w:t></w:r></w:p></w:body></w:document>' % MAKER.W)
    extra = {"project/format.docx": MAKER.office({"word/document.xml": document}),
             "project/section.docx": MAKER.office({"word/document.xml": '<w:document %s><w:body><w:sectPr>'
                                                   '<w:sectPrChange w:id="4" w:author="A. Person"/></w:sectPr>'
                                                   '</w:body></w:document>' % MAKER.W}),
             "project/persons.xlsx": MAKER.office({"xl/persons/person.xml": '<personList><person displayName='
                                                   '"A. Person" id="{1}" userId="A. Person" providerId="None"/>'
                                                   '</personList>'}),
             "project/blank.docx": MAKER.office({"word/document.xml": '<w:document %s><w:body><w:p><w:ins w:id="1" '
                                                 'w:author=""><w:r><w:t>x</w:t></w:r></w:ins></w:p></w:body>'
                                                 '</w:document>' % MAKER.W})}
    found = scan(tmp_path, extra)
    assert blocked(found) == ["project/format.docx", "project/persons.xlsx", "project/section.docx"]


def tar_with(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for member in members:
            info = tarfile.TarInfo(member["name"])
            info.uname = member.get("uname", "")
            info.gname = member.get("gname", "")
            if member.get("pax"):
                info.pax_headers = member["pax"]
            if member.get("link"):
                info.type, info.linkname = tarfile.SYMTYPE, member["link"]
                archive.addfile(info)
            else:
                data = member.get("data", b"x\n")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_tar_member_headers_are_scanned(tmp_path):
    extra = {"project/link.tar": tar_with([{"name": "data/roster.csv", "link": "/Users/jdoelink/Documents/x.csv"}]),
             "project/outside.tar": tar_with([{"name": "data/up.csv", "link": "../../secret.csv"}]),
             "project/owner.tar": tar_with([{"name": "data/a.csv", "uname": "jdoeuname", "gname": "staff"},
                                            {"name": "data/b.csv", "uname": "jdoeuname", "gname": "staff"}]),
             "project/pax.tar": tar_with([{"name": "data/meta.csv", "pax": {"comment": "jdoe.pax@uni.edu"}}]),
             "project/inside.tar": tar_with([{"name": "data/a.csv"}, {"name": "data/b.csv", "link": "a.csv"}]),
             "project/root.tar": tar_with([{"name": "data/a.csv", "uname": "root", "gname": "wheel"}])}
    found = scan(tmp_path, extra)
    assert sorted(set(f["item"].split(":")[0] for f in found if f["severity"] == "blocking")) == [
        "project/link.tar", "project/outside.tar", "project/owner.tar", "project/pax.tar"]
    owners = [f for f in found if "login name" in f["message"]]
    assert [(f["item"], f["evidence"]) for f in owners] == [("project/owner.tar:data/a.csv", "uname")]
    assert ("warning", "project/inside.tar:data/b.csv") in pairs(found)


def test_a_file_a_gitignore_in_the_repository_hides_blocks(tmp_path):
    extra = {"project/.gitignore": b"\xef\xbb\xbf*.HTML\nreport.md\n!keep.md\nmy\\ notes/\n",
             "project/sessions/index.html": b"<p>index</p>\n", "project/verification/prose/report.md": b"# r\n",
             "project/my notes/a.md": b"x\n", "project/keep.md": b"kept\n", "project/plain.md": b"plain\n"}
    found = scan(tmp_path, extra)
    hidden = sorted(f["item"] for f in found if f["severity"] == "blocking" and "gitignore" in f["message"]
                    and f["item"] in extra)
    assert hidden == ["project/my notes/a.md", "project/sessions/index.html",
                      "project/verification/prose/report.md"]


def test_a_file_too_large_is_still_scanned_and_a_ssh_address_is_no_email(tmp_path):
    big = b"x," * 200000 + b"\njdoe.over@uni.edu\n"
    allow = [{"path": "project/big.csv", "text": "%d bytes" % len(big)}]
    extra = {"project/big.csv": big, "project/clone.md": b"git clone git@github.com:example-scholar/x.git\n"}
    found = scan(tmp_path, extra, max_file_mb=0.3, warn_file_mb=0.15, allow=allow)
    assert blocked(found) == ["project/big.csv"]
    assert [f["evidence"] for f in found if f["item"] == "project/big.csv" and f["severity"] == "blocking"] == [
        "jdoe.over@uni.edu"]


def test_keys_the_workflow_and_common_services_use(tmp_path):
    keys = ["export WORKFLOW_MODEL_KEY=mr_live_0a1b2c3d4e5f60718293a4b5c6d7e8f9",
            "WORKFLOW_MODEL_KEY='mr_live_1a2b3c4d5e6f70819203a4b5c6d7e8f9' python3 vg.py run x",
            "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
            "pypi-AgEIcHlwaS5vcmcCJGFiY2RlZmdoLTEyMzQtNTY3OC05MGFi",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqZG9lIn0.c2lnbmF0dXJlc2lnbmF0dXJl",
            "npm_" + "a1" * 18, "rk_live_" + "b2" * 10]
    extra = {"project/k%02d.txt" % n: key.encode("utf-8") for n, key in enumerate(keys)}
    extra["project/.envrc"] = b"export X=1\n"
    extra["project/docs.md"] = b"Set WORKFLOW_MODEL_KEY=$KEY, or Bearer <token>.\n"
    found = scan(tmp_path, extra)
    assert blocked(found) == sorted(n for n in extra if n != "project/docs.md")
    for f in found:
        assert "0a1b2c3d" not in f["evidence"] and "wJalr" not in f["evidence"]


def test_folders_named_with_another_case_and_other_ai_tools_are_found(tmp_path):
    extra = {"project/Notes/a.md": b"x\n", "project/Sources/b.txt": b"x\n", "project/Audit/c.jsonl": b"{}\n",
             "project/.specstory/history/chat.md": b"x\n", "project/.aider.chat.history.md": b"x\n",
             "project/.cursor/rules/x.mdc": b"x\n", "project/.Rapp.history": b"x\n",
             "project/x/.GIT/HEAD": b"x\n"}
    found = scan(tmp_path, extra)
    assert pairs(f for f in found if f["severity"] != "info") == sorted([
        ("blocking", "project/Notes/a.md"), ("blocking", "project/Sources/b.txt"), ("blocking", "project/Audit/c.jsonl"),
        ("blocking", "project/.specstory/history/chat.md"), ("blocking", "project/.aider.chat.history.md"),
        ("warning", "project/.cursor/rules/x.mdc"), ("warning", "project/.Rapp.history"),
        ("blocking", "project/x/.GIT/HEAD")])


def test_an_excluded_folder_in_another_unicode_form_and_inside_the_project(tmp_path):
    home = os.path.expanduser("~")
    folder = os.path.join(home, unicodedata.normalize("NFC", "Ense\u00f1anza"))
    nfd = unicodedata.normalize("NFD", folder)
    extra = {"project/nfd.md": (nfd + "/roster.csv").encode("utf-8"),
             (unicodedata.normalize("NFD", "project/Ense\u00f1anza/roster.csv")): b"Jane Roe,B+\n",
             "project/other.md": b"plain\n"}
    found = scan(tmp_path, extra, excluded_folders=[folder],
                 excluded_paths=[unicodedata.normalize("NFC", "project/Ense\u00f1anza")])
    assert sorted(set(blocked(found)) - {"docs/publish_manifest.json"}) == sorted(n for n in extra
                                                                                  if n != "project/other.md")


# ---------------------------------------------------------------- the recount

def counts_run(tmp_path, files, name="case"):
    sub = tmp_path / name
    sub.mkdir()
    return run_on(sub, inputs_with(sub, settings(), files))


def test_a_repository_without_a_manifest_is_blocking(tmp_path):
    run = counts_run(tmp_path, MAKER.repository())
    assert pairs(problems(run, "publish_counts")) == [("blocking", "docs/publish_manifest.json")]
    assert read(run, "counts.json")["rows"] == []


def test_a_manifest_of_another_schema_is_blocking(tmp_path):
    files = clean_files()
    manifest = json.loads(files[MAKER.MANIFEST])
    manifest["schema_version"] = 2
    files[MAKER.MANIFEST] = json.dumps(manifest).encode("utf-8")
    run = counts_run(tmp_path, files)
    found = problems(run, "publish_counts")
    assert pairs(found) == [("blocking", "docs/publish_manifest.json")]
    assert found[0]["evidence"] == "publish-repo 2"


def test_each_changed_count_is_blocking_and_an_unknown_one_a_warning(tmp_path):
    files = MAKER.repository()
    counts = MAKER.counts_for(files)
    counts["data.scripts_ai"] = 3
    counts["build.hardcoding"] = 1
    counts["builds.paper.epoch"] = MAKER.EPOCH + 86400
    counts["sessions.harnesses"] = "Claude Code"
    counts["prose.words"] = 900
    run = counts_run(tmp_path, MAKER.finish(files, counts))
    assert pairs(problems(run, "publish_counts")) == sorted([
        ("blocking", "data.scripts_ai"), ("blocking", "build.hardcoding"), ("blocking", "builds.paper.epoch"),
        ("blocking", "sessions.harnesses"), ("warning", "prose.words")])
    text = section(report(run), "Counts")
    assert "| data.scripts_ai | 3 | 2 |" in text


def test_lists_may_use_either_separator_and_counts_their_text_form(tmp_path):
    files = MAKER.repository()
    counts = MAKER.counts_for(files)
    counts["missing"] = "slides/data; slides/citations"
    counts["sessions.harnesses"] = "ForgeCode; Claude Code"
    counts["prose.changes"] = "7"
    run = counts_run(tmp_path, MAKER.finish(files, counts))
    assert problems(run, "publish_counts") == []


def test_a_count_the_manifest_lacks_is_a_note(tmp_path):
    files = MAKER.repository()
    counts = MAKER.counts_for(files)
    del counts["refs.works"]
    run = counts_run(tmp_path, MAKER.finish(files, counts))
    assert problems(run, "publish_counts") == []
    notes = findings(run, "info", "publish_counts")
    assert [(f["item"], f["evidence"]) for f in notes] == [("counts", "refs.works")]


def test_files_added_changed_or_missing_after_assembly_are_blocking(tmp_path):
    files = clean_files()
    files["project/added.md"] = b"added later\n"
    files["project/params.yaml"] = b"seed: 8\nsample: 100\n"
    del files["project/results.csv"]
    files["docs/results.svg"] = files["docs/results.svg"].replace(b"5 of 7", b"5 of 6")
    run = counts_run(tmp_path, files)
    assert pairs(problems(run, "publish_counts")) == sorted([
        ("blocking", "project/added.md"), ("blocking", "project/params.yaml"), ("blocking", "project/results.csv"),
        ("blocking", "docs/results.svg"), ("blocking", "docs/results.svg")])
    counts = read(run, "counts.json")
    assert (counts["generated_changed"], counts["files_changed"], counts["files_unlisted"]) == (1, 3, 1)


def test_a_report_the_manifest_names_must_be_in_the_repository(tmp_path):
    files = MAKER.repository()
    del files["project/verification/paper/citations/report.md"]
    final = MAKER.finish(files)
    manifest = json.loads(final[MAKER.MANIFEST])
    for r in manifest["reports"]:
        if (r["group"], r["stream"]) == ("paper", "citations"):
            r["report"] = "project/verification/paper/citations/report.md"
    final[MAKER.MANIFEST] = json.dumps(manifest).encode("utf-8")
    run = counts_run(tmp_path, final)
    assert pairs(problems(run, "publish_counts")) == [("blocking", "project/verification/paper/citations/report.md")]


def test_a_published_results_file_must_equal_the_projects(tmp_path):
    files = MAKER.repository()
    path = "project/verification/paper/prose/results.json"
    files[path] = files[path].replace(b'"paper_prose"', b'"paper_prose_other"', 1)
    run = counts_run(tmp_path, MAKER.finish(files))
    assert pairs(problems(run, "publish_counts")) == [("blocking", path)]


def test_the_manifests_latest_build_must_match_the_ledger(tmp_path):
    files = MAKER.repository()
    final = MAKER.finish(files)
    manifest = json.loads(final[MAKER.MANIFEST])
    manifest["products"][0]["latest"]["epoch"] += 86400
    manifest["products"][1]["latest"] = {"version": "v001", "date": "2026-10-15", "sha256": "0" * 64, "epoch": 0}
    final[MAKER.MANIFEST] = json.dumps(manifest).encode("utf-8")
    run = counts_run(tmp_path, final)
    assert pairs(problems(run, "publish_counts")) == [("blocking", "products.paper.latest"),
                                                     ("blocking", "products.slides.latest")]


def build_results(items, tar):
    return MAKER.results("build", "x_build", items, inputs={"project.tar": "sha256:" + tar * 64})


def test_build_counts_each_products_items_from_its_own_file_and_project_items_once(tmp_path):
    files = MAKER.repository()
    items = MAKER.build_items()
    items.append({"id": "paper", "kind": "deliverable", "findings": [MAKER.finding(
        "read_map", "warning", "Competing canonical copy manuscript_v2.md.")], "needs_decision": True})
    for path, tar in (("project/verification/paper/build", "c"), ("project/verification/slides/build", "d")):
        data = build_results(items, tar)
        files[path + ".json"] = data
        files[path + "/results.json"] = data
    counts = MAKER.counts_for(files)
    counts["build.warnings"] = 4
    counts["build.one_source"] = 0
    counts["decisions.undecided"] = 32  # the added deliverable row in each of the two build files
    run = counts_run(tmp_path, MAKER.finish(files, counts))
    assert problems(run, "publish_counts") == []


def test_products_that_share_a_folder_count_its_files_once(tmp_path):
    files = MAKER.repository()
    for name in list(files):
        if name.startswith("project/verification/slides/"):
            del files[name]
    for name in list(files):
        if name.startswith("project/verification/paper/"):
            files[name.replace("project/verification/paper/", "project/verification/")] = files.pop(name)
    counts = collections.OrderedDict((k, v) for k, v in MAKER.counts_for(files).items()
                                     if ".slides." not in k and ".paper." not in k)
    counts.update((("prose.changes", 5), ("prose.ai", 4), ("prose.no_reason", 2), ("prose.reports", 1),
                   ("prose.paper+slides.changes", 5), ("build.blocking", 3), ("build.warnings", 3),
                   ("build.reports", 1), ("decisions.undecided", 22), ("missing", ""),
                   ("phases.paper+slides.data_analysis.confirmed", 2)))
    final = MAKER.finish(files, counts)
    manifest = json.loads(final[MAKER.MANIFEST])
    manifest["groups"] = [{"key": "paper+slides", "products": ["paper", "slides"], "verification_dir": "verification"}]
    for p in manifest["products"]:
        p["verification_dir"] = "verification"
    for r in manifest["reports"]:
        r["group"] = "paper+slides"
        for field in ("results", "report"):
            if r[field]:
                r[field] = r[field].replace("verification/paper/", "verification/").replace(
                    "verification/slides/", "verification/")
    manifest["reports"] = [r for r in manifest["reports"] if "slides_" not in r["run_id"]]
    final[MAKER.MANIFEST] = json.dumps(manifest).encode("utf-8")
    run = counts_run(tmp_path, final)
    assert problems(run, "publish_counts") == []
    rows = {r["key"]: r["recount"] for r in read(run, "counts.json")["rows"]}
    assert rows["prose.changes"] == 5 and rows["build.blocking"] == 3


def test_a_verified_ledger_row_gives_the_verified_state(tmp_path):
    files = MAKER.repository()
    path = "project/builds/paper/BUILDS.md"
    text = files[path].decode("utf-8").splitlines()
    text[-1] = text[-1].replace("unverified: prose, citations, data, build", "verified")
    files[path] = ("\n".join(text) + "\n").encode("utf-8")
    counts = MAKER.counts_for(files)
    counts["builds.paper.state"] = "verified"
    run = counts_run(tmp_path, MAKER.finish(files, counts))
    assert problems(run, "publish_counts") == []


def test_an_older_seven_column_ledger_row_counts(tmp_path):
    files = MAKER.repository()
    path = "project/builds/paper/BUILDS.md"
    lines = files[path].decode("utf-8").splitlines()
    lines.insert(4, "| v000 | 2026-09-01 | - | %s | first | - | no |" % ("0" * 64))
    files[path] = ("\n".join(lines) + "\n").encode("utf-8")
    counts = MAKER.counts_for(files)
    counts["builds.total"] = 3
    run = counts_run(tmp_path, MAKER.finish(files, counts))
    assert problems(run, "publish_counts") == []


# ---------------------------------------------------------------- the rebuild

def working_make():
    """The make the rebuild step would choose, by the same rule, or None."""
    for command in (["make"], ["arch", "-arm64", "make"], ["/Library/Developer/CommandLineTools/usr/bin/make"]):
        try:
            done = subprocess.run(command + ["--version"], stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and "GNU Make" in done.stdout:
            return command
    return None


MAKE = working_make()
needs_make = pytest.mark.skipif(MAKE is None, reason="no make that runs from this Python")
needs_pandoc = pytest.mark.skipif(MAKE is None or shutil.which("pandoc") is None,
                                  reason="no make that runs from this Python, or no pandoc")
TINY_MAKEFILE = (
    "WORKFLOW ?= ../../workflow\n"
    "OSPIPE ?= PYTHONPATH='$(WORKFLOW)/ospipe' python3 -m ospipe\n"
    "MANIFEST ?= numbers.yml\nPURPOSE ?= draft\n\n"
    ".PHONY: paper\npaper: paper.md $(MANIFEST)\n"
    "\t$(OSPIPE) build --manuscript paper.md --manifest $(MANIFEST) --to docx --builds-dir builds/paper "
    "--purpose \"$(PURPOSE)\"\n")


def tiny_project(tmp_path, makefile=TINY_MAKEFILE, build=True):
    """A tiny real project with one product, built once with make at the fixture's date."""
    project = tmp_path / "tiny" / "project"
    project.mkdir(parents=True)
    (project / "Makefile").write_text(makefile, encoding="utf-8")
    (project / "paper.md").write_text("# A tiny paper\n\nThe mean is {{num:mean}}.\n", encoding="utf-8")
    (project / "numbers.yml").write_text('numbers:\n  mean: {value: "4.2"}\n', encoding="utf-8")
    if build:
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(MAKER.EPOCH), PYTHONDONTWRITEBYTECODE="1",
                   PYTHONPATH=str(REPO / "ospipe"))
        p = subprocess.run(MAKE + ["paper", "WORKFLOW=" + str(REPO)], cwd=str(project), env=env,
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr
    return project


def tiny_repo(project, latest=True):
    files = collections.OrderedDict()
    for top, dirs, names in os.walk(str(project)):
        dirs.sort()
        for name in sorted(names):
            full = os.path.join(top, name)
            with open(full, "rb") as f:
                files["project/" + os.path.relpath(full, str(project)).replace(os.sep, "/")] = f.read()
    row = None
    if latest:
        ledger = files["project/builds/paper/BUILDS.md"].decode("utf-8").splitlines()[-1]
        cells = [c.strip() for c in ledger.strip("|").split("|")]
        row = {"version": cells[0], "date": cells[1], "sha256": cells[3], "epoch": MAKER.EPOCH}
    manifest = {"schema": "publish-repo", "schema_version": 1,
                "products": [{"name": "paper", "source": "paper.md", "builds_dir": "builds/paper",
                              "verification_dir": "verification", "bib": None, "numbers": "numbers.yml",
                              "latest": row, "state": "unverified: no prose report"}],
                "groups": [{"key": "paper", "products": ["paper"], "verification_dir": "verification"}],
                "reports": [], "counts": {}, "generated": {},
                "files": {p: "sha256:" + hashlib.sha256(d).hexdigest() for p, d in files.items()}}
    files[MAKER.MANIFEST] = json.dumps(manifest).encode("utf-8")
    return files


def rebuild_settings(**over):
    cfg = settings(workflow_root=str(REPO), rebuild=True)
    cfg.update(over)
    return cfg


def no_temp_path(run):
    for path in sorted((run / "files").iterdir()):
        if path.suffix in (".json", ".md"):
            # settings.json names the workflow folder, which may itself lie in a temporary folder.
            text = path.read_text(encoding="utf-8").replace(str(REPO), "WORKFLOW")
            for machine in ("/private/", "/var/folders/", "/tmp/"):
                assert machine not in text, (path.name, machine)


@needs_pandoc
def test_a_tiny_project_rebuilds_byte_for_byte_and_replays(tmp_path):
    project = tiny_project(tmp_path)
    run = run_on(tmp_path, inputs_with(tmp_path, rebuild_settings(), tiny_repo(project)))
    assert ran(run) == list(STEPS)
    out = read(run, "rebuild.json")["products"]
    assert [(p["name"], p["latest"], p["result"], p["text_matches"]) for p in out] == [
        ("paper", "v001", "same bytes", True)]
    assert out[0]["rebuilt_sha256"] == out[0]["ledger_sha256"]
    assert problems(run, "publish_rebuild") == []
    assert ("publish_rebuild", "paper") in [(f["check"], f["item"]) for f in findings(run, "info")]
    p = vg("verify", "--run", str(run))
    assert p.returncode == 0, p.stdout + p.stderr
    assert all(line.endswith("replay matches") for line in p.stdout.strip().splitlines()), p.stdout
    no_temp_path(run)
    text = section(report(run), "Rebuild")
    assert "| paper | v001 | same bytes | yes |" in text


@needs_pandoc
def test_a_source_changed_after_its_build_is_blocking(tmp_path):
    project = tiny_project(tmp_path)
    files = tiny_repo(project)
    files["project/paper.md"] = b"# A tiny paper\n\nThe mean is {{num:mean}}, and more.\n"
    run = run_on(tmp_path, inputs_with(tmp_path, rebuild_settings(), files))
    out = read(run, "rebuild.json")["products"]
    assert [(p["result"], p["text_matches"]) for p in out] == [("differs", False)]
    assert pairs(problems(run, "publish_rebuild")) == [("blocking", "paper")]


@needs_make
def test_a_failing_make_is_blocking_with_no_temporary_path(tmp_path):
    makefile = ".PHONY: paper\npaper:\n\t@echo \"cannot build in $(CURDIR)\" >&2; exit 3\n"
    project = tiny_project(tmp_path, makefile=makefile, build=False)
    files = tiny_repo(project, latest=False)
    manifest = json.loads(files[MAKER.MANIFEST])
    manifest["products"][0]["latest"] = {"version": "v001", "date": "2026-10-15", "sha256": "0" * 64,
                                         "epoch": MAKER.EPOCH}
    files[MAKER.MANIFEST] = json.dumps(manifest).encode("utf-8")
    run = run_on(tmp_path, inputs_with(tmp_path, rebuild_settings(), files))
    found = problems(run, "publish_rebuild")
    assert pairs(found) == [("blocking", "paper")]
    assert "exit" in found[0]["message"] and found[0]["evidence"] == "cannot build in <copy>/project"
    assert read(run, "rebuild.json")["products"][0]["result"] == "failed"
    no_temp_path(run)


def test_a_product_with_no_build_is_skipped_with_a_note(tmp_path):
    project = tiny_project(tmp_path, build=False)
    run = run_on(tmp_path, inputs_with(tmp_path, rebuild_settings(), tiny_repo(project, latest=False)))
    assert problems(run, "publish_rebuild") == []
    assert [(f["item"], f["message"]) for f in findings(run, "info", "publish_rebuild")] == [
        ("paper", "The product has no numbered build, so it is not rebuilt.")]
    assert read(run, "rebuild.json")["products"][0]["result"] == "skipped"


def test_a_workflow_folder_without_ospipe_is_blocking(tmp_path):
    project = tiny_project(tmp_path, build=False)
    files = tiny_repo(project, latest=False)
    run = run_on(tmp_path, inputs_with(tmp_path, rebuild_settings(workflow_root=str(tmp_path)), files))
    assert pairs(problems(run, "publish_rebuild")) == [("blocking", "workflow_root")]


def test_no_make_gives_one_blocking_finding_with_no_path(tmp_path):
    """The step run on its own, with its list of make commands replaced by commands that
    do not exist, the way the runtime runs it."""
    step = tmp_path / "step"
    files_dir = step / "files"
    files_dir.mkdir(parents=True)
    code = (ROOT / "implementations" / "ops" / "publish_rebuild.py").read_text(encoding="utf-8")
    start = code.index("MAKES = (")
    end = code.index("\n", start)
    code = code[:start] + 'MAKES = (["no-such-make-a"], ["no-such-make-b"])' + code[end:]
    (step / "publish_rebuild.py").write_text(code, encoding="utf-8")
    shutil.copy(str(ROOT / "implementations" / "_lib.py"), str(step))
    (files_dir / "settings.json").write_text(json.dumps({"workflow_root": str(REPO)}), encoding="utf-8")
    files = clean_files()
    (files_dir / "repo.tar").write_bytes(MAKER.pack_files(files))
    p = subprocess.run([sys.executable, str(step / "publish_rebuild.py"), str(files_dir)], cwd=str(tmp_path),
                       capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stdout + p.stderr
    found = json.loads((files_dir / "findings_publish_rebuild.json").read_text(encoding="utf-8"))
    assert [(f["severity"], f["item"], f["evidence"]) for f in found if f["severity"] != "info"] == [
        ("blocking", "make", "")]
    assert found[0]["message"].startswith("make could not run on this machine")
    out = json.loads((files_dir / "rebuild.json").read_text(encoding="utf-8"))["products"]
    assert [(p["name"], p["result"]) for p in out] == [("paper", "not run"), ("slides", "skipped")]


# ---------------------------------------------------------------- the report

def test_report_headings_in_order_and_settings_name_nothing_private(tmp_path):
    run = run_on(tmp_path, FIX / "seeded")
    text = report(run)
    assert text.startswith("# " + TITLE + "\n")
    heads = [line[3:] for line in text.splitlines() if line.startswith("## ")]
    assert heads == HEADINGS
    settings_part = section(text, "Settings")
    for field in SETTINGS_FIELDS:
        assert field in settings_part, field
    assert "| terms | 1 entry |" in settings_part and "| workflow_root | given |" in settings_part
    assert "Jordan" not in text and "/scholar/" not in text and "PRIVATE KEY" not in text
    assert "- Blocking problems, 13" in section(text, "Files")
    assert "| prose.changes | 8 | 7 |" in section(text, "Counts")
    assert "rebuild set to false" in text.split("## Summary")[0]


# ---------------------------------------------------------------- layers and conventions

def test_no_code_imports_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(audit_layer|ospipe|vg)\b")
    files = sorted((ROOT / "implementations" / "ops").glob("*.py"))
    assert [p for p in files if p.name.startswith("publish_")]
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)


def test_the_steps_keep_the_conventions():
    """Python 3.9 code with no f-strings, type hints, dataclasses, or walrus, no long or
    en dash, and no machine path in a module's docstring."""
    import ast
    for path in sorted((ROOT / "implementations" / "ops").glob("publish_*.py")) + [FIX / "make_fixtures.py"]:
        source = path.read_text(encoding="utf-8")
        assert "\u2014" not in source and "\u2013" not in source, path
        with open(str(path), "rb") as f:
            for tok in tokenize.tokenize(f.readline):
                assert not (tok.type == tokenize.STRING and re.match(r"^[rRbBuU]*[fF]", tok.string)), (path, tok.start)
        tree = ast.parse(source)
        doc = ast.get_docstring(tree) or ""
        for machine in MACHINE_PATHS:
            assert machine not in doc, (path, machine)
        for node in ast.walk(tree):
            assert not isinstance(node, ast.AnnAssign), path
            if isinstance(node, ast.FunctionDef):
                assert node.returns is None and all(a.annotation is None for a in node.args.args), path
            assert type(node).__name__ != "NamedExpr", path
        assert "dataclass" not in source, path
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add((node.module or "").split(".")[0])
        assert imports <= ALLOWED_IMPORTS, (path, imports - ALLOWED_IMPORTS)


def test_the_kb_entry_gives_the_run_command_with_its_inputs():
    entry = REPO / "audit_layer" / "kb" / "corpus" / "procedures" / "procedures-ops-publish.md"
    lines = [line for line in entry.read_text(encoding="utf-8").splitlines() if line.startswith("4. Run command. ")]
    assert len(lines) == 1
    assert "python3 vg.py run graphs/ops_publish.yaml" in lines[0]
    assert "`publish_check.yaml`" in lines[0] and "`repo.tar`" in lines[0]
