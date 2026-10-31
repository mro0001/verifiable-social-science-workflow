"""The portal's procedure pages (step F14).

procedure_body gives the body of one procedure's page. It shows the stream,
the version, the goal, and the first and last steps, then each step in file
order with what it does, its invariant, its foreach, where, and role when
present, the files its step contract says it reads and produces, and its
implementation files. Each step's outgoing edges follow it, each in a
details block with the next step, the relation, the condition, the
guidance, each pitfall, the source, and the check when present. All graph
text is escaped.

Proposal Approach paragraphs 1 and 3 and Status paragraph 3. Appendix A2.4
"Procedural graphs" and Figure A7 (each procedure's steps in order). There
is no drawn diagram, and the steps and edges are listed in order.
"""
import html


def _escape(value):
    return html.escape("" if value is None else str(value), quote=True)


def _code(value):
    return "<code>%s</code>" % _escape(value)


def _files(names):
    if not names:
        return "none"
    return ", ".join(_code(name) for name in names)


def _step_link(step_id, known):
    if step_id in known:
        return '<a href="#step-%s">%s</a>' % (_escape(step_id), _code(step_id))
    return _code(step_id)


def _row(label, value_html):
    return "<dt>%s</dt><dd>%s</dd>" % (label, value_html)


def _edge(edge, known):
    pitfalls = edge.get("pitfalls") or []
    if pitfalls:
        pitfall_html = "<ul>%s</ul>" % "".join(
            "<li>%s</li>" % _escape(pitfall) for pitfall in pitfalls)
    else:
        pitfall_html = "none"
    rows = [
        _row("Next step", _step_link(edge.get("to"), known)),
        _row("Relation", _escape(edge.get("rel"))),
        _row("Condition", _escape(edge.get("condition"))),
        _row("Guidance", _escape(edge.get("guidance"))),
        _row("Pitfalls", pitfall_html),
        _row("Source", _escape(edge.get("source"))),
    ]
    if edge.get("check") is not None:
        rows.append(_row("Check", _code(edge["check"])))
    return "\n".join([
        '<details class="edge">',
        "<summary>To %s, %s</summary>" % (_code(edge.get("to")), _escape(edge.get("rel"))),
        "<dl>",
        "\n".join(rows),
        "</dl>",
        "</details>"])


def _step(node, outgoing, known):
    rows = []
    for key, label in (("invariant", "Invariant"), ("foreach", "For each"),
                       ("where", "Where"), ("role", "Role")):
        if node.get(key) is not None:
            rows.append(_row(label, _escape(node[key])))
    rows.append(_row("Reads", _files(node.get("reads"))))
    if node.get("reads_optional"):
        rows.append(_row("Reads when present", _files(node["reads_optional"])))
    rows.append(_row("Produces", _files(node.get("produces"))))
    rows.append(_row("Implementation", _files(node.get("implementations"))))
    parts = [
        '<li class="step" id="step-%s">' % _escape(node["id"]),
        '<h3>%s <span class="kind">%s</span></h3>' % (_code(node["id"]), _escape(node.get("kind"))),
        "<p>%s</p>" % _escape(node.get("does")),
        "<dl>",
        "\n".join(rows),
        "</dl>",
    ]
    if outgoing:
        parts.append("<h4>Next steps</h4>")
        parts.extend(_edge(edge, known) for edge in outgoing)
    else:
        parts.append("<p>No edge leaves this step.</p>")
    parts.append("</li>")
    return "\n".join(parts)


def procedure_body(proc):
    """The body of one procedure's page, as HTML."""
    known = [node["id"] for node in proc.nodes]
    summary = "\n".join([
        '<dl class="details">',
        _row("Stream", _escape(proc.stream)),
        _row("Version", _escape(proc.version)),
        _row("Goal", _escape(" ".join((proc.goal or "").split()))),
        _row("First step", _step_link(proc.entry, known)),
        _row("Last step", _step_link(proc.exit, known)),
        "</dl>"])
    steps = [_step(node, [edge for edge in proc.edges if edge.get("from") == node["id"]], known)
             for node in proc.nodes]
    parts = [summary, "<h2>Steps</h2>", '<ol class="steps">', "\n".join(steps), "</ol>"]
    loose = [edge for edge in proc.edges if edge.get("from") not in known]
    if loose:
        parts.append("<h2>Edges from no listed step</h2>")
        for edge in loose:
            parts.append("<p>From %s</p>" % _code(edge.get("from")))
            parts.append(_edge(edge, known))
    return "\n".join(parts) + "\n"
