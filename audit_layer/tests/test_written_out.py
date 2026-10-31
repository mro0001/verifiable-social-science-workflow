"""The two tests of written-out files (Track A, Step A21).

Appendix Table A5's first row names the two tests of written-out files
without stating them. Plan choice 22 states them. First, every table has a
written-out form, and what is written out reads back as the store's current
rows. Second, with the audit home deleted, the written-out folder alone loads
and checks out, and nothing in it names a database row or the audit home.
They follow A2.3's replication folder, which another researcher can rebuild
from alone, and the records A2.4 writes out for it, and match spec 0.11's two
deletion tests.

Each test starts from the store full_store.build_full_store makes and adds,
in its own setup, the Forge story conversation in the same project and a
second version of the dataset, so the store holds every kind of row the
write-out covers. The project is written out with every source, every
version of every dataset, and the knowledge entries. read_written loads the
folder back with the standard library and PyYAML only.

Every file here is synthetic. No real session file or Forge database is
read, nothing here calls a model or the network, and every test runs with
its home folder inside a temporary folder. Run from the repository root with
python3 -m pytest -q audit_layer/tests.
"""
import ast
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

from audit_layer.capture import capture_session  # noqa: E402
from audit_layer.records.rationales import rationales  # noqa: E402
from audit_layer.records.session_writes import session_writes  # noqa: E402
from audit_layer.store import LISTS, TABLES, current  # noqa: E402
from audit_layer.stores.data import add_dataset  # noqa: E402
from audit_layer.tests.full_store import DATA, DATASET, GIVEN, STORY_ID, build_full_store  # noqa: E402
from audit_layer.tests.read_written import read_written  # noqa: E402
from audit_layer.writeout import write_out_project  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "forgecode_make_store", Path(__file__).parent / "fixtures" / "forgecode" / "make_store.py"
)
forge = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(forge)

KEPT = ("created_at", "session", "origin", "method", "reason")

# The fields that name another row, and what each is written as.
REFERENCES = {
    "events": ("session_row_id",),
    "transcripts": ("session_row_id",),
    "source_originals": ("source",),
    "source_texts": ("source",),
    "datasets": ("table_name",),
    "codebook": ("dataset",),
}

# The elements written as CSV, which keep a row's own fields and no provenance.
CSV_ONLY = ("codebook", "ds_*")

# W's three records, the records the procedures read. They are not tables, and
# their readers fix their formats, so a rationale keeps its own id, rNN.
RECORDS = ("citation_log", "session_writes", "rationales")


@pytest.fixture(autouse=True)
def home_folder(tmp_path, monkeypatch):
    """Each test's own home folder, so nothing reaches the real ~/.audit_layer, ~/forge, or a real root."""
    home = tmp_path / "home_folder"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AUDIT_HOME", raising=False)
    return home


@pytest.fixture
def full(tmp_path):
    """The full store, with the Forge story conversation and a second dataset version added."""
    built = build_full_store(tmp_path / "full")
    forge_db = forge.make_store(tmp_path / "forge" / ".forge.db", built.project)
    summary = capture_session(
        built.store, "forgecode", f"{forge_db}#{forge.STORY_ID}", built.settings
    )
    assert summary.events and summary.transcripts
    second = tmp_path / "second" / DATA.name
    second.parent.mkdir(parents=True)
    second.write_bytes(DATA.read_bytes() + b"both,Posting and definition,60,9,35.5\n")
    assert add_dataset(built.store, DATASET, second, "2026-10-24", {}, GIVEN)["version"] == 2
    yield built
    built.store.db.close()


@pytest.fixture
def out(tmp_path):
    return tmp_path / "written"


def every_catalog_version(store):
    cursor = store.db.execute("SELECT name, version FROM datasets ORDER BY rowid")
    return [(name, version) for name, version in cursor.fetchall()]


def write_everything(full, out):
    citekeys = [row["citekey"] for row in current(full.store, "sources")]
    return write_out_project(
        full.store,
        full.project,
        out,
        citekeys=citekeys,
        datasets=every_catalog_version(full.store),
        knowledge=True,
    )


def stored_rows(store, table):
    cursor = store.db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def store_tables(store):
    cursor = store.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return sorted(row[0] for row in cursor.fetchall())


def written_names(store):
    """What each row id the write-out names is written as."""
    names = {}
    for row in stored_rows(store, "sessions"):
        names[row["id"]] = row["harness_session_id"]
    for row in stored_rows(store, "sources"):
        names[row["id"]] = row["citekey"]
    for row in stored_rows(store, "datasets"):
        # The catalog record names its table, and a codebook row its catalog
        # row, each by the path of the version's CSV file.
        names[row["table_name"]] = f"data/{row['name']}_v{row['version']}.csv"
        names[row["id"]] = names[row["table_name"]]
    return names


def as_written(table, row, names):
    """The row as the write-out gives it back, its fields then its provenance."""
    record = {name: row[name] for name, _ in TABLES[table]}
    for name in REFERENCES.get(table, ()):
        record[name] = names[record[name]]
    if table not in CSV_ONLY:
        for name in KEPT:
            record[name] = row[name]
    return record


def expected_rows(store):
    """Each element's rows as the store holds them, as the write-out should give them back.

    Every table gives its current rows, with two kinds of table read whole.
    knowledge_history holds only replaced versions, each a version kept in
    full. Each dataset version is named, so the catalog row of every version
    is written, the latest's current and each earlier one as the table keeps it.
    """
    names = written_names(store)
    expected = {}
    for table in TABLES:
        if table in ("knowledge_history", "datasets"):
            rows = stored_rows(store, table)
            for row in rows:
                for name in LISTS.get(table, ()):
                    row[name] = json.loads(row[name])
        else:
            rows = current(store, table)
        expected[table] = [as_written(table, row, names) for row in rows]
    tables = []
    for catalog in stored_rows(store, "datasets"):
        columns = [entry["variable"] for entry in current(store, "codebook", dataset=catalog["id"])]
        rows = [{name: row[name] for name in columns} for row in stored_rows(store, catalog["table_name"])]
        tables.append({"dataset": names[catalog["table_name"]], "rows": rows})
    expected["ds_*"] = tables
    return expected


def canonical(rows):
    return sorted(json.dumps(row, sort_keys=True) for row in rows)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe(part):
    """A part of a session id as the write-out puts it in a path."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", part)


def transcript_file(harness, session_id):
    suffix = "json" if harness == "forgecode" else "jsonl"
    return "audit/transcripts/{}/{}.{}".format(
        harness, "/".join(safe(part) for part in session_id.split("/")), suffix
    )


def records_in(folder):
    """Every record of every YAML list and JSON Lines file listed, with its path.

    W's three records are left out, since they hold no store rows.
    """
    listed = yaml.safe_load((folder / "written_out.yaml").read_text(encoding="utf-8"))["files"]
    for item in listed:
        path = item["path"]
        if path.startswith("working/") or item["element"] in RECORDS:
            continue
        text = (folder / path).read_text(encoding="utf-8") if path.endswith((".yaml", ".jsonl")) else None
        if text is None:
            continue
        if path.endswith(".yaml"):
            records = yaml.safe_load(text) or []
        else:
            records = [json.loads(line) for line in text.splitlines() if line]
        for record in records:
            yield path, record


def test_read_written_uses_the_standard_library_and_pyyaml_only():
    tree = ast.parse((Path(__file__).parent / "read_written.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported == {"csv", "io", "json", "re", "pathlib", "typing", "yaml"}


# Test 1, every stored element can be written out.


def test_1_every_table_in_the_store_has_a_registry_row(full, out):
    tables = store_tables(full.store)
    assert sum(1 for name in tables if name.startswith("ds_")) == 2
    write_everything(full, out)
    held = {row["element"] for row in current(full.store, "export_registry")}
    registry = (out / "schema" / "export_registry.yaml").read_text(encoding="utf-8")
    written = {form["element"] for form in yaml.safe_load(registry)}
    for table in tables:
        element = "ds_*" if table.startswith("ds_") else table
        assert element in held, table
        assert element in written, table


def test_1_what_is_written_out_reads_back_as_the_store_s_current_rows(full, out):
    expected = expected_rows(full.store)
    write_everything(full, out)
    read = read_written(out)

    assert set(read) - set(RECORDS) == set(expected)
    for element, rows in expected.items():
        assert rows, element
        assert canonical(read[element]) == canonical(rows), element


def test_1_w_s_records_read_back_as_their_writers_give_them(full, out):
    write_everything(full, out)
    read = read_written(out)
    assert read["session_writes"] == session_writes(full.store, full.project)
    assert read["rationales"] == rationales(full.store, full.project / "manuscript.md")
    assert {entry["session"] for entry in read["rationales"]} == {STORY_ID, forge.STORY_ID}
    log = yaml.safe_load((out / "audit" / "citation_log.yaml").read_text(encoding="utf-8"))
    assert sorted(log["citations"]) == ["dumont2014", "healy2020", "nakamura2020"]


def test_1_each_kind_of_row_is_there_to_be_read_back(full, out):
    write_everything(full, out)
    read = read_written(out)
    harnesses = {row["harness"] for row in read["sessions"]}
    assert harnesses == {"claude_code", "forgecode"}
    assert [row["version"] for row in read["datasets"]] == [1, 2]
    assert {item["dataset"] for item in read["ds_*"]} == {
        f"data/{DATASET}_v1.csv",
        f"data/{DATASET}_v2.csv",
    }
    assert read["knowledge_history"] and read["source_originals"] and read["source_texts"]


def test_1_references_come_back_as_session_ids_citekeys_and_paths(full, out):
    write_everything(full, out)
    read = read_written(out)
    session_ids = {row["harness_session_id"] for row in read["sessions"]}
    assert {row["session_row_id"] for row in read["events"]} <= session_ids
    assert {row["session_row_id"] for row in read["transcripts"]} == session_ids
    citekeys = {row["citekey"] for row in read["sources"]}
    assert {row["source"] for row in read["source_originals"]} <= citekeys
    assert {row["source"] for row in read["source_texts"]} <= citekeys
    paths = {row["table_name"] for row in read["datasets"]}
    assert all((out / path).is_file() for path in paths)
    assert {row["dataset"] for row in read["codebook"]} == paths


# Test 2, the written-out files stand alone.


@pytest.fixture
def alone(full, out):
    """The written-out folder, with the audit home deleted after the write-out."""
    write_everything(full, out)
    home = full.home
    full.store.db.close()
    shutil.rmtree(str(home))
    assert not home.exists()
    return out


def test_2_every_listed_file_exists_with_its_sha256(alone):
    listed = yaml.safe_load((alone / "written_out.yaml").read_text(encoding="utf-8"))["files"]
    assert listed
    for item in listed:
        assert (alone / item["path"]).is_file(), item["path"]
        assert sha256(alone / item["path"]) == item["sha256"], item["path"]
    on_disk = {p.relative_to(alone).as_posix() for p in alone.rglob("*") if p.is_file()}
    assert on_disk == {item["path"] for item in listed} | {"written_out.yaml"}


def test_2_every_yaml_json_lines_and_csv_file_loads(alone):
    listed = yaml.safe_load((alone / "written_out.yaml").read_text(encoding="utf-8"))["files"]
    loaded = 0
    for item in listed:
        path = alone / item["path"]
        if item["path"].startswith("working/"):
            continue
        text = path.read_text(encoding="utf-8") if path.suffix in (".yaml", ".jsonl", ".csv") else None
        if text is None:
            continue
        if item["element"] == "citation_log":
            assert set(yaml.safe_load(text)) == {"citations"}, item["path"]
        elif path.suffix == ".yaml":
            assert isinstance(yaml.safe_load(text), list), item["path"]
        elif path.suffix == ".jsonl":
            assert all(isinstance(json.loads(line), dict) for line in text.splitlines() if line)
        else:
            assert list(csv.reader(io.StringIO(text, newline=""))), item["path"]
        loaded += 1
    assert loaded >= 15


def test_2_each_transcript_matches_its_listed_checksum(alone):
    sessions = yaml.safe_load((alone / "audit" / "sessions.yaml").read_text(encoding="utf-8"))
    transcripts = yaml.safe_load((alone / "audit" / "transcripts.yaml").read_text(encoding="utf-8"))
    latest = {}
    for record in transcripts:
        latest[record["session_row_id"]] = record
    assert len(sessions) == 3
    for session in sessions:
        record = latest[session["harness_session_id"]]
        path = alone / transcript_file(session["harness"], session["harness_session_id"])
        assert sha256(path) == record["file_sha256"], session["harness_session_id"]
        assert path.stat().st_size == record["byte_size"]


def test_2_each_working_file_sits_at_its_path_with_its_snapshot_s_checksum(alone, full):
    snapshots = yaml.safe_load((alone / "audit" / "snapshots.yaml").read_text(encoding="utf-8"))
    latest = {}
    for record in snapshots:
        full_path = os.path.join(record["project"], record["path"])
        latest[os.path.relpath(full_path, str(full.project))] = record
    assert latest
    for path, record in latest.items():
        assert sha256(alone / "working" / path) == record["file_sha256"], path


def test_2_each_dataset_s_csv_has_its_catalog_row_count(alone):
    catalog = yaml.safe_load((alone / "data" / "datasets.yaml").read_text(encoding="utf-8"))
    assert len(catalog) == 2
    for record in catalog:
        text = (alone / record["table_name"]).read_text(encoding="utf-8")
        rows = list(csv.reader(io.StringIO(text, newline="")))[1:]
        assert len(rows) == record["row_count"], record["table_name"]


def test_2_no_record_has_an_id_or_supersedes(alone):
    count = 0
    for path, record in records_in(alone):
        assert isinstance(record, dict), path
        assert "id" not in record and "supersedes" not in record, path
        count += 1
    assert count


def test_2_no_file_names_a_row_id_the_store_made(full, out):
    made = set()
    for table in store_tables(full.store):
        for row in stored_rows(full.store, table):
            if re.fullmatch(r"[0-9a-f]{32}", str(row["id"])):
                made.add(row["id"])
    assert len(made) > 50
    write_everything(full, out)
    for path in out.rglob("*"):
        if path.is_file():
            found = set(re.findall(rb"[0-9a-f]{32}", path.read_bytes()))
            assert not {item.decode("ascii") for item in found} & made, path


def test_2_no_file_holds_the_audit_home_s_path(alone, full):
    homes = {str(full.home), os.path.realpath(str(full.home))}
    for path in alone.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for home in homes:
                assert home.encode("utf-8") not in data, path
                assert json.dumps(home)[1:-1].encode("utf-8") not in data, path
