"""mneme-llm as tools a model can call, in every major API's format, with one dispatcher for all of them.

    tools = specs("openai")                      # chat completions (also DeepSeek, Qwen, vLLM, Ollama…)
    tools = specs("responses")                   # OpenAI responses API
    tools = specs("anthropic")                   # Claude messages API
    tools = specs("gemini")                      # Gemini function declarations
    reply = Toolbox(m, subject="discord:42").call(name, arguments)

The host decides who the conversation is with (`subject`); the model never chooses whose memory it writes,
except through the MCP server when it is deliberately run for many people at once.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .dates import when
from .memory import KINDS, LASTING

SPECS = [
    {"name": "remember",
     "description": ("Keep a note about the person you are talking with, so you still know it in later "
                     "conversations, whichever model you are. One fact or event per call, as a full sentence in "
                     "their language. For facts that can change, give a key (what it is about, never the value, "
                     "e.g. 'user.city', 'pet.name') and a newer note replaces the old one."),
     "parameters": {"type": "object", "properties": {
         "text": {"type": "string", "description": "The note: one sentence."},
         "kind": {"type": "string", "enum": list(KINDS),
                  "description": ("fact/preference: lasting; episode: something that happened; plan: something "
                                  "coming up; reflection: your own impression of them.")},
         "key": {"type": "string", "description": "Optional: what the note is about, like 'user.city'."},
         "importance": {"type": "integer", "minimum": 1, "maximum": 5,
                        "description": "1 trivial, 2 normal, 3 notable, 4 important, 5 core (always remembered)."},
         "date": {"type": "string", "description": "Optional: when it happened or will, YYYY-MM-DD."}},
         "required": ["text", "kind"]}},
    {"name": "recall",
     "description": "Look up what you remember about the person on a topic (memories already shown may repeat).",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words of the topic, in the language the notes were kept in."}},
         "required": ["query"]}},
    {"name": "forget",
     "description": "Remove a note that is wrong or that the person asked you to forget (by id or by key).",
     "parameters": {"type": "object", "properties": {
         "id": {"type": "integer", "description": "The note's number, as recall shows it."},
         "key": {"type": "string", "description": "Or the key of the note to remove."}}}},
    {"name": "mood",
     "description": "How you feel right now toward the person: your mood and strongest feelings.",
     "parameters": {"type": "object", "properties": {}}},
]

SUBJECT = {"type": "string", "description": "Whose memory: the person's id, like 'discord:42'."}


def specs(style: str = "openai", *, prefix: str = "", with_subject: bool = False,
          only: tuple[str, ...] | None = None) -> list[dict]:
    """The tool definitions in `style`: openai, responses, anthropic, gemini or mcp."""
    found = []
    for spec in SPECS:
        if only is not None and spec["name"] not in only:
            continue
        parameters = json.loads(json.dumps(spec["parameters"]))
        if with_subject:
            parameters["properties"]["subject"] = SUBJECT
            parameters.setdefault("required", []).append("subject")
        name, description = prefix + spec["name"], spec["description"]
        if style == "openai":
            found.append({"type": "function", "function": {"name": name, "description": description,
                                                           "parameters": parameters}})
        elif style == "responses":
            found.append({"type": "function", "name": name, "description": description, "parameters": parameters})
        elif style == "anthropic":
            found.append({"name": name, "description": description, "input_schema": parameters})
        elif style == "mcp":
            found.append({"name": name, "description": description, "inputSchema": parameters})
        elif style == "gemini":
            found.append({"name": name, "description": description, "parameters": _gemini(parameters)})
        else:
            raise ValueError("style is one of openai, responses, anthropic, gemini, mcp")
    return [{"function_declarations": found}] if style == "gemini" else found


def _gemini(schema: dict) -> dict:
    """Gemini's schema dialect has no minimum/maximum on integers in every version; keep the portable core."""
    clean = {key: value for key, value in schema.items() if key not in ("minimum", "maximum")}
    if "properties" in clean:
        clean["properties"] = {key: _gemini(value) for key, value in clean["properties"].items()}
    return clean


class Toolbox:
    """Runs the tools against one Mneme; `subject` is who the conversation is with."""

    def __init__(self, mneme, subject: str | None = None, *, prefix: str = "", source: str = "auto"):
        self.mneme, self.subject, self.prefix, self.source = mneme, subject, prefix, source

    def names(self) -> set[str]:
        return {self.prefix + spec["name"] for spec in SPECS}

    def call(self, name: str, arguments: dict | str | None = None, *, subject: str | None = None) -> str:
        """The tool's reply as text for the model; mistakes come back as text too, never as exceptions."""
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                return "Error: the arguments were not valid JSON."
        arguments = dict(arguments or {})
        who = subject or arguments.pop("subject", None) or self.subject
        if not who:
            return "Error: no subject (whose memory) was given."
        tool = name[len(self.prefix):] if name.startswith(self.prefix) else name
        try:
            handler = getattr(self, f"_{tool}")
        except AttributeError:
            return f"Error: there is no tool named {name}."
        try:
            return handler(str(who), arguments)
        except (TypeError, ValueError) as error:
            return f"Error: {error}"

    def _remember(self, subject: str, arguments: dict[str, Any]) -> str:
        happened = None
        if arguments.get("date"):
            happened = datetime.strptime(str(arguments["date"])[:10], "%Y-%m-%d").replace(hour=12).timestamp()
        outcome, note = self.mneme.memory.keep(
            subject, str(arguments.get("text", "")), kind=str(arguments.get("kind", "episode")),
            key=arguments.get("key") or None, importance=int(arguments.get("importance", 2)), happened_at=happened,
            source=self.source)
        if note is None:
            return ("Not kept: today's limit of everyday notes about them is reached. Only important notes "
                    "(importance 4 or 5) are kept until tomorrow.")
        return {"known": f"Already known (#{note.id}).", "replaced": f"Kept as #{note.id}, replacing the older note."
                }.get(outcome, f"Kept as #{note.id}.")

    def _recall(self, subject: str, arguments: dict[str, Any]) -> str:
        memory = self.mneme.memory
        found = memory.recall(subject, str(arguments.get("query", "")), important=0, recent=0)
        if not found.chosen:
            return "Nothing remembered on that."
        now, lines = memory.clock(), []
        for item in found.chosen:
            note = item.note
            date = "" if note.kind in LASTING else f" [{when(note.happened_at, now, memory.zone, memory.lang)}]"
            lines.append(f"#{note.id}{date} {note.text}")
        return "\n".join(lines)

    def _forget(self, subject: str, arguments: dict[str, Any]) -> str:
        if arguments.get("id") is not None:
            count = self.mneme.memory.forget(subject, id=int(arguments["id"]))
        elif arguments.get("key"):
            count = self.mneme.memory.forget(subject, key=str(arguments["key"]))
        else:
            return "Error: give the id or the key of the note to forget."
        return f"Forgot {count} note." if count == 1 else ("No such note." if not count else f"Forgot {count} notes.")

    def _mood(self, subject: str, arguments: dict[str, Any]) -> str:
        return self.mneme.mood.describe(subject)
