"""A companion's config: its name and languages, its memory, mood and relationship settings, its roles and
feelings, the instructions it gives models and the sentences it shows. Kept in its database, per space, so the
companion carries them wherever the file goes.

    first open   a space with no config takes the built-in defaults, with a config file (TOML) over them
    later        the database's copy is used, whatever file is given; it changes by `set`, `apply` (a file) and
                 `load_defaults` (this version's defaults, for every key or some), never by itself: `newer_defaults`
                 lists the keys a later version improved
    in code      an argument given to `Mneme(...)` wins for that process, and is not stored

Keys are flat: `companion.name`, `mood.threshold`, `roles`, `prompts.note_writer`, `messages.zh.notes.header`.
Every value is checked when it is set or applied (a file is applied whole or not at all); a stored value that no
longer passes (the file edited by hand) is passed over for the default and reported.
"""

from __future__ import annotations

import json
import math
import re
import time
import tomllib
from dataclasses import asdict, fields
from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import text as texts
from .i18n import MESSAGES, placeholders
from .mood import EMOTIONS, Emotion, MoodSettings
from .prompts import PROMPTS
from .relations import ROLES, Role
from .store import Store, dumps

ORIGINS = ("default", "file", "set", "import")


class _Stored:
    """The default of a `Mneme` argument that comes from the companion's config in its database."""

    def __repr__(self) -> str:
        return "STORED"


STORED = _Stored()
SECTIONS = ("companion", "memory", "mood", "relations", "prompts")  # tables of plain keys
WORD = re.compile(r"[a-z][a-z0-9_-]{0,39}")
LANGUAGE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?")
OPEN_KEYS = ("emotion.", "cue.", "role.")  # sentences for a feeling or a role of the companion's own
OFFSET = re.compile(r"UTC(?:([+-])(\d{1,2})(?::?(\d{2}))?)?")


def _defaults() -> dict[str, Any]:
    mood = MoodSettings()
    found: dict[str, Any] = {
        "companion.name": "the assistant", "companion.display_language": "en",
        "companion.memory_language": "English", "companion.zone": "",
        "memory.half_life_days": 30.0, "memory.daily_quota": 8, "memory.max_notes": 50_000,
        "memory.semantic_window": 5000, "memory.said_days": 30.0, "memory.said_budget": 6000,
        "memory.said_cut": 0.08, "memory.said_cut_faded": 0.16,
        **{f"mood.{f.name}": _plain(getattr(mood, f.name)) for f in fields(MoodSettings) if f.name != "emotions"},
        "relations.growth": 1.0, "relations.fade_days": 30.0,
        "roles": [_role_row(role) for role in ROLES],
        "emotions": [{"key": e.key, "lowers": e.lowers, "names": dict(e.names)} for e in EMOTIONS],
    }
    found.update({f"prompts.{name}": text for name, text in PROMPTS.items()})
    for lang, table in MESSAGES.items():
        found.update({f"messages.{lang}.{key}": text for key, text in table.items()})
    return found


def _plain(value):
    if isinstance(value, frozenset):
        return sorted(value)
    return dict(value) if isinstance(value, Mapping) else value


def _role_row(role: Role) -> dict:
    row = asdict(role)
    row["names"] = dict(role.names)
    return row


DEFAULTS = _defaults()


# ---- checking one value -----------------------------------------------------------------------------
def check(key: str, value: Any) -> Any:
    """`value` as `key` keeps it, or ValueError saying what is wrong."""
    rule = _rule(key)
    if rule is None:
        raise ValueError(f"{key}: no such setting")
    try:
        return rule(key, value)
    except (TypeError, OverflowError, RecursionError) as error:  # a value no rule foresaw is a wrong value too
        raise ValueError(f"{key}: {error}") from error


def _rule(key: str):
    if key.startswith("messages."):
        return _message if _message_parts(key) else None
    if key.startswith("prompts."):
        return _prompt if key in DEFAULTS else None
    return RULES.get(key)


def _text(limit: int, empty: bool = False):
    def rule(key, value):
        if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) \
                or texts.SURROGATE.search(value):
            raise ValueError(f"{key}: text of at most {limit} characters" + ("" if empty else ", not empty"))
        return value
    return rule


def _number(low: float, high: float, integer: bool = False):
    def rule(key, value):
        try:  # (an integer too large for a float is out of range like any other)
            finite = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or not low <= value <= high or (integer and value != int(value)):
            raise ValueError(f"{key}: {'a whole number' if integer else 'a number'} from {low:g} to {high:g}")
        return int(value) if integer else float(value)
    return rule


def _one_of(*choices: str):
    def rule(key, value):
        if value not in choices:
            raise ValueError(f"{key}: one of {', '.join(choices)}")
        return value
    return rule


def _numbers(low: float, high: float):
    def rule(key, value):
        if not isinstance(value, Mapping):
            raise ValueError(f"{key}: a table of names and numbers")
        number = _number(low, high)
        return {_word(f"{key} name", name): number(f"{key}.{name}", amount) for name, amount in value.items()}
    return rule


def _words(key, value):
    if not isinstance(value, list):
        raise ValueError(f"{key}: a list of words")
    return sorted({_word(key, item) for item in value})


def _word(key, value) -> str:
    if not isinstance(value, str) or not WORD.fullmatch(value):
        raise ValueError(f"{key}: {value!r} is not a word (lowercase letters, digits, _ and -, at most 40)")
    return value


def _names(key, value) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{key}: a table of names by language")
    found = {}
    for lang, name in value.items():
        if not isinstance(lang, str) or not LANGUAGE.fullmatch(lang):
            raise ValueError(f"{key}: {lang!r} is not a language code (en, zh, ja, pt-BR…)")
        found[lang] = _text(80)(f"{key}.{lang}", name)
    return found


def _zone(key, value):
    _text(60, empty=True)(key, value)
    zone_of(value)
    return value


def _roles(key, value):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key}: a list of roles, at least one")
    found, seen = [], set()
    for index, row in enumerate(value):
        where = f"{key}[{index}]"
        if not isinstance(row, Mapping) or set(row) - {"key", "floor", "ceiling", "start", "fades", "unique", "names"}:
            raise ValueError(f"{where}: a table of key, floor, ceiling, start, fades, unique and names")
        name = _word(f"{where}.key", row.get("key"))
        if name in seen:
            raise ValueError(f"{where}: role {name} given twice")
        seen.add(name)
        clean = {"key": name, "names": _names(f"{where}.names", row.get("names", {}))}
        for field_name in ("floor", "ceiling", "start"):
            if field_name in row:
                clean[field_name] = _number(0, 100)(f"{where}.{field_name}", row[field_name])
        for field_name in ("fades", "unique"):
            if field_name in row:
                if not isinstance(row[field_name], bool):
                    raise ValueError(f"{where}.{field_name}: true or false")
                clean[field_name] = row[field_name]
        found.append(_role_row(Role(**clean)))  # (Role checks its band)
    return found


def _emotions(key, value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError(f"{key}: a list of 1 to 20 feelings")
    found, seen = [], set()
    for index, row in enumerate(value):
        where = f"{key}[{index}]"
        if not isinstance(row, Mapping) or set(row) - {"key", "lowers", "names"}:
            raise ValueError(f"{where}: a table of key, lowers and names")
        name = _word(f"{where}.key", row.get("key"))
        if name in seen or name == "none":
            raise ValueError(f"{where}: feeling {name} given twice (or named none)")
        seen.add(name)
        lowers = row.get("lowers", False)
        if not isinstance(lowers, bool):
            raise ValueError(f"{where}.lowers: true or false")
        found.append({"key": name, "lowers": lowers, "names": _names(f"{where}.names", row.get("names", {}))})
    return found


def _prompt(key, value):
    _text(20_000)(key, value)
    _placeholders(key, value, placeholders(DEFAULTS[key]))
    return value


def _message_parts(key: str) -> tuple[str, str] | None:
    parts = key.split(".", 2)
    if len(parts) != 3 or not LANGUAGE.fullmatch(parts[1]):
        return None
    message = parts[2]
    known = message in MESSAGES["en"] or (message.startswith(OPEN_KEYS) and WORD.fullmatch(message.split(".", 1)[1]))
    return (parts[1], message) if known else None


def _message(key, value):
    _text(2000, empty=True)(key, value)  # (a separator may be a space; an empty sentence is the default's)
    _, message = _message_parts(key)
    _placeholders(key, value, placeholders(MESSAGES["en"].get(message, "")))
    return value


def _placeholders(key: str, value: str, allowed: set[str]) -> None:
    unknown = placeholders(value) - allowed
    if unknown:
        offer = ", ".join(f"{{{name}}}" for name in sorted(allowed)) or "none"
        raise ValueError(f"{key}: no placeholder {', '.join(f'{{{name}}}' for name in sorted(unknown))} here "
                         f"(it may use {offer})")


RULES = {
    "companion.name": _text(80), "companion.display_language": lambda key, value: _language(key, value),
    "companion.memory_language": _text(40, empty=True), "companion.zone": _zone,
    "memory.half_life_days": _number(0.01, 100_000), "memory.daily_quota": _number(0, 10_000, integer=True),
    "memory.max_notes": _number(10, 10_000_000, integer=True),
    "memory.semantic_window": _number(10, 1_000_000, integer=True),
    "memory.said_days": _number(0.01, 100_000), "memory.said_budget": _number(0, 200_000, integer=True),
    "memory.said_cut": _number(-1, 1), "memory.said_cut_faded": _number(-1, 1),
    "mood.baseline": _number(0, 100), "mood.floor": _number(0, 100), "mood.ceiling": _number(0, 100),
    "mood.mood_half_life_h": _number(0.01, 100_000), "mood.emotion_half_life_min": _number(0.01, 1_000_000),
    "mood.step": _number(0, 50), "mood.gain": _number(0, 100), "mood.threshold": _number(0, 1),
    "mood.thresholds": _numbers(0, 1), "mood.tell": _one_of("event", "mood", "off"), "mood.weights": _numbers(0, 10),
    "mood.skip": _words,
    "relations.growth": _number(0, 100), "relations.fade_days": _number(0, 1_000_000),
    "roles": _roles, "emotions": _emotions,
}


def _language(key, value):
    if not isinstance(value, str) or not LANGUAGE.fullmatch(value):
        raise ValueError(f"{key}: a language code (en, zh, ja, pt-BR…)")
    return value


def zone_of(name: str) -> tzinfo | None:
    """A zone from its name: "" for the machine's, "UTC+8" or "UTC-05:30" for a fixed offset, or an IANA name."""
    if not name:
        return None
    offset = OFFSET.fullmatch(name)
    if offset:
        sign, hours, minutes = offset.groups()
        delta = timedelta(hours=int(hours or 0), minutes=int(minutes or 0))
        if int(minutes or 0) > 59 or delta > timedelta(hours=14):
            raise ValueError(f"companion.zone: {name} is more than 14 hours from UTC")
        return timezone(-delta if sign == "-" else delta)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"companion.zone: no time zone {name!r} (an IANA name such as Asia/Shanghai, or UTC+8; on "
                         "Windows, IANA names need `pip install tzdata`)") from error


def _together(values: Mapping[str, Any]) -> None:
    """The rules between keys."""
    low, base, high = (values[f"mood.{name}"] for name in ("floor", "baseline", "ceiling"))
    if not low <= base <= high:
        raise ValueError(f"mood: floor ({low:g}) <= baseline ({base:g}) <= ceiling ({high:g})")


# ---- files ------------------------------------------------------------------------------------------
def load(source: str | Path | Mapping) -> dict[str, Any]:
    """A config file (a TOML path) or an already read table, as flat keys; ValueError names a wrong key."""
    if isinstance(source, Mapping):
        table = source
    else:
        try:
            with open(source, "rb") as handle:
                table = tomllib.load(handle)
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"{source}: not valid TOML ({error})") from error
    flat: dict[str, Any] = {}
    for name, value in table.items():
        if name in SECTIONS:
            if not isinstance(value, Mapping):
                raise ValueError(f"{name}: a table")
            flat.update({f"{name}.{key}": item for key, item in value.items()})
        elif name in ("roles", "emotions"):
            flat[name] = value
        elif name == "messages":
            if not isinstance(value, Mapping) or not all(isinstance(items, Mapping) for items in value.values()):
                raise ValueError("messages: a table per language")
            for lang, items in value.items():  # `notes.header = …` unquoted is a TOML table: the same key
                flat.update({f"messages.{lang}.{key}": text for key, text in _dotted(items)})
        else:
            raise ValueError(f"{name}: no such section (the sections are {', '.join(SECTIONS)}, roles, emotions and "
                             "messages)")
    return flat


def _dotted(table: Mapping, prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key, value in table.items():
        if isinstance(value, Mapping):
            yield from _dotted(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}", value


HEADER = """# mneme-llm config. A database takes it once, when it first meets this companion (space); from then on the
# database keeps its own copy: `mneme-llm config show`, `set`, `apply`, `defaults`, `check`.
# Placeholders are {name}; any other brace is kept as it is.
"""


def to_toml(values: Mapping[str, Any], header: str = HEADER) -> str:
    """Flat keys as a config file (what `load` reads back)."""
    lines = [header.rstrip("\n")] if header else []
    for section in ("companion", "memory", "mood", "relations"):
        items = {key.split(".", 1)[1]: value for key, value in values.items() if key.startswith(section + ".")}
        if items:
            lines += ["", f"[{section}]", *(f"{_key(name)} = {_value(value)}" for name, value in items.items())]
    for name in ("roles", "emotions"):
        for row in values.get(name, []):
            lines += ["", f"[[{name}]]", *(f"{_key(key)} = {_value(value)}" for key, value in row.items())]
    prompts = {key.split(".", 1)[1]: value for key, value in values.items() if key.startswith("prompts.")}
    if prompts:
        lines += ["", "[prompts]", *(f"{_key(name)} = {_value(value)}" for name, value in prompts.items())]
    languages: dict[str, dict[str, str]] = {}
    for key, value in values.items():
        if key.startswith("messages."):
            _, lang, message = key.split(".", 2)
            languages.setdefault(lang, {})[message] = value
    for lang, items in languages.items():
        lines += ["", f"[messages.{_key(lang)}]", *(f"{_key(key)} = {_value(value)}" for key, value in items.items())]
    return "\n".join(lines) + "\n"


def _key(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else json.dumps(name, ensure_ascii=False)


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{_key(str(key))} = {_value(item)}" for key, item in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise TypeError(f"no TOML for {type(value).__name__}")


def _string(text: str) -> str:
    """A TOML string: one line as JSON writes it, more as a multi-line string, escaped where TOML needs it."""
    if "\n" not in text:
        return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007f")
    body = text.replace("\\", "\\\\")
    body = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", lambda found: f"\\u{ord(found.group()):04x}", body)
    # a quote before another quote, or at the very end, is escaped: no run of quotes can close the string early
    body = re.sub(r'"(?="|\Z)', r'\\"', body)
    return '"""\n' + body + '"""'


# ---- the stored config ------------------------------------------------------------------------------
BAND = ("mood.floor", "mood.baseline", "mood.ceiling")


class Config:
    """The config of one space in one file. Every call reads the file (a key takes microseconds, the whole config
    about a millisecond), so it is never out of date with what any process wrote, or with a transaction rolled back;
    a running `Mneme` reads it once, when it opens."""

    def __init__(self, store: Store, space: str, clock=time.time):
        self.store, self.space, self.clock = store, space, clock

    # ---- reading ---------------------------------------------------------------------------------
    def _stored(self) -> tuple[dict[str, dict], dict[str, str], list[str]]:
        """The valid rows by key, the stored keys whose value does not pass (and why), and the keys this version
        does not know, as the file has them now."""
        rows, invalid, unknown = {}, {}, []
        for row in self.store.rows("select * from config where space = ?", (self.space,)):
            key = row["key"]
            if _rule(key) is None:
                unknown.append(key)
                continue
            try:
                value = check(key, json.loads(row["value"]))
            except (ValueError, RecursionError) as error:
                invalid[key] = str(error)
                continue
            rows[key] = {"value": value, "origin": row["origin"], "updated_at": row["updated_at"]}
        try:
            _together({**DEFAULTS, **{key: row["value"] for key, row in rows.items()}})
        except ValueError as error:  # a band spoiled by hand: the mood's defaults instead
            for key in BAND:
                invalid[key] = str(error)
                rows.pop(key, None)
        return rows, invalid, sorted(unknown)

    @property
    def empty(self) -> bool:
        return self.store.row("select 1 from config where space = ? limit 1", (self.space,)) is None

    @property
    def invalid(self) -> dict[str, str]:
        """Stored keys whose value does not pass, and why (the default is used for them)."""
        return self._stored()[1]

    @property
    def unknown(self) -> list[str]:
        """Stored keys this version does not know (kept, not used)."""
        return self._stored()[2]

    def get(self, key: str) -> Any:
        """A key's value: stored, else this version's default."""
        if key in BAND:
            return self.values()[key]  # (one of three that must agree)
        if _rule(key) is None:
            raise KeyError(key)
        row = self.store.row("select value from config where space = ? and key = ?", (self.space, key))
        if row is not None:
            try:
                return check(key, json.loads(row["value"]))
            except (ValueError, RecursionError):
                pass
        return DEFAULTS.get(key)

    def values(self) -> dict[str, Any]:
        """Every key's value (the stored ones over this version's defaults)."""
        return {**DEFAULTS, **{key: row["value"] for key, row in self._stored()[0].items()}}

    def rows(self) -> list[dict]:
        return [{"key": key, **row} for key, row in sorted(self._stored()[0].items())]

    def newer_defaults(self) -> list[str]:
        """Keys stored from a default that this version has changed, and keys this version adds."""
        rows, invalid, _ = self._stored()
        changed = [key for key, row in rows.items() if row["origin"] == "default" and key in DEFAULTS
                   and row["value"] != DEFAULTS[key]]
        return sorted(changed + [key for key in DEFAULTS if key not in rows and key not in invalid])

    def prompts(self) -> dict[str, str]:
        values = self.values()
        return {name: values[f"prompts.{name}"] for name in PROMPTS}

    def messages(self) -> dict[str, dict[str, str]]:
        found: dict[str, dict[str, str]] = {}
        for key, value in self.values().items():
            if key.startswith("messages."):
                _, lang, message = key.split(".", 2)
                found.setdefault(lang, {})[message] = value
        return found

    def mood_settings(self) -> MoodSettings:
        values = self.values()
        found = {f.name: values[f"mood.{f.name}"] for f in fields(MoodSettings) if f.name != "emotions"}
        found["skip"] = frozenset(found["skip"])
        emotions = tuple(Emotion(row["key"], row["lowers"], row["names"]) for row in values["emotions"])
        return MoodSettings(**found, emotions=emotions)

    def roles(self) -> tuple[Role, ...]:
        return tuple(Role(**row) for row in self.get("roles"))

    def zone(self) -> tzinfo | None:
        return zone_of(self.get("companion.zone"))

    def to_toml(self, prefix: str = "") -> str:
        return to_toml({key: value for key, value in self.values().items() if key.startswith(prefix)})

    # ---- changing --------------------------------------------------------------------------------
    def seed(self, source: str | Path | Mapping | None = None) -> bool:
        """A space's first config: the defaults, with `source` (a config file or table) over them. Only for a space
        that has none (for any other, `source` is not even read); returns whether it was seeded."""
        with self.store.transaction():
            if not self.empty:
                return False
            found = load(source) if source is not None else {}
            self._write(DEFAULTS, "default")
            self._apply(found, "file")
        return True

    def apply(self, source: str | Path | Mapping, *, origin: str = "file") -> int:
        """Write every key a config file (or table) gives, all of them checked first; returns how many."""
        if origin not in ORIGINS:
            raise ValueError(f"origin: one of {', '.join(ORIGINS)}")
        found = load(source)
        with self.store.transaction():
            return self._apply(found, origin)

    def set(self, key: str, value: Any) -> None:
        with self.store.transaction():
            self._apply({key: value}, "set")

    def load_defaults(self, keys: Iterable[str] | None = None) -> int:
        """This version's defaults for `keys` (every key when None); returns how many were written. Loading only
        some of the mood's floor, baseline and ceiling must leave them in order."""
        keys = list(DEFAULTS) if keys is None else list(keys)
        missing = [key for key in keys if key not in DEFAULTS]
        if missing:
            raise ValueError(f"no default for {', '.join(missing)}")
        with self.store.transaction():
            found = {key: DEFAULTS[key] for key in keys}
            _together({**self.values(), **found})
            self._write(found, "default")
        return len(keys)

    def _apply(self, found: Mapping[str, Any], origin: str) -> int:
        """Check and write, inside the caller's transaction (so the keys it is checked against are the file's)."""
        checked = {key: check(key, value) for key, value in found.items()}
        _together({**self.values(), **checked})
        self._write(checked, origin)
        return len(checked)

    def _write(self, values: Mapping[str, Any], origin: str) -> None:
        now = self.clock()
        for key, value in values.items():
            self.store.execute("insert or replace into config (space, key, value, origin, updated_at) values "
                               "(?, ?, ?, ?, ?)", (self.space, key, dumps(value), origin, now))

    # ---- moving between files --------------------------------------------------------------------
    def export_rows(self) -> dict:
        return {"config": [{"key": row["key"], "value": row["value"], "origin": row["origin"]} for row in self.rows()]}

    def import_rows(self, rows=()) -> int:
        """Apply an export's config, each valid row (an unknown key or a wrong value is skipped; the mood's floor,
        baseline and ceiling go in together or not at all); returns how many keys were applied."""
        found = {row["key"]: row.get("value") for row in rows
                 if isinstance(row, Mapping) and isinstance(row.get("key"), str)}
        groups = [{key: value} for key, value in found.items() if key not in BAND]
        groups.append({key: value for key, value in found.items() if key in BAND})
        applied = 0
        with self.store.transaction():
            for group in groups:
                try:
                    with self.store.transaction():  # (a savepoint: a group that fails leaves nothing)
                        applied += self._apply(group, "import")
                except (ValueError, RecursionError):
                    continue
        return applied
