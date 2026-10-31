"""The audit layer's triggers, which start the sweep at the times appendix A2.4 names.

The sweep runs while a session runs, when it ends, and again on a schedule
(A2.4 "Capture"). claude_code_hook.py is the script Claude Code's hooks run at
the end of each turn, when a subagent finishes, and when a session ends, and
schedule/audit_layer.sweep.plist is a launchd template that runs the sweep
every 30 minutes (plan choice 7). INSTALL.md says how the scholar adds each
by hand. Nothing in the repository installs any of them.
"""
