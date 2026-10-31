"""Archive lines for older drafts. Temporary projects written by the test, each with a
build file naming a manuscript and slides."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ospipe.layout import ArchiveError, LookAlike, archive, look_alikes, read_map  # noqa: E402

OSPIPE_DIR = Path(__file__).resolve().parents[1]

MAKEFILE = (
    "OSPIPE ?= python3 -m ospipe\n"
    "MANIFEST ?= numbers.yml\n"
    "\n"
    ".PHONY: manuscript slides\n"
    "manuscript: manuscript.md $(MANIFEST)\n"
    "\t$(OSPIPE) build --manuscript manuscript.md --manifest $(MANIFEST) --to docx"
    " --builds-dir builds/manuscript --purpose draft\n"
    "slides: talk/slides.md $(MANIFEST)\n"
    "\t$(OSPIPE) build --manuscript talk/slides.md --manifest $(MANIFEST) --to revealjs"
    " --builds-dir builds/slides --purpose draft\n"
)

TITLE = "Meeting Cadence and  Team Learning"
FRONT = '---\ntitle: "{0}"\nauthor: "A. Example"\n---\n'.format(TITLE)

FILES = {
    "manuscript.md": FRONT + "\n# Introduction\n\nThe current draft.\n",
    "talk/slides.md": "# A fake talk\n\nWidgets.\n",
    "numbers.yml": 'numbers:\n  widgets: {value: "24", from: out.json, field: widgets}\n',
    # Same title as the manuscript, in another case and spacing, with front matter.
    "drafts/early.md": '---\ntitle: "meeting cadence and team   LEARNING"\n---\n\n# Introduction\n\nOld.\n',
    # Same title from its first heading, no front matter.
    "old/full_text.md": "\n# Meeting Cadence and Team Learning\n\nOlder still.\n",
    # The name holds the source's name.
    "manuscript_2026-09.md": "# Something else\n\nA September copy.\n",
    "drafts/slides_v1.md": "# Another talk\n\nAn old talk.\n",
    # Already archived.
    "drafts/archived.md": FRONT + "\n> ARCHIVE 2026-09-30: superseded by manuscript.md\n\nOld.\n",
    # Not look-alikes.
    "builds/manuscript/v001.md": FRONT + "\nA build snapshot.\n",
    "ship/manuscript/manuscript.md": FRONT + "\nA shipped copy.\n",
    ".hidden/manuscript_copy.md": FRONT + "\nHidden.\n",
    "author_draft.md": FRONT + "\nThe manuscript before the session.\n",
    "notes/writing.md": "# Writing\n\nNotes.\n",
}


@pytest.fixture()
def project(tmp_path):
    folder = tmp_path / "project"
    for relative, text in FILES.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (folder / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    return folder


def _found(project):
    return {item.path: item for item in look_alikes(read_map(project / "Makefile"))}


def _cli(command, args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(OSPIPE_DIR)
    return subprocess.run(
        [sys.executable, "-m", "ospipe", command] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def _procedure_reads_as_archived(project, relative):
    """The build procedure's own reading of the line, written out here. The first
    non-empty line after the front matter starts with `> ARCHIVE`, and the path after
    `superseded by` exists in the project."""
    text = (project / relative).read_text(encoding="utf-8")
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    banner = None
    for line in body.splitlines():
        if line.strip():
            banner = line.strip() if line.strip().startswith("> ARCHIVE") else None
            break
    if banner is None:
        return False
    match = re.search(r"superseded by (\S+)", banner)
    return match is not None and (project / match.group(1)).is_file()


class TestLookAlikes:
    def test_same_title_is_found(self, project):
        found = _found(project)
        assert found["drafts/early.md"] == LookAlike(
            path="drafts/early.md", claims="manuscript.md", reason="same title", archived=False
        )
        assert found["old/full_text.md"].claims == "manuscript.md"
        assert found["old/full_text.md"].reason == "same title"

    def test_a_name_holding_the_source_name_is_found(self, project):
        found = _found(project)
        assert found["manuscript_2026-09.md"] == LookAlike(
            path="manuscript_2026-09.md", claims="manuscript.md", reason="name", archived=False
        )
        assert found["drafts/slides_v1.md"] == LookAlike(
            path="drafts/slides_v1.md", claims="talk/slides.md", reason="name", archived=False
        )

    def test_builds_ship_hidden_and_sources_are_not_found(self, project):
        found = _found(project)
        for path in (
            "builds/manuscript/v001.md",
            "ship/manuscript/manuscript.md",
            ".hidden/manuscript_copy.md",
            "manuscript.md",
            "talk/slides.md",
            "notes/writing.md",
        ):
            assert path not in found

    def test_the_author_draft_is_never_a_look_alike(self, project):
        assert "author_draft.md" not in _found(project)

    def test_an_archived_draft_is_marked_and_not_advised(self, project):
        found = _found(project)
        assert found["drafts/archived.md"].archived is True
        run = _cli("products", [], project)
        assert "drafts/archived.md" not in run.stdout

    def test_exactly_the_expected_look_alikes(self, project):
        assert sorted(_found(project)) == [
            "drafts/archived.md",
            "drafts/early.md",
            "drafts/slides_v1.md",
            "manuscript_2026-09.md",
            "old/full_text.md",
        ]


class TestProductsAdvice:
    def test_each_unarchived_look_alike_is_printed(self, project):
        run = _cli("products", [], project)
        assert run.returncode == 0, run.stderr
        lines = run.stdout.splitlines()
        assert "not archived: drafts/early.md reads as manuscript.md (same title)" in lines
        assert "not archived: old/full_text.md reads as manuscript.md (same title)" in lines
        assert "not archived: manuscript_2026-09.md reads as manuscript.md (name)" in lines
        assert "not archived: drafts/slides_v1.md reads as talk/slides.md (name)" in lines
        assert sum(1 for line in lines if line.startswith("not archived: ")) == 4

    def test_advice_leaves_a_problem_exit_alone(self, project):
        (project / "Makefile").write_text(
            MAKEFILE + "broken:\n\t$(OSPIPE) build --manifest $(MANIFEST) --builds-dir builds/broken\n",
            encoding="utf-8",
        )
        run = _cli("products", [], project)
        assert run.returncode == 2
        assert "not archived: drafts/early.md reads as manuscript.md (same title)" in run.stdout


class TestArchive:
    def test_after_front_matter(self, project):
        draft = project / "drafts" / "early.md"
        before = draft.read_text(encoding="utf-8")
        run = _cli("archive", ["drafts/early.md", "--date", "2026-10-28", "--by", "manuscript.md"], project)
        assert run.returncode == 0, run.stderr
        fence_end = before.index("---\n", 4) + len("---\n")
        expected = (
            before[:fence_end]
            + "> ARCHIVE 2026-10-28: superseded by manuscript.md\n\n"
            + before[fence_end:]
        )
        assert draft.read_text(encoding="utf-8") == expected
        products = _cli("products", [], project)
        assert "drafts/early.md" not in products.stdout
        assert _found(project)["drafts/early.md"].archived is True
        assert _procedure_reads_as_archived(project, "drafts/early.md")

    def test_without_front_matter(self, project):
        draft = project / "manuscript_2026-09.md"
        before = draft.read_bytes()
        run = _cli(
            "archive", ["manuscript_2026-09.md", "--date", "2026-10-28", "--by", "manuscript.md"], project
        )
        assert run.returncode == 0, run.stderr
        assert draft.read_bytes() == b"> ARCHIVE 2026-10-28: superseded by manuscript.md\n\n" + before
        assert "manuscript_2026-09.md" not in _cli("products", [], project).stdout
        assert _procedure_reads_as_archived(project, "manuscript_2026-09.md")

    def test_the_function_keeps_every_other_byte(self, project):
        draft = project / "old" / "full_text.md"
        before = draft.read_bytes()
        archive(str(draft), str(project / "manuscript.md"), read_map(project / "Makefile"), on="2026-10-28")
        after = draft.read_bytes()
        assert after == b"> ARCHIVE 2026-10-28: superseded by manuscript.md\n\n" + before

    def test_the_superseding_path_is_relative_to_the_project(self, project):
        archive("drafts/slides_v1.md", "talk/slides.md", read_map(project / "Makefile"), on="2026-10-28")
        text = (project / "drafts" / "slides_v1.md").read_text(encoding="utf-8")
        assert text.startswith("> ARCHIVE 2026-10-28: superseded by talk/slides.md\n\n")
        assert _procedure_reads_as_archived(project, "drafts/slides_v1.md")

    def test_the_date_defaults_to_today(self, project):
        import datetime

        archive("drafts/early.md", "manuscript.md", read_map(project / "Makefile"))
        text = (project / "drafts" / "early.md").read_text(encoding="utf-8")
        assert "> ARCHIVE {0}: superseded by manuscript.md\n".format(datetime.date.today().isoformat()) in text

    def test_nothing_is_moved_renamed_or_deleted(self, project):
        def listing():
            return sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))

        before = listing()
        archive("drafts/early.md", "manuscript.md", read_map(project / "Makefile"), on="2026-10-28")
        assert listing() == before


class TestArchiveRefusals:
    @pytest.mark.parametrize(
        "draft, by, said",
        [
            ("drafts/archived.md", "manuscript.md", "already has an archive line"),
            ("manuscript.md", "drafts/early.md", "source"),
            ("talk/slides.md", "manuscript.md", "source"),
            ("drafts/early.md", "nowhere.md", "does not exist"),
            ("author_draft.md", "manuscript.md", "author_draft.md"),
            ("drafts/missing.md", "manuscript.md", "does not exist"),
        ],
    )
    def test_refusal_leaves_the_file_unchanged(self, project, draft, by, said):
        path = project / draft
        before = path.read_bytes() if path.is_file() else None
        with pytest.raises(ArchiveError) as exc:
            archive(draft, by, read_map(project / "Makefile"), on="2026-10-28")
        assert any(said in problem for problem in exc.value.problems)
        if before is None:
            assert not path.exists()
        else:
            assert path.read_bytes() == before

    def test_the_command_exits_2_on_refusal(self, project):
        before = (project / "drafts" / "archived.md").read_bytes()
        run = _cli("archive", ["drafts/archived.md", "--date", "2026-10-28", "--by", "manuscript.md"], project)
        assert run.returncode == 2
        assert "already has an archive line" in run.stderr
        assert (project / "drafts" / "archived.md").read_bytes() == before

    def test_a_bad_date_exits_2(self, project):
        before = (project / "drafts" / "early.md").read_bytes()
        run = _cli("archive", ["drafts/early.md", "--date", "28-10-2026", "--by", "manuscript.md"], project)
        assert run.returncode == 2
        assert (project / "drafts" / "early.md").read_bytes() == before

    def test_a_missing_build_file_exits_2(self, tmp_path):
        (tmp_path / "draft.md").write_text("# Draft\n", encoding="utf-8")
        (tmp_path / "paper.md").write_text("# Paper\n", encoding="utf-8")
        run = _cli("archive", ["draft.md", "--by", "paper.md"], tmp_path)
        assert run.returncode == 2
        assert (tmp_path / "draft.md").read_text(encoding="utf-8") == "# Draft\n"
