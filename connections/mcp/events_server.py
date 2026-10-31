"""The events tool for outside software, workflow-events (Track D, step D8).

Proposal Status paragraph 3 names wrappers and MCP tools that bring AI
observability into tools outside the workflow, with the same events written
to the logs. Appendix A2.2 names MCP tools that bring events in from software
outside the workflow, and A2.6 says events come through them from that
software (Table A7, Planned).

This server offers one general tool, record_event. A client running beside
the scholar's editor, citation manager, or other software calls it to say
what was done, and the tool writes one event for the server's working folder
with the shared event writer, as the wrappers do (Track D choice 2). Nothing
is recorded in an excluded folder or while the audit settings file is
missing (choice 3). A tool that reads events out of a named program is not
built.
"""
import os
from typing import Any, Dict, List

from connections.events import KINDS, ROLES, VERBS, append_event, make_event
from connections.home import recording_allowed
from connections.mcp.protocol import Tool

SERVER_NAME = "workflow-events"
SERVER_VERSION = "0.1.0"

OFF = "recording is off for this folder"
NOT_WRITTEN = "the event could not be written"


def tools(folder=None) -> List[Tool]:
    """The server's one tool, recording events for folder, else the working folder."""
    folder = os.path.abspath(str(folder)) if folder is not None else os.getcwd()

    def record_event(verb, kind, object, rationale="", role="", program="mcp"):
        return _record(folder, verb, kind, object, rationale, role, program)

    return [
        Tool(
            "record_event",
            "Record one thing done in software outside the workflow, such as an edit in the "
            "word processor or an export from the citation manager, as an event for this "
            "folder. Nothing is recorded in an excluded folder.",
            {
                "type": "object",
                "properties": {
                    "verb": {
                        "type": "string",
                        "enum": list(VERBS),
                        "description": "what was done",
                    },
                    "kind": {
                        "type": "string",
                        "enum": list(KINDS),
                        "description": "whether it was an action, a decision, an observation, or a blocker",
                    },
                    "object": {
                        "type": "string",
                        "description": "what it was done to, such as a file or a citation key",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "why it was done, empty when left out",
                    },
                    "role": {
                        "type": "string",
                        "enum": list(ROLES) + [""],
                        "description": "the file's role when the object is a file, empty when left out",
                    },
                    "program": {
                        "type": "string",
                        "description": "the software it was done in, mcp when left out",
                    },
                },
                "required": ["verb", "kind", "object"],
            },
            record_event,
        )
    ]


def _record(folder, verb, kind, obj, rationale, role, program) -> Dict[str, Any]:
    try:
        event = make_event(folder, verb, kind, obj, rationale=rationale, role=role, program=program)
    except ValueError as error:
        return {"error": {"code": "invalid_argument", "message": str(error)}}
    if not recording_allowed(folder):
        return {"recorded": False, "reason": OFF}
    if not append_event(event):
        return {"recorded": False, "reason": NOT_WRITTEN}
    return {"recorded": True, "source_id": event["source_id"]}
