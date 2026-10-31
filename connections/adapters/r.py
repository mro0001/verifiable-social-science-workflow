"""The R adapter, which turns R scripts into the data stream's pipeline.yaml (Track D, step D12).

The proposal names an adapter for R as designed but not built (Status
paragraph 2) and lists R among the data and analysis code (Table 1). The
data procedure's conventions say R binds the same contract as Python with
runner Rscript, and that each script opens with the sections Purpose, Inputs,
Outputs, Parameters, and Assumptions. Here that block is the comment lines at
the top of the script, marked #' or #, with an optional line Kind: <word>
(Track D choice 17).

python3 -m connections adapt r --out DIR --scripts FILE... [--helpers FILE...]
writes pipeline.yaml with the helpers and one step per script in the order
given, each with id (the file name without .R), kind (the Kind line, else
step), runner Rscript, script, inputs (the names under Inputs), and outputs
(the names under Outputs). Scripts are read, never run.
"""
from pathlib import Path

import yaml

from connections.adapters import ADAPTERS, Adapter, AdapterError
from connections.adapters.headers import file_names, header_lines, kind_of, sections

MARKS = ("#'", "#")
RUNNER = "Rscript"


def add_arguments(parser) -> None:
    parser.add_argument(
        "--scripts",
        nargs="+",
        required=True,
        metavar="FILE",
        help="the R scripts, in pipeline order",
    )
    parser.add_argument(
        "--helpers",
        nargs="*",
        default=[],
        metavar="FILE",
        help="R files the scripts source, listed as the pipeline's helpers",
    )


def _text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        raise AdapterError(f"{path} cannot be read as UTF-8 text, {error}")


def step(path: str, text: str, runner: str, marks=MARKS) -> dict:
    """One pipeline step for the script or document at path, from its header block."""
    lines = header_lines(text, marks)
    found = sections(lines)
    return {
        "id": Path(path).stem,
        "kind": kind_of(lines) or "step",
        "runner": runner,
        "script": path,
        "inputs": file_names(found.get("Inputs", [])),
        "outputs": file_names(found.get("Outputs", [])),
    }


def pipeline_bytes(helpers, steps) -> bytes:
    """pipeline.yaml as bytes, helpers first and then the steps, keys in the order given."""
    text = yaml.safe_dump(
        {"helpers": list(helpers), "steps": list(steps)},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    return text.encode("utf-8")


def read(args):
    helpers = list(args.helpers or [])
    for helper in helpers:
        _text(helper)
    steps = [step(script, _text(script), RUNNER) for script in args.scripts]
    return list(args.scripts) + helpers, {"pipeline.yaml": pipeline_bytes(helpers, steps)}


ADAPTER = Adapter("r", "data", ("pipeline.yaml",), add_arguments, read)
ADAPTERS[ADAPTER.name] = ADAPTER
