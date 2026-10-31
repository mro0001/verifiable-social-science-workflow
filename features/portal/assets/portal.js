/* The portal's script (step F15). It uses no library and no network, so the
   site works opened from disk.

   On the catalog, the search box filters the cards by title, gist, group,
   and kind from window.PORTAL_INDEX, which search_index.js sets, and the
   buttons show one section. On any other page, the search box lists the
   matching pages as links.

   On every item page, the critique box asks for a name, the section the
   critique is about (one of the page's headings or the whole page), and the
   text. Copy puts the critique on the clipboard, and Save downloads it as
   critique_<page id>_<date>.yaml. Nothing is sent anywhere. */
(function () {
  "use strict";

  var SCHEMA = "portal-critique";
  var SCHEMA_VERSION = 1;
  var WHOLE_PAGE = "whole page";

  /* Text as a YAML double-quoted string. JSON's escapes are YAML's, and the
     characters YAML reads as line breaks or will not print are escaped too. */
  function quote(value) {
    return JSON.stringify(String(value == null ? "" : value)).replace(
      /[\u007f-\u009f\u2028\u2029\ufeff]/g,
      function (ch) {
        return "\\u" + ("0000" + ch.charCodeAt(0).toString(16)).slice(-4);
      });
  }

  /* The date as YYYY-MM-DD in the reader's own time zone. */
  function today(now) {
    var d = now || new Date();
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return d.getFullYear() + "-" + two(d.getMonth() + 1) + "-" + two(d.getDate());
  }

  /* One critique as YAML, its keys in a fixed order. */
  function critiqueYaml(page, section, by, date, text) {
    return [
      "schema: " + quote(SCHEMA),
      "schema_version: " + SCHEMA_VERSION,
      "page: " + quote(page.id),
      "title: " + quote(page.title),
      "source: " + quote(page.source),
      "source_commit: " + quote(page.sourceCommit),
      "section: " + quote(section),
      "by: " + quote(by),
      "date: " + quote(date),
      "text: " + quote(text),
      ""
    ].join("\n");
  }

  /* The file name a saved critique takes. */
  function critiqueFileName(pageId, date) {
    return "critique_" + String(pageId).replace(/[^A-Za-z0-9_-]+/g, "-") + "_" + date + ".yaml";
  }

  /* True when every word of the query is in the row's title, gist, group, or kind. */
  function matches(row, query) {
    var words = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
    var hay = [row.title, row.gist, row.group, row.kind].join(" ").toLowerCase();
    return words.every(function (word) { return hay.indexOf(word) !== -1; });
  }

  function rows() {
    return Array.isArray(window.PORTAL_INDEX) ? window.PORTAL_INDEX : [];
  }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text != null) { node.textContent = text; }
    return node;
  }

  /* The catalog. A card shows when its row matches the query and sits in the
     chosen section. A group with no card left is hidden too. */
  function setUpCatalog(form, input, filter) {
    var status = document.querySelector(".search-status");
    var byUrl = {};
    rows().forEach(function (row) { byUrl[row.url] = row; });
    var chosen = "all";

    function update() {
      var query = input.value;
      var shown = 0;
      document.querySelectorAll("section.section").forEach(function (section) {
        var inSection = chosen === "all" || section.id === chosen;
        section.hidden = !inSection;
        section.querySelectorAll("section.group").forEach(function (group) {
          var left = 0;
          group.querySelectorAll("article.card").forEach(function (card) {
            var link = card.querySelector("a[href]");
            var row = link ? byUrl[link.getAttribute("href")] : null;
            var show = inSection && (!query.trim() || (row !== null && row !== undefined && matches(row, query)));
            card.hidden = !show;
            if (show) { left += 1; }
          });
          group.hidden = left === 0;
          shown += left;
        });
      });
      if (status) {
        status.textContent = query.trim() || chosen !== "all"
          ? shown + (shown === 1 ? " page matches" : " pages match") : "";
      }
    }

    filter.hidden = false;
    filter.querySelectorAll("button[data-section]").forEach(function (button) {
      button.addEventListener("click", function () {
        chosen = button.getAttribute("data-section");
        filter.querySelectorAll("button[data-section]").forEach(function (other) {
          other.setAttribute("aria-pressed", other === button ? "true" : "false");
        });
        update();
      });
    });
    input.addEventListener("input", update);
    form.addEventListener("submit", function (event) { event.preventDefault(); update(); });
  }

  /* Any other page. The matching pages are listed under the box as links. */
  function setUpResults(form, input) {
    var root = form.getAttribute("data-root") || "";
    var list = el("ul", { "class": "search-results", "aria-live": "polite" });
    list.hidden = true;
    form.appendChild(list);

    function update() {
      var query = input.value;
      list.textContent = "";
      if (!query.trim()) { list.hidden = true; return; }
      var found = rows().filter(function (row) { return matches(row, query); });
      if (!found.length) {
        list.appendChild(el("li", {}, "No page matches"));
      }
      found.slice(0, 20).forEach(function (row) {
        var item = el("li");
        item.appendChild(el("a", { href: root + row.url }, row.title));
        item.appendChild(document.createTextNode(" (" + row.kind + ")"));
        list.appendChild(item);
      });
      list.hidden = false;
    }

    input.addEventListener("input", update);
    form.addEventListener("submit", function (event) { event.preventDefault(); update(); });
  }

  function setUpSearch() {
    var form = document.querySelector("form.search");
    if (!form) { return; }
    var input = form.querySelector("input[type=search]");
    form.hidden = false;
    var filter = document.querySelector(".section-filter");
    if (filter) {
      setUpCatalog(form, input, filter);
    } else {
      setUpResults(form, input);
    }
  }

  /* Copy text to the clipboard, falling back to selecting it in the preview. */
  function copyText(text, preview, say) {
    function fallback() {
      preview.hidden = false;
      preview.value = text;
      preview.focus();
      preview.select();
      var done = false;
      try { done = document.execCommand("copy"); } catch (error) { done = false; }
      say(done ? "Copied" : "Selected below, so copy it with the keyboard");
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { say("Copied"); }, fallback);
    } else {
      fallback();
    }
  }

  function saveText(text, name, say) {
    var blob = new Blob([text], { type: "application/x-yaml" });
    var url = URL.createObjectURL(blob);
    var link = el("a", { href: url, download: name });
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    say("Saved as " + name);
  }

  function setUpCritique(box) {
    var page = {
      id: box.getAttribute("data-page-id"),
      title: box.getAttribute("data-title"),
      source: box.getAttribute("data-source"),
      sourceCommit: box.getAttribute("data-source-commit")
    };
    var headings = [];
    document.querySelectorAll(".body h2, .body h3").forEach(function (heading) {
      var text = heading.textContent.replace(/\s+/g, " ").trim();
      if (text && headings.indexOf(text) === -1) { headings.push(text); }
    });

    box.appendChild(el("h2", { id: "critique-box" }, "Critique this page"));
    box.appendChild(el("p", {}, "Write what is wrong, missing, or unclear. The critique names "
      + "this page, its source, and its source version. Copy it or save it as a file, since "
      + "the portal sends nothing anywhere."));

    var name = el("input", { type: "text", id: "critique-by", autocomplete: "name" });
    var section = el("select", { id: "critique-section" });
    [WHOLE_PAGE].concat(headings).forEach(function (text) {
      section.appendChild(el("option", { value: text }, text));
    });
    var text = el("textarea", { id: "critique-text", rows: "6" });
    var fields = [
      ["critique-by", "Your name", name],
      ["critique-section", "Section", section],
      ["critique-text", "Critique", text]
    ];
    fields.forEach(function (field) {
      var row = el("p", { "class": "field" });
      row.appendChild(el("label", { "for": field[0] }, field[1]));
      row.appendChild(field[2]);
      box.appendChild(row);
    });

    var buttons = el("p", { "class": "buttons" });
    var copy = el("button", { type: "button" }, "Copy");
    var save = el("button", { type: "button" }, "Save");
    buttons.appendChild(copy);
    buttons.appendChild(save);
    box.appendChild(buttons);
    var status = el("p", { "class": "critique-status", "aria-live": "polite" });
    box.appendChild(status);
    var preview = el("textarea", { "class": "critique-preview", rows: "8", readonly: "readonly",
                                   "aria-label": "The critique as YAML" });
    preview.hidden = true;
    box.appendChild(preview);

    function say(message) { status.textContent = message; }

    function current() {
      if (!name.value.trim() || !text.value.trim()) {
        say("Write your name and the critique first");
        return null;
      }
      var date = today();
      return {
        date: date,
        yaml: critiqueYaml(page, section.value, name.value.trim(), date, text.value)
      };
    }

    copy.addEventListener("click", function () {
      var made = current();
      if (made) { copyText(made.yaml, preview, say); }
    });
    save.addEventListener("click", function () {
      var made = current();
      if (made) { saveText(made.yaml, critiqueFileName(page.id, made.date), say); }
    });
  }

  if (typeof document === "undefined") {
    /* Read outside a browser, the script only shares its plain functions. */
    if (typeof module !== "undefined") {
      module.exports = { quote: quote, today: today, critiqueYaml: critiqueYaml,
                         critiqueFileName: critiqueFileName, matches: matches };
    }
    return;
  }

  function start() {
    setUpSearch();
    document.querySelectorAll("section.critique").forEach(setUpCritique);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
}());
