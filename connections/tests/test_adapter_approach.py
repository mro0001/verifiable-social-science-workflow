"""Tests for the file adapter approach (Track D, step D11).

Appendix A2.2 says file adapters turn a tool's files into the fixed files the
verification layer uses, one adapter for each tool and stream (Figure A2). An
adapter fills its stream's input files, the files the stream's procedure
reads, runs as python3 -m connections adapt <name> --out DIR, writes only its
declared input files plus adapter_record.json, gives the same bytes for the
same inputs, and refuses to replace a file already in DIR (Track D choice 12).
The reconciliation calls these input files, not fields.

These tests register a test adapter inside the test. Every test runs with
HOME, CONNECTIONS_HOME, and AUDIT_HOME inside a temporary folder. Run from the
repository root with python3 -m pytest -q connections/tests.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from connections import adapters  # noqa: E402
from connections.adapters import ADAPTERS, Adapter, AdapterError, run_adapter  # noqa: E402
from connections.cli import main  # noqa: E402


@pytest.fixture(autouse=True)
def homes(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("CONNECTIONS_HOME", str(tmp_path / "connections_home"))
    monkeypatch.setenv("AUDIT_HOME", str(tmp_path / "audit_home"))
    return tmp_path


def _add_arguments(parser):
    parser.add_argument("--source", required=True, metavar="FILE")


def _read(args):
    data = Path(args.source).read_bytes()
    return [args.source], {"first.txt": data, "second.txt": data.upper()}


def _read_outside(args):
    data = Path(args.source).read_bytes()
    return [args.source], {"first.txt": data, "elsewhere.txt": data}


@pytest.fixture
def echo(monkeypatch):
    adapter = Adapter("echo", "test", ("first.txt", "second.txt"), _add_arguments, _read)
    monkeypatch.setitem(ADAPTERS, "echo", adapter)
    return adapter


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.txt"
    path.write_bytes(b"one line of text\n")
    return path


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def snapshot(folder):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(folder.iterdir())}


def test_the_input_files_and_the_record_are_written(echo, source, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["adapt", "echo", "--out", str(out), "--source", str(source)]) == 0
    assert (out / "first.txt").read_bytes() == b"one line of text\n"
    assert (out / "second.txt").read_bytes() == b"ONE LINE OF TEXT\n"
    assert sorted(p.name for p in out.iterdir()) == ["adapter_record.json", "first.txt", "second.txt"]
    printed = capsys.readouterr().out.splitlines()
    assert len(printed) == 3
    for name in ("first.txt", "second.txt", "adapter_record.json"):
        assert any(name in line for line in printed)


def test_the_record_names_the_adapter_and_its_checksums_match(echo, source, tmp_path):
    out = tmp_path / "out"
    assert main(["adapt", "echo", "--out", str(out), "--source", str(source)]) == 0
    record = json.loads((out / "adapter_record.json").read_text(encoding="utf-8"))
    assert sorted(record) == ["adapter", "read", "stream", "version", "wrote"]
    assert record["adapter"] == "echo"
    assert record["stream"] == "test"
    assert record["version"] == adapters.VERSION
    assert record["read"] == {str(source): sha(source.read_bytes())}
    assert record["wrote"] == {
        "first.txt": sha((out / "first.txt").read_bytes()),
        "second.txt": sha((out / "second.txt").read_bytes()),
    }


def test_the_record_holds_no_time(echo, source, tmp_path):
    out = tmp_path / "out"
    run_adapter("echo", _namespace(out, source))
    record = json.loads((out / "adapter_record.json").read_text(encoding="utf-8"))
    keys = set(record) | set(record["read"]) | set(record["wrote"])
    assert keys == {"adapter", "stream", "version", "read", "wrote", str(source), "first.txt", "second.txt"}
    for value in (record["adapter"], record["stream"], record["version"]):
        assert value in ("echo", "test", adapters.VERSION)


def test_a_second_run_into_the_same_folder_refuses_and_changes_nothing(echo, source, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["adapt", "echo", "--out", str(out), "--source", str(source)]) == 0
    before = snapshot(out)
    capsys.readouterr()
    source.write_bytes(b"changed text\n")
    assert main(["adapt", "echo", "--out", str(out), "--source", str(source)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "first.txt" in captured.err
    assert snapshot(out) == before


def test_a_record_alone_in_the_folder_is_not_replaced(echo, source, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "adapter_record.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(AdapterError) as error:
        run_adapter("echo", _namespace(out, source))
    assert "adapter_record.json" in str(error.value)
    assert sorted(p.name for p in out.iterdir()) == ["adapter_record.json"]
    assert (out / "adapter_record.json").read_text(encoding="utf-8") == "{}\n"


def test_one_input_file_already_there_stops_the_whole_run(echo, source, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "second.txt").write_bytes(b"kept\n")
    with pytest.raises(AdapterError):
        run_adapter("echo", _namespace(out, source))
    assert sorted(p.name for p in out.iterdir()) == ["second.txt"]
    assert (out / "second.txt").read_bytes() == b"kept\n"


def test_other_files_in_the_folder_do_not_stop_a_run(echo, source, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "notes.txt").write_bytes(b"the scholar's own file\n")
    run_adapter("echo", _namespace(out, source))
    assert (out / "notes.txt").read_bytes() == b"the scholar's own file\n"
    assert (out / "first.txt").exists()


def test_a_name_outside_fills_is_refused_and_nothing_is_written(monkeypatch, source, tmp_path, capsys):
    adapter = Adapter("stray", "test", ("first.txt",), _add_arguments, _read_outside)
    monkeypatch.setitem(ADAPTERS, "stray", adapter)
    out = tmp_path / "out"
    assert main(["adapt", "stray", "--out", str(out), "--source", str(source)]) == 1
    assert "elsewhere.txt" in capsys.readouterr().err
    assert not out.exists() or list(out.iterdir()) == []


def test_two_runs_on_the_same_inputs_give_identical_bytes(echo, source, tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    run_adapter("echo", _namespace(one, source))
    run_adapter("echo", _namespace(two, source))
    assert sorted(p.name for p in one.iterdir()) == sorted(p.name for p in two.iterdir())
    for path in one.iterdir():
        assert path.read_bytes() == (two / path.name).read_bytes()


def test_run_adapter_returns_the_record(echo, source, tmp_path):
    out = tmp_path / "out"
    record = run_adapter("echo", _namespace(out, source))
    assert record == json.loads((out / "adapter_record.json").read_text(encoding="utf-8"))


def test_an_unknown_adapter_is_refused(source, tmp_path):
    with pytest.raises(AdapterError):
        run_adapter("nothing_by_this_name", _namespace(tmp_path / "out", source))
    with pytest.raises(SystemExit) as stop:
        main(["adapt", "nothing_by_this_name", "--out", str(tmp_path / "out")])
    assert stop.value.code == 2


def test_out_is_required(echo, source):
    with pytest.raises(SystemExit) as stop:
        main(["adapt", "echo", "--source", str(source)])
    assert stop.value.code == 2


def test_the_package_imports_no_other_layer():
    source = Path(adapters.__file__).read_text(encoding="utf-8")
    for layer in ("audit_layer", "ospipe", "verification_procedures", "observability", "features"):
        assert "import " + layer not in source and "from " + layer not in source



def _procedure_inputs():
    """The input files vg.py procedures lists for each stream, read through its command line."""
    import subprocess

    done = subprocess.run(
        [sys.executable, "vg.py", "procedures"],
        cwd=str(ROOT / "verification_procedures"),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return {entry["stream"]: entry["inputs"] for entry in json.loads(done.stdout)}


def test_each_adapter_fills_only_files_its_streams_procedure_reads():
    """D11's late test (reconciliation, Track D, D11).

    Each real adapter's files are among the inputs vg.py procedures lists for
    its stream, named among the required files or matching an optional
    pattern, so the files an adapter writes are files the procedure reads.
    """
    import fnmatch

    inputs = _procedure_inputs()
    real = {name: adapter for name, adapter in ADAPTERS.items() if name != "echo"}
    assert sorted(real) == ["citations", "quarto", "r", "word"]
    for name, adapter in sorted(real.items()):
        assert adapter.stream in inputs, f"{name} serves {adapter.stream}, which no procedure reads"
        listed = inputs[adapter.stream]
        for file in adapter.fills:
            named = file in listed["required"]
            matched = any(fnmatch.fnmatchcase(file, pattern) for pattern in listed["optional"])
            assert named or matched, f"the {name} adapter fills {file}, which {adapter.stream} does not read"


def test_the_word_adapter_fills_every_file_the_prose_procedure_requires():
    inputs = _procedure_inputs()
    assert sorted(ADAPTERS["word"].fills) == sorted(inputs["prose"]["required"])

def _namespace(out, source):
    import argparse

    return argparse.Namespace(out=str(out), source=str(source))
