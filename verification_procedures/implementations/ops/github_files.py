"""List the files in the project snapshot, block on a repository already there, a
credential-like name, or a file too large, warn on data in a public repository, and
record each file's checksum.

Names lose a leading './', and Mac extras ('._*' and '.DS_Store') are skipped. Only
regular files in the tar count. Any path with a part named '.git' is blocking, at the
top or in a subfolder, since git would leave a nested repository out of the commit
without saying so. The snapshot leaves these out, as the comparison before any
command does.
"""
import fnmatch
import hashlib
import posixpath
import tarfile

import _lib

CHECK = "github_files"
MB = 1024 * 1024
CREDENTIAL = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
              "id_ecdsa*", ".netrc", "credentials*", "*secret*", "*token*")
DATA = (".csv", ".tsv", ".xlsx", ".xls", ".sav", ".dta", ".rds", ".rdata", ".parquet", ".sqlite", ".db")


def clean_name(name):
    while name.startswith("./"):
        name = name[2:]
    return name


def skipped(name):
    base = posixpath.basename(name)
    return base.startswith("._") or base == ".DS_Store"


def credential_like(name):
    base = posixpath.basename(name).lower()
    return any(fnmatch.fnmatchcase(base, pattern) for pattern in CREDENTIAL)


def data_file(name):
    return posixpath.splitext(name)[1].lower() in DATA


def in_repository(name):
    return ".git" in name.split("/")


def excluded_by(name, exclude):
    for entry in exclude:
        if entry.endswith("/"):
            if name.startswith(entry):
                return True
        elif name == entry:
            return True
    return False


settings = _lib.read_json("settings.json")
exclude = settings["exclude"]
public = settings["visibility"] == "public"
max_bytes = settings["max_file_mb"] * MB
warn_bytes = settings["warn_file_mb"] * MB

contents = {}
with tarfile.open(_lib.path("project.tar")) as tf:
    for member in tf.getmembers():
        if not member.isfile():
            continue
        name = clean_name(member.name)
        if not name or skipped(name):
            continue
        contents[name] = tf.extractfile(member).read()

findings, commit, excluded, snapshot = [], [], [], {}
already_repo = False
for name in sorted(contents):
    data = contents[name]
    if in_repository(name):
        already_repo = True
        findings.append(_lib.finding(CHECK, "blocking", name,
                                     "The project already holds a repository, and this procedure starts one."
                                     if name.startswith(".git/") else
                                     "A subfolder holds a repository, and git would leave its files out of the commit."))
        continue
    snapshot[name] = "sha256:" + hashlib.sha256(data).hexdigest()
    if excluded_by(name, exclude):
        excluded.append(name)
        if credential_like(name):
            findings.append(_lib.finding(CHECK, "info", name,
                                         "A credential-like file is excluded and stays out of the repository."))
        continue
    blocked = False
    if credential_like(name):
        blocked = True
        findings.append(_lib.finding(CHECK, "blocking", name,
                                     "A credential-like file would be committed, so exclude it or move it out of the project."))
    if len(data) > max_bytes:
        blocked = True
        findings.append(_lib.finding(CHECK, "blocking", name,
                                     "The file is larger than max_file_mb.", "{} bytes".format(len(data))))
    elif len(data) > warn_bytes:
        findings.append(_lib.finding(CHECK, "warning", name,
                                     "The file is larger than warn_file_mb.", "{} bytes".format(len(data))))
    if data_file(name):
        if public:
            findings.append(_lib.finding(CHECK, "warning", name,
                                         "A data file would go to a public repository, so check that it holds no personal information."))
        else:
            findings.append(_lib.finding(CHECK, "info", name,
                                         "A data file goes to a private repository, so check that it holds no personal information."))
    if not blocked:
        commit.append(name)

_lib.write_json("files.json", {
    "blocked": sum(1 for f in findings if f["severity"] == "blocking"),
    "already_repo": already_repo,
    "files": len(contents),
    "commit": commit,
    "excluded": excluded,
    "gitignore": list(exclude),
    "snapshot": snapshot,
})
_lib.emit_findings(CHECK, findings)
