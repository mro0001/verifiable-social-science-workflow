"""Helpers for the end-to-end tests on the test story.

Each helper reaches one layer only through its command line or its files, as a
scholar would. None imports a layer's code. Every command must succeed, and a
failed one stops the test with its output.

- workspace(tmp) copies the story project to tmp/project and writes each story
  session into tmp/sessions/ with {{PROJECT}} replaced by the copy's real path.
- audit(tmp, *args) runs python3 -m audit_layer with AUDIT_HOME at tmp/audit_home.
- build(project, purpose) builds the manuscript with ospipe, using the arguments
  the project README gives, and returns the newest ledger row.
- flags(row) gives the streams the row's verification cell names.
- handoff(script, *args) runs one script in handoffs/.
- run(graph, run_dir, inputs, judge, second) runs vg.py run offline. Judge and
  second name recorded answer files.
- provenance(tmp, project) writes out the audit layer's citation provenance
  record for the project from the story's reference list, as
  audit_out/citation_provenance.yaml in tmp, and gives its path for the
  references handoff's --provenance.
- decide(run_dir, item, approve) records the scholar's approve or hold.
- items(run_dir) reads the items of the run's results.json.
- session_id(name) gives a story session's id, and public_id(session) its
  public id, S and the first 12 hex characters of the sha256 of the id (Track
  P choice 1), worked out here from the rule, not from the audit layer's code.
- fields(run_dir) reads the items of the run's fields.json, and report(run_dir)
  its report.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STORY = Path(__file__).resolve().parents[1]
ROOT = STORY.parents[1]
PROJECT = STORY / "project"
SESSIONS = STORY / "sessions" / "claude_code"
HANDOFFS = ROOT / "handoffs"
OSPIPE = ROOT / "ospipe"
VERIFICATION = ROOT / "verification_procedures"
TOKEN = "{{PROJECT}}"
REFERENCES = STORY / "references"
LEDGER = Path("builds") / "manuscript" / "BUILDS.md"
SCHOLAR = "story scholar"


def _call(command, cwd, env=None):
    done = subprocess.run([str(part) for part in command], cwd=str(cwd), env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, "%s\nexit %d\n%s%s" % (
        " ".join(str(part) for part in command), done.returncode, done.stdout, done.stderr)
    return done


def workspace(tmp):
    """Copy the story project into tmp and write its sessions there. Gives the
    project's real path, the one the sessions name."""
    tmp = Path(tmp)
    shutil.copytree(str(PROJECT), str(tmp / "project"))
    project = Path(os.path.realpath(str(tmp / "project")))
    sessions = tmp / "sessions"
    sessions.mkdir()
    for session in sorted(SESSIONS.glob("*.jsonl")):
        text = session.read_text(encoding="utf-8")
        (sessions / session.name).write_text(text.replace(TOKEN, str(project)), encoding="utf-8")
    return project


def audit(tmp, *args):
    env = dict(os.environ, AUDIT_HOME=str(Path(tmp) / "audit_home"))
    return _call([sys.executable, "-m", "audit_layer"] + list(args), ROOT, env)


def build(project, purpose):
    """Build the manuscript as the project README says, and give the newest
    ledger row as a dict keyed by the ledger's header names."""
    env = dict(os.environ, PYTHONPATH=str(OSPIPE))
    _call([sys.executable, "-m", "ospipe", "build", "--manuscript", "manuscript.md",
           "--manifest", "numbers.yml", "--tables-dir", ".", "--bib", "refs.bib",
           "--builds-dir", "builds/manuscript", "--purpose", purpose], project, env)
    rows = [line.strip() for line in (Path(project) / LEDGER).read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("|")]
    header = _cells(rows[0])
    return dict(zip(header, _cells(rows[-1])))


def _cells(line):
    return [cell.strip() for cell in line[1:-1].split("|")]


def flags(row):
    """The streams after unverified: in the row's verification cell, or none for verified."""
    cell = row["verification"]
    if cell == "verified":
        return set()
    prefix = "unverified:"
    assert cell.startswith(prefix), cell
    return {name.strip() for name in cell[len(prefix):].split(",") if name.strip()}


def handoff(script, *args):
    return _call([sys.executable, str(HANDOFFS / script)] + list(args), ROOT)


def run(graph, run_dir, inputs, judge=None, second=None):
    command = [sys.executable, "vg.py", "run", graph, "--run", run_dir, "--inputs", inputs]
    if judge is not None:
        command += ["--judge", "recorded:%s" % judge]
    if second is not None:
        command += ["--second", "recorded:%s" % second]
    return _call(command, VERIFICATION, dict(os.environ, VG_OFFLINE="1"))


def provenance(tmp, project):
    out = Path(tmp) / "audit_out" / "citation_provenance.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    audit(tmp, "write-out", "citation-provenance", "--project", str(project),
          "--references", str(REFERENCES / "refs.yaml"), "--out", str(out))
    return out


def decide(run_dir, item, approve):
    choice = "--approve" if approve else "--hold"
    return _call([sys.executable, "vg.py", "decide", "--run", run_dir, "--item", item, choice,
                  "--by", SCHOLAR], VERIFICATION)


def items(run_dir):
    with open(str(Path(run_dir) / "results.json"), encoding="utf-8") as f:
        return json.load(f)["items"]


def fields(run_dir):
    with open(str(Path(run_dir) / "files" / "fields.json"), encoding="utf-8") as f:
        return json.load(f)["items"]


def report(run_dir):
    return (Path(run_dir) / "files" / "report.md").read_text(encoding="utf-8")


def session_id(name):
    """The id of the story session kept in the file name, from its first record."""
    first = (SESSIONS / name).read_text(encoding="utf-8").splitlines()[0]
    return json.loads(first)["sessionId"]


def public_id(session):
    return "S" + hashlib.sha256(session.encode("utf-8")).hexdigest()[:12]
