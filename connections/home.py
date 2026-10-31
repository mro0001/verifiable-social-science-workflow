"""The connections home and the folders where connectors record nothing.

Appendix A2.2 says the connectors sit outside any single project, so one setup
serves every project a scholar runs. The connectors keep their settings and
events in one folder per scholar, the connections home, which is the
CONNECTIONS_HOME environment variable if set, else ~/.workflow_connections
(Track D choice 1).

A2.6 and A6 say sessions run in a folder the scholar excludes, such as one
holding student records, are never recorded. The connectors read the same
list capture reads, excluded_folders in the audit layer's settings file, and
apply the same rule to the folder a call or a turn ran in. They write, walk,
or start nothing in a listed folder or a folder inside one, and nothing at
all while that file is missing or unclear (Track D choice 3, reconciliation
item 3). The file is read here directly, since connections imports no audit
layer code.

A listed folder matches whatever its letter case when the disk holding it
ignores case, as a Mac's disk usually does, so a folder listed as .../records
also covers a call or a turn in .../Records. On a disk that keeps case the
match stays exact. The audit layer makes the same check, written again there
(Track L, Step L4, decision 51).
"""
import hashlib
import os
import string
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import yaml

HOME_VARIABLE = "CONNECTIONS_HOME"
DEFAULT_HOME = "~/.workflow_connections"

# The audit layer's home and settings file, as the audit layer names them in
# audit_layer/settings.py.
AUDIT_HOME_VARIABLE = "AUDIT_HOME"
AUDIT_DEFAULT_HOME = "~/.audit_layer"
AUDIT_SETTINGS = "settings.yaml"


def connections_home() -> Path:
    """The connections home, CONNECTIONS_HOME if set, else ~/.workflow_connections.

    A variable set to nothing counts as not set. The folder is expanded and
    never created here.
    """
    chosen = os.environ.get(HOME_VARIABLE) or DEFAULT_HOME
    return Path(os.path.expanduser(chosen))


def audit_settings_path() -> Path:
    """settings.yaml in AUDIT_HOME if set, else in ~/.audit_layer."""
    chosen = os.environ.get(AUDIT_HOME_VARIABLE) or AUDIT_DEFAULT_HOME
    return Path(os.path.expanduser(chosen)) / AUDIT_SETTINGS


def excluded_folders() -> Optional[List[str]]:
    """The real paths listed under excluded_folders, or None.

    None means the settings file is missing, cannot be read, does not parse,
    or does not clearly list the folders. That is, it is not a mapping, has
    no excluded_folders list, or lists something other than a full path. A
    listed folder starting with ~ is taken from the home folder, and links
    are followed. A file holding any setting besides excluded_folders is
    unclear too, as the slice's audit_layer/settings.py refuses it, so a
    misspelled name never leaves a listed folder recorded.
    """
    path = audit_settings_path()
    try:
        settings = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(settings, dict):
        return None
    if any(name != "excluded_folders" for name in settings):
        return None
    folders = settings.get("excluded_folders")
    if not isinstance(folders, list):
        return None
    found = []
    for folder in folders:
        if not isinstance(folder, str) or not folder.strip():
            return None
        expanded = os.path.expanduser(folder)
        if not os.path.isabs(expanded):
            return None
        found.append(os.path.realpath(expanded))
    return found


def recording_allowed(path) -> bool:
    """Whether a connector may record or start anything for path.

    True only when the excluded folders can be read and the real path of path
    is neither a listed folder nor inside one. Folders are compared by whole
    path parts, so listing /a/records leaves /a/records_old allowed, and
    letter case is ignored for a folder whose own disk ignores it.
    """
    folders = excluded_folders()
    if folders is None:
        return False
    return not inside(path, case_rules(folders))


# A listed folder as its whole path parts, and whether its disk ignores case.
Rule = Tuple[Tuple[str, ...], bool]


def case_rules(folders: Sequence[str]) -> List[Rule]:
    """Each listed folder's path parts, with whether its own disk ignores letter case.

    The disk is checked once here, so a walk over many files compares each
    with the list without checking the disk again.
    """
    rules = []
    for folder in folders:
        fold = ignores_case(folder)
        rules.append((_parts(folder, fold), fold))
    return rules


def inside(path, rules: Sequence[Rule]) -> bool:
    """Whether the real path of path is one of the listed folders or inside one.

    Folders are compared by whole path parts, so listing /a/records leaves
    /a/records_old out. Letter case is ignored for a folder whose disk
    ignores it.
    """
    real = os.path.realpath(str(path))
    for top, fold in rules:
        if _parts(real, fold)[: len(top)] == top:
            return True
    return False


def _parts(path: str, fold: bool) -> Tuple[str, ...]:
    parts = Path(path).parts
    return tuple(part.casefold() for part in parts) if fold else parts


# Swaps the small and capital letters of A to Z, and leaves every other
# character as it is.
_SWAP = str.maketrans(
    string.ascii_lowercase + string.ascii_uppercase,
    string.ascii_uppercase + string.ascii_lowercase,
)


def ignores_case(path) -> bool:
    """Whether the disk holding path ignores letter case in names.

    Found on the disk itself. The folder, or the nearest folder above it that
    exists, is looked up again under its own name with its small and capital
    letters swapped, and the disk ignores case when that finds the same
    folder. A name with no letter to swap is passed over for the one above it,
    as long as that name is still looked up on the same disk. When no such
    name can be tried, or the disk cannot be read, the disk is taken to ignore
    case, the safe choice for folders holding student records (decision 51).
    """
    here = os.path.realpath(str(path))
    while not os.path.exists(here):
        above = os.path.dirname(here)
        if above == here:
            return True
        here = above
    try:
        own_disk = os.stat(here).st_dev
    except OSError:
        return True
    while True:
        above = os.path.dirname(here)
        if above == here:
            return True
        try:
            same_disk = os.stat(above).st_dev == own_disk
        except OSError:
            return True
        if not same_disk:
            return True
        name = os.path.basename(here)
        swapped = name.translate(_SWAP)
        if swapped != name:
            try:
                return os.path.samestat(os.stat(here), os.stat(os.path.join(above, swapped)))
            except FileNotFoundError:
                return False
            except OSError:
                return True
        here = above


def folder_key(path) -> str:
    """The first 12 hex characters of the sha256 of the real path of path, as text."""
    real = os.path.realpath(str(path))
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:12]
