"""The shapes the publish modules share (publish design R16).

collect.py fills a Collected from the project, counts.py turns it into the
counts every published number comes from, render.py and figure.py write the
pages and the figure from both, and assemble.py plans and writes the
repository. Each record here is a namedtuple, so it compares by value and
prints plainly in a test.
"""
import collections


class PublishError(Exception):
    """A reason publish stops. The message starts in lower case, so it can
    follow "publish build stopped, "."""


# The four verification streams, as ospipe's build reads them, and the three
# data phase reports, which reach no build.
STREAMS = ("prose", "citations", "data", "build")
PHASES = ("data_collection", "data_cleaning", "data_analysis")

# The names the README and the figure give each stream and its check.
STREAM_TITLES = collections.OrderedDict((
    ("prose", "Prose"),
    ("citations", "References"),
    ("data", "Data and analysis code"),
    ("build", "Build"),
))
CHECK_TITLES = collections.OrderedDict((
    ("prose", "Change review"),
    ("citations", "Source support"),
    ("data", "Code"),
    ("build", "Build integrity"),
))
PHASE_TITLES = collections.OrderedDict((
    ("data_collection", "data collection"),
    ("data_cleaning", "data cleaning"),
    ("data_analysis", "data analysis"),
))

WORKFLOW_URL = "https://github.com/mro0001/verifiable-social-science-workflow"
HARNESS_NAMES = collections.OrderedDict((
    ("claude_code", "Claude Code"),
    ("forgecode", "ForgeCode"),
))

MANIFEST_PATH = "docs/publish_manifest.json"
MANIFEST_SCHEMA = "publish-repo"
SCHEMA_VERSION = 1

# The answers file, read once (design A.1, R1 to R18). sessions, check, and
# github are plain dicts with every key filled; github is None when absent.
# anonymous is true unless the answers say false: the scholar's name and its
# words are then scrubbed from the session index and looked for by the check.
Answers = collections.namedtuple("Answers", (
    "title summary repo_url workflow_url workflow_folder runs exclude "
    "harness_names notes files anonymous sessions check github phase_runs unknown_keys"))

# One row of a product's ledger, builds/<product>/BUILDS.md. epoch is the
# build date's midnight UTC in seconds, the SOURCE_DATE_EPOCH that rebuilds it.
LedgerRow = collections.namedtuple("LedgerRow", (
    "version date git sha256 purpose verification runs epoch"))

# A research product from the Makefile map, with its ledger rows, oldest
# first, and its latest row, or None when it has no numbered build.
Product = collections.namedtuple("Product", (
    "name source builds_dir verification_dir to ledger latest"))

# Products that share one verification folder (design R2). key joins the
# product names with "+", label with commas and "and".
Group = collections.namedtuple("Group", "key products verification_dir label")

# One report to publish (design R3). stream is one of STREAMS or PHASES.
# results is the parsed results file and results_bytes the bytes published as
# results.json; report_bytes is the report.md to publish, or None when no
# report whose results match was found; report_from says where it came from,
# "run <id>" or "project", or None.
Report = collections.namedtuple("Report", (
    "group stream run_id results results_bytes report_bytes report_from note"))

# Everything collect() reads from the project and the runs folder.
# project_files maps each path inside project/ to its bytes, after the rules
# that leave files out and the Makefile rewrite, and before report folders are
# added. left_out holds (relpath, rule, why) and rewritten (relpath, what).
Collected = collections.namedtuple("Collected", (
    "project_dir answers products groups reports makefile_style project_files "
    "left_out rewritten pipeline numbers_keys refs_works notes excluded_folders "
    "workflow_root workflow_commit"))

# What run_publish() planned and, when asked, wrote. plan, check_plan, and
# github_plan map relpaths to bytes for OUT, OUT.check, and OUT.github
# (github_plan is None without a github block). left_out_local is the full
# list kept out of OUT, written to OUT.check/left_out.json and printed.
PublishResult = collections.namedtuple("PublishResult", (
    "collected counts plan check_plan github_plan left_out_local notes missing"))
