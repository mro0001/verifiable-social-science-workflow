"""Copy a verification run's results file into a project's verification folder,
where the build reads it.

    python3 handoffs/results_to_pipeline.py --run RUN --stream {prose,citations,data,build}
        --project DIR [--product NAME]

RUN/results.json is copied byte for byte to DIR/verification/<stream>.json,
replacing an older copy. With --product NAME it goes to
DIR/verification/NAME/<stream>.json instead, the folder a build file with
several products reads for that product, and the product's folder is made when
absent. NAME is one folder name of letters, digits, hyphens, and underscores,
as ospipe add-product names a product. The script reads only the file's stream
field, and refuses when it differs from --stream, so a data result never lands
as citations. It also refuses a run with no results.json and a product name of
any other form. A refusal exits 2 and writes nothing.

vg.py decide writes the scholar's decisions into the run's own results file, so
the scholar runs this copy again after deciding. It is a plain copy kept in
handoffs/ for a scholar to replace when they connect the layers. No layer's code
calls it. Standard library only.
"""
import argparse
import json
import os
import re
import shutil
import sys

STREAMS = ("prose", "citations", "data", "build")
PRODUCT_NAME = re.compile(r"[A-Za-z0-9_-]+")


def refuse(message):
    print(message, file=sys.stderr)
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="results_to_pipeline.py",
        description="Copy a run's results file into a project's verification folder.")
    parser.add_argument("--run", required=True, help="the run folder")
    parser.add_argument("--stream", required=True, choices=STREAMS,
                        help="the stream the results belong to")
    parser.add_argument("--project", required=True, help="the project folder")
    parser.add_argument("--product", default=None,
                        help="the product whose verification folder gets the copy")
    args = parser.parse_args(argv)

    if args.product is not None and not PRODUCT_NAME.fullmatch(args.product):
        return refuse("product name %r is not one folder name of letters, digits, "
                      "hyphens, and underscores" % args.product)

    source = os.path.join(args.run, "results.json")
    if not os.path.isfile(source):
        return refuse("no results file at %s, since only a run that completed has one" % source)
    if not os.path.isdir(args.project):
        return refuse("no project folder at %s" % args.project)
    try:
        with open(source, encoding="utf-8") as f:
            stream = json.load(f).get("stream")
    except (ValueError, AttributeError):
        return refuse("%s is not a results file with a stream field" % source)
    if stream != args.stream:
        return refuse("%s holds results of the %s stream, not %s" % (source, stream, args.stream))

    folder = os.path.join(args.project, "verification")
    if args.product is not None:
        folder = os.path.join(folder, args.product)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, args.stream + ".json")
    shutil.copyfile(source, dest)
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
