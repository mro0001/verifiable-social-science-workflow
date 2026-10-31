"""The triggers, which start the verification procedures (Track D, steps D9, D10, and D20).

The proposal says events in the harness, such as an AI edit or the end of a
turn, start the verification procedures (Overview paragraph 2), and names the
harness triggers as designed but not built (Status paragraph 2). Appendix
A2.2 says triggers are designed for one harness's hooks, and Table A6 lists
the procedure registry and triggers as specified.

registry.py reads the verification layer's procedure registry, read only, and
the scholar's own trigger settings. hook.py answers Claude Code's hooks.
make.py and verify.mk start the stale streams before a build. The
command that starts a procedure is always the scholar's, since the scholar makes
the connections between layers (Track D choice 19).
"""
