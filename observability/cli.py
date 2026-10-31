"""The observability layer's command line.

build reads the audit record at --audit-home and writes the view, trace
files and data.js, to --out, which is ~/.observability/view unless named,
so transcript text stays out of project folders, commits, and replication
folders (plan choice 14). --vg-runs adds verification runs, read from
vg.py's run folders (step E13). watch takes the same options and --interval,
and keeps the view live, rebuilding it when the record or a run changes
(step E9). The command line is the one place the connections to the audit
layer and the verification runs are made (plan choice 4).
"""
import argparse
import os
import sys

from observability import build as bd
from observability import kb
from observability import watch as wt

DEFAULT_OUT = os.path.join("~", ".observability", "view")


def _build_options(command):
    """The options build and watch share."""
    command.add_argument("--audit-home", required=True, metavar="DIR",
                         help="the audit home holding audit.sqlite, read only")
    command.add_argument("--project", metavar="DIR",
                         help="keep only sessions in this folder or inside it")
    command.add_argument("--kb-dir", action="append", default=[], metavar="DIR",
                         help="a folder of knowledge base entry files, may be given again")
    command.add_argument("--kb-server", action="append", default=[], metavar="NAME",
                         help="a knowledge base server whose calls are retrievals, may be "
                              "given again (pipeline-kb and workflow-kb when none is given)")
    command.add_argument("--vg-runs", nargs="+", action="extend", default=[],
                         metavar="PATH",
                         help="a run folder of vg.py, or a folder holding run folders, "
                              "read only, one or more")
    command.add_argument("--out", default=DEFAULT_OUT, metavar="DIR",
                         help="the folder the view goes to (default ~/.observability/view)")


def _parser():
    parser = argparse.ArgumentParser(
        prog="python3 -m observability",
        description="Build the observability view from the audit record.")
    commands = parser.add_subparsers(dest="command")
    build = commands.add_parser("build", help="build the trace files and the view's data")
    _build_options(build)
    watch = commands.add_parser(
        "watch", help="keep the view live, rebuilding it when the record changes")
    _build_options(watch)
    watch.add_argument("--interval", type=float, default=5, metavar="SECONDS",
                       help="seconds between checks of the record (default 5)")
    return parser


def _view_options(options):
    return {
        "audit_home": options.audit_home,
        "out": os.path.expanduser(options.out),
        "project": options.project,
        "kb_dirs": tuple(options.kb_dir),
        "kb_servers": tuple(options.kb_server) or kb.KB_SERVERS,
        "vg_runs": tuple(options.vg_runs),
    }


def _summary_line(summary):
    count = summary["traces"]
    return "%s, %d %s" % (summary["out"], count, "trace" if count == 1 else "traces")


def _seconds_text(seconds):
    if float(seconds).is_integer():
        return "%d" % seconds
    return "%g" % seconds


def main(argv=None):
    parser = _parser()
    options = parser.parse_args(argv)
    if options.command not in ("build", "watch"):
        parser.print_help(sys.stderr)
        return 2
    view = _view_options(options)
    try:
        if options.command == "build":
            print(_summary_line(bd.build_view(**view)))
            return 0
        interval = options.interval
        if float(interval).is_integer():
            interval = int(interval)
        print("watching, the view is in %s, checked every %s seconds"
              % (view["out"], _seconds_text(interval)), flush=True)
        summaries = wt.watch(view, interval)
    except bd.RecordError as error:
        print("observability: %s" % error, file=sys.stderr)
        return 1
    print(_summary_line(summaries[-1]))
    return 0
