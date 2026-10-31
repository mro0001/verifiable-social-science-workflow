"""Tests for the knowledge base's source check (Track G plan, Step G12).

Appendix A2.4 "Managing entries" says the checksum of an entry's source shows
when the source has changed since the entry was written. sources.py compares
each entry's recorded checksum with the file at <root>/<source> and reads
nothing outside <root>. Every corpus, root, and source file here is synthetic.
Run from the repository root with python3 -m pytest audit_layer/kb/tests.
"""
import builtins
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from audit_layer.kb.cli import main  # noqa: E402
from audit_layer.kb.graph_entries import sync  # noqa: E402
from audit_layer.kb.sources import source_status  # noqa: E402

DATE = "2026-10-29"


def short(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()[:12]


def entry(ident, group, source, commit):
    title = "The {} entry".format(ident)
    return (
        "---\nid: {i}\ntitle: {t}\nsource: {s}\nsource_commit: {c}\nupdated: 2026-10-01\n"
        "group: {g}\n---\n\n# {t}\n\nA synthetic entry for the source check.\n"
    ).format(i=ident, t=title, s=source, c=commit, g=group)


def setup(tmp_path, make_corpus):
    """A root holding three source files and a corpus with one entry per status.

    alpha's source is unchanged, gamma's had one byte edited after its entry was
    written, beta records a seven-character git hash, and the others name a skill,
    a web address, a path with '..', and an absolute path. The file outside the root
    matches its recorded checksum, so a status other than not_found would show it
    was read.
    """
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    alpha = b"The alpha source.\n"
    gamma = b"The gamma source.\n"
    (root / "docs" / "alpha.md").write_bytes(alpha)
    (root / "docs" / "gamma.md").write_bytes(gamma.replace(b"gamma", b"gammA"))
    (root / "docs" / "beta.md").write_bytes(b"The beta source.\n")
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"Outside the root.\n")
    overrides = {
        "formats/formats-alpha.md": entry("formats-alpha", "FORMATS", "docs/alpha.md", short(alpha)),
        "loop/loop-gamma.md": entry("loop-gamma", "LOOP", "docs/gamma.md", short(gamma)),
        "formats/formats-beta.md": entry("formats-beta", "FORMATS", "docs/beta.md", "abc1234"),
        "loop/loop-skill.md": entry("loop-skill", "LOOP", "abt-review", "sha256:0123456789ab"),
        "loop/loop-web.md": entry("loop-web", "LOOP", "https://example.org/guide", "sha256:0123456789ab"),
        "loop/loop-up.md": entry("loop-up", "LOOP", "../outside.md", short(outside.read_bytes())),
        "loop/loop-absolute.md": entry("loop-absolute", "LOOP", str(outside), short(outside.read_bytes())),
    }
    return root, make_corpus(overrides), outside


def test_one_row_per_entry_sorted_by_id_with_each_status(tmp_path, make_corpus):
    root, corpus, _ = setup(tmp_path, make_corpus)
    rows = source_status(corpus, root)
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    assert all(set(r) == {"id", "source", "recorded", "current", "status"} for r in rows)
    status = {r["id"]: r["status"] for r in rows}
    assert status == {
        "formats-alpha": "same",
        "formats-beta": "not_checked",
        "loop-absolute": "not_found",
        "loop-gamma": "changed",
        "loop-skill": "not_found",
        "loop-up": "not_found",
        "loop-web": "not_checked",
    }


def test_rows_carry_the_recorded_and_current_checksums(tmp_path, make_corpus):
    root, corpus, _ = setup(tmp_path, make_corpus)
    rows = {r["id"]: r for r in source_status(corpus, root)}
    alpha = (root / "docs" / "alpha.md").read_bytes()
    gamma = (root / "docs" / "gamma.md").read_bytes()
    assert rows["formats-alpha"]["recorded"] == rows["formats-alpha"]["current"] == short(alpha)
    assert rows["loop-gamma"]["current"] == short(gamma)
    assert rows["loop-gamma"]["recorded"] != rows["loop-gamma"]["current"]
    assert rows["loop-skill"]["source"] == "abt-review" and rows["loop-skill"]["current"] == ""
    assert rows["formats-beta"]["recorded"] == "abc1234" and rows["formats-beta"]["current"] == ""


def test_nothing_outside_the_root_is_read(tmp_path, make_corpus, monkeypatch):
    root, corpus, outside = setup(tmp_path, make_corpus)
    opened = []
    real_open = builtins.open

    def watching(file, *args, **kwargs):
        opened.append(Path(str(file)).resolve())
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", watching)
    rows = {r["id"]: r for r in source_status(corpus, root)}
    monkeypatch.setattr(builtins, "open", real_open)
    assert (root / "docs" / "alpha.md").resolve() in opened
    assert outside.resolve() not in opened
    assert rows["loop-up"]["current"] == "" and rows["loop-absolute"]["current"] == ""


def test_a_link_inside_the_root_that_leads_outside_is_not_found(tmp_path, make_corpus):
    root, _, outside = setup(tmp_path, make_corpus)
    (root / "docs" / "link.md").symlink_to(outside)
    corpus = make_corpus({"loop/loop-link.md": entry("loop-link", "LOOP", "docs/link.md",
                                                     short(outside.read_bytes()))})
    rows = {r["id"]: r for r in source_status(corpus, root)}
    assert rows["loop-link"]["status"] == "not_found"


def test_a_folder_is_not_a_source_file(tmp_path, make_corpus):
    root, _, _ = setup(tmp_path, make_corpus)
    corpus = make_corpus({"loop/loop-folder.md": entry("loop-folder", "LOOP", "docs", "sha256:0123456789ab")})
    rows = {r["id"]: r for r in source_status(corpus, root)}
    assert rows["loop-folder"]["status"] == "not_found"


def test_the_command_prints_each_entry_and_the_counts_and_exits_1_on_a_change(tmp_path, make_corpus, capsys):
    root, corpus, _ = setup(tmp_path, make_corpus)
    code = main(["source-check", "--root", str(root), "--corpus", str(corpus)])
    out = capsys.readouterr().out.splitlines()
    assert code == 1
    assert out[:-1] == [
        "same formats-alpha docs/alpha.md",
        "not_checked formats-beta docs/beta.md",
        "not_found loop-absolute {}".format(tmp_path / "outside.md"),
        "changed loop-gamma docs/gamma.md",
        "not_found loop-skill abt-review",
        "not_found loop-up ../outside.md",
        "not_checked loop-web https://example.org/guide",
    ]
    assert out[-1] == "7 entries, 1 same, 1 changed, 3 not_found, 2 not_checked"


def test_the_command_exits_0_when_nothing_changed(tmp_path, make_corpus, capsys):
    root, corpus, _ = setup(tmp_path, make_corpus)
    (corpus / "loop" / "loop-gamma.md").unlink()
    assert main(["source-check", "--root", str(root), "--corpus", str(corpus)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "6 entries, 1 same, 0 changed, 3 not_found, 2 not_checked"


def test_a_graph_entry_reads_same_against_a_copy_of_its_graph_and_changed_after_an_edit(
        tmp_path, make_corpus, make_procedures):
    procedures = make_procedures()
    corpus = make_corpus()
    sync(procedures, corpus, DATE)
    root = tmp_path / "repo"
    graphs = root / "verification_procedures" / "graphs"
    graphs.mkdir(parents=True)
    shutil.copy(str(procedures / "graphs" / "two_steps.yaml"), str(graphs / "two_steps.yaml"))
    rows = {r["id"]: r for r in source_status(corpus, root)}
    row = rows["procedures-two-steps"]
    assert (row["source"], row["status"]) == ("verification_procedures/graphs/two_steps.yaml", "same")
    copy = graphs / "two_steps.yaml"
    copy.write_text(copy.read_text(encoding="utf-8").replace("version: 0.2", "version: 0.3"), encoding="utf-8")
    assert {r["id"]: r for r in source_status(corpus, root)}["procedures-two-steps"]["status"] == "changed"


def test_contract_names_the_command():
    text = (ROOT / "audit_layer" / "kb" / "CONTRACT.md").read_text(encoding="utf-8")
    assert "python3 -m audit_layer.kb source-check --root DIR [--corpus DIR]" in text
