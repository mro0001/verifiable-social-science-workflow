"""The features' command line, python3 -m features.

Three command groups, setup, organize, and portal, which later steps fill.
A group given with no command prints its help. setup system is step F3,
setup project is step F5, setup plan is step S1, organize scan is steps F6
and F7, organize check is step F8, organize apply is step F9, organize undo
and organize log are step F10, and portal build is step F15.
"""
import argparse
import sys

from features import __version__
from features.organizer import apply as organize_apply
from features.organizer import inventory as organize_inventory
from features.organizer import proposals as organize_proposals
from features.organizer import undo as organize_undo
from features.portal import render as portal_render
from features.setup import plan as setup_plan
from features.setup import project as setup_project
from features.setup import system as setup_system

GROUPS = (
    ("setup", "set up the scholar's system once, then each project"),
    ("organize", "propose, check, apply, and undo changes to a project's files"),
    ("portal", "build the portal, a static site to learn and critique the workflow"),
)


def _parser():
    parser = argparse.ArgumentParser(
        prog="features",
        description="Pipeline setup, the project organizer, and the portal.")
    parser.add_argument("--version", action="version", version="features " + __version__)
    groups = parser.add_subparsers(dest="group", metavar="GROUP")
    helps = {}
    for name, text in GROUPS:
        group = groups.add_parser(name, help=text, description=text)
        commands = group.add_subparsers(dest="command", metavar="COMMAND")
        if name == "setup":
            setup_plan.add_command(commands)
            setup_system.add_command(commands)
            setup_project.add_command(commands)
        if name == "organize":
            organize_inventory.add_command(commands)
            organize_proposals.add_command(commands)
            organize_apply.add_command(commands)
            organize_undo.add_commands(commands)
        if name == "portal":
            portal_render.add_command(commands)
        helps[name] = group
    return parser, helps


def main(argv=None):
    parser, helps = _parser()
    options = parser.parse_args(argv)
    if options.group is None:
        parser.print_help(sys.stderr)
        return 2
    if getattr(options, "command", None) is None:
        helps[options.group].print_help(sys.stdout)
        return 0
    return options.run(options)
