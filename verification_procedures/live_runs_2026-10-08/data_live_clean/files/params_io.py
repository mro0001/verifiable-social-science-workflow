"""Read params.yaml once and write the records that a run produces.

Purpose:
    Give every pipeline script one way to read parameters. A value is set once,
    in params.yaml. Every value a script reads through Params is remembered and
    written to that step's parameter record by the run itself, so the record is
    produced by the process and never typed.
Inputs:
    params.yaml - flat `name: value` parameters; the only place values are set.
Outputs:
    params_record_<step>.csv - written by Params.write_record (param, value, step, script).
    model_record_<step>.json - written by write_model_record.
Parameters:
    none; this module carries no values of its own.
Assumptions:
    params.yaml is flat: one `name: value` per line, `#` starts a comment, and a
    string value may be quoted. An indented line means nested YAML, which this
    reader refuses rather than guessing. Standard library only, so the pipeline
    replays anywhere. (R binding: the same contract via yaml::read_yaml and a
    data.frame written with write.csv; Quarto: params read in a setup chunk.)
"""
import csv
import hashlib
import json


def file_sha256(name):
    """Return 'sha256:<hex>' for the bytes of a file; model records carry it."""
    with open(name, "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


def parse_value(text):
    """Turn the text after `name:` into an int, a float, or a string."""
    text = text.strip()
    # A quoted value is a string: strip the matching quotes and keep the rest as is.
    if text[:1] in ("'", '"') and text[-1:] == text[:1]:
        return text[1:-1]
    # Otherwise try int, then float; anything else stays text.
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def load(name):
    """Read a flat params.yaml into a dict; an indented line raises an error."""
    values = {}
    with open(name) as f:
        for line in f:
            # Everything after `#` is a comment (so `#` cannot appear inside a value).
            body = line.split("#", 1)[0].rstrip()
            if not body.strip():
                continue
            # Nested YAML is refused: an indented line is an error, not a guess.
            if body[:1].isspace():
                raise ValueError("params.yaml must be flat; nested line: " + line.strip())
            key, _, text = body.partition(":")
            values[key.strip()] = parse_value(text)
    return values


class Params:
    """The parameters for one step; every value read is remembered for the record."""

    def __init__(self, step, script, name="params.yaml"):
        """Load params.yaml and its hash, and start an empty record of uses."""
        self.step = step
        self.script = script
        self.values = load(name)
        self.sha256 = file_sha256(name)
        self.used = {}

    def __getitem__(self, key):
        """Return the value of `key` and add it to this step's record of uses."""
        value = self.values[key]
        self.used[key] = value
        return value

    def write_record(self):
        """Write params_record_<step>.csv: one row per parameter this run read."""
        with open("params_record_" + self.step + ".csv", "w", newline="") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["param", "value", "step", "script"])
            # Sorted by name so a rerun writes identical bytes.
            for key in sorted(self.used):
                writer.writerow([key, self.used[key], self.step, self.script])


def write_model_record(params, model, spec, n, outputs, estimates):
    """Write model_record_<step>.json: spec, parameters used, params.yaml hash, n, outputs."""
    record = {
        "step": params.step,
        "script": params.script,
        "model": model,
        "spec": spec,
        "params": dict(sorted(params.used.items())),
        "params_sha256": params.sha256,
        "n": n,
        "outputs": outputs,
        "estimates": estimates,
    }
    with open("model_record_" + params.step + ".json", "w") as f:
        json.dump(record, f, indent=2, sort_keys=True)  # not-a-param: JSON layout, not an analytic choice
        f.write("\n")
