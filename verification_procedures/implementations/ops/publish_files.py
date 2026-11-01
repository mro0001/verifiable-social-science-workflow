"""Scan every file in the repository and in each archive it holds, and block on a private
folder, a run folder, a database, a credential-like name, an archive that cannot be
scanned, a file too large, an email address, a home folder path on a Mac, Linux, or
Windows machine or a temporary folder, an excluded folder, a key, a name from the
settings, a raw id of an indexed session, an author named in an Office file, or a file
a .gitignore in the repository would hide from git.

An item is a file's path in the tar, or the tar's path, a colon, and the member's path
for a file inside a tar the repository holds. The evidence of a name or path rule is the
item, the evidence of a key is its first four characters, its length, and a short hash,
the evidence of a term is its place in the settings' list, and other evidence is the
matched text, cut to 120 characters. An allow entry accepts a finding by its evidence,
the text the evidence stands for, its item, or both, and an accepted finding becomes a
note.

What a file is comes from its first bytes as well as its name, so a compressed file, an
older Office file, or a zip file is found whatever it is called, and a text file named
like an image is read as text. Text is read as UTF-8 with bad bytes replaced, as UTF-16
after its byte order mark or when every other byte is zero, and also as Latin-1 when
UTF-8 does not fit. Each rule reads the text as written, with HTML entities and JSON
escapes undone, and in Unicode's composed form, so a name or a path written another way
is found too. Office files, Word, Excel, PowerPoint, and OpenDocument, are scanned part
by part, with the text of each paragraph and cell joined, an Office file inside one
scanned in turn, and the names of a file's custom properties listed in one note. An
image or PDF file has its text and metadata scanned, and gets a note that what it shows
is not. A tar's member headers, link targets, owner names, and extended headers, are
scanned too. A compressed file, an archive inside a tar, and a zip file that is not an
Office file are not opened, so they block.
"""
import base64
import collections
import csv
import fnmatch
import hashlib
import html
import io
import json
import os
import posixpath
import re
import tarfile
import unicodedata
import zipfile
import zlib

import _lib

CHECK = "publish_files"
MB = 1024 * 1024
EVIDENCE = 120
SESSIONS = "project/sessions/sessions.csv"
INFLATE_LIMIT = 64 * MB
NESTED = 3
LOOK_BACK = 2048

CREDENTIAL = (".env", ".env.*", ".env*", ".envrc", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*",
              "id_ed25519*", "id_ecdsa*", ".netrc", ".git-credentials", ".gitconfig", ".pgpass", ".pypirc",
              ".npmrc", "credentials*", "*secret*", "token", "*.token", "token.txt", "token.json",
              "*access_token*", "*api_key*", "*apikey*")
DATABASES = (".sqlite", ".sqlite3", ".db", ".db3", ".sqlite-wal", ".sqlite-shm", ".sqlite-journal", ".db-wal",
             ".db-shm", ".db-journal", ".duckdb", ".duckdb.wal", ".mdb", ".accdb")
PRIVATE_FOLDERS = (
    ("project/audit/", "The file lies in project/audit/, which holds raw session ids and the AI's words and stays private."),
    ("project/sources/", "The file lies in project/sources/, which holds source texts, most not openly licensed."),
    ("project/notes/", "The file lies in project/notes/, which holds the scholar's notes."),
)
LEFT_OUT_PARTS = (".claude", ".vscode", ".idea", ".ipynb_checkpoints", ".rproj.user", ".venv", "venv",
                  ".quarto", ".pytest_cache", "__pycache__", ".cursor", ".continue", ".codex", ".gemini",
                  ".windsurf")
LEFT_OUT_NAMES = ("*_history", "*.history", ".rhistory", ".viminfo", ".lesshst", ".rdata", ".aider*")
TRANSCRIPT_PARTS = (".specstory",)
TRANSCRIPT_NAMES = (".aider.chat.history*", ".aider.input.history*")
PACKAGES = (".docx", ".docm", ".dotx", ".dotm", ".xlsx", ".xlsm", ".xltx", ".xltm", ".xlsb", ".xlam", ".pptx",
            ".pptm", ".potx", ".potm", ".ppsx", ".ppsm", ".ppam", ".sldx", ".vsdx", ".vsdm", ".odt", ".ods",
            ".odp", ".odg", ".odf", ".ott", ".ots", ".otp", ".otg")
OFFICE_PARTS = (".xml", ".rels", ".vml")
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".pdf", ".bmp", ".emf", ".wmf", ".ico")
MEDIA = IMAGES + (".odttf", ".ttf", ".otf", ".fntdata", ".wdp", ".jfif")
ARCHIVES = (".zip", ".gz", ".tgz", ".bz2", ".tbz", ".tbz2", ".xz", ".txz", ".lzma", ".zst", ".7z", ".rar", ".svgz")
IMAGE_KINDS = ("pdf", "png", "jpeg", "gif", "webp", "tiff")
COMPRESSED_KINDS = ("gzip", "bzip2", "xz", "zstd", "lzma", "7z", "rar")
IMAGE_DOMAINS = ("png", "jpg", "jpeg", "gif", "svg", "webp")
EXAMPLE_ENDINGS = (".invalid", ".test", ".localhost", ".example")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
OWNERS = ("", "root", "wheel", "staff", "admin", "users", "nobody", "nogroup", "daemon", "everyone", "0")
PAX_KEYS = ("path", "linkpath", "size", "mtime", "atime", "ctime", "uid", "gid", "uname", "gname", "charset",
            "hdrcharset")

EMAIL = re.compile(r"(?<![A-Za-z0-9._+-])([A-Za-z0-9][A-Za-z0-9._+-]*)(?:@|%40)"
                   r"((?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,})(?![A-Za-z0-9-])")
USER_PART = r"[^/\s\"'<>:;,)`]+"
# A home path is found wherever it starts, so a path below a drive or a volume, as WSL,
# Git Bash, Cygwin, a second volume, and many clusters write them, is found too. Only a
# path inside a web address with a host other than this machine is passed over.
HOME = (
    re.compile(r"/Users/(?!Shared(?![^/\s\"'<>:;,)`]))" + USER_PART),
    re.compile(r"/home/" + USER_PART),
    re.compile(r"\b[A-Z]\\?:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+(?!(?:Public|Default|Shared)\b)[^\\/\s\"']+", re.I),
    re.compile(r"(?<![A-Za-z0-9])-Users-[A-Za-z0-9._]+-"),
    re.compile(r"(?<![^\s/\\\"'`(<\[{=:,;|])-users-[a-z0-9._]+-", re.I),
    re.compile(r"(?<![A-Za-z0-9])_Users_[A-Za-z0-9.]+_"),
    re.compile(r"(?:/private)?/var/folders/[a-z0-9_+-]{2}/"),
    re.compile(r"/private/tmp/claude-\d+/"),
    re.compile(r"%2[Ff][Uu]sers%2[Ff]"),
    re.compile(r"(?<=[{:;])Users/[^/\s]+/"),
    re.compile(r"(?<![\\\w])\\\\[A-Za-z][A-Za-z0-9._$-]+\\[^\\\s\"'<>]+\\[^\\\s\"'<>]+"),
)
TOKEN_EDGE = re.compile(r"[\s\"'<>()\[\]{}`,;]")
PLACEHOLDER_NAME = re.compile(r"^(?:[$<{%*]|\.+$)")
TILDE = re.compile(r"(?<![\w/~])~/[^\s\"'<>`)\]]+")
TRANSCRIPTS = re.compile(r"\.claude/projects/")
KEYS = (
    re.compile(r"(?<![A-Za-z0-9_-])sk-(?:ant-|proj-)?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{36}"),
    re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{30,}"),
    re.compile(r"(?<![A-Za-z0-9_])glpat-[A-Za-z0-9_-]{20}"),
    re.compile(r"(?<![A-Za-z0-9_])[sr]k_live_[A-Za-z0-9]{20,}"),
    re.compile(r"hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
    re.compile(r"(?<![A-Za-z0-9_])xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![0-9A-Z])"),
    re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"(?<![A-Za-z0-9_-])pypi-AgEI[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}"),
    re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
    re.compile(r"aws_secret_access_key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+]{40}", re.I),
    re.compile(r"WORKFLOW_MODEL_KEY[\"']?\s*[:=]\s*[\"']?(?![$<{%])[^\s\"']{16,}"),
)
ASSIGNMENT = re.compile(r"(?:api[_-]?key|[A-Za-z0-9]_key|secret|token|passw(?:or)?d|bearer)"
                        r"[\"']?\s*[:=]\s*[\"']?[^\s\"']{16,}", re.I)
BASE_URL = re.compile(r"base_url[\"']?\s*:\s*[\"']?([A-Za-z][A-Za-z0-9+.-]*://)?([^/\s\"',]+)")
HOST = re.compile(r"^(?:[^@/]+@)?[A-Za-z0-9.-]+(?::\d+)?$")
UUID = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})"
                  r"(?![0-9A-Fa-f])(/agent-[0-9A-Za-z]+)?")
JSON_ESCAPE = re.compile(r"\\u([0-9A-Fa-f]{4})")
BIBDESK = re.compile(r"Bdsk-File-\d+\s*=\s*\{([A-Za-z0-9+/=\s]{16,})\}")
PDF_STREAM = re.compile(rb"stream\r?\n")
PDF_WIDE = re.compile(rb"\(\xfe\xff((?:[^)\\]|\\.)*)\)", re.S)
PDF_HEX = re.compile(rb"<FEFF([0-9A-Fa-f\s]+)>", re.I)
# Each paragraph of an Office part, a Word or PowerPoint paragraph, an Excel string, or an
# OpenDocument paragraph or heading, with its tags taken away, so words split across runs
# are read joined.
XML_PARAGRAPH = re.compile(r"<((?:[\w.-]+:)?(?:p|h|si|is))(?:\s[^<>]*)?>(.*?)</\1>", re.S)
XML_SPACE = re.compile(r"<(?:[\w.-]+:)?(?:br|cr|tab|s|line-break)\b[^<>]*/>")
XML_TAG = re.compile(r"<[^<>]*>")
CREATOR = re.compile(r"<((?:[\w.-]+:)?(?:creator|lastModifiedBy|initial-creator))\b[^>]*>([^<]*)<")
APP_PEOPLE = re.compile(r"<((?:[\w.-]+:)?(?:Company|Manager))\b[^>]*>([^<]*)<")
CUSTOM_PROPERTY = re.compile(r"<(?:\w+:)?property\b[^>]*?\bname=\"([^\"]*)\"")
ODF_PROPERTY = re.compile(r"<meta:user-defined\b[^>]*?\bmeta:name=\"([^\"]*)\"")
WORD_AUTHOR = re.compile(r"<([\w.-]+:[\w.-]+)\b[^>]*?\bw:author=\"([^\"]*)\"")
WORD_PERSON = re.compile(r"<w15:person\b[^>]*?\bw15:author=\"([^\"]*)\"")
SLIDE_AUTHOR = re.compile(r"<\w+:(?:cmAuthor|author)\b[^>]*?\bname=\"([^\"]*)\"")
SHEET_AUTHOR = re.compile(r"<(?:\w+:)?author>([^<]*)</")
SHEET_PERSON = re.compile(r"<(?:\w+:)?person\b([^>]*)>")
PERSON_ATTRIBUTE = re.compile(r"\b(displayName|userId)=\"([^\"]*)\"")
WORD_COMMENT = re.compile(r"<w:comment\b(?!s)")
ODF_COMMENT = re.compile(r"<office:annotation\b(?!-end)")

MESSAGES = {
    "git": "The path lies inside a folder named .git, so the repository would publish another repository.",
    "homes": "The path lies inside a .homes folder, where the workflow keeps its private homes.",
    "database": "A database file, such as an audit store, would be published.",
    "credential": "The file has a credential-like name, so it may hold a key or a password.",
    "run_folder": "The folder holds a manifest and a trail, so it is a run folder, whose manifest names local paths and the model service.",
    "left_out": "The path is an editor, environment, cache, or shell history file, which publish build leaves out.",
    "transcript": "The path is where an AI tool keeps its saved chats, which publish build leaves out.",
    "excluded_path": "The file lies in a folder the scholar excluded, which publish build leaves out unopened.",
    "ignored": "A .gitignore in the repository matches this file, so git would leave it out of a commit and a link to it would break.",
    "archive": "The archive is not opened by this check, so its files are not scanned.",
    "compressed": "The file is compressed, so this check cannot read it and its text is not scanned.",
    "old_office": "The file is an older Office file or an object inside one, which this check cannot read, so its text and authors are not scanned.",
    "bad_tar": "The tar could not be read, so its files are not scanned.",
    "bad_office": "The Office file could not be opened, so its parts are not scanned.",
    "special": "The tar holds a link or a special file, which is not published as a file.",
    "link_out": "The tar holds a link to a path outside it, which names a folder of the machine that made it.",
    "owner": "The tar records the login name of the account that made it, which names its user.",
    "max_size": "The file is larger than max_file_mb.",
    "warn_size": "The file is larger than warn_file_mb.",
    "image": "The image or PDF file's text and metadata are scanned, but not what it shows, so look at it before publishing.",
    "office_images": "The Office file holds images, whose text and metadata are scanned, but not what they show, so look at them before publishing.",
    "email": "The text holds an email address whose domain is not an example domain.",
    "home": "The text holds a home folder path or a temporary folder of a computer, which names its user.",
    "excluded": "The text holds a path in a folder the settings exclude.",
    "tilde": "The text holds a path inside a home folder, written with a tilde.",
    "transcripts": "The text holds a path to the folder where Claude Code keeps its transcripts.",
    "key": "The text holds a string shaped like a key or a token.",
    "assignment": "The text sets a key, secret, token, or password to a long value.",
    "term": "The text holds a word or name from the settings' terms.",
    "path_term": "The path holds a word or name from the settings' terms.",
    "base_url": "The text sets base_url to a host that is not an example host.",
    "session": "The text holds a raw id of an indexed session, which ties the public index to its private transcript.",
    "notebook": "The notebook keeps the outputs of its cells, which may show data or paths.",
    "office_person": "The Office file names a person in its properties.",
    "office_custom": "The Office file has custom properties, which are published with it. Their values are "
                     "scanned like its other parts, and only a problem found in them blocks.",
    "word_author": "The Word file names the author of a comment or a tracked change.",
    "word_person": "The Word file lists a person who commented or edited.",
    "slide_author": "The PowerPoint file names a comment author.",
    "sheet_author": "The Excel file names a comment author.",
    "sheet_person": "The Excel file lists a person who commented.",
    "word_comment": "The Word file holds a comment.",
    "odf_comment": "The document holds a comment.",
    "accepted": "Accepted by the settings. ",
}


def nfc(text):
    return unicodedata.normalize("NFC", text)


def clean_name(name):
    while name.startswith("./"):
        name = name[2:]
    return name


def cut(text):
    text = str(text)
    return text if len(text) <= EVIDENCE else text[:EVIDENCE - 4] + " ..."


def masked(text):
    """A key's evidence: its first four characters, its length, and a short hash."""
    digest = hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()[:12]
    return "%s (%d characters, sha256 %s)" % (text[:4], len(text), digest)


def wide(data):
    """utf-16-le or utf-16-be when data has no byte order mark and every other byte of it
    is zero, as some Windows tools write text, else ""."""
    sample = data[:65536]
    if len(sample) < 8:
        return ""
    even, odd = sample[0::2].count(0), sample[1::2].count(0)
    if odd * 10 >= len(sample[1::2]) * 7 and even * 10 <= len(sample[0::2]):
        return "utf-16-le"
    if even * 10 >= len(sample[0::2]) * 7 and odd * 10 <= len(sample[1::2]):
        return "utf-16-be"
    return ""


def decode(data):
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    encoding = wide(data)
    if encoding:
        return data.decode(encoding, "replace")
    return data.decode("utf-8", "replace")


def readings(data):
    """Each way to read data as text: decode(), and also UTF-8 when decode() read it as
    UTF-16, and Latin-1 when UTF-8 does not fit."""
    first = decode(data)
    out = [first]
    utf8 = data.decode("utf-8", "replace")
    if utf8 != first and wide(data):
        out.append(utf8)
    if "�" in utf8:
        out.append(data.decode("latin-1"))
    return out


def kind_of(data):
    """What the first bytes say a file is, or ""."""
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if data.startswith(b"\x1f\x8b"):
        return "gzip"
    if data.startswith(b"BZh") and data[3:4] in (b"1", b"2", b"3", b"4", b"5", b"6", b"7", b"8", b"9"):
        return "bzip2"
    if data.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    if data.startswith(b"\x28\xb5\x2f\xfd"):
        return "zstd"
    if data.startswith(b"\x5d\x00\x00"):
        return "lzma"
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if data.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if data.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "tiff"
    if len(data) > 262 and data[257:262] == b"ustar":
        return "tar"
    return ""


def looks_text(data):
    sample = data[:8192]
    return b"\x00" not in sample or bool(wide(data))


def public_id(text):
    return "S" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def example_domain(domain):
    domain = domain.lower().rstrip(".")
    return "example" in domain.split(".") or domain.endswith(EXAMPLE_ENDINGS)


def example_host(host):
    host = host.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host in LOCAL_HOSTS:
        return True
    host = host.split(":", 1)[0]
    return host in LOCAL_HOSTS or example_domain(host)


def placeholder_host(host):
    return any(mark in host for mark in "%{}<>$")


def term_pattern(term):
    """The term's words, in composed form, with any space between them, or none, or one
    '.', '_', or '-', with no letter just before or after, case ignored."""
    tokens = [re.escape(token) for token in nfc(term).split()]
    return re.compile(r"(?<![^\W\d_])" + r"(?:\s+|[._-]?)".join(tokens) + r"(?![^\W\d_])", re.I)


def folder_spellings(folder, home):
    """Each way a path to the folder may be written: absolute, its real path, with the
    home folder as a tilde, and with every character that is not a letter or a digit
    turned into a hyphen, as a harness names its project folders, each in composed and
    decomposed form."""
    out = set()
    absolute = os.path.normpath(os.path.expanduser(folder))
    for path in (absolute, os.path.realpath(absolute)):
        for form in ("NFC", "NFD"):
            path = unicodedata.normalize(form, path)
            out.add((nfc(path), False))
            for top in (home, os.path.realpath(home)):
                top = unicodedata.normalize(form, top)
                if top and top != "/" and path.startswith(top + "/"):
                    out.add((nfc("~" + path[len(top):]), False))
            out.add((re.sub(r"[^A-Za-z0-9]", "-", path), True))
    patterns = []
    for spelling, encoded in sorted(out):
        tail = r"(?![A-Za-z0-9])" if encoded else r"(?![A-Za-z0-9_])"
        patterns.append(re.compile(re.escape(spelling) + tail, re.I))
    return patterns


settings = _lib.read_json("settings.json")
MAX_BYTES = settings["max_file_mb"] * MB
WARN_BYTES = settings["warn_file_mb"] * MB
TERMS = [(n, term_pattern(term)) for n, term in enumerate(settings["terms"], 1)]
HOME_FOLDER = os.path.expanduser("~")
EXCLUDED = []
for entry in settings["excluded_folders"]:
    EXCLUDED.extend(folder_spellings(entry, HOME_FOLDER))
EXCLUDED_PATHS = [nfc(path).strip("/").casefold() for path in settings.get("excluded_paths") or []]
ALLOW = settings["allow"]

found = []
counts = collections.OrderedDict((key, 0) for key in (
    "files", "text_files", "office_files", "archives", "archive_members", "images"))


def add(severity, item, kind, evidence="", alts=()):
    found.append({"severity": severity, "item": item, "message": MESSAGES[kind], "evidence": cut(evidence),
                  "alts": [cut(evidence), evidence] + [a for a in alts if a]})


# ---------------------------------------------------------------- names and paths

def name_rules(item, name, top):
    """The rules on a file's name: folders and names that must not be published. Folder
    names are compared with case ignored."""
    parts = name.split("/")
    base = parts[-1]
    lower = base.lower()
    folded = [part.casefold() for part in parts]
    if ".git" in folded:
        add("blocking", item, "git", item)
    if ".homes" in folded:
        add("blocking", item, "homes", item)
    if lower.endswith(DATABASES):
        add("blocking", item, "database", item)
    if any(fnmatch.fnmatchcase(lower, pattern) for pattern in CREDENTIAL):
        add("blocking", item, "credential", item)
    for prefix, message in PRIVATE_FOLDERS:
        if name.casefold().startswith(prefix):
            found.append({"severity": "blocking" if top else "warning", "item": item, "message": message,
                          "evidence": cut(item), "alts": [item]})
    if top:
        spelled = nfc(name).casefold()
        for path in EXCLUDED_PATHS:
            if spelled.startswith(path + "/"):
                add("blocking", item, "excluded_path", item)
    folder_parts = folded[:-1]
    if any(part in TRANSCRIPT_PARTS for part in folder_parts) or \
            any(fnmatch.fnmatchcase(lower, pattern) for pattern in TRANSCRIPT_NAMES):
        add("blocking", item, "transcript", item)
    elif any(part in LEFT_OUT_PARTS or fnmatch.fnmatchcase(part, ".aider*") for part in folder_parts) or \
            any(fnmatch.fnmatchcase(lower, pattern) for pattern in LEFT_OUT_NAMES):
        add("warning", item, "left_out", item)


def path_rules(item, name):
    """Home folders, excluded folders, and terms written in a file's path."""
    name = nfc(name)
    for pattern in HOME:
        for m in pattern.finditer(name):
            if not placeholder_path(m) and not in_web_address(name, m.start()):
                add("blocking", item, "home", m.group(0))
    for pattern in EXCLUDED:
        for m in pattern.finditer(name):
            add("blocking", item, "excluded", m.group(0))
    spaced = re.sub(r"[/_.\-]+", " ", name)
    for n, pattern in TERMS:
        for text in (name, spaced):
            for m in pattern.finditer(text):
                add("blocking", item, "path_term", "term %d" % n, [m.group(0)])


def placeholder_path(match):
    """A home path whose user part is a placeholder such as $USER or <name>."""
    text = match.group(0)
    for lead in ("/Users/", "/home/"):
        if text.startswith(lead):
            return PLACEHOLDER_NAME.match(text[len(lead):]) is not None
    return False


def in_web_address(text, start):
    """Whether the path found at start lies in a web address whose host is another
    machine, such as https://example.org/home/page."""
    if not text.startswith(("/Users/", "/home/"), start):
        return False
    left = start
    while left > 0 and start - left < LOOK_BACK and not TOKEN_EDGE.match(text[left - 1]):
        left -= 1
    token = text[left:start]
    mark = token.find("://")
    if mark < 0:
        return False
    host = token[mark + 3:].split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0].lower()
    return host not in ("", "localhost", "127.0.0.1")


def run_folders(prefix, names, severity):
    """Each folder holding both manifest.json and trail.jsonl."""
    folders = collections.defaultdict(set)
    for name in names:
        folders[posixpath.dirname(name)].add(posixpath.basename(name))
    for folder in sorted(folders):
        if "manifest.json" in folders[folder] and "trail.jsonl" in folders[folder]:
            item = prefix + (folder or ".")
            add(severity, item, "run_folder", item)


# ---------------------------------------------------------------- .gitignore files in the repository

def gitignore_rules(folder, text):
    """(folder, parts, anchored, folders only, negated) for each line of a .gitignore."""
    rules = []
    for raw in text.lstrip("﻿").splitlines():
        line = raw.rstrip("\r")
        while line.endswith(" ") and not line.endswith("\\ "):
            line = line[:-1]
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        if line.startswith("\\"):
            line = line[1:]
        line = line.replace("\\ ", " ")
        folders_only = line.endswith("/")
        pattern = line.rstrip("/")
        parts = [part.casefold() for part in pattern.strip("/").split("/") if part]
        if parts:
            rules.append((folder, parts, "/" in pattern, folders_only, negated))
    return rules


def parts_match(pattern, parts):
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return any(parts_match(pattern[1:], parts[n:]) for n in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pattern[0]) and parts_match(pattern[1:], parts[1:])


def rule_matches(rule, name):
    folder, pattern, anchored, folders_only, _ = rule
    if folder:
        if not name.startswith(folder + "/"):
            return False
        name = name[len(folder) + 1:]
    parts = name.casefold().split("/")
    if anchored:
        ends = range(1, len(parts)) if folders_only else range(1, len(parts) + 1)
        return any(parts_match(pattern, parts[:end]) for end in ends)
    candidates = parts[:-1] if folders_only else parts
    return any(fnmatch.fnmatchcase(part, pattern[0]) for part in candidates)


def ignored_rules(files):
    """Each file of the repository a .gitignore in it matches, with the .gitignore and
    its line, as git applies them with case ignored, the last matching line winning."""
    rules = []
    for name in sorted(files, key=lambda n: (n.count("/"), n)):
        if posixpath.basename(name) == ".gitignore":
            folder = posixpath.dirname(name)
            for rule in gitignore_rules(folder, decode(files[name])):
                rules.append((name, rule))
    for name in sorted(files):
        if posixpath.basename(name) == ".gitignore":
            continue
        hit = None
        for source, rule in rules:
            if rule_matches(rule, name):
                hit = None if rule[4] else (source, rule)
        if hit is not None:
            source, rule = hit
            add("blocking", name, "ignored", "%s: %s" % (source, "/".join(rule[1])))


# ---------------------------------------------------------------- content

def json_unescaped(text):
    return JSON_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text).replace("\\/", "/")


def views(text, extra=()):
    """The text as written and with its HTML entities and JSON escapes undone, each in
    composed form, once each."""
    out = []
    first = [text] + [t for t in extra if t]
    for base in first:
        candidates = [base]
        if "&" in base:
            candidates.append(html.unescape(base))
        if "\\" in base:
            candidates.extend([json_unescaped(t) for t in list(candidates)])
        for candidate in candidates:
            for form in (candidate, nfc(candidate)):
                if form not in out:
                    out.append(form)
    for m in BIBDESK.finditer(text):
        try:
            decoded = base64.b64decode(re.sub(r"\s+", "", m.group(1)), validate=False)
        except (ValueError, TypeError):
            continue
        for reading in (decoded.decode("utf-8", "replace"), decoded.decode("latin-1")):
            if reading not in out:
                out.append(reading)
    return out


def content_rules(item, text, office=False, part="", extra=(), count=True, binary=False):
    """The rules on a file's text, read each way views() gives. Returns the number of
    UUIDs that name no indexed session, or 0 when count is false. part names the Office
    part, shown before the evidence. binary is true for the bytes of an image, a PDF, or
    another binary part, read as text, where a tilde path, a long assignment, or a
    base_url is only noise, so those warnings are not given."""
    lead = part + ": " if part else ""

    def hit(severity, kind, shown, raw=""):
        add(severity, item, kind, lead + shown, [shown, raw])

    readings_ = views(text, extra)
    for view in readings_:
        for m in EMAIL.finditer(view):
            domain = m.group(2)
            if example_domain(domain) or domain.rsplit(".", 1)[1].lower() in IMAGE_DOMAINS:
                continue
            if m.group(1).lower() == "git" and view[m.end():m.end() + 1] == ":":
                continue  # git@host:owner/repo, the address of a repository over ssh
            hit("blocking", "email", m.group(0))
        for pattern in HOME:
            for m in pattern.finditer(view):
                if not placeholder_path(m) and not in_web_address(view, m.start()):
                    hit("blocking", "home", m.group(0))
        for pattern in EXCLUDED:
            for m in pattern.finditer(view):
                hit("blocking", "excluded", m.group(0))
        for m in TRANSCRIPTS.finditer(view):
            hit("blocking", "transcripts", m.group(0))
        for pattern in KEYS:
            for m in pattern.finditer(view):
                hit("blocking", "key", masked(m.group(0)), m.group(0))
        for n, pattern in TERMS:
            for m in pattern.finditer(view):
                hit("blocking", "term", "term %d" % n, m.group(0))
    noisy = "" if binary else text
    for m in TILDE.finditer(noisy):
        hit("warning", "tilde", m.group(0))
    for m in ASSIGNMENT.finditer(noisy):
        hit("warning", "assignment", masked(m.group(0)), m.group(0))
    for m in BASE_URL.finditer(noisy):
        scheme, host = m.group(1), m.group(2)
        if placeholder_host(host) or not HOST.match(host) or not (scheme or "." in host):
            continue
        if not example_host(host):
            hit("warning", "base_url", m.group(0))
    other = 0
    for m in UUID.finditer(text):
        if office and m.start() > 0 and text[m.start() - 1] == "{":
            continue
        names = [m.group(1), m.group(1).lower()]
        if m.group(2):
            names += [m.group(1) + m.group(2), m.group(1).lower() + m.group(2)]
        indexed = sorted(set(public_id(n) for n in names) & INDEXED)
        if indexed:
            hit("blocking", "session", "raw id of " + indexed[0], m.group(0))
        else:
            other += 1
    return other if count else 0


def uuid_note(item, other):
    if other:
        found.append({"severity": "info", "item": item,
                      "message": "The text holds %d %s that name%s no indexed session, which may still be raw "
                                 "ids of other sessions." % (other, "UUID" if other == 1 else "UUIDs",
                                                             "s" if other == 1 else ""),
                      "evidence": "", "alts": []})


def notebook_rule(item, text):
    try:
        cells = json.loads(text).get("cells") or []
    except (ValueError, AttributeError):
        return
    if any(isinstance(cell, dict) and cell.get("outputs") for cell in cells):
        add("warning", item, "notebook", item)


def inflated(data):
    """The text a PDF or PNG file keeps compressed: each FlateDecode stream of a PDF and
    each zTXt and compressed iTXt chunk of a PNG, inflated, up to a limit."""
    out = []
    total = 0
    if data.startswith(b"%PDF-"):
        for m in PDF_STREAM.finditer(data):
            end = data.find(b"endstream", m.end())
            if end < 0:
                break
            try:
                chunk = zlib.decompressobj().decompress(data[m.end():end], INFLATE_LIMIT - total)
            except zlib.error:
                continue
            out.append(chunk)
            total += len(chunk)
            if total >= INFLATE_LIMIT:
                break
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        place = 8
        while place + 8 <= len(data) and total < INFLATE_LIMIT:
            size = int.from_bytes(data[place:place + 4], "big")
            kind = data[place + 4:place + 8]
            body = data[place + 8:place + 8 + size]
            place += 12 + size
            packed = None
            if kind == b"zTXt" and b"\x00" in body:
                packed = body.split(b"\x00", 1)[1][1:]
            elif kind == b"iTXt" and b"\x00" in body:
                rest = body.split(b"\x00", 1)[1]
                if rest[:1] == b"\x01":
                    packed = rest[2:].split(b"\x00", 2)[-1]
            if packed is None:
                continue
            try:
                chunk = zlib.decompressobj().decompress(packed, INFLATE_LIMIT - total)
            except zlib.error:
                continue
            out.append(chunk)
            total += len(chunk)
    return out


def pdf_strings(data):
    """The PDF's text strings written in UTF-16, as its Info dictionary often holds them."""
    out = []
    for m in PDF_WIDE.finditer(data):
        out.append(re.sub(rb"\\(.)", rb"\1", m.group(1)).decode("utf-16-be", "replace"))
    for m in PDF_HEX.finditer(data):
        digits = re.sub(rb"\s+", b"", m.group(1))
        if len(digits) % 2 == 0:
            try:
                out.append(bytes.fromhex(digits.decode("ascii")).decode("utf-16-be", "replace"))
            except ValueError:
                continue
    return out


def media_rules(item, data, part="", note=True):
    """An image or PDF file: its bytes, its compressed text, and its UTF-16 strings are
    scanned, and, unless note is false, a note says that what it shows is not."""
    texts = [data.decode("latin-1")] + [chunk.decode("utf-8", "replace") for chunk in inflated(data)]
    texts += pdf_strings(data)
    for text in texts:
        content_rules(item, text, part=part, count=False, binary=True)
    if note:
        add("info", item, "image", part or item)


def shown_name(name):
    """A custom property's name as a note shows it, with a key and a term written the
    way every other finding shows them."""
    for pattern in KEYS:
        name = pattern.sub(lambda m: masked(m.group(0)), name)
    for n, pattern in TERMS:
        name = pattern.sub("term %d" % n, nfc(name))
    return name


def custom_note(item, names):
    """One note per Office file naming its custom properties. A custom property is not a
    problem by itself, since pandoc writes its bibliography and csl options into every
    Word build; the content rules scan the values with the rest of the part."""
    if names:
        add("info", item, "office_custom", "custom %s: %s" % ("property" if len(names) == 1 else "properties",
                                                              ", ".join(shown_name(n) for n in names)))


def is_package(book, ext):
    names = set(book.namelist())
    if "[Content_Types].xml" in names:
        return True
    if "mimetype" in names:
        try:
            return book.read("mimetype").startswith(b"application/vnd.oasis.opendocument")
        except (zipfile.BadZipFile, ValueError, OSError, NotImplementedError, RuntimeError):
            return False
    return ext in PACKAGES


def flat_text(text):
    """The text of each paragraph of an XML part with its tags taken away, one a line."""
    lines = []
    for m in XML_PARAGRAPH.finditer(text):
        lines.append(html.unescape(XML_TAG.sub("", XML_SPACE.sub(" ", m.group(2)))))
    return "\n".join(lines)


def xml_part_rules(item, part, text, shown, custom):
    """One XML part of an Office file: its text, as written and with its paragraphs
    joined, and the people it names."""
    lead = shown + ": "
    other = content_rules(item, text, office=True, part=shown)
    content_rules(item, flat_text(text), office=True, part=shown, count=False)
    base = posixpath.basename(part)

    def person(kind, label, name):
        if name.strip():
            add("blocking", item, kind, lead + label, [label, html.unescape(name)])

    for m in CREATOR.finditer(text):
        person("office_person", m.group(1), m.group(2))
    if base == "app.xml":
        for m in APP_PEOPLE.finditer(text):
            person("office_person", m.group(1), m.group(2))
    if part == "docProps/custom.xml":
        for m in CUSTOM_PROPERTY.finditer(text):
            name = html.unescape(m.group(1))
            if name not in custom:
                custom.append(name)
    if base == "meta.xml":
        for m in ODF_PROPERTY.finditer(text):
            name = html.unescape(m.group(1))
            if name not in custom:
                custom.append(name)
    if part.startswith("word/"):
        for m in WORD_AUTHOR.finditer(text):
            person("word_author", m.group(1), m.group(2))
        for m in WORD_COMMENT.finditer(text):
            add("warning", item, "word_comment", lead + "w:comment", ["w:comment"])
    if part == "word/people.xml":
        for m in WORD_PERSON.finditer(text):
            add("blocking", item, "word_person", lead + "w15:person", ["w15:person", html.unescape(m.group(1))])
    if part in ("ppt/commentAuthors.xml", "ppt/authors.xml"):
        for m in SLIDE_AUTHOR.finditer(text):
            person("slide_author", "author", m.group(1))
    if part.startswith("xl/comments") and part.endswith(".xml"):
        for m in SHEET_AUTHOR.finditer(text):
            person("sheet_author", "author", m.group(1))
    if part.startswith("xl/persons/"):
        for m in SHEET_PERSON.finditer(text):
            for attribute in PERSON_ATTRIBUTE.finditer(m.group(1)):
                person("sheet_person", "person " + attribute.group(1), attribute.group(2))
    if part in ("content.xml", "styles.xml"):
        for m in ODF_COMMENT.finditer(text):
            add("warning", item, "odf_comment", lead + "office:annotation", ["office:annotation"])
    return other


def office_rules(item, data, ext, prefix="", depth=0):
    """Every part of a Word, Excel, PowerPoint, or OpenDocument file, with the people it
    names. An Office file inside one is scanned the same way, an image inside one as an
    image, an older Office object inside one blocks, and any other part is scanned as
    text."""
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
        parts = sorted(book.namelist())
    except (zipfile.BadZipFile, ValueError, OSError, RuntimeError):
        add("blocking", item, "bad_office", (prefix + item) if not prefix else prefix.rstrip(": "))
        return
    if depth == 0:
        counts["office_files"] += 1
    other = 0
    custom = []
    pictures = 0
    for part in parts:
        if part.endswith("/"):
            continue
        shown = prefix + part
        try:
            raw = book.read(part)
        except (zipfile.BadZipFile, ValueError, OSError, NotImplementedError, RuntimeError):
            add("blocking", item, "bad_office", item + " " + shown)
            continue
        lower = part.lower()
        kind = kind_of(raw)
        if lower.endswith(OFFICE_PARTS) and kind != "zip":
            other += xml_part_rules(item, part, decode(raw), shown, custom)
        elif kind == "zip":
            inner_ext = posixpath.splitext(lower)[1]
            try:
                inner = zipfile.ZipFile(io.BytesIO(raw))
                package = is_package(inner, inner_ext)
            except (zipfile.BadZipFile, ValueError, OSError, RuntimeError):
                package = False
            if package and depth < NESTED:
                office_rules(item, raw, inner_ext, shown + ": ", depth + 1)
            else:
                add("blocking", item, "archive", shown)
        elif kind == "ole":
            add("blocking", item, "old_office", shown)
        elif kind in COMPRESSED_KINDS:
            add("blocking", item, "compressed", shown)
        elif kind in IMAGE_KINDS or lower.endswith(MEDIA):
            media_rules(item, raw, shown, note=False)
            pictures += kind in IMAGE_KINDS or lower.endswith(IMAGES)
        else:
            texts = readings(raw)
            binary = not looks_text(raw)
            if binary:
                texts.append(raw.decode("utf-16-le", "replace"))
                texts.append(raw[1:].decode("utf-16-le", "replace"))
            other += content_rules(item, texts[0], office=True, part=shown, extra=texts[1:],
                                   binary=binary)
    if pictures:
        add("info", item, "office_images", "%s%d %s" % (prefix, pictures, "image" if pictures == 1 else "images"))
    if depth == 0:
        custom_note(item, custom)
        uuid_note(item, other)
    elif custom:
        custom_note(item, custom)


# ---------------------------------------------------------------- files

def scan_text(item, data, ext):
    counts["text_files"] += 1
    texts = readings(data)
    uuid_note(item, content_rules(item, texts[0], extra=texts[1:]))
    if ext == ".ipynb":
        notebook_rule(item, texts[0])


def scan_file(item, name, data, top):
    lower = posixpath.basename(name).lower()
    ext = posixpath.splitext(lower)[1]
    kind = kind_of(data)
    name_rules(item, name, top)
    path_rules(item, name)
    if top:
        if len(data) > MAX_BYTES:
            add("blocking", item, "max_size", "%d bytes" % len(data))
        elif len(data) > WARN_BYTES:
            add("warning", item, "warn_size", "%d bytes" % len(data))
    if kind == "sqlite" and not lower.endswith(DATABASES):
        add("blocking", item, "database", item)
    if kind == "zip" or (ext in PACKAGES and kind not in ("ole",)):
        package = ext in PACKAGES
        if kind == "zip" and not package:
            try:
                package = is_package(zipfile.ZipFile(io.BytesIO(data)), ext)
            except (zipfile.BadZipFile, ValueError, OSError, RuntimeError):
                package = False
        if package:
            office_rules(item, data, ext)
        else:
            add("blocking", item, "archive", item)
        return
    if kind == "ole":
        add("blocking", item, "old_office", item)
        return
    if kind in COMPRESSED_KINDS:
        add("blocking", item, "compressed", item)
        return
    if lower.endswith(ARCHIVES):
        add("blocking", item, "archive", item)
        return
    if kind == "tar" or ext == ".tar":
        if top:
            scan_tar(item, data)
        else:
            add("blocking", item, "archive", item)
        return
    if kind in IMAGE_KINDS or (ext in IMAGES and not looks_text(data)):
        if top:
            counts["images"] += 1
        media_rules(item, data)
        return
    scan_text(item, data, ext)


def header_rules(item, member, owners):
    """A tar member's header: a link's target, the owner's names, and extended headers.
    owners holds the owner names already found in this tar, each found once."""
    if member.issym() or member.islnk():
        target = member.linkname or ""
        content_rules(item, target, count=False)
        path_rules(item, target)
        place = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), target))
        if target.startswith("/") or place == ".." or place.startswith("../"):
            add("blocking", item, "link_out", item)
    for field in ("uname", "gname"):
        value = (getattr(member, field, "") or "").strip()
        if value.casefold() not in OWNERS and value not in owners:
            owners.add(value)
            add("blocking", item, "owner", field, [value])
            content_rules(item, value, count=False)
    for key, value in sorted((member.pax_headers or {}).items()):
        if key in PAX_KEYS:
            continue
        text = "%s=%s" % (key, value)
        content_rules(item, text.encode("utf-8", "surrogateescape").decode("utf-8", "replace"), count=False)


def scan_tar(item, data):
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
        members = archive.getmembers()
    except (tarfile.TarError, EOFError, OSError):
        add("blocking", item, "bad_tar", item)
        return
    counts["archives"] += 1
    for key, value in sorted((archive.pax_headers or {}).items()):
        content_rules(item, "%s=%s" % (key, value), count=False)
    inner = collections.OrderedDict()
    owners = set()
    for member in members:
        name = clean_name(member.name)
        if not name:
            continue
        header_rules(item + ":" + name, member, owners)
        if member.isdir():
            continue
        if not member.isfile():
            add("warning", item + ":" + name, "special", item + ":" + name)
            continue
        inner[name] = archive.extractfile(member).read()
    for name in sorted(inner):
        counts["archive_members"] += 1
        scan_file(item + ":" + name, name, inner[name], False)
    run_folders(item + ":", inner, "warning")


files = collections.OrderedDict()
with tarfile.open(_lib.path("repo.tar")) as tf:
    for member in tf.getmembers():
        name = clean_name(member.name)
        if member.isdir() or not name:
            continue
        if not member.isfile():
            add("warning", name, "special", name)
            continue
        files[name] = tf.extractfile(member).read()

INDEXED = set()
if SESSIONS in files:
    for row in csv.DictReader(io.StringIO(decode(files[SESSIONS]))):
        if row.get("public_id"):
            INDEXED.add(row["public_id"].strip())

for name in sorted(files):
    counts["files"] += 1
    scan_file(name, name, files[name], True)
run_folders("", files, "blocking")
ignored_rules(files)


# ---------------------------------------------------------------- allow entries and output

def accepted(f):
    for entry in ALLOW:
        if isinstance(entry, str):
            if entry in f["alts"]:
                return True
            continue
        if "text" in entry and entry["text"] not in f["alts"]:
            continue
        if "path" in entry and not fnmatch.fnmatchcase(f["item"], entry["path"]):
            continue
        return True
    return False


findings, seen = [], set()
for f in found:
    severity, message = f["severity"], f["message"]
    if severity != "info" and accepted(f):
        severity, message = "info", MESSAGES["accepted"] + message
    key = (severity, f["item"], message, f["evidence"])
    if key in seen:
        continue
    seen.add(key)
    findings.append(_lib.finding(CHECK, severity, f["item"], message, f["evidence"]))

scan = dict(counts)
scan["blocked"] = sum(1 for f in findings if f["severity"] == "blocking")
scan["warned"] = sum(1 for f in findings if f["severity"] == "warning")
scan["accepted"] = sum(1 for f in findings if f["message"].startswith(MESSAGES["accepted"]))
_lib.write_json("scan.json", scan)
_lib.emit_findings(CHECK, findings)
