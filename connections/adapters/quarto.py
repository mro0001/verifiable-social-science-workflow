"""The Quarto adapter, which turns Quarto documents into the data stream's input files (Track D, step D13).

The proposal names an adapter for Quarto as designed but not built (Status
paragraph 2) and lists Quarto among the data and analysis code (Table 1).
The data procedure's conventions put Quarto parameters in the document's YAML
header and give a Quarto step runner quarto render. Each document's header
block, the sections Purpose, Inputs, Outputs, Parameters, and Assumptions and
an optional line Kind: <word>, is the comment lines that open its first code
chunk, after the chunk options (Track D choice 17).

python3 -m connections adapt quarto --out DIR --docs FILE... writes
pipeline.yaml with one step per document in the order given, and params.yaml
with each document's front matter params in order. A nested value, or one
name with two values across documents, is refused with the name and nothing
is written. With no params, params.yaml holds {}. Quarto is never run.
"""
import re
from pathlib import Path

import yaml

from connections.adapters import ADAPTERS, Adapter, AdapterError
from connections.adapters.r import MARKS, pipeline_bytes, step

RUNNER = "quarto render"

# A code chunk Quarto runs opens with three or more backticks and a brace
# holding the language, as in ```{r} or ```{python}. A brace starting with a
# dot, as in ```{.r}, only shows code, and plain backticks start no chunk.
_CHUNK = re.compile(r"^(`{3,})\s*\{[A-Za-z]")
_FENCE_END = re.compile(r"^(`{3,})\s*$")


def add_arguments(parser) -> None:
    parser.add_argument(
        "--docs",
        nargs="+",
        required=True,
        metavar="FILE",
        help="the Quarto documents, in pipeline order",
    )


def _text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        raise AdapterError(f"{path} cannot be read as UTF-8 text, {error}")


def front_matter(path: str, text: str) -> dict:
    """The YAML block between a first line --- and the next line --- or ..., or {} when there is none."""
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return {}
    for number in range(1, len(lines)):
        if lines[number].rstrip() in ("---", "..."):
            block = "\n".join(lines[1:number])
            break
    else:
        raise AdapterError(f"{path} opens front matter with --- and never closes it")
    try:
        found = yaml.safe_load(block)
    except yaml.YAMLError:
        raise AdapterError(f"the front matter of {path} is not YAML")
    if found is None:
        return {}
    if not isinstance(found, dict):
        raise AdapterError(f"the front matter of {path} is not a mapping")
    return found


def first_chunk(text: str) -> str:
    """The lines inside the document's first code chunk, or nothing when it has none."""
    lines = text.splitlines()
    for number, line in enumerate(lines):
        opened = _CHUNK.match(line)
        if opened is None:
            continue
        fence = opened.group(1)
        body = []
        for inner in lines[number + 1:]:
            closed = _FENCE_END.match(inner)
            if closed and len(closed.group(1)) >= len(fence):
                break
            body.append(inner)
        return "\n".join(body)
    return ""


def _same(one, two) -> bool:
    return type(one) is type(two) and one == two


def read(args):
    docs = list(args.docs)
    steps = []
    params = {}
    first_seen = {}
    for doc in docs:
        text = _text(doc)
        header = front_matter(doc, text)
        given = header.get("params")
        if given is None:
            given = {}
        if not isinstance(given, dict):
            raise AdapterError(f"the params of {doc} are not a mapping of names to values")
        for name, value in given.items():
            if isinstance(value, (dict, list)):
                raise AdapterError(f"the parameter {name} in {doc} holds a nested value")
            if name in params and not _same(params[name], value):
                raise AdapterError(
                    f"the parameter {name} is {params[name]!r} in {first_seen[name]} and {value!r} in {doc}"
                )
            if name not in params:
                params[name] = value
                first_seen[name] = doc
        steps.append(step(doc, first_chunk(text), RUNNER, MARKS))
    params_text = yaml.safe_dump(params, sort_keys=False, default_flow_style=False, allow_unicode=True)
    files = {"pipeline.yaml": pipeline_bytes([], steps), "params.yaml": params_text.encode("utf-8")}
    return docs, files


ADAPTER = Adapter("quarto", "data", ("pipeline.yaml", "params.yaml"), add_arguments, read)
ADAPTERS[ADAPTER.name] = ADAPTER
