# The Make trigger (Track D, step D20). Include this file in a project's Makefile
# and make each research product depend on verify. Before the build, verify starts
# the start command of every stream whose results file no longer covers the
# source text or the numbers file, and never stops the make.
#
#   paper: verify
#   	...
#   include /path/to/repo/connections/triggers/verify.mk
#
# Put the include line after the first rule, so verify does not become the
# default target. Set VERIFY_SOURCE or VERIFY_NUMBERS before the include line,
# or on the make command line, when the project names its files otherwise.
# Only GNU Make 3.81 features are used.

WORKFLOW_REPO := $(abspath $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../..)
VERIFY_SOURCE ?= manuscript.md
VERIFY_NUMBERS ?= numbers.yml

.PHONY: verify
verify:
	-PYTHONPATH="$(WORKFLOW_REPO)$${PYTHONPATH:+:$$PYTHONPATH}" python3 -m connections trigger make --project "$(CURDIR)" --source "$(VERIFY_SOURCE)" --numbers "$(VERIFY_NUMBERS)"
