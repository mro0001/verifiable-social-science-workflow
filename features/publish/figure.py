"""The README's figure, docs/results.svg (publish design A.4, R14).

The figure is the workflow's layer figure filled in with what the reports
found, laid out like the demo's results figure: the scholar and the AI
harness at the top, four columns (Prose, References, Data and analysis code,
Build) in three rows, "What was checked", "What the checks found", and
"Reproducible pipeline", the audit layer at the right, and the products with
their latest builds at the bottom right. A stream that no group has a report
for is drawn in grey and says "no report yet".

- results_svg(collected, counts) gives the SVG text. It is pure and
  deterministic: every number in it comes from counts, and every coordinate is
  a whole pixel.
- alt_text(collected, counts) gives the same figure as one paragraph of plain
  text, for the README's image, so every number the figure shows is also in
  the alt text.

Text is wrapped by a width estimate, 0.6 times the font size for each
character of regular text and 0.66 for bold, inside 12 pixels of padding on
each side, so the box sizes follow the text and no line runs past its box.
"""
import collections

from features.publish.model import CHECK_TITLES, STREAMS, STREAM_TITLES

WIDTH = 1000
FONT = "Helvetica, Arial, sans-serif"
MONO = "Menlo, Consolas, monospace"

INK = "#16191F"
MUTED = "#4B5563"
BRASS = "#7A5C12"
BRASS_FILL = "#F5EFDE"
RED = "#8C2F39"
RED_FILL = "#F8E9EA"
RED_BAND = "#FBF2F2"
SLATE = "#2F4858"
SLATE_FILL = "#E9EFF3"
SLATE_SUB = "#E0E4E6"
AUDIT = "#5B3A8E"
AUDIT_FILL = "#EFE9F6"
AUDIT_BAND = "#F5F2FA"
GHOST = "#6B7280"
GHOST_FILL = "#F3F4F6"
WHITE = "#FFFFFF"

TITLE_SIZE = 14
SMALL_SIZE = 13
TITLE_LINE = 17
SMALL_LINE = 16
REGULAR_FACTOR = 0.6
BOLD_FACTOR = 0.66
PAD_X = 12
PAD_Y = 9

LABEL_X = 12
LABEL_WIDTH = 124
COLUMN_X = (222, 394, 566, 738)
COLUMN_WIDTH = 164
BAND_LEFT = 134
BAND_RIGHT = 826
AUDIT_LEFT = 850
AUDIT_RIGHT = 988
AUDIT_X = 919
AUDIT_BOX_WIDTH = 126
PRODUCT_LEFT = 846
PRODUCT_WIDTH = 148
TOP_X = 480
TOP_WIDTH = 330

# One line of a box: its text, whether it is bold, mono, and its color (None
# takes the box's text color).
Line = collections.namedtuple("Line", "text bold mono color")
# A short space between two products in the products box.
GAP = Line("", False, False, None)
GAP_HEIGHT = 6
# One stream's column: its stream, whether it is drawn in grey, and the text
# of its two boxes.
Column = collections.namedtuple("Column", "stream ghost title checked check_title found")


def _count(counts, key):
    value = counts.get(key, 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _plural(number, word, many=None):
    if number == 1:
        return "%d %s" % (number, word)
    return "%d %s" % (number, many or word + "s")


def join_and(items):
    """"a", "a and b", or "a, b, and c"."""
    items = [str(item) for item in items]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return "%s and %s" % (items[0], items[1])
    return "%s, and %s" % (", ".join(items[:-1]), items[-1])


def wrap(text, width, size, bold=False, mono=False):
    """The lines of text inside a box width pixels wide, with PAD_X on each
    side. A word longer than a line is cut where the line ends, so no line
    runs past the box."""
    factor = BOLD_FACTOR if bold and not mono else REGULAR_FACTOR
    room = max(1, int((width - 2 * PAD_X) / (factor * size)))
    lines = []
    current = ""
    for word in text.split():
        while len(word) > room:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:room])
            word = word[room:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= room:
            current = current + " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# What the figure says, from the counts.

def _has_stream(counts, stream):
    return _count(counts, "%s.reports" % stream) > 0


def _prose_texts(counts):
    changes = _count(counts, "prose.changes")
    ai = _count(counts, "prose.ai")
    no_reason = _count(counts, "prose.no_reason")
    if changes == 0:
        checked = "no change found"
    else:
        checked = "%s, %d by an AI" % (_plural(changes, "change"), ai)
    if ai == 0:
        found = "no AI change to review"
    elif no_reason == 0:
        found = "each AI change has a recorded reason"
    elif no_reason == 1:
        found = "1 AI change has no recorded reason"
    else:
        found = "%d AI changes have no recorded reason" % no_reason
    return checked, found


def _citation_texts(counts):
    rows = _count(counts, "citations.rows")
    ai = _count(counts, "citations.ai")
    no_quote = _count(counts, "citations.no_quote")
    not_found = _count(counts, "citations.not_found")
    if rows == 0:
        checked = "no citation found"
    else:
        checked = "%s, %d first named by an AI" % (_plural(rows, "citation"), ai)
    if ai == 0:
        found = "no AI citation to check"
    elif no_quote == 0:
        found = "every quote checked was found in its source"
    elif no_quote == 1:
        found = "1 AI citation has no quote found in the source"
    else:
        found = "%d AI citations have no quote found in the source" % no_quote
    if not_found:
        found = "%s, %s not found" % (found, _plural(not_found, "cited work"))
    return checked, found


def _data_texts(counts):
    numbers = _count(counts, "data.numbers")
    reproduce = _count(counts, "data.reproduce")
    scripts = _count(counts, "data.scripts")
    scripts_ai = _count(counts, "data.scripts_ai")
    if numbers == 0:
        checked = "no number found"
    else:
        checked = _plural(numbers, "number")
    if scripts:
        checked = "%s, from %s, %d by an AI" % (checked, _plural(scripts, "script"), scripts_ai)
    if numbers == 0:
        found = "no number to reproduce"
    elif reproduce == numbers:
        found = "all %s reproduce from the raw data" % _plural(numbers, "number")
        if numbers == 1:
            found = "the 1 number reproduces from the raw data"
    else:
        found = "%d of %s %s from the raw data" % (reproduce, _plural(numbers, "number"),
                                                   "reproduces" if reproduce == 1 else "reproduce")
    return checked, found


def _build_texts(counts):
    builds = _count(counts, "builds.total")
    blocking = _count(counts, "build.blocking")
    ai_writes = _count(counts, "build.ai_writes")
    one_source = _count(counts, "build.one_source") if "build.one_source" in counts else 1
    checked = _plural(builds, "numbered build") if builds else "no numbered build yet"
    parts = []
    if not one_source:
        parts.append("a document has more than one source")
    if ai_writes == 0:
        parts.append("no AI wrote to a build")
    else:
        parts.append("AI wrote to a build %s" % (
            "once" if ai_writes == 1 else "%d times" % ai_writes))
    if blocking == 0:
        parts.append("no problem flagged")
    else:
        parts.append("%s flagged" % _plural(blocking, "problem"))
    return checked, ", ".join(parts)


TEXTS = {
    "prose": _prose_texts,
    "citations": _citation_texts,
    "data": _data_texts,
    "build": _build_texts,
}


def columns(counts):
    """The four columns, in the order of STREAMS."""
    found = []
    for stream in STREAMS:
        if _has_stream(counts, stream):
            checked, what = TEXTS[stream](counts)
            found.append(Column(stream, False, STREAM_TITLES[stream], checked,
                                CHECK_TITLES[stream], what))
        else:
            found.append(Column(stream, True, STREAM_TITLES[stream], "no report yet",
                                CHECK_TITLES[stream], "no report yet"))
    return found


def scholar_text(counts):
    approved = _count(counts, "decisions.approved")
    held = _count(counts, "decisions.held")
    undecided = _count(counts, "decisions.undecided")
    phases = ""
    if "phases.decisions.approved" in counts:
        waiting = _count(counts, "phases.decisions.held") + _count(counts, "phases.decisions.undecided")
        if waiting:
            # The data phase reports' items are counted apart, since no build reads them.
            phases = ", and %s of the data phases not yet approved" % _plural(waiting, "item")
    if approved + held + undecided == 0:
        return "approves or holds each item" + phases
    if approved == 0 and held == 0:
        return "approves or holds each item, none decided yet" + phases
    if held == 0 and undecided == 0:
        return "approves or holds each item, all %d approved%s" % (approved, phases)
    parts = []
    for number, word in ((approved, "approved"), (held, "held"), (undecided, "not yet decided")):
        if number:
            parts.append("%d %s" % (number, word))
    return "approves or holds each item, with %s%s" % (join_and(parts), phases)


def harness_text(counts):
    names = [name.strip() for name in str(counts.get("sessions.harnesses") or "").split(";")]
    return join_and([name for name in names if name])


def has_index(counts):
    return "sessions.indexed" in counts


def audit_boxes(counts):
    """The two boxes of the audit layer, as (title, sub, sub_is_mono)."""
    if has_index(counts):
        sessions = _count(counts, "sessions.indexed")
        first = (_plural(sessions, "AI session"), "in the public index", False)
        second = ("Transcripts private", "public index in sessions/", False)
    else:
        first = ("AI sessions", "index not published", False)
        second = ("Transcripts private", "kept by the scholar", False)
    return [first, second]


def pipeline_boxes(collected, counts):
    """The four boxes of the pipeline row, each a list of (text, mono)."""
    sources = []
    for product in collected.products:
        if product.source and product.source not in sources:
            sources.append(product.source)
    if len(sources) > 3:
        shown = [(source, True) for source in sources[:2]]
        shown.append(("and %d more" % (len(sources) - 2), False))
    else:
        shown = [(source, True) for source in sources] or [("no source", False)]
    files = collected.project_files or {}
    works = _count(counts, "refs.works")
    if "refs.bib" in files or works:
        refs = [("refs.bib", True), (_plural(works, "work"), False)]
    else:
        refs = [("no refs.bib", False)]
    numbers = _count(counts, "numbers.total")
    if "numbers.yml" in files or numbers:
        numbered = [("numbers.yml", True), (_plural(numbers, "number"), False)]
    else:
        numbered = [("no numbers.yml", False)]
    make = [("make", True), ("one command each", False)]
    return [shown, refs, numbered, make]


def product_lines(collected, counts):
    """The products box: each product with its latest version, then its state,
    once when every product shares it."""
    rows = []
    for product in collected.products:
        state_key = "builds.%s.state" % product.name
        if product.latest is None:
            rows.append(("%s" % product.name, "no build yet"))
        else:
            version = counts.get("builds.%s.latest" % product.name) or product.latest.version
            state = counts.get(state_key) or "unverified until the scholar decides"
            rows.append(("%s %s" % (product.name, version), state))
    states = set(state for _, state in rows)
    lines = []
    if len(states) == 1 and rows:
        for title, _ in rows:
            lines.append(Line(title, True, False, None))
        lines.append(Line(rows[0][1], False, False, SLATE_SUB))
    else:
        for index, (title, state) in enumerate(rows):
            if index:
                lines.append(GAP)
            lines.append(Line(title, True, False, None))
            lines.append(Line(state, False, False, SLATE_SUB))
    return lines


def alt_text(collected, counts):
    """The figure as one paragraph, with every number it shows."""
    parts = ["A layer figure of what the workflow found."]
    parts.append("Scholar: %s." % scholar_text(counts))
    harness = harness_text(counts)
    parts.append("AI harness: %s." % harness if harness else "AI harness: not named.")
    for column in columns(counts):
        if column.ghost:
            parts.append("%s: no report yet." % column.title)
        else:
            parts.append("%s: %s. %s: %s." % (column.title, column.checked,
                                              column.check_title, column.found))
    pipeline = []
    for index, box in enumerate(pipeline_boxes(collected, counts)):
        texts = [text for text, _ in box]
        pipeline.append(join_and(texts) if index == 0 else ", ".join(texts))
    parts.append("Reproducible pipeline: %s." % "; ".join(pipeline))
    audit = []
    for index, (title, sub, _) in enumerate(audit_boxes(counts)):
        if index == 0 and has_index(counts):
            audit.append("%s %s" % (title, sub))
        else:
            audit.append("%s, %s" % (title if index == 0 else title.lower(), sub))
    parts.append("Audit layer: %s." % "; ".join(audit))
    rows = []
    for line in product_lines(collected, counts):
        if line == GAP:
            continue
        if line.bold:
            rows.append([line.text])
        elif rows:
            rows[-1].append(line.text)
    if len(rows) > 1 and all(len(row) == 1 for row in rows[:-1]):
        # Every product shares the one state on the last line.
        products = "%s, %s" % (join_and([row[0] for row in rows]), rows[-1][-1])
    else:
        products = "; ".join(", ".join(row) for row in rows)
    parts.append("Products: %s." % products)
    text = " ".join(parts)
    return text.replace("[", "(").replace("]", ")")


# Drawing.

def _box_lines(title, sub, width, title_mono=False, sub_mono=False, sub_color=None):
    lines = []
    if title:
        for part in wrap(title, width, TITLE_SIZE, bold=True, mono=title_mono):
            lines.append(Line(part, True, title_mono, None))
    if sub:
        for part in wrap(sub, width, SMALL_SIZE, mono=sub_mono):
            lines.append(Line(part, False, sub_mono, sub_color))
    return lines


def _wrap_lines(lines, width):
    out = []
    for line in lines:
        if line == GAP:
            out.append(line)
            continue
        size = TITLE_SIZE if line.bold else SMALL_SIZE
        for part in wrap(line.text, width, size, bold=line.bold, mono=line.mono):
            out.append(Line(part, line.bold, line.mono, line.color))
    return out


def _step(line):
    if line == GAP:
        return GAP_HEIGHT
    return TITLE_LINE if line.bold else SMALL_LINE


def _lines_height(lines):
    return sum(_step(line) for line in lines)


def _box_height(lines, least=0):
    return max(least, _lines_height(lines) + 2 * PAD_Y)


class _Svg(object):
    """Collects the SVG's elements in drawing order."""

    def __init__(self):
        self.parts = []

    def rect(self, x, y, width, height, fill, stroke=None, dashed=False, rx=3):
        attrs = 'x="%d" y="%d" width="%d" height="%d" rx="%d" fill="%s"' % (
            x, y, width, height, rx, fill)
        if stroke:
            attrs += ' stroke="%s" stroke-width="1.5"' % stroke
        if dashed:
            attrs += ' stroke-dasharray="5 3"'
        self.parts.append("<rect %s/>" % attrs)

    def band(self, x, y, width, height, fill):
        self.parts.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>' % (
            x, y, width, height, fill))

    def line(self, x1, y1, x2, y2, color, arrow=False, width="1.5"):
        attrs = 'x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="%s"' % (
            x1, y1, x2, y2, color, width)
        if arrow:
            attrs += ' marker-end="url(#%s)"' % _marker_id(color)
        self.parts.append("<line %s/>" % attrs)

    def text(self, x, y, text, color, bold=False, mono=False, size=SMALL_SIZE, anchor="middle"):
        attrs = 'x="%d" y="%d" fill="%s" font-size="%d"' % (x, y, color, size)
        if anchor != "middle":
            attrs += ' text-anchor="%s"' % anchor
        if bold:
            attrs += ' font-weight="bold"'
        if mono:
            attrs += ' font-family="%s"' % MONO
        self.parts.append("<text %s>%s</text>" % (attrs, _escape(text)))

    def lines(self, cx, top, height, lines, color, anchor="middle"):
        """Draw lines centered in a box from top to top + height."""
        block = _lines_height(lines)
        y = top + (height - block) // 2
        for line in lines:
            step = _step(line)
            if line == GAP:
                y += step
                continue
            size = TITLE_SIZE if line.bold else SMALL_SIZE
            baseline = y + (step - size) // 2 + int(round(size * 0.8))
            self.text(cx, baseline, line.text, line.color or color, bold=line.bold,
                      mono=line.mono, size=size, anchor=anchor)
            y += step


MARKER_COLORS = (INK, BRASS, RED, SLATE, AUDIT, GHOST)


def _marker_id(color):
    return "arrow%s" % color.lstrip("#").lower()


def _markers():
    parts = []
    for color in MARKER_COLORS:
        parts.append(
            '<marker id="%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            'markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker>'
            % (_marker_id(color), color))
    return "<defs>%s</defs>" % "".join(parts)


def _colors(column, row):
    if column.ghost:
        return GHOST, GHOST_FILL, GHOST
    if row == 1:
        return BRASS, BRASS_FILL, BRASS
    return RED, RED_FILL, RED


def results_svg(collected, counts):
    """docs/results.svg, as text ending with one newline."""
    svg = _Svg()
    cols = columns(counts)

    # The scholar and the AI harness.
    top = 10
    scholar = _box_lines("Scholar", scholar_text(counts), TOP_WIDTH)
    scholar_height = _box_height(scholar)
    svg.rect(TOP_X - TOP_WIDTH // 2, top, TOP_WIDTH, scholar_height, WHITE, INK)
    svg.lines(TOP_X, top, scholar_height, scholar, INK)
    harness_top = top + scholar_height + 24
    harness = _box_lines("AI harness", harness_text(counts), TOP_WIDTH)
    harness_height = _box_height(harness)
    middle = top + scholar_height + 12
    svg.line(TOP_X, middle, TOP_X, top + scholar_height + 1, INK, arrow=True)
    svg.line(TOP_X, middle, TOP_X, harness_top - 1, INK, arrow=True)

    # Row 1, what was checked.
    bus = harness_top + harness_height + 14
    row1_top = bus + 18
    row1 = []
    for column in cols:
        row1.append(_box_lines(column.title, column.checked, COLUMN_WIDTH))
    row1_height = max(_box_height(lines, 64) for lines in row1)

    # Row 2, what the checks found, inside the red band.
    band_top = row1_top + row1_height + 14
    row2_top = band_top + 18
    row2 = []
    for column in cols:
        row2.append(_box_lines(column.check_title, column.found, COLUMN_WIDTH))
    row2_height = max(_box_height(lines, 64) for lines in row2)
    band_bottom = row2_top + row2_height + 14

    # Row 3, the reproducible pipeline.
    row3_top = band_bottom + 22
    row3 = []
    for box in pipeline_boxes(collected, counts):
        lines = []
        for text, mono in box:
            lines.append(Line(text, False, True, None) if mono else Line(text, False, False, None))
        row3.append(_wrap_lines(lines, COLUMN_WIDTH))
    row3_height = max(_box_height(lines, 44) for lines in row3)
    row3_middle = row3_top + row3_height // 2

    products = _wrap_lines(product_lines(collected, counts), PRODUCT_WIDTH)
    product_height = _box_height(products, 52)

    # The audit layer, from the harness down to the red band's foot.
    audit_top = harness_top - 6
    audit = audit_boxes(counts)
    audit_lines = []
    for title, sub, mono in audit:
        audit_lines.append(_box_lines(title, sub, AUDIT_BOX_WIDTH, sub_mono=mono))
    first_height = _box_height(audit_lines[0])
    second_height = _box_height(audit_lines[1])
    heading_y = audit_top + 20
    first_top = max(heading_y + 10, row1_top + (row1_height - first_height) // 2)
    second_top = max(first_top + first_height + 10,
                     row2_top + (row2_height - second_height) // 2)
    audit_bottom = max(band_bottom, second_top + second_height + 10)

    # The products box sits below the audit layer, level with the pipeline row
    # when it is short enough, and the arrow from make meets it inside both.
    product_top = max(audit_bottom + 12, row3_middle - product_height // 2)
    arrow_y = min(max(row3_middle, product_top + 14), row3_top + row3_height - 6)

    height = max(row3_top + row3_height, product_top + product_height, audit_bottom) + 10

    # Bands first, so boxes and arrows sit on them.
    svg.band(AUDIT_LEFT, audit_top, AUDIT_RIGHT - AUDIT_LEFT, audit_bottom - audit_top, AUDIT_BAND)
    svg.line(AUDIT_LEFT, audit_top, AUDIT_LEFT, audit_bottom, AUDIT)
    svg.line(AUDIT_RIGHT, audit_top, AUDIT_RIGHT, audit_bottom, AUDIT)
    svg.band(BAND_LEFT, band_top, BAND_RIGHT - BAND_LEFT, band_bottom - band_top, RED_BAND)
    svg.line(BAND_LEFT, band_top, BAND_RIGHT, band_top, RED)
    svg.line(BAND_LEFT, band_bottom, BAND_RIGHT, band_bottom, RED)

    svg.rect(TOP_X - TOP_WIDTH // 2, harness_top, TOP_WIDTH, harness_height, BRASS_FILL, BRASS)
    svg.lines(TOP_X, harness_top, harness_height, harness, BRASS)
    harness_middle = harness_top + harness_height // 2
    svg.line(TOP_X + TOP_WIDTH // 2, harness_middle, AUDIT_LEFT - 1, harness_middle, AUDIT,
             arrow=True)

    svg.text(AUDIT_X, heading_y, "Audit layer", AUDIT, bold=True, size=TITLE_SIZE)
    svg.rect(AUDIT_X - AUDIT_BOX_WIDTH // 2, first_top, AUDIT_BOX_WIDTH, first_height,
             AUDIT_FILL, AUDIT)
    svg.lines(AUDIT_X, first_top, first_height, audit_lines[0], AUDIT)
    svg.rect(AUDIT_X - AUDIT_BOX_WIDTH // 2, second_top, AUDIT_BOX_WIDTH, second_height,
             AUDIT_FILL, AUDIT)
    svg.lines(AUDIT_X, second_top, second_height, audit_lines[1], AUDIT)
    row2_middle = row2_top + row2_height // 2
    svg.line(AUDIT_LEFT, row2_middle, BAND_RIGHT + 1, row2_middle, AUDIT, arrow=True)

    # Row labels.
    for label, color, row_top, row_height in (
            ("What was checked", BRASS, row1_top, row1_height),
            ("What the checks found", RED, row2_top, row2_height),
            ("Reproducible pipeline", SLATE, row3_top, row3_height)):
        lines = [Line(part, True, False, None)
                 for part in wrap(label, LABEL_WIDTH + 2 * PAD_X, TITLE_SIZE, bold=True)]
        svg.lines(LABEL_X, row_top, row_height, lines, color, anchor="start")

    # The brass bus from the harness to the four columns.
    svg.line(TOP_X, harness_top + harness_height, TOP_X, bus, BRASS)
    svg.line(COLUMN_X[0], bus, COLUMN_X[-1], bus, BRASS)

    left = COLUMN_WIDTH // 2
    for index, column in enumerate(cols):
        x = COLUMN_X[index]
        stroke, fill, text = _colors(column, 1)
        svg.line(x, bus, x, row1_top - 1, BRASS, arrow=True)
        svg.rect(x - left, row1_top, COLUMN_WIDTH, row1_height, fill, stroke, dashed=column.ghost)
        svg.lines(x, row1_top, row1_height, row1[index], text)
        svg.line(x, row1_top + row1_height, x, row2_top - 1, GHOST if column.ghost else BRASS,
                 arrow=True)
        stroke, fill, text = _colors(column, 2)
        svg.rect(x - left, row2_top, COLUMN_WIDTH, row2_height, fill, stroke, dashed=column.ghost)
        svg.lines(x, row2_top, row2_height, row2[index], text)
        svg.line(x, row2_top + row2_height, x, row3_top - 1, GHOST if column.ghost else RED,
                 arrow=True)
        svg.rect(x - left, row3_top, COLUMN_WIDTH, row3_height, SLATE_FILL, SLATE)
        svg.lines(x, row3_top, row3_height, row3[index], SLATE)

    # The products and their latest builds.
    svg.line(COLUMN_X[-1] + left, arrow_y, PRODUCT_LEFT - 1, arrow_y, SLATE, arrow=True)
    svg.rect(PRODUCT_LEFT, product_top, PRODUCT_WIDTH, product_height, SLATE, SLATE)
    svg.lines(PRODUCT_LEFT + PRODUCT_WIDTH // 2, product_top, product_height, products, WHITE)

    head = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 %d %d" font-family="%s" font-size="%d" text-anchor="middle" '
            'role="img">' % (WIDTH, height, WIDTH, height, FONT, SMALL_SIZE))
    body = [head,
            '<rect x="0" y="0" width="100%" height="100%" fill="#FFFFFF"/>',
            "<title>%s</title>" % _escape(alt_text(collected, counts)),
            _markers()]
    body.extend(svg.parts)
    body.append("</svg>")
    return "\n".join(body) + "\n"
