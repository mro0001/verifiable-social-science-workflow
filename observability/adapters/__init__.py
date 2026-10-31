"""Observability adapters, one for each harness whose kept transcripts this layer reads.

An adapter turns one harness's transcripts into trace spans that follow
OpenTelemetry's conventions for AI calls, so the view is the same for every
harness (appendix A2.6). Claude Code is the first harness (claude_code.py).
A harness without a transcript adapter is shown from the audit events table
instead (events.py, plan choice 5). Verification runs, the one AI program
outside the harness read directly, come from vg.py's run folders
(vg_run.py, plan choice 12).
"""
