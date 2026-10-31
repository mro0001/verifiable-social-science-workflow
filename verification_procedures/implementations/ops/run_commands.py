"""Run the planned commands in order when the settings file sets apply to true, after
checking that the folder still matches its snapshot and holds no repository yet whenever
the plan names a folder (an empty snapshot is still compared), and stop at the first
failure. A plan with an empty cwd, such as the cluster plan, names no folder, so it is
not compared. Otherwise list the commands as planned.

Shared by the operational procedures. The step is marked replay network, since what it
runs acts outside the run, so verify hashes its outputs and never reruns it. A missing
program counts as exit 127 and a timeout as exit 124.
"""
import hashlib
import os
import shlex
import subprocess

import _lib

CHECK = "run_commands"
TIMEOUT = 300
TAIL = 500
SHOWN = 5


def tail(text):
    return (text or "")[-TAIL:]


def skipped(rel):
    base = os.path.basename(rel)
    return rel == ".git" or rel.startswith(".git/") or base.startswith("._") or base == ".DS_Store"


def live_files(folder):
    out = {}
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for fn in names:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            if skipped(rel):
                continue
            h = hashlib.sha256()
            with open(full, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 16), b""):
                    h.update(chunk)
            out[rel] = "sha256:" + h.hexdigest()
    return out


def differences(folder, snapshot):
    """Each way the folder differs from the snapshot. The snapshot never holds a
    repository, so a .git already in the folder counts as new."""
    if not os.path.isdir(folder):
        return ["missing folder {}".format(folder)]
    live = live_files(folder)
    out = ["new .git"] if os.path.lexists(os.path.join(folder, ".git")) else []
    for rel in sorted(set(snapshot) | set(live)):
        if rel not in live:
            out.append("missing {}".format(rel))
        elif rel not in snapshot:
            out.append("new {}".format(rel))
        elif live[rel] != snapshot[rel]:
            out.append("changed {}".format(rel))
    return out


def last_line(text):
    """The last line that starts with fatal or error, else the last line that is not
    blank and not a hint."""
    lines = [ln.strip() for ln in (text or "").splitlines()
             if ln.strip() and not ln.strip().lower().startswith("hint:")]
    errors = [ln for ln in lines if ln.lower().startswith(("fatal:", "error:"))]
    return (errors or lines or [""])[-1]


settings = _lib.read_json("settings.json")
plan = _lib.read_json("commands.json")
commands = plan["commands"]
findings, results, refused, applied = [], [], "", False


def unrun(status):
    return [{"n": c["n"], "argv": c["argv"], "status": status} for c in commands]


if not settings["apply"]:
    results = unrun("planned")
    findings.append(_lib.finding(CHECK, "info", "commands",
                                 "{} commands are planned and none ran, since the settings file does not set apply to true.".format(len(commands))))
else:
    cwd = plan["cwd"] or None
    diffs = differences(plan["cwd"], plan["snapshot"]) if plan["cwd"] else []
    if diffs:
        if "new .git" in diffs:
            refused = ("The project folder already holds a repository, perhaps from an earlier run "
                       "that stopped, so finish it or remove it by hand before running again.")
        else:
            refused = "The project folder no longer matches the snapshot the file check saw."
        results = unrun("not run")
        findings.append(_lib.finding(CHECK, "blocking", "snapshot", refused + " Nothing ran.",
                                     "; ".join(diffs[:SHOWN]) + ("; and {} more".format(len(diffs) - SHOWN)
                                                                 if len(diffs) > SHOWN else "")))
    else:
        applied = True
        for w in plan["writes"]:
            target = os.path.join(plan["cwd"], w["path"])
            if not os.path.exists(target):
                with open(target, "w", encoding="utf-8") as f:
                    f.write(w["text"])
        failed = None
        for c in commands:
            if failed is not None:
                results.append({"n": c["n"], "argv": c["argv"], "status": "not run"})
                continue
            try:
                proc = subprocess.run(c["argv"], cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                                      text=True, timeout=TIMEOUT)
                code, out, err = proc.returncode, proc.stdout, proc.stderr
            except FileNotFoundError as e:
                code, out, err = 127, "", str(e)
            except subprocess.TimeoutExpired as e:
                code = 124
                out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
                err = "timed out after {} seconds".format(TIMEOUT)
            results.append({"n": c["n"], "argv": c["argv"], "status": "ok" if code == 0 else "failed",
                            "exit_code": code, "stdout_tail": tail(out), "stderr_tail": tail(err)})
            if code != 0:
                failed = c
                findings.append(_lib.finding(
                    CHECK, "blocking", "command {}".format(c["n"]),
                    "The command {} failed with exit {}{}.".format(
                        shlex.join(c["argv"]), code,
                        ", so the later commands did not run" if c is not commands[-1] else ""),
                    last_line(err) or last_line(out)))
        if failed is None:
            findings.append(_lib.finding(CHECK, "info", "commands", "All {} commands ran.".format(len(commands))))

_lib.write_json("applied.json", {"applied": applied, "refused": refused, "results": results})
_lib.emit_findings(CHECK, findings)
