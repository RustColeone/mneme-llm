"""The `mneme-llm` command: look inside a memory file, fix it by hand, move it, or serve it over MCP.

    mneme-llm --db companion.db --space whale_chan notes discord:42
    mneme-llm recall discord:42 "考试" --explain        mneme-llm relate discord:42 creator
    mneme-llm export > backup.json        mneme-llm import backup.json --into other_space
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import KINDS, Mneme, __version__
from . import text as texts
from .dates import noon, stamp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mneme-llm", description="Memory and mood for AI companions, for any LLM.")
    parser.add_argument("--db", default=os.environ.get("MNEME_LLM_DB", "mneme.db"), help="the memory file")
    parser.add_argument("--space", default=os.environ.get("MNEME_LLM_SPACE", "default"), help="whose memory (an app)")
    parser.add_argument("--display-language", default=os.environ.get("MNEME_LLM_DISPLAY_LANGUAGE", "en"),
                        choices=("en", "zh"), help="the language of what is shown (headers, dates, moods)")
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
    find.add_argument("--meaning", action="store_true",
                      help="use the meaning tiers too (OpenAI embeddings with OPENAI_API_KEY)")

    context = commands.add_parser("context", help="the block a system prompt would get")
    context.add_argument("subject")
    context.add_argument("query", nargs="?", default="")
    context.add_argument("--user-name", help="how the header names the person")

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

    recalls = commands.add_parser("recalls", help="what was recalled for a subject lately, and why")
    recalls.add_argument("subject")
    recalls.add_argument("--limit", type=int, default=10)

    profile = commands.add_parser("profile", help="show or set a subject's profile card")
    profile.add_argument("subject")
    profile.add_argument("text", nargs="?")

    relate = commands.add_parser("relate", help="show or set who a subject is to the companion")
    relate.add_argument("subject")
    relate.add_argument("role", nargs="?", help="creator, family, friend or acquaintance")
    relate.add_argument("--closeness", type=float, help="0-100, within the role's band (its start otherwise)")
    relate.add_argument("--remove", action="store_true", help="take the role away")

    commands.add_parser("relations", help="everyone with a role, closest first")

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

    micro = commands.add_parser("micro", help="what the micro decision model has learned")
    micro.add_argument("--reset", action="store_true", help="forget it all (it relearns from Luna)")

    serve = commands.add_parser("mcp", help="serve the tools over MCP (stdio)")
    serve.add_argument("--subject", help="bind every call to this person")

    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure") and (sys.stdout.encoding or "").lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")  # notes are often Chinese; some consoles default to cp1252
    if args.command == "tools":
        from .tools import specs
        print(json.dumps(specs(args.style), ensure_ascii=False, indent=2))
        return 0
    space = args.space
    if args.command == "import":  # into --into, or back into the space it came from
        with open(args.file, encoding="utf-8") as handle:
            args.data = json.load(handle)
        space = args.into or str(args.data.get("space") or args.space)
    meaning = args.command == "mcp" or getattr(args, "meaning", False)
    m = Mneme(args.db, space, display_language=args.display_language, luna=False, embed=meaning,
              memory_language=None)
    if (m.store.meta("terms_version") or "").endswith("+jieba") and not texts.use_jieba():
        print("note: this file's search terms were made with jieba, which is not installed here; they will be "
              "rebuilt without it (pip install mneme-llm[jieba])", file=sys.stderr)
    try:
        return _run(m, args)
    finally:
        m.close()


def _run(m: Mneme, args) -> int:
    memory = m.memory
    if args.command == "remember":
        happened = noon(args.date, memory.zone) if args.date else None
        if args.date and happened is None:
            print("--date is a day from 1970 to 2999, written YYYY-MM-DD", file=sys.stderr)
            return 2
        outcome, note = memory.keep(args.subject, args.text, kind=args.kind, key=args.key,
                                    importance=args.importance, happened_at=happened, source="cli")
        print(f"{outcome} #{note.id}" if note else outcome)
    elif args.command == "recall":
        if args.meaning:
            from .providers import run
            found = run(memory.arecall(args.subject, args.query, log=False))
        else:
            found = memory.recall(args.subject, args.query, log=False)
        print(found.explain() if args.explain else "\n".join(f"#{r.note.id} {r.note.text}" for r in found.chosen))
    elif args.command == "context":
        print(m.prompt(args.subject, args.query, user_name=args.user_name, mark=False) or "(nothing to say)")
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
            print("this deletes every note, the profile, the mood and the role of the subject; add --yes",
                  file=sys.stderr)
            return 2
        print(f"erased {m.erase(args.subject)} notes")
    elif args.command == "subjects":
        print("\n".join(memory.subjects()))
    elif args.command == "recalls":
        for entry in memory.recalls(args.subject, args.limit):
            chosen = ", ".join(f"#{id} ({why})" for id, why in entry["chosen"])
            print(f"{stamp(entry['at'])} {entry['query']!r}: {chosen or '(nothing)'}")
    elif args.command == "profile":
        if args.text is not None:
            memory.set_profile(args.subject, args.text)
        print(memory.profile(args.subject) or "(no profile)")
    elif args.command == "relate":
        if args.remove:
            print("removed" if m.relations.remove(args.subject) else "(no role)")
            return 0
        if args.role:
            try:
                m.relate(args.subject, args.role, closeness=args.closeness)
            except ValueError as error:
                print(error, file=sys.stderr)
                return 2
        found = m.relations.get(args.subject)
        print(_relationship(found) if found else "(no role)")
    elif args.command == "relations":
        print("\n".join(_relationship(found) for found in m.relations.all()) or "(nobody has a role)")
    elif args.command == "mood":
        if args.reset:
            m.mood.reset(args.subject)
        print(m.mood.describe(args.subject))
        for event in m.mood.timeline(args.subject, 15):
            print(f"  {stamp(event.at)} {event.value:5.1f} ({event.delta:+.1f}) [{event.source}/{event.judge}] "
                  f"{event.reason}")
    elif args.command == "export":
        text = json.dumps(m.export_data(), ensure_ascii=False, indent=1)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text)
        else:
            print(text)
    elif args.command == "import":
        print(f"imported {m.import_data(args.data)} notes into {m.space}")
    elif args.command == "micro":
        try:
            from .decide.micro import Micro
        except ImportError:
            print("(the micro model is not installed)")
            return 0
        if args.reset:
            Micro(m.store).reset()
        rows = Micro.saved(m.store)
        for row in rows:
            print(f"{row['question']}: {row['examples']} lessons, saved {stamp(row['updated_at'])}")
        if not rows:
            print("(nothing learned yet)")
    elif args.command == "mcp":
        from .mcp import serve
        serve(m, args.subject)
    return 0


def _relationship(found) -> str:
    return f"{found.subject}: {found.role}, closeness {found.closeness:.0f} (since {stamp(found.since)})"


if __name__ == "__main__":
    sys.exit(main())
