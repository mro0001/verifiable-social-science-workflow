"""The one place the features run another layer's commands.

The features never import ospipe, the audit layer, or the verification
runtime. They run those layers' command lines in a subprocess through this
file and read the files the commands write (track F choice 2).

  ospipe       python -m ospipe ARGS, with <root>/ospipe first on PYTHONPATH
  audit_layer  python -m audit_layer ARGS, with <root> first on PYTHONPATH
  vg           python <root>/verification_procedures/vg.py ARGS,
               run in <root>/verification_procedures
  connections  python -m connections ARGS, with <root> first on PYTHONPATH

System setup checks the first three by their help (LAYERS). It runs the
connectors' provider set to write the provider setting (Track S, step S2).
"""
import collections
import os
import subprocess
import sys

LAYERS = ("ospipe", "audit_layer", "vg")
# Every layer whose command run_layer starts.
RUNNABLE = LAYERS + ("connections",)

LayerResult = collections.namedtuple("LayerResult", "argv returncode stdout stderr")


class LayerMissing(Exception):
    """A layer's folder or script is not in the root the command was given."""


def default_root():
    """The folder that holds features/."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parts(layer, args, root, python):
    """The argument list, the folder to put first on PYTHONPATH (or None), and the folder to run in."""
    root = os.path.abspath(str(root))
    args = [str(arg) for arg in args]
    if layer == "ospipe":
        return [python, "-m", "ospipe"] + args, os.path.join(root, "ospipe"), None
    if layer == "audit_layer":
        return [python, "-m", "audit_layer"] + args, root, None
    if layer == "vg":
        folder = os.path.join(root, "verification_procedures")
        return [python, os.path.join(folder, "vg.py")] + args, None, folder
    if layer == "connections":
        return [python, "-m", "connections"] + args, root, None
    raise ValueError("unknown layer %r, expected one of %s" % (layer, ", ".join(RUNNABLE)))


def _first_on(path, existing):
    if existing:
        return path + os.pathsep + existing
    return path


def layer_command(layer, args, root, python=sys.executable):
    """(argv, env_add, cwd) for one layer's command.

    env_add holds only what must be added to the environment, PYTHONPATH with
    the layer's folder first and any PYTHONPATH already set after it. cwd is
    None when the command runs in the caller's folder.
    """
    argv, first, cwd = _parts(layer, args, root, python)
    env_add = {}
    if first is not None:
        env_add["PYTHONPATH"] = _first_on(first, os.environ.get("PYTHONPATH", ""))
    return argv, env_add, cwd


def _required(layer, root):
    root = os.path.abspath(str(root))
    if layer == "ospipe":
        return os.path.join(root, "ospipe", "ospipe")
    if layer == "audit_layer":
        return os.path.join(root, "audit_layer")
    if layer == "connections":
        return os.path.join(root, "connections")
    return os.path.join(root, "verification_procedures", "vg.py")


def run_layer(layer, args, root=None, cwd=None, env=None, timeout=600):
    """Run one layer's command and give back LayerResult(argv, returncode, stdout, stderr).

    env is merged into the current environment. A cwd given here is used in
    place of the layer's own folder. A nonzero exit is returned, never
    raised. LayerMissing names the layer's folder or script when the root
    lacks it.
    """
    if root is None:
        root = default_root()
    argv, first, own_cwd = _parts(layer, args, root, sys.executable)
    needed = _required(layer, root)
    if not os.path.exists(needed):
        raise LayerMissing("the %s layer is missing, %s does not exist" % (layer, needed))
    merged = dict(os.environ)
    if env:
        merged.update({str(key): str(value) for key, value in env.items()})
    if first is not None:
        merged["PYTHONPATH"] = _first_on(first, merged.get("PYTHONPATH", ""))
    done = subprocess.run(
        argv, cwd=cwd if cwd is not None else own_cwd, env=merged,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, timeout=timeout)
    return LayerResult(argv, done.returncode, done.stdout, done.stderr)
