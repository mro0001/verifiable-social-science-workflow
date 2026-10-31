"""Regenerate the build-stream fixtures from source/ (synthetic project, no real text).

    python3 fixtures/build/make_fixtures.py

clean/   the project after three real builds (make paper twice, make slides once),
         plus a session record in which the AI only wrote canonical sources.
seeded/  a copy of clean/ with faults planted AFTER the builds (listed in truth.yaml).

Each fixture holds project/ (the readable tree) and project.tar (the same tree,
packed deterministically: the shape `git archive` gives in real use). The run reads
only the tar; init_run copies top-level files only. Needs make and pandoc.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "source")
EPOCH = {"v1": "1790000000", "v2": "1790600000", "s1": "1790700000"}  # fixed ledger dates


# /usr/bin/make is an xcrun shim that fails under an x86_64 python; call the real binary
MAKE = next((m for m in ("/Library/Developer/CommandLineTools/usr/bin/make",) if os.path.exists(m)), "make")


def make(proj, target, epoch, purpose):
    env = dict(os.environ, SOURCE_DATE_EPOCH=epoch)
    subprocess.run([MAKE, "-s", target, "PURPOSE=" + purpose], cwd=proj, env=env, check=True)


def pack(proj, tar_path):
    names = []
    for root, dirs, files in os.walk(proj):
        dirs.sort()
        for fn in sorted(files):
            names.append(os.path.relpath(os.path.join(root, fn), proj))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name in sorted(names):
            with open(os.path.join(proj, name), "rb") as f:
                data = f.read()
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tf.addfile(info, io.BytesIO(data))
    with open(tar_path, "wb") as f:
        f.write(buf.getvalue())


def write_trace(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def build_writes(session, target, builds, version, ext="html"):
    tool = "make " + target
    return [{"session": session, "actor": "build", "tool": tool, "path": f"{builds}/{version}.md"},
            {"session": session, "actor": "build", "tool": tool, "path": f"{builds}/{version}.{ext}"},
            {"session": session, "actor": "build", "tool": tool, "path": f"{builds}/BUILDS.md"}]


CLEAN_TRACE = (
    [{"session": "s-0101", "actor": "ai", "tool": "Write", "path": "paper/paper.md"},
     {"session": "s-0101", "actor": "author", "tool": "Edit", "path": "build_prefs.yaml"}]
    + build_writes("s-0101", "paper", "builds/paper", "v001")
    + [{"session": "s-0102", "actor": "ai", "tool": "Edit", "path": "paper/paper.md"},
       {"session": "s-0102", "actor": "ai", "tool": "Write", "path": "slides/slides.md"}]
    + build_writes("s-0102", "paper", "builds/paper", "v002")
    + build_writes("s-0102", "slides", "builds/slides", "v001")
    + [{"session": "s-0103", "actor": "author", "tool": "Word", "path": "builds/paper/returns/v002_author.docx"},
       {"session": "s-0103", "actor": "ai", "tool": "Edit", "path": "notes/ideas.md"}]
)


def reset(path):
    if os.path.exists(path):
        shutil.rmtree(path)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def edit(path, old, new, count=1):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert old in text, (path, old)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new, count))


def build_clean():
    out = os.path.join(HERE, "clean")
    proj = os.path.join(out, "project")
    reset(proj)
    shutil.copytree(SOURCE, proj)
    paper = os.path.join(proj, "paper", "paper.md")
    with open(paper, encoding="utf-8") as f:
        final = f.read()
    # v001 is cut before the Limitations section existed
    early = re.sub(r"# Limitations\n\n.*?\n\n", "", final, flags=re.S)
    with open(paper, "w", encoding="utf-8") as f:
        f.write(early)
    make(proj, "paper", EPOCH["v1"], "first full draft")
    with open(paper, "w", encoding="utf-8") as f:
        f.write(final)
    make(proj, "paper", EPOCH["v2"], "limitations added")
    make(proj, "slides", EPOCH["s1"], "district association talk")
    write_trace(os.path.join(out, "session_writes.jsonl"), CLEAN_TRACE)
    pack(proj, os.path.join(out, "project.tar"))
    return out


def build_seeded(clean):
    out = os.path.join(HERE, "seeded")
    proj = os.path.join(out, "project")
    reset(proj)
    shutil.copytree(os.path.join(clean, "project"), proj)
    p = lambda *a: os.path.join(proj, *a)
    # B1 a ledgered build edited after it was cut (the ledger was left alone)
    edit(p("builds", "paper", "v001.html"), "carry lessons", "carry the lessons")
    # B2 a direct edit to a build, with the ledger hash rewritten to hide it
    edit(p("builds", "paper", "v002.html"), "<p>The survey is cross-sectional",
         "<p>Monthly meetings clearly cause better learning.</p>\n<p>The survey is cross-sectional")
    old = sha(p("builds", "paper", "v002.html"))
    with open(p("builds", "paper", "BUILDS.md"), encoding="utf-8") as f:
        rows = f.read().splitlines()
    for i, ln in enumerate(rows):
        if ln.startswith("| v002 "):
            cells = ln.split(" | ")
            cells[4] = old
            rows[i] = " | ".join(cells)
    with open(p("builds", "paper", "BUILDS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    # B3 a result typed into the canonical text instead of pulled from numbers.yml
    edit(p("paper", "paper.md"), "{{num:effect_monthly}}", "0.31")
    # B4 a preference the author declared that the map does not carry
    edit(p("build_prefs.yaml"), "slides:\n  format: slides\n", "slides:\n  format: slides\n  number_sections: true\n")
    # B6 a second file claiming to be the paper, with no ARCHIVE line
    with open(p("paper", "paper.md"), encoding="utf-8") as f:
        canon = f.read()
    with open(p("drafts", "paper_full.md"), "w", encoding="utf-8") as f:
        f.write(canon.replace("{{num:n_districts}}", "46").replace("{{num:n_members}}", "1,190"))
    # B7 a placeholder whose key the numbers file lacks
    edit(p("slides", "slides.md"), "districts surveyed", "districts surveyed, {{num:n_teams}} teams")
    # B5 the AI wrote into the builds folder directly (the session record shows it)
    trace = CLEAN_TRACE + [
        {"session": "s-0104", "actor": "ai", "tool": "Edit", "path": "builds/slides/v001.html"},
        {"session": "s-0104", "actor": "ai", "tool": "Edit", "path": "paper/paper.md"},
    ]
    write_trace(os.path.join(out, "session_writes.jsonl"), trace)
    pack(proj, os.path.join(out, "project.tar"))


if __name__ == "__main__":
    build_seeded(build_clean())
    print("fixtures written")
