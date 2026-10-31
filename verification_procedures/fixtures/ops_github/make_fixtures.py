"""Regenerate the fixtures for adding a project to GitHub (synthetic, no real secret).

    python3 fixtures/ops_github/make_fixtures.py

clean/   project.tar, the test story's project packed, and github.yaml, with a
         synthetic project folder and remote and apply false.
seeded/  the same project plus three files with credential-like names, each
         holding a line saying it is not a real secret, the same settings, and
         truth.yaml naming the three.

pack() writes a tar the same way every time (sorted names, mtime 0, mode 0644, USTAR
format), so a fixture changes only when the files do. The tests use it too.
"""
import io
import os
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
STORY = os.path.normpath(os.path.join(HERE, "..", "..", "..", "examples", "test_story", "project"))
NOT_SECRET = b"This is not a real secret. It is a synthetic file for a test.\n"
SEEDED = (".env", "keys/id_ed25519", "secrets/token.txt")
SETTINGS = """\
# Settings for adding the test story's project to GitHub. The folder and the
# remote are synthetic, and apply is false, so a run only plans.
project_dir: /scholar/test_story/project
repo_name: test-story
remote_url: git@github.example.invalid:scholar/test-story.git
apply: false
"""
TRUTH = """\
# The three files with credential-like names the seeded tar adds.
faults:
  - {id: f1, check: github_files, item: .env}
  - {id: f2, check: github_files, item: keys/id_ed25519}
  - {id: f3, check: github_files, item: secrets/token.txt}
"""


def pack(src_dir, tar_path, extra=None):
    """Write every file under src_dir, plus any extra {name: bytes}, into tar_path."""
    files = {}
    for root, dirs, names in os.walk(src_dir):
        dirs.sort()
        for fn in names:
            full = os.path.join(root, fn)
            with open(full, "rb") as f:
                files[os.path.relpath(full, src_dir).replace(os.sep, "/")] = f.read()
    files.update(extra or {})
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tf.addfile(info, io.BytesIO(data))
    with open(tar_path, "wb") as f:
        f.write(buf.getvalue())


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    for name in ("clean", "seeded"):
        os.makedirs(os.path.join(HERE, name), exist_ok=True)
        write(os.path.join(HERE, name, "github.yaml"), SETTINGS)
    pack(STORY, os.path.join(HERE, "clean", "project.tar"))
    pack(STORY, os.path.join(HERE, "seeded", "project.tar"), extra={n: NOT_SECRET for n in SEEDED})
    write(os.path.join(HERE, "seeded", "truth.yaml"), TRUTH)


if __name__ == "__main__":
    main()
