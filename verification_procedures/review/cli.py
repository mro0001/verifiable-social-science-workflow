"""The `review` command line, run as `python3 -m review <command>` from
`verification_procedures/`.

Each command prints the lines the pipeline's command line printed for it
before the move. With `--json`, the `returns`, `reconcile`, and `lint`
commands print one JSON value instead, so an adapter in another layer reads
the result as a file rather than importing these modules.
"""
import argparse
import json
import sys
from pathlib import Path

from review.annotate import annotate as run_annotate, load_annotations
from review.lint import lint
from review.reconcile import ReconcileError, format_reconciliation, reconcile as run_reconcile
from review.returns import extract


def _load_allowlist(path):
    """One allowed token per line. Blank lines and lines starting with # are skipped."""
    if path is None:
        return ()
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return tuple(ln.strip() for ln in lines if ln.strip() and not ln.startswith("#"))


def _delta(d):
    return {
        "kind": d.kind,
        "text": d.text,
        "author": d.author,
        "date": d.date,
        "touches_number": d.touches_number,
    }


def _comment(c):
    return {"author": c.author, "text": c.text}


def _change(c):
    return {
        "baseline_text": c.baseline_text,
        "revision_text": c.revision_text,
        "context": c.context,
        "found_text": c.found_text,
    }


def _print_json(value):
    print(json.dumps(value, indent=2))


def _cmd_returns(args):
    bundle = extract(args.reviewed_docx)
    if args.json:
        _print_json({
            "deltas": [_delta(d) for d in bundle.deltas],
            "comments": [_comment(c) for c in bundle.comments],
        })
    else:
        for d in bundle.deltas:
            flag = " [NUMBER — triage]" if d.touches_number else ""
            print("{0} ({1}, {2}){3}: {4!r}".format(d.kind, d.author, d.date, flag, d.text))
        for c in bundle.comments:
            print("comment ({0}): {1!r}".format(c.author, c.text))
    if not bundle.deltas and not bundle.comments:
        print("no tracked changes or comments found", file=sys.stderr)
    return 0


def _cmd_reconcile(args):
    try:
        result = run_reconcile(args.return_docx, args.builds_dir, args.of)
    except ReconcileError as err:
        print("reconcile failed: {0}".format(err), file=sys.stderr)
        return 2
    if args.json:
        _print_json({
            "accepted": [_change(c) for c in result.accepted],
            "rejected": [_change(c) for c in result.rejected],
            "modified": [_change(c) for c in result.modified],
            "pending": [_delta(d) for d in result.pending],
            "author_edits": list(result.author_edits),
            "conflicts": list(result.conflicts),
            "comments": [_comment(c) for c in result.comments],
        })
    else:
        print(format_reconciliation(result))
    return 0


def _cmd_annotate(args):
    result = run_annotate(args.docx, load_annotations(args.spec), args.out, author=args.author)
    print("{0} comments -> {1}".format(result.count, result.out_path))
    for m in result.misses:
        print("miss: anchor not found: {0!r}".format(m), file=sys.stderr)
    return 0


def _cmd_lint(args):
    text = Path(args.manuscript).read_text(encoding="utf-8")
    findings = lint(text, _load_allowlist(args.allowlist))
    if args.json:
        _print_json([{"line": f.line, "token": f.token, "context": f.context} for f in findings])
    else:
        for f in findings:
            print("lint: line {0}: bare numeral {1!r}: {2}".format(f.line, f.token, f.context))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="review")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    ret = sub.add_parser("returns", help="extract tracked edits and comments from a reviewed docx")
    ret.add_argument("reviewed_docx")
    ret.add_argument("--json", action="store_true", help="print one JSON object")

    rec = sub.add_parser("reconcile", help="classify a reviewed return against the build lineage")
    rec.add_argument("return_docx")
    rec.add_argument("--builds-dir", required=True)
    rec.add_argument("--of", required=True, help="the build version the review was of, e.g. v002")
    rec.add_argument("--json", action="store_true", help="print one JSON object")

    ann = sub.add_parser("annotate", help="attach margin comments to a docx from a YAML spec")
    ann.add_argument("--docx", required=True)
    ann.add_argument("--spec", required=True)
    ann.add_argument("--out", required=True)
    ann.add_argument("--author", default="Claude")

    lnt = sub.add_parser("lint", help="flag numbers typed into a markdown source (advisory)")
    lnt.add_argument("--manuscript", required=True)
    lnt.add_argument("--allowlist", default=None, help="a file of allowed tokens, one per line")
    lnt.add_argument("--json", action="store_true", help="print the findings as one JSON list")

    args = parser.parse_args(argv)
    handlers = {
        "returns": _cmd_returns,
        "reconcile": _cmd_reconcile,
        "annotate": _cmd_annotate,
        "lint": _cmd_lint,
    }
    return handlers[args.command](args)
