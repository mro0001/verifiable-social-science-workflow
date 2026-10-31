"""Tests for the layer's contract (Track E, step E15).

observability/CONTRACT.md states what the layer reads and writes, so Track
D's wrappers and the authors' connections have one place that names the inputs
and the trace file form (plan choice 16). These tests hold the contract to
the code. Every attribute key and operation name in conventions.py appears
in it, and so do the commands build and watch and every option the command
line accepts. Run from the repository root with python3 -m pytest -q
observability/tests.
"""
import argparse
from pathlib import Path

import pytest

from observability import cli
from observability import conventions as cv

CONTRACT = Path(__file__).resolve().parents[1] / "CONTRACT.md"


@pytest.fixture(scope="module")
def contract():
    return CONTRACT.read_text(encoding="utf-8")


def _commands():
    parser = cli._parser()
    [commands] = [action for action in parser._actions
                  if isinstance(action, argparse._SubParsersAction)]
    return commands.choices


def _options():
    found = set()
    for command in _commands().values():
        for action in command._actions:
            for option in action.option_strings:
                if option not in ("-h", "--help"):
                    found.add(option)
    return sorted(found)


def test_the_contract_exists():
    assert CONTRACT.is_file()


@pytest.mark.parametrize("key", cv.ATTRIBUTE_KEYS)
def test_every_attribute_key_is_in_the_contract(contract, key):
    assert "`%s`" % key in contract


@pytest.mark.parametrize("operation", cv.OPERATIONS)
def test_every_operation_name_is_in_the_contract(contract, operation):
    assert "`%s`" % operation in contract


def test_the_commands_are_build_and_watch():
    assert sorted(_commands()) == ["build", "watch"]


@pytest.mark.parametrize("command", ["build", "watch"])
def test_both_commands_are_in_the_contract(contract, command):
    assert "python3 -m observability %s" % command in contract


def test_the_command_line_has_options_to_check():
    assert "--audit-home" in _options()
    assert "--vg-runs" in _options()
    assert "--interval" in _options()


@pytest.mark.parametrize("option", _options())
def test_every_option_is_in_the_contract(contract, option):
    assert "`%s" % option in contract


def test_the_contract_uses_no_em_dash(contract):
    assert "—" not in contract
