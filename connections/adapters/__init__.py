"""The file adapters, which turn a tool's files into a stream's input files (Track D, step D11).

Appendix A2.2 says file adapters turn the files a scholar's tools save into the
fixed files the verification layer uses, one adapter for each tool and stream
(Figure A2). Table A6 lists adapters for Word, a citation manager's export, R,
and Quarto as specified, and the proposal names the R and Quarto adapters as
designed but not built (Status paragraph 2).

An adapter fills its stream's input files, the files the stream's procedure
reads, because the procedure's own steps fill the report from them. Every
adapter runs as python3 -m connections adapt <name> --out DIR, reads only the
files named on its command line, writes only its declared input files plus
adapter_record.json, gives the same bytes for the same inputs, and refuses to
replace a file already in DIR (Track D choice 12). The reconciliation calls
these input files.

An Adapter is a name, the stream it serves, the input files it fills,
add_arguments, which adds its options to its command, and read, which takes
the parsed options and returns the paths it read and a mapping of input file
name to bytes. read writes nothing. run_adapter writes.
"""
import hashlib
import json
from collections import namedtuple
from pathlib import Path
from typing import Dict

# The version of the adapter code, written into each adapter_record.json.
VERSION = "0.2.0"

RECORD = "adapter_record.json"

Adapter = namedtuple("Adapter", "name stream fills add_arguments read")

# The adapters, by name. Later steps add theirs.
ADAPTERS = {}  # type: Dict[str, Adapter]


class AdapterError(ValueError):
    """An adapter run was refused. The message names the adapter, the folder, or the file."""


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def run_adapter(name: str, args) -> dict:
    """Run the adapter called name with the parsed options args and return its record.

    args.out is the output folder, made if it is missing. The run is refused,
    with AdapterError and nothing written, when the adapter is unknown, when
    the folder already holds one of the adapter's input files or
    adapter_record.json, when read returns a name outside the adapter's
    fills, or when read raises AdapterError itself. Otherwise each input file
    and then adapter_record.json is written, and one line per file is printed.
    The record holds adapter, stream, version, read (each path as given to its
    sha256), and wrote (each input file to its sha256), and no time.
    """
    adapter = ADAPTERS.get(name)
    if adapter is None:
        raise AdapterError(f"there is no adapter called {name}")
    out = Path(args.out)
    present = [file for file in list(adapter.fills) + [RECORD] if (out / file).exists()]
    if present:
        raise AdapterError(
            f"{out} already holds {', '.join(present)}, which the {name} adapter never replaces"
        )
    read_paths, files = adapter.read(args)
    outside = sorted(file for file in files if file not in adapter.fills)
    if outside:
        raise AdapterError(
            f"the {name} adapter made {', '.join(outside)}, which is not among the files it fills"
        )
    read = {}
    for path in read_paths:
        try:
            read[str(path)] = _sha256(Path(path).read_bytes())
        except OSError as error:
            raise AdapterError(f"{path} cannot be read, {error}")
    record = {
        "adapter": adapter.name,
        "stream": adapter.stream,
        "version": VERSION,
        "read": read,
        "wrote": {file: _sha256(files[file]) for file in sorted(files)},
    }
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AdapterError(f"the folder {out} cannot be made, {error}")
    for file in sorted(files):
        (out / file).write_bytes(files[file])
        print(f"wrote {out / file}")
    (out / RECORD).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out / RECORD}")
    return record


# The adapters later steps add register themselves when imported here.
from connections.adapters import citations, quarto, r, word  # noqa: E402,F401
