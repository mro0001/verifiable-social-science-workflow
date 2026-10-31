"""Connecting a project to a university computing cluster, written as a procedural
graph (graphs/ops_hpc.yaml).

The run reads the scholar's settings as hpc.yaml and, when given, a copy of the
scholar's ssh config as ssh_config. The host, the user, and the identity file are
synthetic, and no test reads a real ssh config or key. Every test sets HOME to a
temporary folder, and a run that applies uses a stand-in ssh first on PATH, a small
script that logs its arguments and exits with a set code. No test uses the network.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
FIX = ROOT / "fixtures" / "ops_hpc"
GRAPH = "graphs/ops_hpc.yaml"
TITLE = "Connect a project to a university computing cluster"
SETTINGS_FIELDS = ("task", "valid", "apply", "alias", "host", "user", "identity_file", "scheduler",
                   "modules", "remote_dir")
BLOCK = ("Host cluster\n"
         "    HostName cluster.example.edu\n"
         "    User scholar\n"
         "    IdentityFile ~/.ssh/id_ed25519_cluster\n"
         "    IdentitiesOnly yes\n")
PLANNED = [
    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "cluster", "true"],
    ["ssh", "cluster", "mkdir", "-p", "projects/test_story"],
    ["ssh", "cluster", "sinfo", "--version"],
    ["ssh", "cluster", "bash -lc 'module load python/3.11'"],
]
STEPS = {"hpc_settings", "hpc_ssh_entry", "hpc_plan", "run_commands", "report"}


def base_env(tmp_path, bin_dir=None):
    """An environment whose HOME is a temporary folder, with any stand-in programs
    first on PATH."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home))
    if bin_dir is not None:
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


def stand_in_ssh(tmp_path, code=0, stderr=""):
    """A stand-in ssh that appends its arguments as one JSON line to a log and exits
    with code, writing stderr first. It returns the bin folder and the log path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "ssh_calls.jsonl"
    script = bin_dir / "ssh"
    script.write_text(
        "#!{python}\n"
        "import json, sys\n"
        "with open({log!r}, 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.stderr.write({stderr!r})\n"
        "sys.exit({code})\n".format(python=sys.executable, log=str(log), stderr=stderr, code=code),
        encoding="utf-8")
    script.chmod(0o755)
    return bin_dir, log


def vg(*args, env=None):
    return subprocess.run(VG + list(args), cwd=ROOT, capture_output=True, text=True, env=env)


def run_on(tmp_path, inputs, name="run", env=None):
    run = tmp_path / name
    p = vg("run", GRAPH, "--run", str(run), "--inputs", str(inputs), env=env or base_env(tmp_path))
    assert p.returncode == 0, p.stdout + p.stderr
    return run


def clean_settings(**over):
    cfg = yaml.safe_load((FIX / "clean" / "hpc.yaml").read_text(encoding="utf-8"))
    cfg.update(over)
    return cfg


def inputs_with(tmp_path, cfg, ssh_config="clean", drop=()):
    """An inputs folder holding hpc.yaml and, unless ssh_config is None, a copy of an
    ssh config, the clean fixture's by default or the given text."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for key in drop:
        cfg.pop(key, None)
    (inputs / "hpc.yaml").write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
    if ssh_config == "clean":
        ssh_config = (FIX / "clean" / "ssh_config").read_text(encoding="utf-8")
    if ssh_config is not None:
        (inputs / "ssh_config").write_text(ssh_config, encoding="utf-8")
    return inputs


def read(run, name):
    return json.loads((run / "files" / name).read_text(encoding="utf-8"))


def findings(run, severity=None):
    return [f for f in read(run, "findings.json") if severity is None or f["severity"] == severity]


def problems(run):
    return [f for f in read(run, "findings.json") if f["severity"] in ("blocking", "warning")]


def skipped(run):
    lines = (run / "trail.jsonl").read_text(encoding="utf-8").splitlines()
    return [e["node"] for e in map(json.loads, lines) if e["event"] == "step_skipped"]


def argvs(run):
    return [c["argv"] for c in read(run, "commands.json")["commands"]]


def logged(log):
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


# ---------------------------------------------------------------- the graph

def test_graph_passes_check():
    p = vg("check", GRAPH)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.startswith("OK: ")


def test_graph_names_its_stream_title_triggers_and_ends():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert graph["stream"] == "ops" and graph["version"] == 0.1
    assert graph["title"] == TITLE
    assert graph["contracts"] == "contracts/ops_hpc.yaml"
    assert len(graph["triggers"]) == 2 and all(t.endswith(".") for t in graph["triggers"])
    assert (graph["entry"], graph["exit"]) == ("hpc_settings", "report")


def test_graph_steps_edges_and_pitfalls():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert set(nodes) == STEPS
    assert all(n["kind"] == "tool" for n in nodes.values())
    assert nodes["run_commands"].get("replay") == "network"
    assert all("replay" not in n for k, n in nodes.items() if k != "run_commands")
    edges = {(e["from"], e["to"]): e for e in graph["edges"]}
    assert set(edges) == {("hpc_settings", "hpc_ssh_entry"), ("hpc_settings", "report"),
                          ("hpc_ssh_entry", "hpc_plan"), ("hpc_plan", "run_commands"),
                          ("run_commands", "report")}
    assert edges[("hpc_settings", "hpc_ssh_entry")]["rel"] == "LEADS_TO"
    assert edges[("hpc_settings", "hpc_ssh_entry")]["check"] == "settings.json:valid == true"
    assert edges[("hpc_settings", "report")]["rel"] == "CONVERGES_TO"
    assert edges[("hpc_settings", "report")]["check"] == "settings.json:valid == false"
    assert edges[("hpc_ssh_entry", "hpc_plan")]["rel"] == "LEADS_TO"
    assert edges[("hpc_plan", "run_commands")]["rel"] == "LEADS_TO"
    assert edges[("run_commands", "report")]["rel"] == "CONVERGES_TO"
    text = " ".join(p for e in graph["edges"] for p in e["pitfalls"]).lower()
    for words in ("copying a key into the run folder", "writing to the scholar's ssh config",
                  "wait for a password"):
        assert words in text, words


def test_both_operational_graphs_share_the_run_and_report_code():
    for name in ("ops_github", "ops_hpc"):
        p = vg("check", "graphs/{}.yaml".format(name))
        assert p.returncode == 0, p.stdout + p.stderr
    code = sorted(p.name for p in (ROOT / "implementations" / "ops").glob("*.py"))
    assert code.count("run_commands.py") == 1 and code.count("report.py") == 1
    for name in ("hpc_settings.py", "hpc_ssh_entry.py", "hpc_plan.py"):
        assert name in code


# ---------------------------------------------------------------- the clean and seeded fixtures

def test_clean_settings_are_valid_with_every_field(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    s = read(run, "settings.json")
    assert set(s) == set(SETTINGS_FIELDS)
    assert s["valid"] is True and s["apply"] is False and s["task"] == TITLE
    assert (s["alias"], s["host"], s["user"]) == ("cluster", "cluster.example.edu", "scholar")
    assert (s["identity_file"], s["scheduler"]) == ("~/.ssh/id_ed25519_cluster", "slurm")
    assert (s["modules"], s["remote_dir"]) == (["python/3.11"], "projects/test_story")


def test_clean_plans_four_commands_with_their_exact_arguments(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    plan = read(run, "commands.json")
    assert (plan["cwd"], plan["snapshot"], plan["writes"]) == ("", {}, [])
    assert [c["n"] for c in plan["commands"]] == [1, 2, 3, 4]
    assert all(c["why"] for c in plan["commands"])
    assert argvs(run) == PLANNED
    applied = read(run, "applied.json")
    assert (applied["applied"], applied["refused"]) == (False, "")
    assert [r["status"] for r in applied["results"]] == ["planned"] * 4
    assert problems(run) == []
    assert ("run_commands", "info") in [(f["check"], f["severity"]) for f in findings(run)]


def test_clean_ssh_entry_matches(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    entry = read(run, "ssh_entry.json")
    assert (entry["given"], entry["present"], entry["matches"]) == (True, True, True)
    assert entry["block"] == BLOCK


def test_seeded_ssh_config_scores_recall_one(tmp_path):
    run = run_on(tmp_path, FIX / "seeded")
    p = vg("score", "--run", str(run), "--truth", str(FIX / "seeded" / "truth.yaml"))
    assert p.returncode == 0, p.stdout + p.stderr
    result = json.loads((run / "score.json").read_text())
    assert result["recall"] == 1.0 and result["extra_findings"] == []
    entry = read(run, "ssh_entry.json")
    assert (entry["given"], entry["present"], entry["matches"]) == (True, True, False)
    assert sorted(f["item"] for f in problems(run)) == ["cluster IdentityFile", "cluster User"]
    assert all(f["severity"] == "warning" for f in problems(run))
    assert argvs(run) == PLANNED


def test_seeded_truth_names_the_two_planted_faults():
    truth = yaml.safe_load((FIX / "seeded" / "truth.yaml").read_text(encoding="utf-8"))
    assert sorted((f["check"], f["item"]) for f in truth["faults"]) == [
        ("hpc_ssh_entry", "cluster IdentityFile"), ("hpc_ssh_entry", "cluster User")]
    assert yaml.safe_load((FIX / "seeded" / "hpc.yaml").read_text(encoding="utf-8")) == clean_settings()


# ---------------------------------------------------------------- the settings

def test_scheduler_pbs_is_blocking_and_skips_the_later_steps(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(scheduler="pbs")))
    blocking = findings(run, "blocking")
    assert [(f["check"], f["item"]) for f in blocking] == [("hpc_settings", "scheduler")]
    s = read(run, "settings.json")
    assert s["valid"] is False and s["scheduler"] == "slurm"
    assert set(skipped(run)) == {"hpc_ssh_entry", "hpc_plan", "run_commands"}
    for name in ("ssh_entry.json", "commands.json", "applied.json"):
        assert not (run / "files" / name).exists()


def test_each_settings_problem_is_blocking(tmp_path):
    cases = [
        ({}, ("alias",)),
        ({}, ("user",)),
        ({}, ("host",)),
        ({}, ("identity_file",)),
        ({}, ("remote_dir",)),
        ({"alias": "my cluster"}, ()),
        ({"alias": "-oProxyCommand"}, ()),
        ({"user": "a/b"}, ()),
        ({"host": ""}, ()),
        ({"modules": "python/3.11"}, ()),
        ({"modules": ["python/3.11", ""]}, ()),
        ({"apply": "yes"}, ()),
        ({"remote_dir": "projects\nother"}, ()),
        ({"remote_dir": "-rf"}, ()),
    ]
    for n, (over, drop) in enumerate(cases):
        sub = tmp_path / "case_{}".format(n)
        sub.mkdir()
        run = run_on(sub, inputs_with(sub, clean_settings(**over), drop=drop))
        key = drop[0] if drop else list(over)[0]
        blocking = findings(run, "blocking")
        assert [(f["check"], f["item"]) for f in blocking] == [("hpc_settings", key)], (over, drop)
        s = read(run, "settings.json")
        assert set(s) == set(SETTINGS_FIELDS) and s["valid"] is False
        assert "hpc_plan" in skipped(run)


def test_defaults_fill_scheduler_modules_and_apply(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(), drop=("scheduler", "modules", "apply")))
    s = read(run, "settings.json")
    assert (s["scheduler"], s["modules"], s["apply"], s["valid"]) == ("slurm", [], False, True)
    assert argvs(run) == PLANNED[:3]


def test_scheduler_none_plans_no_scheduler_command(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(scheduler="none", modules=[])))
    assert argvs(run) == PLANNED[:2]


def test_unknown_key_is_a_warning(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(port=2222)))
    assert [(f["check"], f["severity"], f["item"]) for f in problems(run)] == [("hpc_settings", "warning", "port")]
    assert read(run, "settings.json")["valid"] is True


def test_unreadable_settings_file_is_blocking(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "hpc.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    run = run_on(tmp_path, inputs)
    assert [(f["check"], f["item"]) for f in findings(run, "blocking")][0] == ("hpc_settings", "hpc.yaml")
    assert set(read(run, "settings.json")) == set(SETTINGS_FIELDS)


def test_each_module_is_one_quoted_command(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(modules=["python/3.11", "r/4.3 extra"])))
    last = argvs(run)[3:]
    assert last == [["ssh", "cluster", "bash -lc 'module load python/3.11'"],
                    ["ssh", "cluster", "bash -lc " + shlex.quote("module load " + shlex.quote("r/4.3 extra"))]]
    assert shlex.split(last[1][2]) == ["bash", "-lc", "module load 'r/4.3 extra'"]


def test_a_remote_folder_under_home_keeps_its_tilde_outside_the_quotes(tmp_path):
    """A leading ~/ is left for the cluster's shell to expand, and the rest is quoted."""
    cases = [
        ("~/projects/test_story", "~/projects/test_story", ["mkdir", "-p", "/home/scholar/projects/test_story"]),
        ("~/my projects/x;y", "~/" + shlex.quote("my projects/x;y"), ["mkdir", "-p", "/home/scholar/my projects/x;y"]),
        ("~", "~", ["mkdir", "-p", "/home/scholar"]),
        ("~/", "~/", ["mkdir", "-p", "/home/scholar/"]),
        ("/scratch/a b", shlex.quote("/scratch/a b"), ["mkdir", "-p", "/scratch/a b"]),
        ("~other/x", shlex.quote("~other/x"), ["mkdir", "-p", "~other/x"]),
    ]
    for n, (remote_dir, planned, expanded) in enumerate(cases):
        sub = tmp_path / "case_{}".format(n)
        sub.mkdir()
        run = run_on(sub, inputs_with(sub, clean_settings(remote_dir=remote_dir)))
        argv = argvs(run)[1]
        assert argv == ["ssh", "cluster", "mkdir", "-p", planned], remote_dir
        # ssh joins its arguments with spaces for the remote shell. A shell that
        # expands ~ the way the cluster's would, with HOME set to /home/scholar,
        # reads back the folder the scholar meant.
        p = subprocess.run(["sh", "-c", 'for a in ' + " ".join(argv[2:]) + '; do printf "%s\\n" "$a"; done'],
                           capture_output=True, text=True, env=dict(os.environ, HOME="/home/scholar"))
        assert p.stdout.splitlines() == expanded, remote_dir


# ---------------------------------------------------------------- the ssh entry

def test_no_config_at_all_gives_its_warning_and_the_block(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(), ssh_config=None))
    entry = read(run, "ssh_entry.json")
    assert (entry["given"], entry["present"], entry["matches"]) == (False, False, False)
    assert entry["block"] == BLOCK
    assert [(f["check"], f["severity"], f["item"]) for f in problems(run)] == [
        ("hpc_ssh_entry", "warning", "ssh_config")]
    assert argvs(run) == PLANNED


def test_a_config_with_no_cluster_entry_gives_its_warning_and_the_block(tmp_path):
    text = "Host other\n    HostName other.example.edu\n    User scholar\n"
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(), ssh_config=text))
    entry = read(run, "ssh_entry.json")
    assert (entry["given"], entry["present"], entry["matches"]) == (True, False, False)
    assert entry["block"] == BLOCK
    assert [(f["check"], f["severity"], f["item"]) for f in problems(run)] == [
        ("hpc_ssh_entry", "warning", "cluster")]
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    section = report.split("## SSH entry")[1].split("\n## ")[0]
    assert "```\n" + BLOCK + "```" in section


def test_config_parsing_rules(tmp_path):
    """Keywords in any case, values split at spaces or '=', quotes stripped, a Match
    block skipped, a host pattern list, and the first block naming the alias."""
    text = ("# a synthetic config\n"
            "Match host cluster\n"
            "    User matched_user\n"
            "host other cluster\n"
            "    hostname=cluster.example.edu\n"
            "    USER = \"scholar\"\n"
            "    IdentityFile \"~/.ssh/id_ed25519_cluster\"\n"
            "    User second_value_ignored\n"
            "Host cluster\n"
            "    User later_block_ignored\n")
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(), ssh_config=text))
    entry = read(run, "ssh_entry.json")
    assert (entry["given"], entry["present"], entry["matches"]) == (True, True, True)
    assert problems(run) == []


def test_a_host_line_must_name_the_alias_exactly(tmp_path):
    text = "Host cluster2 cluster*\n    HostName cluster.example.edu\n    User scholar\n"
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(), ssh_config=text))
    assert read(run, "ssh_entry.json")["present"] is False


def test_a_differing_host_name_is_a_warning(tmp_path):
    text = ("Host cluster\n    HostName login.example.edu\n    User scholar\n"
            "    IdentityFile ~/.ssh/id_ed25519_cluster\n")
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(), ssh_config=text))
    assert [(f["severity"], f["item"]) for f in problems(run)] == [("warning", "cluster HostName")]
    assert read(run, "ssh_entry.json")["matches"] is False


def test_an_include_line_is_an_info_note(tmp_path):
    text = "Include config.d/*\n" + (FIX / "clean" / "ssh_config").read_text(encoding="utf-8")
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(), ssh_config=text))
    assert problems(run) == []
    notes = [f for f in findings(run, "info") if f["check"] == "hpc_ssh_entry"]
    assert [f["item"] for f in notes] == ["Include"] and "not checked" in notes[0]["message"]


def test_the_identity_file_is_never_opened(tmp_path):
    """A key file the settings name, inside HOME, is never read or copied into the run."""
    env = base_env(tmp_path)
    key = Path(env["HOME"]) / ".ssh" / "id_ed25519_cluster"
    key.parent.mkdir()
    key.write_text("NOT A REAL KEY, a marker for this test\n", encoding="utf-8")
    run = run_on(tmp_path, FIX / "clean", env=env)
    for path in run.rglob("*"):
        if path.is_file():
            assert b"NOT A REAL KEY" not in path.read_bytes(), path
    for name in ("hpc_settings.py", "hpc_ssh_entry.py", "hpc_plan.py"):
        code = (ROOT / "implementations" / "ops" / name).read_text(encoding="utf-8")
        for line in code.splitlines():
            if "identity_file" in line:
                assert not re.search(r"\b(open|read_text|read_bytes|read_json|read_yaml|copy\w*)\(", line), (name, line)


def test_report_names_the_task_settings_and_the_ssh_entry(tmp_path):
    run = run_on(tmp_path, FIX / "seeded")
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# " + TITLE)
    for heading in ("## Summary", "## Problems", "## Settings", "## SSH entry", "## Commands"):
        assert heading in report, heading
    assert "## Files" not in report
    section = report.split("## SSH entry")[1].split("\n## ")[0]
    assert "given, yes" in section and "present, yes" in section and "matches the settings, no" in section
    assert "```\n" + BLOCK + "```" in section
    commands = report.split("## Commands")[1].split("\n## ")[0]
    assert "BatchMode=yes" in commands and commands.count("planned") == 4


def test_report_has_no_ssh_entry_section_when_the_settings_block(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(scheduler="pbs")))
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    assert "## SSH entry" not in report
    assert report.split("## Commands")[1].split("\n## ")[0].strip() == "None planned."


# ---------------------------------------------------------------- running with a stand-in ssh

def test_apply_runs_the_four_commands_in_order_through_the_stand_in(tmp_path):
    bin_dir, log = stand_in_ssh(tmp_path)
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(apply=True)), env=base_env(tmp_path, bin_dir))
    applied = read(run, "applied.json")
    assert (applied["applied"], applied["refused"]) == (True, "")
    assert [(r["status"], r["exit_code"]) for r in applied["results"]] == [("ok", 0)] * 4
    assert logged(log) == [argv[1:] for argv in PLANNED]
    assert problems(run) == []


def test_a_refused_key_stops_at_the_first_command(tmp_path):
    bin_dir, log = stand_in_ssh(tmp_path, code=255, stderr="scholar@cluster.example.edu: Permission denied (publickey).\n")
    run = run_on(tmp_path, inputs_with(tmp_path, clean_settings(apply=True)), env=base_env(tmp_path, bin_dir))
    applied = read(run, "applied.json")
    assert [r["status"] for r in applied["results"]] == ["failed", "not run", "not run", "not run"]
    assert applied["results"][0]["exit_code"] == 255
    blocking = findings(run, "blocking")
    assert [(f["check"], f["item"]) for f in blocking] == [("run_commands", "command 1")]
    assert "Permission denied (publickey)." in blocking[0]["evidence"]
    assert logged(log) == [PLANNED[0][1:]]


def test_apply_false_runs_nothing_even_with_ssh_on_the_path(tmp_path):
    bin_dir, log = stand_in_ssh(tmp_path)
    run = run_on(tmp_path, FIX / "clean", env=base_env(tmp_path, bin_dir))
    assert read(run, "applied.json")["applied"] is False
    assert logged(log) == []


# ---------------------------------------------------------------- replay and layers

def test_verify_names_run_commands_as_a_network_step_and_replays_the_rest(tmp_path):
    for name in ("planned", "applied", "seeded"):
        sub = tmp_path / name
        sub.mkdir()
        if name == "applied":
            bin_dir, _ = stand_in_ssh(sub)
            env = base_env(sub, bin_dir)
            run = run_on(sub, inputs_with(sub, clean_settings(apply=True)), env=env)
        else:
            env = base_env(sub)
            run = run_on(sub, FIX / ("clean" if name == "planned" else "seeded"), env=env)
        p = vg("verify", "--run", str(run), env=env)
        assert p.returncode == 0, p.stdout + p.stderr
        verdicts = {line.split()[1]: line.split(None, 2)[2] for line in p.stdout.strip().splitlines()}
        assert set(verdicts) == STEPS
        assert verdicts.pop("run_commands") == "network step: outputs hashed, not replayed"
        assert set(verdicts.values()) == {"replay matches"}, p.stdout


def test_no_code_imports_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(audit_layer|ospipe|vg)\b")
    files = sorted((ROOT / "implementations" / "ops").glob("*.py"))
    assert files
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)
