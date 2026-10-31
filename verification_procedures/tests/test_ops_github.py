"""Adding a project to GitHub, written as a procedural graph (graphs/ops_github.yaml).

The run reads a snapshot of the project folder as project.tar and the scholar's
settings as github.yaml. The fixtures are made by fixtures/ops_github/make_fixtures.py
from the test story's project, and the seeded tar adds three files with
credential-like names, each holding a line saying it is not a real secret.

Tests that run git set HOME and XDG_CONFIG_HOME to a temporary folder, set
GIT_CONFIG_NOSYSTEM, and give the commit identity through the environment, so no
test reads the scholar's own git settings. git pushes to a local bare repository,
and no test uses the network.
"""
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VG = [sys.executable, str(ROOT / "vg.py")]
FIX = ROOT / "fixtures" / "ops_github"
GRAPH = "graphs/ops_github.yaml"
TITLE = "Add a project to version control on GitHub"
STORY_CSV = "params_record_results.csv"
SETTINGS_FIELDS = ("task", "valid", "apply", "project_dir", "repo_name", "owner", "visibility",
                   "create_with", "remote_url", "branch", "message", "exclude", "max_file_mb",
                   "warn_file_mb")


def load_maker():
    spec = importlib.util.spec_from_file_location("ops_github_make_fixtures", str(FIX / "make_fixtures.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vg(*args, env=None):
    return subprocess.run(VG + list(args), cwd=ROOT, capture_output=True, text=True, env=env)


def run_on(tmp_path, inputs, name="run", env=None):
    run = tmp_path / name
    p = vg("run", GRAPH, "--run", str(run), "--inputs", str(inputs), env=env)
    assert p.returncode == 0, p.stdout + p.stderr
    return run


def settings(**over):
    base = {"project_dir": "/scholar/test_story/project", "repo_name": "test-story",
            "remote_url": "git@example.invalid:scholar/test-story.git"}
    base.update(over)
    return base


def tar_of(files):
    """A tar of the given {name: bytes}, packed the way the fixtures are."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(files[name]), 0, 0o644
            tf.addfile(info, io.BytesIO(files[name]))
    return buf.getvalue()


def inputs_with(tmp_path, cfg, tar_bytes=None, extra=None):
    """An inputs folder holding github.yaml and a project.tar, by default the clean one
    with any extra files added."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "github.yaml").write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
    if tar_bytes is None:
        if extra:
            files = story_files()
            files.update(extra)
            tar_bytes = tar_of(files)
        else:
            tar_bytes = (FIX / "clean" / "project.tar").read_bytes()
    (inputs / "project.tar").write_bytes(tar_bytes)
    return inputs


def story_files():
    with tarfile.open(str(FIX / "clean" / "project.tar")) as tf:
        return {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}


def read(run, name):
    return json.loads((run / "files" / name).read_text(encoding="utf-8"))


def findings(run, severity=None):
    out = read(run, "findings.json")
    return [f for f in out if severity is None or f["severity"] == severity]


def problems(run):
    return [f for f in read(run, "findings.json") if f["severity"] in ("blocking", "warning")]


def skipped(run):
    lines = (run / "trail.jsonl").read_text(encoding="utf-8").splitlines()
    return [e["node"] for e in map(json.loads, lines) if e["event"] == "step_skipped"]


def ran(run):
    return [json.loads(p.read_text())["node"] for p in sorted((run / "records").glob("*.json"))]


# ---------------------------------------------------------------- the graph

def test_graph_passes_check():
    p = vg("check", GRAPH)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.startswith("OK: ")


def test_graph_names_its_stream_title_triggers_and_ends():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert graph["stream"] == "ops"
    assert graph["title"] == TITLE
    assert graph["contracts"] == "contracts/ops_github.yaml"
    assert len(graph["triggers"]) == 2 and all(t.endswith(".") for t in graph["triggers"])
    assert (graph["entry"], graph["exit"]) == ("github_settings", "report")


def test_graph_edges_and_pitfalls():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    edges = {(e["from"], e["to"]): e for e in graph["edges"]}
    assert edges[("github_settings", "github_files")]["rel"] == "LEADS_TO"
    assert edges[("github_settings", "github_files")]["check"] == "settings.json:valid == true"
    assert edges[("github_settings", "report")]["rel"] == "CONVERGES_TO"
    assert edges[("github_settings", "report")]["check"] == "settings.json:valid == false"
    assert edges[("github_files", "report")]["rel"] == "CONVERGES_TO"
    text = " ".join(p for e in graph["edges"] for p in e["pitfalls"]).lower()
    for words in ("credential", "student records", "git add -a", "public"):
        assert words in text, words


# ---------------------------------------------------------------- the fixtures

def test_fixture_tars_are_packed_the_same_way_every_time(tmp_path):
    maker = load_maker()
    story = ROOT.parent / "examples" / "test_story" / "project"
    maker.pack(str(story), str(tmp_path / "a.tar"))
    maker.pack(str(story), str(tmp_path / "b.tar"))
    assert (tmp_path / "a.tar").read_bytes() == (tmp_path / "b.tar").read_bytes()
    assert (tmp_path / "a.tar").read_bytes() == (FIX / "clean" / "project.tar").read_bytes()
    with tarfile.open(str(tmp_path / "a.tar")) as tf:
        members = tf.getmembers()
    assert [m.name for m in members] == sorted(m.name for m in members)
    assert all(m.mtime == 0 and m.mode == 0o644 for m in members)
    assert (tmp_path / "a.tar").read_bytes()[257:263] == b"ustar\x00"  # the USTAR magic


def test_pack_adds_extra_names(tmp_path):
    maker = load_maker()
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a\n")
    maker.pack(str(src), str(tmp_path / "x.tar"), extra={"z/b.txt": b"b\n"})
    with tarfile.open(str(tmp_path / "x.tar")) as tf:
        assert tf.getnames() == ["a.txt", "z/b.txt"]
        assert tf.extractfile("z/b.txt").read() == b"b\n"


def test_seeded_tar_holds_three_marked_files():
    with tarfile.open(str(FIX / "seeded" / "project.tar")) as tf:
        names = set(tf.getnames())
        for name in (".env", "keys/id_ed25519", "secrets/token.txt"):
            assert name in names
            assert b"not a real secret" in tf.extractfile(name).read()
    assert names - {".env", "keys/id_ed25519", "secrets/token.txt"} == set(story_files())


# ---------------------------------------------------------------- settings

def test_clean_settings_are_valid_with_every_field(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    s = read(run, "settings.json")
    assert set(s) == set(SETTINGS_FIELDS)
    assert s["valid"] is True and s["apply"] is False
    assert s["task"] == TITLE
    assert s["repo_name"] == "test-story"
    assert (s["visibility"], s["create_with"], s["branch"]) == ("private", "none", "main")
    assert s["message"] == "First commit of the project"
    assert (s["exclude"], s["max_file_mb"], s["warn_file_mb"]) == ([], 100, 50)


def test_missing_project_dir_is_blocking_and_skips_the_file_check(tmp_path):
    cfg = settings()
    del cfg["project_dir"]
    run = run_on(tmp_path, inputs_with(tmp_path, cfg))
    blocking = findings(run, "blocking")
    assert [(f["check"], f["item"]) for f in blocking] == [("github_settings", "project_dir")]
    assert read(run, "settings.json")["valid"] is False
    assert read(run, "settings.json")["project_dir"] == ""
    assert "github_files" in skipped(run)
    assert ran(run) == ["github_settings", "report"]


def test_each_settings_problem_is_blocking(tmp_path):
    cases = [
        ({"project_dir": "relative/path"}, "project_dir"),
        ({"repo_name": "bad name!"}, "repo_name"),
        ({"visibility": "secret"}, "visibility"),
        ({"create_with": "svn"}, "create_with"),
        ({"remote_url": ""}, "remote_url"),
        ({"create_with": "gh", "owner": ""}, "owner"),
        ({"exclude": ["../outside"]}, "exclude"),
        ({"exclude": ["/abs/path"]}, "exclude"),
        ({"exclude": "notes/"}, "exclude"),
        ({"apply": "yes"}, "apply"),
        ({"max_file_mb": "big"}, "max_file_mb"),
        ({"warn_file_mb": -1}, "warn_file_mb"),
        ({"branch": ""}, "branch"),
        ({"message": 3}, "message"),
    ]
    for n, (over, item) in enumerate(cases):
        sub = tmp_path / "case{}".format(n)
        sub.mkdir()
        run = run_on(sub, inputs_with(sub, settings(**over)))
        blocking = findings(run, "blocking")
        assert [f["item"] for f in blocking] == [item], (over, blocking)
        s = read(run, "settings.json")
        assert set(s) == set(SETTINGS_FIELDS) and s["valid"] is False, over


def test_gh_with_owner_needs_no_remote_url(tmp_path):
    cfg = settings(create_with="gh", owner="scholar", remote_url="")
    run = run_on(tmp_path, inputs_with(tmp_path, cfg))
    assert read(run, "settings.json")["valid"] is True
    assert findings(run, "blocking") == []


def test_unknown_key_is_a_warning(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, settings(colour="blue")))
    warnings = findings(run, "warning")
    assert [(f["check"], f["item"]) for f in warnings] == [("github_settings", "colour")]
    assert read(run, "settings.json")["valid"] is True


def test_unreadable_settings_file_is_blocking(tmp_path):
    inputs = inputs_with(tmp_path, settings())
    (inputs / "github.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    run = run_on(tmp_path, inputs)
    assert read(run, "settings.json")["valid"] is False
    assert [(f["check"], f["item"]) for f in findings(run, "blocking")] == [("github_settings", "github.yaml")]
    assert "github_files" in skipped(run)


# ---------------------------------------------------------------- the file check

def test_clean_project_has_no_problem_and_commits_every_file(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    assert problems(run) == []
    files = read(run, "files.json")
    assert files["commit"] == sorted(story_files())
    assert (files["blocked"], files["already_repo"], files["files"]) == (0, False, len(story_files()))
    assert (files["excluded"], files["gitignore"]) == ([], [])
    assert sorted(files["snapshot"]) == sorted(story_files())
    notes = [(f["check"], f["item"]) for f in findings(run, "info")]
    assert ("github_files", STORY_CSV) in notes


def test_snapshot_holds_each_files_sha256(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    snapshot = read(run, "files.json")["snapshot"]
    for name, data in story_files().items():
        assert snapshot[name] == "sha256:" + hashlib.sha256(data).hexdigest()


def test_seeded_project_scores_recall_one(tmp_path):
    run = run_on(tmp_path, FIX / "seeded")
    p = vg("score", "--run", str(run), "--truth", str(FIX / "seeded" / "truth.yaml"))
    assert p.returncode == 0, p.stdout + p.stderr
    result = json.loads((run / "score.json").read_text())
    assert result["recall"] == 1.0 and result["extra_findings"] == []
    files = read(run, "files.json")
    assert files["blocked"] == 3
    for name in (".env", "keys/id_ed25519", "secrets/token.txt"):
        assert name not in files["commit"]


def test_a_tar_holding_a_repository_is_blocking(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, settings(), extra={".git/HEAD": b"ref: refs/heads/main\n"}))
    blocking = findings(run, "blocking")
    assert [(f["check"], f["item"]) for f in blocking] == [("github_files", ".git/HEAD")]
    files = read(run, "files.json")
    assert files["already_repo"] is True and files["blocked"] == 1
    assert ".git/HEAD" not in files["commit"]


def test_an_excluded_env_file_is_a_note_and_goes_in_gitignore(tmp_path):
    cfg = settings(exclude=[".env"])
    run = run_on(tmp_path, inputs_with(tmp_path, cfg, extra={".env": b"not a real secret\n"}))
    assert problems(run) == []
    notes = [(f["check"], f["item"]) for f in findings(run, "info")]
    assert ("github_files", ".env") in notes
    files = read(run, "files.json")
    assert ".env" not in files["commit"]
    assert files["excluded"] == [".env"] and files["gitignore"] == [".env"]


def test_an_excluded_folder_covers_its_files(tmp_path):
    cfg = settings(exclude=["private/"])
    extra = {"private/a.txt": b"a\n", "private/deep/b.txt": b"b\n", "privateer.txt": b"c\n"}
    run = run_on(tmp_path, inputs_with(tmp_path, cfg, extra=extra))
    files = read(run, "files.json")
    assert files["excluded"] == ["private/a.txt", "private/deep/b.txt"]
    assert "privateer.txt" in files["commit"]
    assert files["gitignore"] == ["private/"]


def test_credential_like_names_in_any_case_are_blocking(tmp_path):
    names = [".env", ".ENV.local", "server.pem", "site.Key", "cert.p12", "cert.pfx", "id_rsa.pub",
             "ssh/id_ed25519", "id_ecdsa", ".netrc", "Credentials.json", "my_secret.txt", "API_TOKEN"]
    extra = {name: b"not a real secret\n" for name in names}
    run = run_on(tmp_path, inputs_with(tmp_path, settings(), extra=extra))
    blocking = sorted(f["item"] for f in findings(run, "blocking"))
    assert blocking == sorted(names)
    assert read(run, "files.json")["blocked"] == len(names)


def test_size_limits_block_and_warn(tmp_path):
    files = {"big.txt": b"x" * 2048, "mid.txt": b"x" * 1024, "small.txt": b"x" * 10}
    cfg = settings(max_file_mb=0.0015, warn_file_mb=0.0005)
    run = run_on(tmp_path, inputs_with(tmp_path, cfg, tar_bytes=tar_of(files)))
    assert [f["item"] for f in findings(run, "blocking")] == ["big.txt"]
    assert [f["item"] for f in findings(run, "warning")] == ["mid.txt"]
    assert read(run, "files.json")["commit"] == ["mid.txt", "small.txt"]


def test_story_csv_is_a_warning_in_a_public_repository(tmp_path):
    run = run_on(tmp_path, inputs_with(tmp_path, settings(visibility="public")))
    warnings = [(f["check"], f["item"]) for f in findings(run, "warning")]
    assert warnings == [("github_files", STORY_CSV)]
    assert findings(run, "blocking") == []


def test_mac_extras_and_leading_dot_slash_are_handled(tmp_path):
    files = {"./a.txt": b"a\n", "./sub/._a.txt": b"x", "./.DS_Store": b"x", "sub/.DS_Store": b"x"}
    run = run_on(tmp_path, inputs_with(tmp_path, settings(), tar_bytes=tar_of(files)))
    out = read(run, "files.json")
    assert out["commit"] == ["a.txt"] and list(out["snapshot"]) == ["a.txt"]


# ---------------------------------------------------------------- the report

def test_report_names_the_task_settings_and_files(tmp_path):
    run = run_on(tmp_path, FIX / "clean")
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# " + TITLE + "\n")
    assert "apply" in report.split("## Summary")[0]
    heads = [line[3:] for line in report.splitlines() if line.startswith("## ")]
    for head in ("Summary", "Problems", "Settings", "Files", "Commands"):
        assert head in heads, head
    settings_part = report.split("## Settings")[1].split("\n## ")[0]
    for field in SETTINGS_FIELDS:
        assert field in settings_part, field


def test_report_has_no_files_section_when_the_check_was_skipped(tmp_path):
    cfg = settings()
    del cfg["repo_name"]
    run = run_on(tmp_path, inputs_with(tmp_path, cfg))
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    assert "## Files" not in report
    assert "## Commands" in report


# ---------------------------------------------------------------- replay and layers

def test_verify_reports_replay_matches(tmp_path):
    for name in ("clean", "seeded"):
        sub = tmp_path / name
        sub.mkdir()
        run = run_on(sub, FIX / name)
        p = vg("verify", "--run", str(run))
        assert p.returncode == 0, p.stdout + p.stderr
        lines = p.stdout.strip().splitlines()
        assert lines and all(line.endswith(("replay matches", "network step: outputs hashed, not replayed"))
                             for line in lines), p.stdout


def test_verify_names_run_commands_as_a_network_step(tmp_path):
    for name, cfg in (("planned", None), ("applied", "apply")):
        sub = tmp_path / name
        sub.mkdir()
        env = git_env(sub)
        if cfg is None:
            run = run_on(sub, FIX / "clean", env=env)
        else:
            proj = story_copy(sub)
            run = run_on(sub, apply_inputs(sub, proj, remote_url=str(bare(sub, env))), env=env)
        p = vg("verify", "--run", str(run), env=env)
        assert p.returncode == 0, p.stdout + p.stderr
        verdicts = {line.split()[1]: line.split(None, 2)[2] for line in p.stdout.strip().splitlines()}
        assert set(verdicts) == {"github_settings", "github_files", "github_plan", "run_commands", "report"}
        assert verdicts.pop("run_commands") == "network step: outputs hashed, not replayed"
        assert set(verdicts.values()) == {"replay matches"}, p.stdout


def test_no_code_imports_another_layer():
    pattern = re.compile(r"^\s*(import|from)\s+(audit_layer|ospipe|vg)\b")
    files = sorted((ROOT / "implementations" / "ops").glob("*.py"))
    assert files
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not pattern.match(line), "{}:{} {}".format(path, number, line)


# ---------------------------------------------------------------- the plan and the run

# On a Mac with an x86_64 Python, /usr/bin/git is an xcrun shim that fails, as
# fixtures/build/make_fixtures.py notes for make, so the tests put a small script
# that runs the real binary first on PATH. The procedure itself runs whatever git
# is on PATH.
REAL_GIT = next((g for g in ("/Library/Developer/CommandLineTools/usr/bin/git",) if os.path.exists(g)),
                shutil.which("git") or "git")


def git_env(tmp_path, **over):
    """An environment in which git reads no settings of the scholar's."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    if not bin_dir.exists():
        bin_dir.mkdir()
        script = bin_dir / "git"
        script.write_text('#!/bin/sh\nexec "{}" "$@"\n'.format(REAL_GIT), encoding="utf-8")
        script.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="A. Scholar", GIT_AUTHOR_EMAIL="scholar@example.invalid",
               GIT_COMMITTER_NAME="A. Scholar", GIT_COMMITTER_EMAIL="scholar@example.invalid")
    env.update(over)
    return env


def git(env, *args, cwd=None):
    p = subprocess.run([REAL_GIT] + list(args), cwd=cwd, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout


def bare(tmp_path, env):
    path = tmp_path / "remote.git"
    git(env, "init", "-q", "--bare", str(path))
    return path


def story_copy(tmp_path, extra=None):
    """A temporary copy of the story's project, with any extra {name: text} added."""
    proj = tmp_path / "project"
    shutil.copytree(str(ROOT.parent / "examples" / "test_story" / "project"), str(proj),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name, text in (extra or {}).items():
        (proj / name).parent.mkdir(parents=True, exist_ok=True)
        (proj / name).write_text(text, encoding="utf-8")
    return proj


def apply_inputs(tmp_path, proj, **over):
    """Inputs for a run that applies, with the project's tar made by pack."""
    tar = tmp_path / "project.tar"
    load_maker().pack(str(proj), str(tar))
    cfg = settings(project_dir=str(proj), apply=True)
    cfg.update(over)
    return inputs_with(tmp_path, cfg, tar_bytes=tar.read_bytes())


def argvs(run):
    return [c["argv"] for c in read(run, "commands.json")["commands"]]


def test_graph_plans_and_runs_after_the_file_check():
    graph = yaml.safe_load((ROOT / GRAPH).read_text(encoding="utf-8"))
    assert graph["version"] == 0.2
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert all(n["kind"] == "tool" for n in nodes.values())
    assert nodes["run_commands"].get("replay") == "network"
    assert all("replay" not in n for k, n in nodes.items() if k != "run_commands")
    edges = {(e["from"], e["to"]): e for e in graph["edges"]}
    assert edges[("github_files", "github_plan")]["rel"] == "TRIGGERS"
    assert edges[("github_files", "github_plan")]["check"] == "files.json:blocked == 0"
    assert edges[("github_files", "report")]["check"] == "files.json:blocked > 0"
    assert edges[("github_plan", "run_commands")]["rel"] == "LEADS_TO"
    assert edges[("run_commands", "report")]["rel"] == "CONVERGES_TO"
    text = " ".join(p for e in graph["edges"] for p in e["pitfalls"]).lower()
    for words in ("apply is false", "changed since its snapshot", "failed command", "author"):
        assert words in text, words


def test_clean_fixture_plans_five_commands_and_runs_none(tmp_path):
    run = run_on(tmp_path, FIX / "clean", env=git_env(tmp_path))
    plan = read(run, "commands.json")
    assert plan["cwd"] == "/scholar/test_story/project"
    assert plan["snapshot"] == read(run, "files.json")["snapshot"]
    assert plan["writes"] == []
    assert [c["n"] for c in plan["commands"]] == [1, 2, 3, 4, 5]
    assert all(c["why"] for c in plan["commands"])
    assert argvs(run) == [
        ["git", "init", "-b", "main"],
        ["git", "add", "--"] + sorted(story_files()),
        ["git", "commit", "-m", "First commit of the project"],
        ["git", "remote", "add", "origin", "git@github.example.invalid:scholar/test-story.git"],
        ["git", "push", "-u", "origin", "main"],
    ]
    applied = read(run, "applied.json")
    assert (applied["applied"], applied["refused"]) == (False, "")
    assert [r["status"] for r in applied["results"]] == ["planned"] * 5
    assert problems(run) == []
    assert ("run_commands", "info") in [(f["check"], f["severity"]) for f in findings(run)]
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    commands = report.split("## Commands")[1].split("\n## ")[0]
    assert "git push -u origin main" in commands and commands.count("planned") == 5


def test_a_plan_with_apply_false_leaves_the_folder_alone(tmp_path):
    env = git_env(tmp_path)
    proj = story_copy(tmp_path)
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, apply=False, remote_url=str(bare(tmp_path, env))), env=env)
    assert read(run, "applied.json")["applied"] is False
    assert not (proj / ".git").exists()


def test_a_run_that_applies_pushes_one_commit_of_exactly_the_checked_files(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path)
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(remote)), env=env)
    applied = read(run, "applied.json")
    assert (applied["applied"], applied["refused"]) == (True, "")
    assert [r["status"] for r in applied["results"]] == ["ok"] * 5
    for r in applied["results"]:
        assert set(r) == {"n", "argv", "status", "exit_code", "stdout_tail", "stderr_tail"}
        assert r["exit_code"] == 0 and len(r["stdout_tail"]) <= 500 and len(r["stderr_tail"]) <= 500
    assert problems(run) == []
    assert git(env, "--git-dir", str(remote), "rev-list", "--count", "main").strip() == "1"
    tree = git(env, "--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main").split()
    assert tree == read(run, "files.json")["commit"]
    author = git(env, "--git-dir", str(remote), "log", "-1", "--format=%an <%ae>", "main").strip()
    assert author == "A. Scholar <scholar@example.invalid>"
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    assert report.split("## Commands")[1].split("\n## ")[0].count("| ok |") == 5


def test_an_excluded_env_file_stays_out_and_gitignore_names_it(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path, extra={".env": "This is not a real secret.\n"})
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(remote), exclude=[".env"]), env=env)
    plan = read(run, "commands.json")
    assert plan["writes"] == [{"path": ".gitignore", "text": "/.env\n!/.env/\n"}]
    assert argvs(run)[1] == ["git", "add", "--"] + sorted(list(story_files()) + [".gitignore"])
    assert [r["status"] for r in read(run, "applied.json")["results"]] == ["ok"] * 5
    tree = git(env, "--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main").split()
    assert ".env" not in tree and ".gitignore" in tree
    assert git(env, "--git-dir", str(remote), "show", "main:.gitignore").splitlines() == ["/.env", "!/.env/"]


def test_a_project_with_its_own_gitignore_gets_no_write(tmp_path):
    env = git_env(tmp_path)
    proj = story_copy(tmp_path, extra={".gitignore": "*.log\n", ".env": "This is not a real secret.\n"})
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, apply=False, exclude=[".env"]), env=env)
    assert read(run, "commands.json")["writes"] == []
    assert ".gitignore" in argvs(run)[1]


def test_a_project_changed_after_its_snapshot_is_refused(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path)
    inputs = apply_inputs(tmp_path, proj, remote_url=str(remote))
    (proj / "manuscript.md").write_text("Changed after the check.\n", encoding="utf-8")
    (proj / "new_notes.md").write_text("Added after the check.\n", encoding="utf-8")
    run = run_on(tmp_path, inputs, env=env)
    applied = read(run, "applied.json")
    assert applied["applied"] is False and applied["refused"]
    assert [r["status"] for r in applied["results"]] == ["not run"] * 5
    blocking = findings(run, "blocking")
    assert [f["check"] for f in blocking] == ["run_commands"]
    assert "manuscript.md" in blocking[0]["evidence"] and "new_notes.md" in blocking[0]["evidence"]
    assert not (proj / ".git").exists()


def test_mac_extras_in_the_folder_do_not_count_as_changes(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path)
    inputs = apply_inputs(tmp_path, proj, remote_url=str(remote))
    (proj / ".DS_Store").write_bytes(b"x")
    (proj / "._manuscript.md").write_bytes(b"x")
    run = run_on(tmp_path, inputs, env=env)
    assert read(run, "applied.json")["refused"] == ""
    assert [r["status"] for r in read(run, "applied.json")["results"]] == ["ok"] * 5


def test_a_remote_that_is_not_a_repository_fails_at_the_push(tmp_path):
    env = git_env(tmp_path)
    proj = story_copy(tmp_path)
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(tmp_path / "no_such_repo.git")), env=env)
    results = read(run, "applied.json")["results"]
    assert [r["status"] for r in results] == ["ok", "ok", "ok", "ok", "failed"]
    assert results[4]["exit_code"] != 0
    blocking = findings(run, "blocking")
    assert [(f["check"], f["item"]) for f in blocking] == [("run_commands", "command 5")]
    assert "git push -u origin main" in blocking[0]["message"]
    assert blocking[0]["evidence"].startswith("fatal:")
    assert git(env, "rev-list", "--count", "HEAD", cwd=str(proj)).strip() == "1"


def test_a_missing_program_counts_as_exit_127_and_stops_the_run(tmp_path):
    empty = tmp_path / "empty_bin"
    empty.mkdir()
    env = git_env(tmp_path, PATH=str(empty))
    proj = story_copy(tmp_path)
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(tmp_path / "remote.git")), env=env)
    results = read(run, "applied.json")["results"]
    assert [r["status"] for r in results] == ["failed"] + ["not run"] * 4
    assert results[0]["exit_code"] == 127
    assert [f["item"] for f in findings(run, "blocking")] == ["command 1"]
    assert not (proj / ".git").exists()


def test_create_with_gh_plans_the_repository_create_line(tmp_path):
    for visibility in ("private", "public"):
        sub = tmp_path / visibility
        sub.mkdir()
        cfg = settings(create_with="gh", owner="scholar", remote_url="", visibility=visibility)
        run = run_on(sub, inputs_with(sub, cfg), env=git_env(sub))
        assert argvs(run)[3] == ["gh", "repo", "create", "scholar/test-story", "--" + visibility,
                                 "--source", ".", "--remote", "origin"]
        assert len(argvs(run)) == 5


def test_paths_are_added_in_groups_of_100(tmp_path):
    files = {"f{:03d}.txt".format(i): b"x\n" for i in range(205)}
    run = run_on(tmp_path, inputs_with(tmp_path, settings(), tar_bytes=tar_of(files)), env=git_env(tmp_path))
    adds = [a for a in argvs(run) if a[:2] == ["git", "add"]]
    assert [len(a) - 3 for a in adds] == [100, 100, 5]
    assert sum((a[3:] for a in adds), []) == sorted(files)
    assert len(argvs(run)) == 7
    assert [c["n"] for c in read(run, "commands.json")["commands"]] == list(range(1, 8))


def test_the_seeded_fixture_never_reaches_the_plan(tmp_path):
    run = run_on(tmp_path, FIX / "seeded", env=git_env(tmp_path))
    assert "github_plan" in skipped(run) and "run_commands" in skipped(run)
    assert ran(run) == ["github_settings", "github_files", "report"]
    assert not (run / "files" / "commands.json").exists()
    report = (run / "files" / "report.md").read_text(encoding="utf-8")
    assert report.split("## Commands")[1].split("\n## ")[0].strip() == "None planned."


# ---------------------------------------------------------------- review fixes

def pushed_tree(env, remote):
    return git(env, "--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main").split()


def test_a_folder_already_under_git_is_refused_even_when_its_tar_leaves_git_out(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path, extra={"api_token.txt": "This is not a real secret.\n"})
    git(env, "init", "-q", "-b", "main", cwd=str(proj))
    git(env, "add", "--", ".", cwd=str(proj))
    git(env, "commit", "-q", "-m", "first", cwd=str(proj))
    git(env, "rm", "-q", "--", "api_token.txt", cwd=str(proj))
    git(env, "commit", "-q", "-m", "remove the token", cwd=str(proj))
    files = story_files()
    cfg = settings(project_dir=str(proj), apply=True, remote_url=str(remote))
    run = run_on(tmp_path, inputs_with(tmp_path, cfg, tar_bytes=tar_of(files)), env=env)
    applied = read(run, "applied.json")
    assert applied["applied"] is False and applied["refused"]
    assert [r["status"] for r in applied["results"]] == ["not run"] * 5
    blocking = findings(run, "blocking")
    assert [(f["check"], f["item"]) for f in blocking] == [("run_commands", "snapshot")]
    assert "new .git" in blocking[0]["evidence"]
    assert git(env, "--git-dir", str(remote), "for-each-ref").strip() == ""
    assert git(env, "rev-list", "--count", "HEAD", cwd=str(proj)).strip() == "2"


def test_an_exclude_entry_without_a_slash_leaves_out_only_that_path(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path, extra={"notes.md": "top\n", "sub/notes.md": "deep\n"})
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(remote), exclude=["notes.md"]), env=env)
    assert read(run, "commands.json")["writes"] == [{"path": ".gitignore", "text": "/notes.md\n!/notes.md/\n"}]
    assert [r["status"] for r in read(run, "applied.json")["results"]] == ["ok"] * 5
    tree = pushed_tree(env, remote)
    assert "sub/notes.md" in tree and "notes.md" not in tree
    assert tree == sorted(read(run, "files.json")["commit"] + [".gitignore"])


def test_gitignore_lines_are_anchored_and_match_names_literally(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path, extra={"a*b.txt": "star\n", "axb.txt": "x\n", "private/a.txt": "p\n"})
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(remote),
                                        exclude=["a*b.txt", "private/"]), env=env)
    assert read(run, "commands.json")["writes"] == [{"path": ".gitignore", "text": "/a\\*b.txt\n!/a\\*b.txt/\n/private/\n"}]
    assert read(run, "files.json")["gitignore"] == ["a*b.txt", "private/"]
    assert [r["status"] for r in read(run, "applied.json")["results"]] == ["ok"] * 5
    tree = pushed_tree(env, remote)
    assert "axb.txt" in tree and "a*b.txt" not in tree and "private/a.txt" not in tree


def test_a_failed_add_names_the_error_and_not_a_hint(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path, extra={".gitignore": "*.log\n", "run.log": "a log\n"})
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(remote)), env=env)
    results = read(run, "applied.json")["results"]
    assert [r["status"] for r in results] == ["ok", "failed", "not run", "not run", "not run"]
    blocking = findings(run, "blocking")
    assert [(f["check"], f["item"]) for f in blocking] == [("run_commands", "command 2")]
    assert not blocking[0]["evidence"].lower().startswith("hint:")
    assert "run.log" in blocking[0]["evidence"]


def test_an_empty_tar_still_compares_the_folder(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path)
    cfg = settings(project_dir=str(proj), apply=True, remote_url=str(remote))
    run = run_on(tmp_path, inputs_with(tmp_path, cfg, tar_bytes=tar_of({})), env=env)
    assert read(run, "commands.json")["snapshot"] == {}
    applied = read(run, "applied.json")
    assert applied["applied"] is False and applied["refused"]
    assert all(r["status"] == "not run" for r in applied["results"])
    assert [(f["check"], f["item"]) for f in findings(run, "blocking")] == [("run_commands", "snapshot")]
    assert not (proj / ".git").exists()


def test_a_repository_inside_a_subfolder_is_blocking(tmp_path):
    extra = {"sub/.git/HEAD": b"ref: refs/heads/main\n", "lib/.git": b"gitdir: ../.git/modules/lib\n"}
    run = run_on(tmp_path, inputs_with(tmp_path, settings(), extra=extra))
    blocking = sorted((f["check"], f["item"]) for f in findings(run, "blocking"))
    assert blocking == [("github_files", "lib/.git"), ("github_files", "sub/.git/HEAD")]
    files = read(run, "files.json")
    assert files["already_repo"] is True and files["blocked"] == 2
    for name in extra:
        assert name not in files["commit"] and name not in files["snapshot"]


# ---------------------------------------------------------------- review fixes, round 2

def run_step_directly(tmp_path, plan, apply=True):
    """Run the shared run_commands step on its own, the way the runtime does, with the
    given commands.json."""
    step = tmp_path / "step"
    files = step / "files"
    files.mkdir(parents=True)
    shutil.copy(str(ROOT / "implementations" / "ops" / "run_commands.py"), str(step))
    shutil.copy(str(ROOT / "implementations" / "_lib.py"), str(step))
    (files / "settings.json").write_text(json.dumps({"apply": apply}), encoding="utf-8")
    (files / "commands.json").write_text(json.dumps(plan), encoding="utf-8")
    p = subprocess.run([sys.executable, str(step / "run_commands.py"), str(files)],
                       cwd=str(tmp_path), capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads((files / "applied.json").read_text(encoding="utf-8"))


def test_a_plan_with_no_folder_runs_its_commands_without_a_comparison(tmp_path):
    plan = {"cwd": "", "snapshot": {}, "writes": [],
            "commands": [{"n": 1, "argv": [sys.executable, "-c", "print('ran')"], "why": "A harmless command."}]}
    applied = run_step_directly(tmp_path, plan)
    assert (applied["applied"], applied["refused"]) == (True, "")
    assert [(r["status"], r["exit_code"], r["stdout_tail"]) for r in applied["results"]] == [("ok", 0, "ran\n")]


def test_an_exclude_entry_without_a_slash_does_not_leave_out_a_folder(tmp_path):
    env = git_env(tmp_path)
    remote = bare(tmp_path, env)
    proj = story_copy(tmp_path, extra={"data/x.csv": "a,b\n"})
    run = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(remote), exclude=["data"]), env=env)
    assert "data/x.csv" in read(run, "files.json")["commit"]
    assert read(run, "commands.json")["writes"] == [{"path": ".gitignore", "text": "/data\n!/data/\n"}]
    assert [r["status"] for r in read(run, "applied.json")["results"]] == ["ok"] * 5
    assert "data/x.csv" in pushed_tree(env, remote)


def test_a_rerun_after_a_failed_push_says_the_folder_already_holds_a_repository(tmp_path):
    """The second run reuses the first run's tar, so the file check passes and the
    comparison before any command finds the .git the first run left."""
    env = git_env(tmp_path)
    proj = story_copy(tmp_path)
    first = run_on(tmp_path, apply_inputs(tmp_path, proj, remote_url=str(tmp_path / "no_such_repo.git")), env=env)
    assert [r["status"] for r in read(first, "applied.json")["results"]][-1] == "failed"
    again = tmp_path / "again"
    again.mkdir()
    cfg = settings(project_dir=str(proj), apply=True, remote_url=str(bare(again, env)))
    run = run_on(again, inputs_with(again, cfg, tar_bytes=(tmp_path / "project.tar").read_bytes()), env=env)
    applied = read(run, "applied.json")
    assert applied["applied"] is False and "already holds a repository" in applied["refused"]
    blocking = findings(run, "blocking")
    assert [(f["check"], f["item"]) for f in blocking] == [("run_commands", "snapshot")]
    assert "already holds a repository" in blocking[0]["message"] and "by hand" in blocking[0]["message"]
