"""The `mneme-llm` command: look inside a memory file, fix it by hand, move it, or serve it over MCP.

    mneme-llm --db companion.db --space whale_chan notes discord:42
    mneme-llm recall discord:42 "考试" --explain
    mneme-llm export > backup.json        mneme-llm import backup.json --into other_space
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from . import KINDS, Mneme, __version__
from .dates import stamp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mneme-llm", description="Memory and mood for AI companions, for any LLM.")
    parser.add_argument("--db", default=os.environ.get("MNEME_LLM_DB", "mneme.db"), help="the memory file")
    parser.add_argument("--space", default=os.environ.get("MNEME_LLM_SPACE", "default"), help="whose memory (an app)")
    parser.add_argument("--lang", default=os.environ.get("MNEME_LLM_LANG", "en"), choices=("en", "zh"))
    parser.add_argument("--version", action="version", version=f"mneme-llm {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("remember", help="keep a note")
    add.add_argument("subject")
    add.add_argument("text")
    add.add_argument("--kind", default="fact", choices=KINDS)
    add.add_argument("--key")
    add.add_argument("--importance", type=int, default=3)
    add.add_argument("--date", help="when it happened, YYYY-MM-DD")

    find = commands.add_parser("recall", help="what would be recalled for a query")
    find.add_argument("subject")
    find.add_argument("query")
    find.add_argument("--explain", action="store_true", help="also show what was skipped and why")

    context = commands.add_parser("context", help="the block a system prompt would get")
    context.add_argument("subject")
    context.add_argument("query", nargs="?", default="")
    context.add_argument("--name")

    listing = commands.add_parser("notes", help="every live note of a subject")
    listing.add_argument("subject")
    listing.add_argument("--kind", choices=KINDS)

    history = commands.add_parser("history", help="every version a key has had")
    history.add_argument("subject")
    history.add_argument("key")

    forget = commands.add_parser("forget", help="remove a note")
    forget.add_argument("subject")
    which = forget.add_mutually_exclusive_group(required=True)
    which.add_argument("--id", type=int)
    which.add_argument("--key")

    erase = commands.add_parser("erase", help="delete everything about a subject, for good")
    erase.add_argument("subject")
    erase.add_argument("--yes", action="store_true", help="really do it")

    commands.add_parser("subjects", help="who this space remembers")

    profile = commands.add_parser("profile", help="show or set a subject's profile card")
    profile.add_argument("subject")
    profile.add_argument("text", nargs="?")

    mood = commands.add_parser("mood", help="a subject's mood and its timeline")
    mood.add_argument("subject")
    mood.add_argument("--reset", action="store_true")

    export = commands.add_parser("export", help="the whole space as JSON")
    export.add_argument("--out", help="a file (stdout otherwise)")

    load = commands.add_parser("import", help="add an export to this file")
    load.add_argument("file")
    load.add_argument("--into", help="a space other than the export's own")

    tools = commands.add_parser("tools", help="print the tool definitions for a model API")
    tools.add_argument("--style", default="openai", choices=("openai", "responses", "anthropic", "gemini", "mcp"))

    commands.add_parser("micro", help="what the micro decision model has learned")

    serve = commands.add_parser("mcp", help="serve the tools over MCP (stdio)")
    serve.add_argument("--subject", help="bind every call to this person")

    args = parser.parse_args(argv)
    if args.command == "tools":
        from .tools import specs
        print(json.dumps(specs(args.style), ensure_ascii=False, indent=2))
        return 0
    space = args.space
    if args.command == "import" and args.into:
        space = args.into
    m = Mneme(args.db, space, lang=args.lang, luna=False)
    try:
        return _run(m, args)
    finally:
        m.close()


def _run(m: Mneme, args) -> int:
    memory = m.memory
    if args.command == "remember":
        happened = datetime.strptime(args.date, "%Y-%m-%d").replace(hour=12).timestamp() if args.date else None
        outcome, note = memory.keep(args.subject, args.text, kind=args.kind, key=args.key,
                                    importance=args.importance, happened_at=happened, source="cli")
        print(f"{outcome} #{note.id}" if note else outcome)
    elif args.command == "recall":
        found = memory.recall(args.subject, args.query, log=False)
        print(found.explain() if args.explain else "\n".join(f"#{r.note.id} {r.note.text}" for r in found.chosen))
    elif args.command == "context":
        print(memory.context(args.subject, args.query, name=args.name) or "(nothing to say)")
    elif args.command == "notes":
        for note in memory.notes(args.subject, kinds=[args.kind] if args.kind else None):
            key = f" {note.key}" if note.key else ""
            print(f"#{note.id} {stamp(note.happened_at)} {note.kind}{key} ({note.importance}) {note.text}")
    elif args.command == "history":
        for note in memory.history(args.subject, args.key):
            state = "removed" if note.deleted_at else ("replaced" if note.superseded_by else "live")
            print(f"#{note.id} {stamp(note.created_at)} {state}: {note.text}")
    elif args.command == "forget":
        print(f"forgot {memory.forget(args.subject, id=args.id, key=args.key)}")
    elif args.command == "erase":
        if not args.yes:
            print("this deletes every note, the profile and the mood of the subject; add --yes", file=sys.stderr)
            return 2
        print(f"erased {memory.erase(args.subject)} notes")
    elif args.command == "subjects":
        print("\n".join(memory.subjects()))
    elif args.command == "profile":
        if args.text is not None:
            memory.set_profile(args.subject, args.text)
        print(memory.profile(args.subject) or "(no profile)")
    elif args.command == "mood":
        if args.reset:
            m.mood.reset(args.subject)
        print(m.mood.describe(args.subject))
        for event in m.mood.timeline(args.subject, 15):
            print(f"  {stamp(event.at)} {event.value:5.1f} ({event.delta:+.1f}) [{event.source}/{event.judge}] "
                  f"{event.reason}")
    elif args.command == "export":
        text = json.dumps(m.export(), ensure_ascii=False, indent=1)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text)
        else:
            print(text)
    elif args.command == "import":
        with open(args.file, encoding="utf-8") as handle:
            print(f"imported {m.import_(json.load(handle))} notes")
    elif args.command == "micro":
        rows = m.store.rows("select question, examples, updated_at from micro_models order by question")
        for row in rows:
            print(f"{row['question']}: {row['examples']} lessons, saved {stamp(row['updated_at'])}")
        if not rows:
            print("(nothing learned yet)")
    elif args.command == "mcp":
        from .mcp import serve
        serve(m, args.subject)
    return 0


if __name__ == "__main__":
    sys.exit(main())
