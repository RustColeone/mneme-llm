"""Who each person is to the companion: a role, and a closeness from 0 to 100 that moves with time spent together.

    role        set by the host, never by a model: creator (one per space, and the bond never fades), family,
                friend, acquaintance, or a role of the host's own. Each role keeps closeness within its band, so
                family never falls below 60 however much time passes, and an acquaintance never rises above 60
                until the host calls them a friend
    closeness   grows by one point on each day the person talks to the companion, up to the role's ceiling, and
                fades by one point for every 30 days without them, down to its floor (computed when read, and always
                within the role's band as the host has it now)
    weight      how much the person's words move the mood: 0.5 at closeness 0, 1.0 at 50, 1.5 at 100. A person
                with no role counts 1.0, as everyone did before roles existed
    telling     `line()` says it for the system prompt ("(Leo is your creator; you are very close.)")
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Callable, Mapping

from . import dates, text as texts
from .i18n import Speaks, Words, code, has, say
from .people import People, Resolves
from .store import Store

DAY = 86400.0


@dataclass(frozen=True)
class Role:
    """What a person can be to the companion. The built-in roles are named in `i18n`; a host's own role brings its
    names, by language (`Role("teacher", 40, 95, 70, names={"en": "your teacher", "zh": "你的老师"})`)."""
    key: str
    floor: float = 0.0      # closeness never fades below this
    ceiling: float = 100.0  # nor grows above this
    start: float = 50.0     # closeness when the role is given
    fades: bool = True      # does closeness fade without contact?
    unique: bool = False    # at most one person per space
    names: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not 0 <= self.floor <= self.start <= self.ceiling <= 100:
            raise ValueError(f"role {self.key}: needs 0 <= floor <= start <= ceiling <= 100")

    def label(self, lang: str | Words) -> str:
        if code(lang) in self.names:
            return self.names[code(lang)]
        key = f"role.{self.key}"
        return say(lang, key) if has(key, lang) else self.names.get("en", self.key)


ROLES = (Role("creator", floor=80, ceiling=100, start=100, fades=False, unique=True),
         Role("family", floor=60, ceiling=100, start=80),
         Role("friend", floor=20, ceiling=90, start=50),
         Role("acquaintance", floor=0, ceiling=60, start=20))
NEAR = ((80, "very_close"), (60, "close"), (40, "friendly"), (20, "distant"), (0, "stranger"))  # i18n near.<name>


@dataclass(frozen=True)
class Relationship:
    subject: str
    role: str
    closeness: float  # now, faded
    since: float      # when the role was given
    updated_at: float  # when closeness was last written (given, or a day of contact)


class Relations(Speaks, Resolves):
    def __init__(self, store: Store, space: str, *, roles: tuple[Role, ...] = ROLES, growth: float = 1.0,
                 fade_days: float = 30.0, zone: tzinfo | None = None, display_language: str | Words = "en",
                 people: People | None = None, clock: Callable[[], float] = time.time):
        self.store, self.space, self.roles = store, space, {role.key: role for role in roles}
        self.people = people
        self.growth, self.fade_days, self.zone = growth, fade_days, zone
        self.words, self.clock = Words.of(display_language), clock

    # ---- reading -------------------------------------------------------------------------------------
    def get(self, subject: str, now: float | None = None) -> Relationship | None:
        subject = self.who(subject)
        row = self.store.row("select * from relationships where space = ? and subject = ?", (self.space, subject))
        return self._of(row, self.clock() if now is None else now) if row is not None else None

    def all(self) -> list[Relationship]:
        """Everyone with a role, closest first."""
        now = self.clock()
        found = [self._of(row, now) for row in self.store.rows("select * from relationships where space = ?",
                                                                (self.space,))]
        return sorted(found, key=lambda relationship: (-relationship.closeness, relationship.subject))

    def weight(self, subject: str) -> float:
        """How much the person's words move the mood (1.0 for a person with no role)."""
        relationship = self.get(subject)
        return 1.0 if relationship is None else 0.5 + relationship.closeness / 100

    def line(self, subject: str, user_name: str | None = None) -> str:
        """Who the person is to the companion, for the system prompt ("" for a person with no role)."""
        relationship = self.get(subject)
        if relationship is None:
            return ""
        lang = self.words
        near = next(name for least, name in NEAR if round(relationship.closeness) >= least)
        return say(lang, "relation.line", who=user_name or subject, role=self._role(relationship.role).label(lang),
                   near=say(lang, f"near.{near}"))

    # ---- changing ------------------------------------------------------------------------------------
    def set(self, subject: str, role: str, *, closeness: float | None = None) -> Relationship:
        """Give a person a role (the host's call, never a model's). `closeness` defaults to the role's start, or to
        the person's present closeness when the role stays the same (then nothing changes: a host may say it at
        every start); it must lie within the role's band."""
        texts.required(subject, "subject")
        if role not in self.roles:
            raise ValueError(f"no role {role!r}; the roles are {', '.join(self.roles)}")
        kind = self.roles[role]
        with self.writing(subject) as subject:
            now = self.clock()
            present = self.get(subject, now)
            if closeness is None and present is not None and present.role == role:
                return present  # already so: the day's contact and the fading stay as they were
            if closeness is None:
                closeness = kind.start
            if isinstance(closeness, bool) or not isinstance(closeness, (int, float)) or not math.isfinite(closeness) \
                    or not kind.floor <= closeness <= kind.ceiling:
                raise ValueError(f"closeness for {role} is a number from {kind.floor:g} to {kind.ceiling:g}")
            if kind.unique:
                other = self.store.row("select subject from relationships where space = ? and role = ? and "
                                       "subject != ?", (self.space, role, subject))
                if other is not None:
                    raise ValueError(f"{other['subject']} is already the {role}; give them another role first")
            same = present is not None and present.role == role
            since = present.since if same else now
            updated = max(now, present.updated_at) if same else now  # (a clock set back moves no time back)
            self.store.execute(
                "insert or replace into relationships (space, subject, role, closeness, since, updated_at) values "
                "(?, ?, ?, ?, ?, ?)", (self.space, subject, role, float(closeness), since, updated))
        return Relationship(subject, role, float(closeness), since, updated)

    def seen(self, subject: str) -> Relationship | None:
        """A contact: the first one on a day (in the companion's zone) grows closeness by `growth`. A person with no
        role is left without one. A clock that went back changes nothing (time never moves backwards here)."""
        with self.writing(subject) as subject:
            now = self.clock()
            present = self.get(subject, now)
            if present is None or now <= present.updated_at:
                return present
            kind = self._role(present.role)
            closeness = present.closeness
            if dates.local(present.updated_at, self.zone).date() < dates.local(now, self.zone).date():
                closeness = max(closeness, min(closeness + self.growth, kind.ceiling))  # never lowered by a visit
            self.store.execute("update relationships set closeness = ?, updated_at = ? where space = ? and "
                               "subject = ?", (closeness, now, self.space, subject))
        return Relationship(subject, present.role, closeness, present.since, now)

    def remove(self, subject: str) -> bool:
        with self.writing(subject) as subject:
            return bool(self.store.execute("delete from relationships where space = ? and subject = ?",
                                           (self.space, subject)).rowcount)

    def join(self, old: str, new: str) -> None:
        """`old` is the person `new` now (`People.link`): of two relationships the closer is kept (the person's own
        when they are as close), since the earlier of the two days."""
        with self.store.transaction():
            now = self.clock()
            rows = {row["subject"]: row for row in self.store.rows(
                "select * from relationships where space = ? and subject in (?, ?)", (self.space, old, new))}
            if old not in rows:
                return
            self.store.execute("delete from relationships where space = ? and subject = ?", (self.space, old))
            kept = rows[old] if new not in rows or self._of(rows[old], now).closeness > \
                self._of(rows[new], now).closeness else rows[new]
            since = min(row["since"] for row in rows.values())
            self.store.execute(
                "insert or replace into relationships (space, subject, role, closeness, since, updated_at) values "
                "(?, ?, ?, ?, ?, ?)", (self.space, new, kept["role"], kept["closeness"], since, kept["updated_at"]))

    # ---- moving between files ------------------------------------------------------------------------
    def export_rows(self) -> dict:
        return {"relationships": [dict(row) for row in self.store.rows(
            "select * from relationships where space = ? order by rowid", (self.space,))]}

    def import_rows(self, rows=()) -> None:
        """Add exported relationships to this space, replacing a person's present one: closeness is kept within the
        role's band (0-100 for a role this host does not have), times are seconds, and a second holder of a
        one-person role (a second creator) is skipped."""
        now = self.clock()
        rows = [row for row in rows if isinstance(row, dict)]
        # one-person roles last, so who holds one does not depend on the order of the rows
        rows.sort(key=lambda row: self._role(row["role"]).unique if isinstance(row.get("role"), str) else False)
        with self.store.transaction():
            for row in rows:
                subject, role = row.get("subject"), row.get("role")
                if not isinstance(subject, str) or not subject.strip() or not isinstance(role, str) or \
                        not role.strip():
                    continue
                role = texts.clip(role, 40)
                kind = self._role(role)
                if kind.unique and self.store.row("select 1 from relationships where space = ? and role = ? and "
                                                  "subject != ?", (self.space, role, subject)) is not None:
                    continue
                closeness = _number(row.get("closeness"), kind.start, kind.floor, kind.ceiling)
                updated = dates.seconds(row.get("updated_at"))
                since = dates.seconds(row.get("since"))
                self.store.execute(
                    "insert or replace into relationships (space, subject, role, closeness, since, updated_at) "
                    "values (?, ?, ?, ?, ?, ?)", (self.space, subject, role, closeness,
                                                  now if since is None else min(now, since),
                                                  now if updated is None else min(now, updated)))

    # ---- inside --------------------------------------------------------------------------------------
    def _role(self, key: str) -> Role:
        """A role by its key; one this host does not know (from another project's export) has the widest band."""
        return self.roles.get(key) or Role(key)

    def _of(self, row, now: float) -> Relationship:
        kind = self._role(row["role"])
        closeness = row["closeness"]
        if kind.fades and self.fade_days > 0:
            closeness -= max(0.0, now - row["updated_at"]) / (self.fade_days * DAY)
        closeness = min(kind.ceiling, max(kind.floor, closeness))  # within the band, as the host has it now
        return Relationship(row["subject"], row["role"], closeness, row["since"], row["updated_at"])


def _number(value, default: float, low: float, high: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, value)) if math.isfinite(value) else default
