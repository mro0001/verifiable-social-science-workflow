import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.reconcile import (  # noqa: E402
    Change,
    ReconcileError,
    Reconciliation,
    format_reconciliation,
    normalize_tokens,
    reconcile,
)
from review.reconcile import fixture  # noqa: E402


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def builds_dir(tmp_path_factory):
    return fixture.build_builds_dir(tmp_path_factory.mktemp("builds"))


def _run(tmp_path_factory, builds_dir, builder, name, **kwargs):
    docx_path = builder(tmp_path_factory.mktemp(name) / (name + ".docx"))
    return reconcile(docx_path, builds_dir, "v002", **kwargs)


@pytest.fixture(scope="module")
def rec_all_accepted(tmp_path_factory, builds_dir):
    return _run(tmp_path_factory, builds_dir, fixture.build_return_all_accepted, "acc")


@pytest.fixture(scope="module")
def rec_rejected(tmp_path_factory, builds_dir):
    return _run(tmp_path_factory, builds_dir, fixture.build_return_one_rejected, "rej")


@pytest.fixture(scope="module")
def rec_modified(tmp_path_factory, builds_dir):
    return _run(tmp_path_factory, builds_dir, fixture.build_return_one_modified, "mod")


@pytest.fixture(scope="module")
def rec_author(tmp_path_factory, builds_dir):
    return _run(tmp_path_factory, builds_dir, fixture.build_return_author_edit, "auth")


@pytest.fixture(scope="module")
def pending_docx(tmp_path_factory):
    return fixture.build_return_pending(tmp_path_factory.mktemp("pend") / "pend.docx")


@pytest.fixture(scope="module")
def rec_pending(pending_docx, builds_dir):
    return reconcile(pending_docx, builds_dir, "v002")


@pytest.fixture(scope="module")
def rec_conflict(tmp_path_factory, builds_dir):
    return _run(tmp_path_factory, builds_dir, fixture.build_return_conflict, "conf")


class TestAllAccepted:
    def test_four_regions_all_accepted(self, rec_all_accepted):
        assert isinstance(rec_all_accepted, Reconciliation)
        assert len(rec_all_accepted.accepted) == fixture.REGION_COUNT
        assert rec_all_accepted.rejected == []
        assert rec_all_accepted.modified == []
        assert rec_all_accepted.pending == []
        assert rec_all_accepted.author_edits == []
        assert rec_all_accepted.comments == []
        assert rec_all_accepted.conflicts == []

    def test_word_swap_region_texts(self, rec_all_accepted):
        (swap,) = [c for c in rec_all_accepted.accepted if c.baseline_text == fixture.SWAP_BASE_WORD]
        assert swap.revision_text == fixture.SWAP_REV_WORD
        assert swap.found_text is None

    def test_insertion_region_has_empty_baseline(self, rec_all_accepted):
        (ins,) = [c for c in rec_all_accepted.accepted if c.revision_text == fixture.S_INSERTED]
        assert ins.baseline_text == ""

    def test_deletion_region_has_empty_revision(self, rec_all_accepted):
        (dele,) = [c for c in rec_all_accepted.accepted if c.baseline_text == fixture.DELETED_SENTENCE]
        assert dele.revision_text == ""

    def test_rewrite_merged_into_one_region(self, rec_all_accepted):
        (rew,) = [
            c for c in rec_all_accepted.accepted if c.baseline_text == fixture.REWRITE_BASE_PHRASE
        ]
        assert rew.revision_text == fixture.REWRITE_REV_PHRASE

    def test_context_drawn_from_revision_side(self, rec_all_accepted):
        (swap,) = [c for c in rec_all_accepted.accepted if c.baseline_text == fixture.SWAP_BASE_WORD]
        assert "assay was" in swap.context
        assert "against the" in swap.context


class TestRejected:
    def test_native_reject_restores_baseline(self, rec_rejected):
        (rej,) = rec_rejected.rejected
        assert rej.baseline_text == fixture.REWRITE_BASE_PHRASE
        assert rej.revision_text == fixture.REWRITE_REV_PHRASE
        assert len(rec_rejected.accepted) == fixture.REGION_COUNT - 1

    def test_rejection_not_double_reported_as_author_edit(self, rec_rejected):
        assert rec_rejected.author_edits == []
        assert rec_rejected.conflicts == []


class TestModified:
    def test_rewritten_region_reports_found_text(self, rec_modified):
        (mod,) = rec_modified.modified
        assert mod.baseline_text == fixture.SWAP_BASE_WORD
        assert mod.revision_text == fixture.SWAP_REV_WORD
        assert mod.found_text == fixture.MODIFIED_WORD
        assert len(rec_modified.accepted) == fixture.REGION_COUNT - 1

    def test_modification_not_double_reported_as_author_edit(self, rec_modified):
        assert rec_modified.author_edits == []
        assert rec_modified.conflicts == []


class TestAuthorEdit:
    def test_edit_outside_regions_is_the_authors(self, rec_author):
        assert len(rec_author.author_edits) == 1
        assert "author appended this untracked remark" in rec_author.author_edits[0]
        assert len(rec_author.accepted) == fixture.REGION_COUNT

    def test_comment_passthrough(self, rec_author):
        (comment,) = rec_author.comments
        assert comment.author == fixture.COMMENT_AUTHOR
        assert comment.text == fixture.COMMENT_TEXT


class TestPending:
    def test_unresolved_ai_insertion_stays_pending(self, rec_pending):
        (delta,) = rec_pending.pending
        assert delta.kind == "insertion"
        assert delta.author == fixture.PENDING_AUTHOR
        assert delta.text == fixture.S_INSERTED

    def test_pending_region_never_ruled_accepted(self, rec_pending):
        assert len(rec_pending.accepted) == fixture.REGION_COUNT - 1
        assert fixture.S_INSERTED not in [c.revision_text for c in rec_pending.accepted]
        assert rec_pending.rejected == []
        assert rec_pending.modified == []
        assert rec_pending.author_edits == []
        assert rec_pending.conflicts == []

    def test_ai_authors_knob(self, pending_docx, builds_dir):
        rec = reconcile(pending_docx, builds_dir, "v002", ai_authors=())
        assert rec.pending == []
        assert len(rec.accepted) == fixture.REGION_COUNT


class TestConflict:
    def test_destroyed_context_is_conflict_never_guessed(self, rec_conflict):
        assert len(rec_conflict.conflicts) == 1
        assert fixture.REWRITE_REV_PHRASE in rec_conflict.conflicts[0]

    def test_conflicted_region_absent_from_ruled_buckets(self, rec_conflict):
        assert len(rec_conflict.accepted) == fixture.REGION_COUNT - 1
        ruled = rec_conflict.accepted + rec_conflict.rejected + rec_conflict.modified
        assert fixture.REWRITE_REV_PHRASE not in [c.revision_text for c in ruled]


class TestLineageErrors:
    def test_missing_ledger(self, tmp_path, builds_dir):
        docx_path = fixture.build_return_all_accepted(tmp_path / "r.docx")
        with pytest.raises(ReconcileError, match="ledger absent"):
            reconcile(docx_path, tmp_path, "v002")

    def test_unknown_version(self, tmp_path, builds_dir):
        docx_path = fixture.build_return_all_accepted(tmp_path / "r.docx")
        with pytest.raises(ReconcileError, match="no ledger row"):
            reconcile(docx_path, builds_dir, "v009")

    def test_version_without_baseline(self, tmp_path, builds_dir):
        docx_path = fixture.build_return_all_accepted(tmp_path / "r.docx")
        with pytest.raises(ReconcileError, match="no baseline"):
            reconcile(docx_path, builds_dir, "v001")

    def test_missing_snapshot(self, tmp_path):
        broken = fixture.build_builds_dir(tmp_path / "builds")
        (broken / "v001.md").unlink()
        docx_path = fixture.build_return_all_accepted(tmp_path / "r.docx")
        with pytest.raises(ReconcileError, match="snapshot absent"):
            reconcile(docx_path, broken, "v002")

    def test_version_shorthand_normalized(self, tmp_path, builds_dir):
        docx_path = fixture.build_return_all_accepted(tmp_path / "r.docx")
        rec = reconcile(docx_path, builds_dir, "2")
        assert len(rec.accepted) == fixture.REGION_COUNT


NINE_COLUMN_LEDGER = """# Builds

| version | date | git | sha256 | purpose | baseline | reviewed | verification | runs |
|---|---|---|---|---|---|---|---|---|
| v001 | 2026-07-23 | 0000000 | 00ff00ff | synthetic baseline | - | no | none | - |
| v002 | 2026-07-23 | 1111111 | 11ee11ee | synthetic revision | v001 | no | prose | prose_run |
| v003 | 2026-07-24 | 2222222 | 22dd22dd | short row | v002 | no |
"""


# An older ledger keeps its seven-column header while newer builds append
# nine-cell rows under it.
MIXED_WIDTH_LEDGER = """# Builds

| version | date | git | sha256 | purpose | baseline | reviewed |
|---|---|---|---|---|---|---|
| v001 | 2026-07-23 | 0000000 | 00ff00ff | synthetic baseline | - | no |
| v002 | 2026-07-23 | 1111111 | 11ee11ee | synthetic revision | v001 | no | prose | prose_run |
"""

# Same rows with the columns in another order (baseline before purpose).
REORDERED_LEDGER = """# Builds

| version | baseline | date | git | sha256 | purpose | reviewed |
|---|---|---|---|---|---|---|
| v001 | - | 2026-07-23 | 0000000 | 00ff00ff | synthetic baseline | no |
| v002 | v001 | 2026-07-23 | 1111111 | 11ee11ee | synthetic revision | no |
"""


def _ledger_builds_dir(dirpath, ledger):
    builds = fixture.build_builds_dir(dirpath)
    (builds / "BUILDS.md").write_text(ledger, encoding="utf-8")
    return builds


def _nine_column_builds_dir(dirpath):
    return _ledger_builds_dir(dirpath, NINE_COLUMN_LEDGER)


class TestLedgerReadByColumnName:
    def test_nine_columns_reconcile_like_seven(self, tmp_path, builds_dir):
        nine = _nine_column_builds_dir(tmp_path / "nine")
        docx_path = fixture.build_return_one_rejected(tmp_path / "r.docx")
        assert reconcile(docx_path, nine, "v002") == reconcile(docx_path, builds_dir, "v002")

    def test_longer_row_under_older_header_reads_by_header_names(self, tmp_path, builds_dir):
        mixed = _ledger_builds_dir(tmp_path / "mixed", MIXED_WIDTH_LEDGER)
        docx_path = fixture.build_return_one_rejected(tmp_path / "r.docx")
        assert reconcile(docx_path, mixed, "v002") == reconcile(docx_path, builds_dir, "v002")

    def test_reordered_columns_read_by_name(self, tmp_path, builds_dir):
        reordered = _ledger_builds_dir(tmp_path / "reordered", REORDERED_LEDGER)
        docx_path = fixture.build_return_one_rejected(tmp_path / "r.docx")
        assert reconcile(docx_path, reordered, "v002") == reconcile(docx_path, builds_dir, "v002")

    def test_row_with_wrong_cell_count_is_skipped(self, tmp_path):
        nine = _nine_column_builds_dir(tmp_path / "nine")
        (nine / "v003.md").write_text((nine / "v002.md").read_text(encoding="utf-8"), encoding="utf-8")
        docx_path = fixture.build_return_all_accepted(tmp_path / "r.docx")
        with pytest.raises(ReconcileError, match="no ledger row for v003"):
            reconcile(docx_path, nine, "v003")


class TestReadOnly:
    def test_reconcile_writes_nothing(self, tmp_path, builds_dir):
        docx_path = fixture.build_return_all_accepted(tmp_path / "r.docx")
        before_docx = _sha256(docx_path)
        before_files = {p.name: _sha256(p) for p in builds_dir.iterdir()}
        reconcile(docx_path, builds_dir, "v002")
        assert _sha256(docx_path) == before_docx
        assert {p.name: _sha256(p) for p in builds_dir.iterdir()} == before_files


class TestNormalizeTokens:
    def test_pipe_and_pandoc_tables_tokenize_identically(self):
        pipe = "| Site | Batch |\n|---|---|\n| North | A |\n"
        pandoc_style = (
            "  ---------------\n  Site    Batch\n  ------- -------\n"
            "  North   A\n  ---------------\n"
        )
        assert normalize_tokens(pipe) == normalize_tokens(pandoc_style)

    def test_hard_line_breaks_stripped(self):
        assert normalize_tokens("alpha\\\n\\\nbeta") == ["alpha", "beta"]

    def test_pandoc_escapes_undone(self):
        assert normalize_tokens("rose 48.6\\% overall \\[sic\\]") == [
            "rose",
            "48.6%",
            "overall",
            "[sic]",
        ]

    def test_heading_markers_dropped(self):
        assert normalize_tokens("# Title\n\n## Sub head") == ["Title", "Sub", "head"]

    def test_smart_punctuation_normalized(self):
        assert normalize_tokens("the framework’s “best” run") == [
            "the",
            "framework's",
            '"best"',
            "run",
        ]


class TestFormatting:
    def test_format_lists_every_bucket(self, rec_pending):
        text = format_reconciliation(rec_pending)
        for label in ("accepted", "rejected", "modified", "pending", "author edits", "comments", "conflicts"):
            assert label in text
        assert fixture.S_INSERTED in text

    def test_change_is_the_contract_shape(self):
        change = Change("a", "b", "ctx")
        assert change.found_text is None
        assert change._fields == ("baseline_text", "revision_text", "context", "found_text")
