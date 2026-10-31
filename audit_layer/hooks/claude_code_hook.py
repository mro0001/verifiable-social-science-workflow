"""The Claude Code hook script, which starts the sweep of one session file.

Claude Code runs it at the end of each turn (Stop), when a subagent finishes
(SubagentStop), and when a session ends (SessionEnd), as INSTALL.md says to
set up by hand (plan choice 7). Claude Code gives the hook a JSON object on
standard input. The script takes agent_transcript_path when the object has
one, else transcript_path, and starts

    python3 -m audit_layer sweep --harness claude_code --file <path>

as a detached process writing to <audit home>/hook.log, so a turn never waits
on capture. The python3 is the one running this script. The audit home is
the AUDIT_HOME environment variable, else ~/.audit_layer, as for every
audit_layer command.

The script always exits 0 and writes nothing to standard output, so it never
stops or slows a turn. Input it cannot use becomes one line in hook.log with
the time, the hook event, and the outcome, and never a path, since a harness
folder's name can spell out the folder a session ran in. When the audit home
does not exist the script writes nothing and starts nothing.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run by its absolute path, the script finds the audit_layer package in the
# repository that holds it. The package is imported only inside main's guard.
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LOG = "hook.log"

HARNESS = "claude_code"


def handle(payload, home, spawn) -> None:
    """Ask spawn to start the sweep of the transcript the hook's payload names.

    spawn is called with the command and the log file's path. A payload with
    no transcript path starts nothing and becomes one line in the log.
    """
    home = Path(home)
    path = _transcript(payload)
    if path is None:
        _log(home, payload, "no transcript path was given, so no sweep was started")
        return
    command = [sys.executable, "-m", "audit_layer", "sweep", "--harness", HARNESS, "--file", path]
    spawn(command, home / LOG)


def detached(command, log):
    """Start command as a process of its own session, writing to log, and do not wait for it.

    It runs from the repository folder, so python3 -m audit_layer finds the
    package, with AUDIT_HOME set to the folder that holds the log.
    """
    from audit_layer.settings import HOME_VARIABLE

    log = Path(log)
    environment = dict(os.environ)
    environment[HOME_VARIABLE] = str(log.parent)
    with log.open("a", encoding="utf-8") as out:
        return subprocess.Popen(
            command,
            cwd=str(REPO),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def main() -> int:
    """Read the hook's JSON from standard input and handle it, always giving 0.

    The audit_layer package is imported here, inside the guard, so a python3
    that cannot import it (one without PyYAML, say) still gives 0 and prints
    nothing.
    """
    try:
        from audit_layer.settings import audit_home

        home = audit_home()
        text = sys.stdin.read()
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        handle(payload, home, detached)
    except Exception:  # noqa: BLE001, a hook never stops a turn
        pass
    return 0


def _transcript(payload):
    """The transcript path the payload names, the subagent's first, or None."""
    if not isinstance(payload, dict):
        return None
    for key in ("agent_transcript_path", "transcript_path"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _log(home: Path, payload, outcome: str) -> None:
    """Add one line to the hook's log, with the time, the hook event, and the outcome.

    The event is logged only when it is a plain name, so the line never holds
    a path. A log in an audit home that does not exist is not written.
    """
    event = payload.get("hook_event_name") if isinstance(payload, dict) else None
    if not (isinstance(event, str) and event.isidentifier()):
        event = "unknown_event"
    if not isinstance(payload, dict):
        outcome = "the hook's input was not a JSON object, so no sweep was started"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not home.is_dir():
        return
    with (home / LOG).open("a", encoding="utf-8") as out:
        out.write(f"{stamp} {event} {outcome}\n")


if __name__ == "__main__":
    sys.exit(main())
