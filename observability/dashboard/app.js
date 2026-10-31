/*
 * The observability view (Track E, steps E7 and E8).
 *
 * A static page that opens from disk with no server and no network. It reads
 * only window.OBS, which data.js sets, and writes nothing. Text from the
 * record is placed with textContent and never parsed as HTML. The open tab,
 * trace, and span are kept after the # of the address, so a reload keeps
 * them, and while OBS.live is true the page reloads every
 * OBS.refresh_seconds seconds.
 */
(function () {
  "use strict";

  var OBS = window.OBS;
  var CATEGORIES = ["agent", "model", "tool", "kb", "step", "judgment", "event", "other"];
  var CATEGORY_WORDS = {
    agent: "session, agent, or run", model: "model turn", tool: "tool call",
    kb: "knowledge base retrieval", step: "step", judgment: "judged item",
    event: "event from the record", other: "other"
  };
  var ALL = "";
  var filters = { source: ALL, project: ALL, role: ALL, trace: ALL };

  // Small helpers

  function $(id) { return document.getElementById(id); }

  function clear(node) {
    while (node.firstChild) { node.removeChild(node.firstChild); }
    return node;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function add(parent, tag, className, text) {
    var node = el(tag, className, text);
    parent.appendChild(node);
    return node;
  }

  function parsed(text) {
    if (typeof text !== "string" || text === "") { return null; }
    try { return JSON.parse(text); } catch (error) { return null; }
  }

  function pretty(text) {
    var value = parsed(text);
    if (value === null || typeof value !== "object") { return text; }
    return JSON.stringify(value, null, 2);
  }

  function seconds(value) {
    var number = Number(value) || 0;
    if (number >= 100) { return number.toFixed(0) + " s"; }
    if (number >= 10) { return number.toFixed(1) + " s"; }
    return number.toFixed(3) + " s";
  }

  function unique(rows, key) {
    var seen = {};
    var found = [];
    rows.forEach(function (row) {
      var value = row[key] === undefined || row[key] === null ? "" : String(row[key]);
      if (!seen.hasOwnProperty(value)) { seen[value] = true; found.push(value); }
    });
    found.sort();
    return found;
  }

  function fillSelect(select, values, chosen, label) {
    clear(select);
    var all = add(select, "option", null, "all");
    all.value = ALL;
    values.forEach(function (value) {
      var words = label ? label(value) : value;
      var option = add(select, "option", null, words === "" ? "(none)" : words);
      option.value = value;
    });
    select.value = values.indexOf(chosen) >= 0 ? chosen : ALL;
    return select.value;
  }

  // Tables built from rows, each cell placed as text

  function table(node, columns, rows, options) {
    options = options || {};
    clear(node);
    var head = add(add(node, "thead"), "tr");
    columns.forEach(function (column) {
      add(head, "th", column.num ? "num" : null, column.label);
    });
    var body = add(node, "tbody");
    if (!rows.length) {
      var cell = add(add(body, "tr"), "td", "empty", options.empty || "Nothing to show.");
      cell.colSpan = columns.length;
      return;
    }
    rows.forEach(function (row) {
      var line = add(body, "tr", options.open ? "click" : null);
      if (options.selected && options.selected(row)) { line.classList.add("sel"); }
      columns.forEach(function (column) {
        var value = column.value ? column.value(row) : row[column.key];
        var classes = [];
        if (column.num) { classes.push("num"); }
        if (column.path) { classes.push("path"); }
        if (column.time) { classes.push("time"); }
        if (column.flag && column.flag(row)) { classes.push("err"); }
        add(line, "td", classes.join(" ") || null, value === undefined || value === null ? "" : value);
      });
      if (options.open) {
        line.addEventListener("click", function () { options.open(row); });
      }
    });
  }

  // The place on the page, kept after the # of the address

  function readHash() {
    var place = { tab: "", trace: "", span: "" };
    location.hash.replace(/^#/, "").split("&").forEach(function (pair) {
      var at = pair.indexOf("=");
      if (at < 0) { return; }
      var key = decodeURIComponent(pair.slice(0, at));
      if (place.hasOwnProperty(key)) { place[key] = decodeURIComponent(pair.slice(at + 1)); }
    });
    return place;
  }

  function hashFor(place) {
    var parts = [];
    ["tab", "trace", "span"].forEach(function (key) {
      if (place[key]) { parts.push(key + "=" + encodeURIComponent(place[key])); }
    });
    return "#" + parts.join("&");
  }

  function go(place) {
    var next = hashFor(place);
    if (next === location.hash || (next === "#" && location.hash === "")) {
      render();
    } else {
      location.hash = next;
    }
  }

  function tabNames() {
    return Array.prototype.map.call(document.querySelectorAll("nav.tabs button"), function (button) {
      return button.getAttribute("data-tab");
    });
  }

  function currentPlace() {
    var place = readHash();
    var names = tabNames();
    if (names.indexOf(place.tab) < 0) { place.tab = names[0]; }
    if (place.trace && !OBS.spans.hasOwnProperty(place.trace)) { place.trace = ""; place.span = ""; }
    return place;
  }

  // The header

  function renderHeader() {
    var live = $("live");
    if (OBS.live) {
      live.textContent = "live, rebuilt every " + OBS.refresh_seconds + " seconds";
      live.className = "badge live";
    } else {
      live.textContent = "not live";
      live.className = "badge";
    }
    var meta = clear($("meta"));
    var sources = OBS.sources || {};
    var kbDirs = sources.kb_dirs || [];
    [
      ["Built", OBS.built_at],
      ["Audit home", sources.audit_home || "none"],
      ["Knowledge base folders", kbDirs.length ? kbDirs.join(", ") : "none"],
      ["Conventions", OBS.semconv]
    ].forEach(function (item) {
      var pair = add(meta, "div");
      add(pair, "dt", null, item[0]);
      add(pair, "dd", null, item[1]);
    });
    var notes = clear($("notes"));
    (OBS.notes || []).forEach(function (note) { add(notes, "li", null, note); });
  }

  function renderTabs(place) {
    Array.prototype.forEach.call(document.querySelectorAll("nav.tabs button"), function (button) {
      button.classList.toggle("on", button.getAttribute("data-tab") === place.tab);
    });
    Array.prototype.forEach.call(document.querySelectorAll("section.tab"), function (section) {
      section.classList.toggle("on", section.id === "tab-" + place.tab);
    });
  }

  // The sessions and runs tab

  function renderTraces(place) {
    var rows = OBS.traces || [];
    filters.source = fillSelect($("filter-source"), unique(rows, "source"), filters.source);
    filters.project = fillSelect($("filter-project"), unique(rows, "project"), filters.project);
    var shown = rows.filter(function (row) {
      return (filters.source === ALL || row.source === filters.source) &&
        (filters.project === ALL || row.project === filters.project);
    });
    table($("traces"), [
      { label: "Started", key: "started", time: true },
      { label: "Source", key: "source" },
      { label: "Title", key: "title" },
      { label: "Session", key: "session_id" },
      { label: "Length", num: true, value: function (row) { return seconds(row.duration_s); } },
      { label: "Model calls", key: "model_calls", num: true },
      { label: "Tokens in", key: "input_tokens", num: true },
      { label: "Tokens out", key: "output_tokens", num: true },
      { label: "Tool calls", key: "tool_calls", num: true },
      { label: "Subagents", key: "subagents", num: true },
      { label: "Retrievals", key: "kb_reads", num: true },
      { label: "Errors", key: "errors", num: true },
      { label: "Reasoning exposed", value: function (row) {
        var reasoning = row.reasoning || {};
        return (reasoning.exposed || 0) + " of " + (reasoning.turns || 0) + " turns";
      } }
    ], shown, {
      empty: rows.length ? "No session or run matches the filters." : "No session or run in this view.",
      selected: function (row) { return row.trace_id === place.trace; },
      open: function (row) { go({ tab: "traces", trace: row.trace_id, span: "" }); }
    });
    renderTimeline(place);
  }

  function traceRow(traceId) {
    var found = null;
    (OBS.traces || []).forEach(function (row) { if (row.trace_id === traceId) { found = row; } });
    return found;
  }

  function renderTimeline(place) {
    var view = $("trace-view");
    var timeline = clear($("timeline"));
    var keys = clear($("timeline-keys"));
    var title = $("timeline-title");
    if (!place.trace) {
      view.hidden = true;
      return;
    }
    view.hidden = false;
    var row = traceRow(place.trace) || {};
    title.textContent = (row.title || "untitled") + ", " + (row.source || "") + " " + (row.session_id || "");
    CATEGORIES.forEach(function (name) {
      var key = add(keys, "span");
      add(key, "i", "c-" + name);
      key.appendChild(document.createTextNode(CATEGORY_WORDS[name]));
    });
    var errorKey = add(keys, "span");
    add(errorKey, "i", "c-error");
    errorKey.appendChild(document.createTextNode("error"));

    var spans = OBS.spans[place.trace] || [];
    var total = 0;
    spans.forEach(function (span) { total = Math.max(total, Number(span.end_s) || 0); });
    if (total <= 0) { total = 1; }

    var axis = add(timeline, "div", "wf-axis");
    add(axis, "div", null, "Span");
    var ticks = add(axis, "div", "ticks");
    [0, 0.25, 0.5, 0.75, 1].forEach(function (share, index, all) {
      var tick = add(ticks, "span", index === 0 ? "first" : (index === all.length - 1 ? "last" : null),
        seconds(total * share));
      tick.style.left = (share * 100) + "%";
    });

    var selectedLine = null;
    spans.forEach(function (span) {
      var line = add(timeline, "div", "wf-row");
      if (span.span_id === place.span) { line.classList.add("sel"); selectedLine = line; }
      var name = add(line, "div", "wf-name", span.name);
      name.style.paddingLeft = (span.depth * 14) + "px";
      name.title = span.name;
      var track = add(line, "div", "wf-track");
      var bar = add(track, "div", "wf-bar c-" + (CATEGORY_WORDS[span.category] ? span.category : "other"));
      if (span.status === "error") { bar.classList.add("err"); }
      var start = Math.max(0, Number(span.start_s) || 0);
      var end = Math.max(start, Number(span.end_s) || 0);
      bar.style.left = (start / total * 100) + "%";
      bar.style.width = Math.max((end - start) / total * 100, 0.3) + "%";
      bar.title = seconds(start) + " to " + seconds(end);
      line.addEventListener("click", function () {
        go({ tab: "traces", trace: place.trace, span: span.span_id });
      });
    });
    if (!spans.length) { add(timeline, "p", "none", "This trace holds no spans."); }
    renderDetail(place, spans);
    if (selectedLine && selectedLine.scrollIntoView) { selectedLine.scrollIntoView({ block: "nearest" }); }
  }

  function traceLabel(traceId) {
    var row = traceRow(traceId);
    if (!row) { return traceId; }
    return (row.title || "untitled") + ", " + (row.session_id || traceId);
  }

  function openSpan(row) {
    go({ tab: "traces", trace: row.trace_id, span: row.span_id });
  }

  // The files tab

  function renderFiles() {
    var rows = OBS.files || [];
    filters.role = fillSelect($("filter-role"), unique(rows, "role"), filters.role);
    filters.trace = fillSelect($("filter-trace"), unique(rows, "trace_id"), filters.trace, traceLabel);
    var shown = rows.filter(function (row) {
      return (filters.role === ALL || row.role === filters.role) &&
        (filters.trace === ALL || row.trace_id === filters.trace);
    });
    table($("files"), [
      { label: "Time", key: "time", time: true },
      { label: "Role", key: "role" },
      { label: "File", key: "path", path: true },
      { label: "Tool", key: "tool" },
      { label: "Agent", key: "agent" },
      { label: "Session or run", value: function (row) { return traceLabel(row.trace_id); } }
    ], shown, {
      empty: rows.length ? "No file matches the filters." : "No file was read, edited, or produced in this view.",
      open: openSpan
    });
  }

  // The knowledge base tab

  function tile(parent, value, words) {
    var box = add(parent, "div", "tile");
    add(box, "div", "v", value);
    add(box, "div", "l", words);
  }

  function renderKb() {
    var reads = OBS.kb_reads || [];
    var entries = OBS.kb_entries || [];
    var kbDirs = (OBS.sources || {}).kb_dirs || [];
    var tiles = clear($("kb-tiles"));
    tile(tiles, reads.length, "retrievals");
    if (kbDirs.length) {
      tile(tiles, entries.length, "entries in the knowledge base folders");
      tile(tiles, entries.filter(function (entry) { return !entry.reads; }).length,
        "entries never retrieved");
    }
    table($("kb-reads"), [
      { label: "Time", key: "time", time: true },
      { label: "Tool", key: "tool" },
      { label: "Source", key: "source" },
      { label: "Entries", value: function (row) { return (row.entries || []).join(", "); } },
      { label: "Query", key: "query" },
      { label: "Agent", key: "agent" },
      { label: "Outcome", key: "outcome", flag: function (row) { return row.outcome === "error"; } },
      { label: "Session or run", value: function (row) { return traceLabel(row.trace_id); } }
    ], reads, { empty: "No knowledge base retrieval in this view.", open: openSpan });
    table($("kb-entries"), [
      { label: "Entry", key: "id" },
      { label: "Title", key: "title" },
      { label: "Group", key: "group" },
      { label: "Reads", key: "reads", num: true },
      { label: "File", key: "path", path: true }
    ], entries, {
      empty: kbDirs.length ? "No entry with front matter in the knowledge base folders." :
        "No knowledge base folder was given to the build."
    });
  }

  // The detail panel for the selected span

  function section(panel, heading) {
    add(panel, "h4", null, heading);
  }

  function block(panel, heading, text) {
    section(panel, heading);
    if (text === undefined || text === null || text === "") {
      add(panel, "p", "none", "none");
    } else {
      add(panel, "pre", null, text);
    }
  }

  function keyValues(panel, pairs) {
    var body = add(add(panel, "table", "kv"), "tbody");
    pairs.forEach(function (pair) {
      var line = add(body, "tr");
      add(line, "td", null, pair[0]);
      add(line, "td", null, pair[1] === undefined || pair[1] === null || pair[1] === "" ? "none" : pair[1]);
    });
  }

  function messageParts(text) {
    var messages = parsed(text);
    var parts = [];
    if (!Array.isArray(messages)) { return parts; }
    messages.forEach(function (message) {
      if (!message || !Array.isArray(message.parts)) { return; }
      message.parts.forEach(function (part) {
        if (part && typeof part === "object") { parts.push(part); }
      });
    });
    return parts;
  }

  function ofType(parts, type) {
    return parts.filter(function (part) { return part.type === type; });
  }

  function argumentsText(value) {
    if (typeof value === "string") { return pretty(value); }
    return JSON.stringify(value, null, 2);
  }

  function renderModelTurn(panel, attributes) {
    var prompt = ofType(messageParts(attributes["gen_ai.input.messages"]), "text")
      .map(function (part) { return part.content; }).join("\n\n");
    block(panel, "Prompt", prompt || "");
    var output = messageParts(attributes["gen_ai.output.messages"]);
    var reasoning = ofType(output, "reasoning")
      .map(function (part) { return part.content || ""; })
      .filter(function (text) { return text !== ""; }).join("\n\n");
    section(panel, "Reasoning");
    if (reasoning) {
      add(panel, "pre", null, reasoning);
    } else {
      add(panel, "p", "none", "not exposed by the model");
    }
    block(panel, "Text", ofType(output, "text").map(function (part) { return part.content; }).join("\n\n"));
    var calls = ofType(output, "tool_call");
    section(panel, "Tool calls asked for");
    if (!calls.length) { add(panel, "p", "none", "none"); }
    calls.forEach(function (call) {
      add(panel, "div", "mono", (call.name || "") + (call.id ? ", " + call.id : ""));
      add(panel, "pre", null, argumentsText(call.arguments));
    });
  }

  function renderToolCall(panel, attributes) {
    block(panel, "Arguments", pretty(attributes["gen_ai.tool.call.arguments"] || ""));
    block(panel, "Result", attributes["gen_ai.tool.call.result"] || "");
  }

  function renderRetrieval(panel, attributes) {
    var documents = parsed(attributes["gen_ai.retrieval.documents"]);
    var ids = Array.isArray(documents) ? documents.map(function (item) {
      return item && item.id !== undefined ? String(item.id) : "";
    }).filter(function (id) { return id !== ""; }) : [];
    section(panel, "Retrieval");
    keyValues(panel, [
      ["Source", attributes["gen_ai.data_source.id"]],
      ["Entries", ids.join(", ")],
      ["Query", attributes["gen_ai.retrieval.query.text"]]
    ]);
  }

  function renderEvent(panel, attributes) {
    section(panel, "Event from the record");
    keyValues(panel, [["Ordinal", attributes["audit.ordinal"]]]);
    add(panel, "p", "none", "times not in the record");
  }

  function renderDetail(place, spans) {
    var panel = clear($("detail"));
    var span = null;
    spans.forEach(function (item) { if (item.span_id === place.span) { span = item; } });
    if (!span) {
      add(panel, "p", "none", "Select a line of the timeline to see its detail.");
      return;
    }
    var attributes = span.attributes || {};
    add(panel, "div", "ptype", CATEGORY_WORDS[span.category] || span.category);
    add(panel, "div", "pname", span.name);
    keyValues(panel, [
      ["Agent", span.agent],
      ["Starts", seconds(span.start_s) + " after the trace starts"],
      ["Ends", seconds(span.end_s) + " after the trace starts"],
      ["Length", seconds((Number(span.end_s) || 0) - (Number(span.start_s) || 0))],
      ["Status", span.status],
      ["Error", span.error_type]
    ]);
    if (span.category === "model") {
      renderModelTurn(panel, attributes);
    } else if (span.category === "tool" || span.category === "kb") {
      renderToolCall(panel, attributes);
    }
    if (span.category === "kb") { renderRetrieval(panel, attributes); }
    if (span.category === "event") { renderEvent(panel, attributes); }
    var details = add(panel, "details");
    details.open = true;
    var keys = Object.keys(attributes).sort();
    add(details, "summary", null, "Attributes (" + keys.length + ")");
    keyValues(details, keys.map(function (key) { return [key, attributes[key]]; }));
  }

  // The whole page

  function render() {
    var place = currentPlace();
    renderTabs(place);
    if (place.tab === "traces") { renderTraces(place); }
    if (place.tab === "files") { renderFiles(); }
    if (place.tab === "kb") { renderKb(); }
  }

  function start() {
    if (!OBS || typeof OBS !== "object") {
      $("nodata").hidden = false;
      return;
    }
    OBS.spans = OBS.spans || {};
    renderHeader();
    Array.prototype.forEach.call(document.querySelectorAll("nav.tabs button"), function (button) {
      button.addEventListener("click", function () {
        var place = currentPlace();
        place.tab = button.getAttribute("data-tab");
        go(place);
      });
    });
    $("filter-source").addEventListener("change", function (event) {
      filters.source = event.target.value;
      render();
    });
    $("filter-project").addEventListener("change", function (event) {
      filters.project = event.target.value;
      render();
    });
    $("filter-role").addEventListener("change", function (event) {
      filters.role = event.target.value;
      render();
    });
    $("filter-trace").addEventListener("change", function (event) {
      filters.trace = event.target.value;
      render();
    });
    window.addEventListener("hashchange", render);
    render();
    if (OBS.live) {
      var wait = Math.max(1, Number(OBS.refresh_seconds) || 5) * 1000;
      window.setTimeout(function () { location.reload(); }, wait);
    }
  }

  start();
}());
