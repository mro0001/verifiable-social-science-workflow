"""The connectors' command line, run as python3 -m connections.

The later steps of Track D add their commands to the table in main.

wrap -- PROGRAM [ARGS...]   run a program and log the call (step D3)
serve kb --index FILE       serve the knowledge base over MCP from a kb-index export (step D6)
serve audit [--home DIR]    serve the audit store over MCP (step D7)
serve events                serve the events tool over MCP for this folder (step D8)
provider show               show the provider setting and whether the key is set (step D14)
provider set --base-url URL --model NAME [--second-model NAME]
  [--token-limit N --token-limit-field FIELD] [--request-timeout SECONDS] [--home DIR]
                            write the provider setting, never a key (Track S, step S2)
adapt NAME --out DIR ...    turn a tool's files into a stream's input files (step D11)
trigger hook                answer one Claude Code hook, the AI-edit and end-of-turn triggers (step D10)
trigger make --project DIR  start the stale streams before a build, the Make trigger (step D20)
"""
import argparse
import contextlib
import io
import os
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="connections")
    commands = parser.add_subparsers(dest="command", metavar="command")

    wrap = commands.add_parser(
        "wrap",
        usage="connections wrap -- PROGRAM [ARGS...]",
        help="run a program and log the call",
    )
    wrap.add_argument("program", nargs=argparse.REMAINDER)

    serve = commands.add_parser(
        "serve", help="serve a store to an MCP client over standard input and output"
    )
    servers = serve.add_subparsers(dest="server", metavar="server", required=True)
    kb = servers.add_parser(
        "kb", help="the knowledge base server, workflow-kb, which runs the knowledge base graph"
    )
    kb.add_argument(
        "--index",
        required=True,
        metavar="FILE",
        help="the kb-index export the server answers from, read on each call",
    )
    audit = servers.add_parser("audit", help="the audit store server, workflow-audit")
    audit.add_argument(
        "--home",
        metavar="DIR",
        help="the audit home folder, else the AUDIT_HOME environment variable, else ~/.audit_layer",
    )
    servers.add_parser(
        "events", help="the events tool for outside software, workflow-events, for this folder"
    )

    provider = commands.add_parser("provider", help="the provider setting, the model service and model")
    provider_actions = provider.add_subparsers(dest="action", metavar="show|set", required=True)
    provider_actions.add_parser(
        "show", help="print the setting's file, base_url, and model, and whether the key is set"
    )
    provider_set = provider_actions.add_parser(
        "set", help="write the provider setting in the connections home, never a key"
    )
    provider_set.add_argument("--base-url", required=True, metavar="URL",
                              help="the model service's address, starting with http:// or https://")
    provider_set.add_argument("--model", required=True, metavar="NAME",
                              help="the model that answers the checks' questions")
    provider_set.add_argument("--second-model", metavar="NAME",
                              help="another model on the same service that rechecks doubtful"
                              " source verdicts")
    provider_set.add_argument("--token-limit", type=int, metavar="N",
                              help="the output limit of each live reply, given with"
                              " --token-limit-field")
    provider_set.add_argument("--token-limit-field", metavar="FIELD",
                              help="max_tokens or max_completion_tokens, given with --token-limit")
    provider_set.add_argument("--request-timeout", type=int, metavar="SECONDS",
                              help="the seconds each live request waits, 300 when left out")
    provider_set.add_argument("--home", metavar="DIR",
                              help="the connections home, else the CONNECTIONS_HOME environment"
                              " variable, else ~/.workflow_connections")

    from connections.adapters import ADAPTERS

    adapt = commands.add_parser("adapt", help="turn a tool's files into a stream's input files")
    adapt_names = adapt.add_subparsers(dest="adapter", metavar="name", required=True)
    for adapter in ADAPTERS.values():
        one = adapt_names.add_parser(
            adapter.name,
            help=f"fill {', '.join(adapter.fills)} for the {adapter.stream} stream",
        )
        one.add_argument(
            "--out",
            required=True,
            metavar="DIR",
            help="the folder the input files and adapter_record.json are written to",
        )
        adapter.add_arguments(one)

    trigger = commands.add_parser("trigger", help="start the registered verification procedures")
    trigger_kinds = trigger.add_subparsers(dest="trigger", metavar="hook|make", required=True)
    trigger_kinds.add_parser(
        "hook",
        help="read one Claude Code hook input on standard input, mark procedures due after an AI "
        "edit, and start them at the end of the turn",
    )
    make = trigger_kinds.add_parser(
        "make",
        help="start each stale stream's command before a build, and never fail the make",
    )
    make.add_argument("--project", required=True, metavar="DIR", help="the project folder")
    make.add_argument(
        "--source",
        default="manuscript.md",
        metavar="FILE",
        help="the source text prose, citations, and build cover, from the project (default manuscript.md)",
    )
    make.add_argument(
        "--numbers",
        default="numbers.yml",
        metavar="FILE",
        help="the numbers file data covers, from the project (default numbers.yml)",
    )

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_usage(sys.stderr)
        return 2
    if args.command == "wrap":
        program = list(args.program)
        if program[:1] == ["--"]:
            program = program[1:]
        if not program:
            wrap.print_usage(sys.stderr)
            return 2
        from connections.wrap import run_wrapped

        return run_wrapped(program)
    if args.command == "serve" and args.server == "kb":
        from connections.mcp.kb_server import SERVER_NAME, SERVER_VERSION, tools
        from connections.mcp.protocol import serve as serve_lines

        stdin, stdout = _utf8_streams()
        serve_lines(SERVER_NAME, SERVER_VERSION, tools(args.index), stdin, stdout)
        return 0
    if args.command == "serve" and args.server == "audit":
        from connections.mcp.audit_server import SERVER_NAME, SERVER_VERSION, audit_home, tools
        from connections.mcp.protocol import serve as serve_lines

        stdin, stdout = _utf8_streams()
        serve_lines(SERVER_NAME, SERVER_VERSION, tools(audit_home(args.home)), stdin, stdout)
        return 0
    if args.command == "serve" and args.server == "events":
        from connections.mcp.events_server import SERVER_NAME, SERVER_VERSION, tools
        from connections.mcp.protocol import serve as serve_lines

        stdin, stdout = _utf8_streams()
        serve_lines(SERVER_NAME, SERVER_VERSION, tools(), stdin, stdout)
        return 0
    if args.command == "provider" and args.action == "show":
        from connections.provider import ProviderError, show

        try:
            sys.stdout.write(show())
        except ProviderError as error:
            print(f"connections provider: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "provider" and args.action == "set":
        if (args.token_limit is None) != (args.token_limit_field is None):
            provider_set.error("--token-limit and --token-limit-field are given together")
        from connections.provider import ProviderError, show, write_provider

        try:
            path = write_provider(args.base_url, args.model, args.second_model,
                                  args.token_limit, args.token_limit_field,
                                  request_timeout=args.request_timeout, home=args.home)
            sys.stdout.write(f"wrote {path}\n" + show(args.home))
        except ProviderError as error:
            print(f"connections provider: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "adapt":
        from connections.adapters import AdapterError, run_adapter

        try:
            run_adapter(args.adapter, args)
        except AdapterError as error:
            print(f"connections adapt: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "trigger" and args.trigger == "hook":
        return _trigger_hook()
    if args.command == "trigger" and args.trigger == "make":
        return _trigger_make(args)
    return 2


def _trigger_hook() -> int:
    """Answer one hook. Always 0, and nothing ever reaches standard error."""
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            from connections.triggers.hook import handle_hook

            text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
            said = handle_hook(text)
            if said:
                sys.stdout.write(said + "\n")
                sys.stdout.flush()
        except Exception:
            pass
    return 0


def _trigger_make(args) -> int:
    """Run the Make trigger. Always 0, so the make never stops on it."""
    try:
        from connections.triggers.make import make_trigger

        make_trigger(os.path.abspath(args.project), args.source, args.numbers)
    except Exception as error:
        print(f"connections trigger make: {error}", file=sys.stderr)
    return 0


def _utf8_streams():
    """Standard input and output read and written as UTF-8, as MCP over stdio is."""
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
    return stdin, stdout
