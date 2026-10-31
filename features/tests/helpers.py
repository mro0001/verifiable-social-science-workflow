"""Shared helpers for the organizer's tests (step F7).

copy_fixture copies a fixture folder into a temporary folder. make_audit_db
makes a database with the slice's sessions and events columns, written here
by hand and never with the audit layer's code, so a test can hold any rows.
story_session writes the test story's synthetic session with its
{{PROJECT}} paths set to a temporary project. parse_site_page, is_outside_link,
and site_files read a built portal for the portal's tests.
"""
import os
import shutil
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "features" / "tests" / "fixtures"
STORY_SESSION = ROOT / "examples" / "test_story" / "sessions" / "claude_code" / "story_session.jsonl"
STORY_SESSION_ID = "5f3c0413-2a7d-4b9e-8c61-a0d4e7b2c913"
PLACEHOLDER = "{{PROJECT}}"

# The columns of the slice's sessions and events tables, in the order
# audit_layer init makes them (PRAGMA table_info on a fresh store).
SESSION_TABLE = ("id", "harness", "harness_session_id", "project", "started_at", "ended_at",
                 "tools", "title", "gist", "summary", "keywords", "models", "harness_version",
                 "created_at", "session", "origin", "method", "reason", "supersedes")
EVENT_TABLE = ("id", "session_row_id", "ordinal", "verb", "kind", "object", "rationale", "role",
               "created_at", "session", "origin", "method", "reason", "supersedes")
TRANSCRIPT_TABLE = ("id", "session_row_id", "file_sha256", "byte_size", "created_at", "session",
                    "origin", "method", "reason", "supersedes")


def copy_fixture(name, tmp):
    """Copy features/tests/fixtures/<name> to <tmp>/<name> and give the copy's path."""
    target = Path(str(tmp)) / name
    shutil.copytree(str(FIXTURES / name), str(target))
    return target


def _table(db, name, columns, rows):
    db.execute("CREATE TABLE %s (%s)" % (name, ", ".join(
        "%s %s" % (column, "INTEGER" if column in ("ordinal", "byte_size") else "TEXT")
        for column in columns)))
    for number, row in enumerate(rows, start=1):
        unknown = sorted(set(row) - set(columns))
        if unknown:
            raise ValueError("%s has no column %s" % (name, ", ".join(unknown)))
        values = dict((column, None) for column in columns)
        values["id"] = "%s-%04d" % (name, number)
        values.update(row)
        db.execute("INSERT INTO %s (%s) VALUES (%s)" % (
            name, ", ".join(columns), ", ".join("?" for _ in columns)),
            [values[column] for column in columns])


def make_audit_db(path, sessions, events):
    """Write a database at path holding the given sessions and events rows.

    Each row is a mapping of column to value. A row with no id gets one in
    the order given. The transcripts table is made empty, as a real store
    has one.
    """
    path = Path(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    try:
        _table(db, "sessions", SESSION_TABLE, sessions)
        _table(db, "events", EVENT_TABLE, events)
        _table(db, "transcripts", TRANSCRIPT_TABLE, [])
        db.commit()
    finally:
        db.close()
    return path


def story_session(tmp_project, out):
    """Write the story session to out with {{PROJECT}} set to the project's real path."""
    real = os.path.realpath(str(tmp_project))
    text = STORY_SESSION.read_text(encoding="utf-8").replace(PLACEHOLDER, real)
    out = Path(str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


# The portal's tests (steps F13 to F15) read the site's HTML with these.

class _SiteParser(HTMLParser):
    """Collect every link and source in a page, and each catalog card with its headings."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.links = []
        self.cards = []
        self._heading = None
        self._text = []
        self.h2 = None
        self.h3 = None
        self._card_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ("href", "src"):
            if attrs.get(name) is not None:
                self.links.append((tag, name, attrs[name]))
        if tag in ("h2", "h3"):
            self._heading = tag
            self._text = []
        if tag == "article" and "card" in (attrs.get("class") or "").split():
            self._card_depth = 1
        elif self._card_depth and tag == "a" and attrs.get("href"):
            self.cards.append((self.h2, self.h3, attrs["href"]))

    def handle_endtag(self, tag):
        if tag == self._heading:
            text = " ".join("".join(self._text).split())
            if tag == "h2":
                self.h2, self.h3 = text, None
            else:
                self.h3 = text
            self._heading = None
        if tag == "article":
            self._card_depth = 0

    def handle_data(self, data):
        if self._heading:
            self._text.append(data)


def parse_site_page(path):
    """A parsed page, with .links as (tag, attribute, value) and .cards as (h2, h3, href)."""
    parser = _SiteParser()
    parser.feed(Path(str(path)).read_text(encoding="utf-8"))
    parser.close()
    return parser


def is_outside_link(value):
    """True for a link to the web, to a fragment, or to mail, which need no file in the site."""
    return value.startswith(("http://", "https://", "mailto:", "#"))


def site_files(out_dir):
    """Every file in a built site, as paths from the site's folder."""
    out_dir = Path(str(out_dir))
    return sorted(str(path.relative_to(out_dir)).replace(os.sep, "/")
                  for path in out_dir.rglob("*") if path.is_file())
