"""The audit home, its settings file, and the folders whose sessions are never recorded.

The audit home is the --home option, else the AUDIT_HOME environment variable,
else ~/.audit_layer (plan Step 5). The init command writes settings.yaml there
with an empty excluded_folders list, and capture does not run until that file
exists, so the scholar always declares the folders (plan choice 5).

Appendix A6 and A2.6 say sessions run in a folder the scholar excludes, such
as one holding student records, are never recorded. Capture skips every
session run in a listed folder or in a folder inside one, and nothing more. A
session run elsewhere that reads a file in a listed folder is still recorded,
as A6 says.

add_excluded (Track S, step S2) adds folders to the list for the command
python3 -m audit_layer excluded add, which setup runs before anything
records. It never removes a folder.

A listed folder matches whatever its letter case when the disk holding it
ignores case, as a Mac's disk usually does, so a folder listed as .../records
also leaves out sessions run in .../Records. On a disk that keeps case the
match stays exact (Track L, Step L4, decision 51).
"""
import os
import string
from collections.abc import Mapping
from pathlib import Path
from typing import Any, List

import yaml

SETTINGS = "settings.yaml"
HOME_VARIABLE = "AUDIT_HOME"
DEFAULT_HOME = "~/.audit_layer"

# The settings capture knows. A name it does not know, such as a misspelled
# excluded_folders, is refused rather than passed over.
_KNOWN = ("excluded_folders",)

# The settings file as init writes it.
_TEMPLATE = """\
# Settings for the audit layer, which records AI sessions.
#
# List under excluded_folders every folder that holds student records, and
# any other folder whose AI sessions must never be kept. A session run in a
# listed folder, or in any folder inside one, is never recorded. A session
# run elsewhere that reads a file in a listed folder is still recorded.
#
# Give each folder as a full path on its own line, starting with / or ~, and
# write its capital and small letters as the folder shows them, as below.
#
# excluded_folders:
#   - ~/Documents/Courses
#   - /Volumes/Shared/Advising
excluded_folders: []
"""


class SettingsError(ValueError):
    """Settings that capture cannot rely on."""


def audit_home(given=None) -> Path:
    """The audit home, which is given (the --home option), else AUDIT_HOME, else ~/.audit_layer.

    A variable set to nothing counts as not set.
    """
    chosen = given or os.environ.get(HOME_VARIABLE) or DEFAULT_HOME
    return Path(os.path.expanduser(str(chosen)))


def write_settings(home) -> bool:
    """Write <home>/settings.yaml with no excluded folders, unless the file exists.

    An existing file is kept as it is, so running init again never drops the
    folders the scholar listed. Gives True when the file was written.
    """
    path = Path(home) / SETTINGS
    if path.exists():
        return False
    path.write_text(_TEMPLATE, encoding="utf-8")
    return True


def read_settings(home) -> dict:
    """The settings in <home>/settings.yaml.

    A missing file is refused, and so is a file that does not clearly list the
    excluded folders, since a mistake there would quietly record sessions the
    scholar meant to leave out.
    """
    path = Path(home) / SETTINGS
    if not path.is_file():
        raise SettingsError(
            f"there is no settings file at {path}. Run python3 -m audit_layer init,"
            " then list in it every folder whose sessions are never recorded"
        )
    try:
        settings = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise SettingsError(f"{path} is not YAML that can be read ({error})") from error
    try:
        _folders(settings)
    except SettingsError as error:
        raise SettingsError(f"{path} is refused, {error}") from error
    return settings


def excluded(path, settings) -> bool:
    """Whether path is a listed folder or a folder inside one.

    Both sides are compared as real paths, with links followed, so a link into
    a listed folder still counts and a listed link stands for the folder it
    points to. A folder counts only whole, so listing /a/records leaves out
    /a/records_old. A listed folder starting with ~ is taken from the home
    folder. Letter case is ignored when the listed folder's own disk ignores
    it, and kept otherwise.
    """
    real = os.path.realpath(str(path))
    for folder in _folders(settings):
        top = os.path.realpath(os.path.expanduser(folder))
        seen = real
        if ignores_case(top):
            seen, top = real.casefold(), top.casefold()
        if seen == top or seen.startswith(top.rstrip(os.sep) + os.sep):
            return True
    return False


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


def _folders(settings: Any) -> List[str]:
    """The listed folders, once the settings are checked to list them clearly."""
    if not isinstance(settings, Mapping):
        raise SettingsError("the settings must be a mapping with an excluded_folders list")
    unknown = sorted(str(name) for name in settings if name not in _KNOWN)
    if unknown:
        raise SettingsError(f"there is no setting named {', '.join(unknown)}")
    folders = settings.get("excluded_folders")
    if not isinstance(folders, list):
        raise SettingsError("excluded_folders must be a list of folders, or [] for none")
    for folder in folders:
        if not isinstance(folder, str) or not folder.strip():
            raise SettingsError(f"excluded_folders holds {folder!r}, which is not a folder")
        if not os.path.isabs(os.path.expanduser(folder)):
            raise SettingsError(f"excluded_folders holds {folder!r}, which is not a full path")
    return folders


def full_path_problem(folder: str):
    """Why folder cannot be listed, or None when it is a full path starting with / or ~."""
    if not isinstance(folder, str) or not folder.strip():
        return f"{folder!r} is not a folder"
    if not folder.startswith(("/", "~")) or not os.path.isabs(os.path.expanduser(folder)):
        return (f"{folder} is not a full path. Give each folder as a full path starting"
                " with / or ~")
    return None


def _same(one: str, other: str) -> bool:
    return os.path.normpath(os.path.expanduser(one)) == os.path.normpath(os.path.expanduser(other))


def add_excluded(home, folders) -> List[str]:
    """Add each folder to excluded_folders in <home>/settings.yaml and give back the list.

    Each folder is stored as given, with ~ expanded. A folder already listed,
    however it was written, is not added again, and no folder is ever
    removed. The settings file must exist and be one capture accepts, so a
    file the scholar mistyped is left as it is (SettingsError). Its leading
    comment lines are kept. Nothing is written when no folder is new.
    """
    for folder in folders:
        problem = full_path_problem(folder)
        if problem:
            raise SettingsError(problem)
    settings = read_settings(home)
    listed = list(_folders(settings))
    added = False
    for folder in folders:
        expanded = os.path.expanduser(folder)
        if not any(_same(expanded, kept) for kept in listed):
            listed.append(expanded)
            added = True
    if added:
        _write_folders(Path(home) / SETTINGS, listed)
    return listed


def _write_folders(path: Path, folders: List[str]) -> None:
    """Write the list after the file's leading comment lines, replacing the file in one step."""
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            break
        kept.append(line)
    text = "\n".join(kept) + ("\n" if kept else "")
    text += yaml.safe_dump({"excluded_folders": folders}, default_flow_style=False,
                           allow_unicode=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(text, encoding="utf-8")
    os.replace(str(partial), str(path))
