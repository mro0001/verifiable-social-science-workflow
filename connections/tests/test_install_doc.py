"""Tests for the install instructions, connections/README.md (Track D, step D21).

The track installs nothing on the machine. The README says what each
connector is and its command, where events land, and how capture reads them,
then gives the install steps, all done by hand, each with how to undo it
(A2.2 paragraph 2, A2.6 paragraph 2, A4).

These tests check that every json block in the README parses, that every
python3 -m connections command it names is accepted, and that running each
command once leaves no file under the home folder outside the connections
home, the audit home, and the project folder. Every test runs with HOME,
CONNECTIONS_HOME, and AUDIT_HOME in a temporary folder. Run from the
repository root with python3 -m pytest -q connections/tests.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "connections" / "README.md"

COMMAND = re.compile(r"python3 -m connections((?: [a-z]+){1,2})")


def readme():
    return README.read_text(encoding="utf-8")


def blocks(language):
    return re.findall(r"```" + language + r"\n(.*?)```", readme(), flags=re.S)


def named_commands():
    """Each python3 -m connections command the README names, as its words before any option."""
    found = set()
    for match in COMMAND.finditer(readme()):
        found.add(tuple(match.group(1).split()))
    return sorted(found)


def test_the_readme_has_json_blocks_and_each_parses():
    found = blocks("json")
    assert len(found) >= 2
    for block in found:
        json.loads(block)


def test_the_readme_yaml_blocks_parse():
    for block in blocks("yaml"):
        yaml.safe_load(block)


def test_the_readme_names_every_command():
    names = {" ".join(words) for words in named_commands()}
    for command in (
        "wrap",
        "serve kb",
        "serve audit",
        "serve events",
        "provider show",
        "provider set",
        "adapt citations",
        "adapt word",
        "adapt r",
        "adapt quarto",
        "trigger hook",
        "trigger make",
    ):
        assert command in names, command


def test_every_command_the_readme_names_is_accepted():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    commands = named_commands()
    assert commands
    for words in commands:
        done = subprocess.run(
            [sys.executable, "-m", "connections", *words, "--help"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=env,
            timeout=60,
        )
        assert done.returncode == 0, (words, done.stderr)


OTHER = re.compile(r"python3 (-m audit_layer(?:\.kb)?|handoffs/[a-z_]+\.py|vg\.py)((?: [^\n;&|#]*)?)")


def other_commands():
    """Each audit_layer, handoffs/, and vg.py command in the README's sh blocks.

    Each is (program, subcommand words, options), with the words before the
    first option and every --option the line uses.
    """
    found = []
    for block in blocks("sh"):
        for match in OTHER.finditer(block):
            tokens = shlex.split(match.group(2))
            words = []
            for token in tokens:
                if token.startswith("-"):
                    break
                words.append(token)
            options = sorted({t for t in tokens if t.startswith("--")})
            found.append((match.group(1), tuple(words), tuple(options)))
    return found


def test_every_other_command_the_readme_names_is_accepted_with_its_options(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["HOME"] = str(tmp_path)
    env["CONNECTIONS_HOME"] = str(tmp_path / "connections_home")
    env["AUDIT_HOME"] = str(tmp_path / "audit_home")
    commands = other_commands()
    programs = {program for program, _, _ in commands}
    for program in ("-m audit_layer", "-m audit_layer.kb", "vg.py",
                    "handoffs/results_to_pipeline.py", "handoffs/project_to_references.py"):
        assert program in programs, program
    for program, words, options in commands:
        if program == "vg.py":
            argv = [sys.executable, "vg.py"]
            cwd = ROOT / "verification_procedures"
        elif program.startswith("-m "):
            argv = [sys.executable, "-m", program[3:]]
            cwd = ROOT
        else:
            argv = [sys.executable, program]
            cwd = ROOT
        done = subprocess.run(
            argv + list(words) + ["--help"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            env=env,
            timeout=60,
        )
        assert done.returncode == 0, (program, words, done.stderr)
        for option in options:
            assert option in done.stdout, (program, words, option)


def test_the_start_script_runs_the_full_run_under_make_and_the_quick_run_otherwise():
    script = [b for b in blocks("sh") if "vg.py run citations" in b]
    assert len(script) == 1
    text = script[0]
    assert '"$MAKELEVEL"' in text
    runs = [line for line in text.splitlines() if "vg.py run citations" in line]
    assert any("--quick" in line for line in runs)
    full = [line for line in runs if "--quick" not in line]
    assert full and all("--judge live" in line for line in full)
    assert "handoffs/results_to_pipeline.py" in text
    assert "--stream citations" in text
    assert text.index("MAKELEVEL") < text.index("results_to_pipeline.py")
    assert "is still yours to start" not in readme()


def test_the_hooks_block_holds_both_triggers_and_the_capture_command():
    hooks = None
    for block in blocks("json"):
        data = json.loads(block)
        if "hooks" in data:
            hooks = data["hooks"]
    assert hooks is not None
    post = hooks["PostToolUse"]
    assert post[0]["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert "python3 -m connections trigger hook" in post[0]["hooks"][0]["command"]
    stop = [h["command"] for entry in hooks["Stop"] for h in entry["hooks"]]
    assert any("audit_layer/hooks/claude_code_hook.py" in c for c in stop)
    assert any("python3 -m connections trigger hook" in c for c in stop)


def test_the_servers_block_names_the_three_servers():
    servers = None
    for block in blocks("json"):
        data = json.loads(block)
        if "mcpServers" in data:
            servers = data["mcpServers"]
    assert sorted(servers) == ["workflow-audit", "workflow-events", "workflow-kb"]
    text = readme()
    for name in ("workflow-kb", "workflow-audit", "workflow-events"):
        assert f"claude mcp add -s user {name} -e PYTHONPATH=" in text
        assert f"claude mcp remove -s user {name}" in text


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A temporary home folder holding the two homes and a project folder."""
    home = tmp_path / "home"
    home.mkdir()
    connections = home / "connections_home"
    audit = home / "audit_home"
    project = home / "project"
    project.mkdir()
    audit.mkdir()
    (audit / "settings.yaml").write_text("excluded_folders: []\n", encoding="utf-8")
    connections.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CONNECTIONS_HOME", str(connections))
    monkeypatch.setenv("AUDIT_HOME", str(audit))
    monkeypatch.delenv("WORKFLOW_MODEL_KEY", raising=False)
    return {"home": home, "connections": connections, "audit": audit, "project": project}


def run(args, cwd, stdin=""):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "connections", *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=120,
    )


INITIALIZE = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
) + "\n"


def files_under(folder):
    return [p for p in Path(folder).rglob("*") if p.is_file()]


def test_running_each_command_writes_only_in_the_two_homes_and_the_project(machine):
    home, connections, project = machine["home"], machine["connections"], machine["project"]
    (connections / "provider.yaml").write_text(
        "base_url: http://127.0.0.1:9/v1\nmodel: test-model\n", encoding="utf-8"
    )
    marker = "import pathlib, sys; pathlib.Path(sys.argv[1], 'started').write_text('yes')"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(marker)} {{project}}"
    (connections / "triggers.yaml").write_text(
        yaml.safe_dump({"start": {"prose": command}}), encoding="utf-8"
    )
    (project / "manuscript.md").write_text("# A paper\n", encoding="utf-8")
    (project / "numbers.yml").write_text("effect: 0.42\n", encoding="utf-8")
    export = project / "export.json"
    export.write_text(
        json.dumps([{"id": "smith2020", "type": "article-journal", "title": "A title",
                     "issued": {"date-parts": [[2020]]}}]),
        encoding="utf-8",
    )

    assert run(["provider", "show"], project).returncode == 0
    wrapped = run(["wrap", "--", sys.executable, "-c", "open('o.txt', 'w').write('x')"], project)
    assert wrapped.returncode == 0, wrapped.stderr
    adapted = run(["adapt", "citations", "--out", str(project / "refs"), "--export", str(export)], project)
    assert adapted.returncode == 0, adapted.stderr
    edit = {"hook_event_name": "PostToolUse", "cwd": str(project), "tool_name": "Edit",
            "tool_input": {"file_path": str(project / "manuscript.md")}}
    assert run(["trigger", "hook"], project, json.dumps(edit)).returncode == 0
    stop = {"hook_event_name": "Stop", "cwd": str(project)}
    stopped = run(["trigger", "hook"], project, json.dumps(stop))
    assert stopped.returncode == 0
    assert "Verification started for prose." in stopped.stdout
    end = time.time() + 15
    while not (project / "started").exists() and time.time() < end:
        time.sleep(0.05)
    assert (project / "started").exists()
    (project / "started").unlink()
    made = run(["trigger", "make", "--project", str(project)], project)
    assert made.returncode == 0
    assert "verify prose stale, started, exit 0" in made.stdout
    for server in (["serve", "kb", "--index", str(project / "kb_index.json")],
                   ["serve", "audit"], ["serve", "events"]):
        served = run(server, project, INITIALIZE)
        assert served.returncode == 0, served.stderr
        reply = json.loads(served.stdout.splitlines()[0])
        assert reply["id"] == 1 and "serverInfo" in reply["result"]

    assert list((connections / "events").glob("*.jsonl"))
    allowed = (connections, machine["audit"], project)
    stray = [
        str(p) for p in files_under(home)
        if not any(str(p).startswith(str(a) + os.sep) for a in allowed)
    ]
    assert stray == []
