"""Tier 3 of meaning: one language for all notes, written by your own chat model.

Notes are kept in whatever language they were written in, and people ask in theirs. This tier has the chat
model you already use write each note once more in one language of your choice (English by default: most
models know it best), stored beside the original as its `gloss`; and when a query is written in another script
(Chinese against English, or the reverse), it translates the query first. Word matching then runs on both,
so "我的猫" finds "Has a cat named 年糕". Glosses are written once per note (in batches); translated queries are
remembered for the session, so a repeated question costs nothing.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Mapping, Sequence

from .. import text as texts
from ..i18n import fill
from ..prompts import PROMPTS
from ..providers import Complete, Rest, ask, json_in

# The script each language is written in, as `text.script` names it; a language not listed is taken as Latin.
SCRIPTS = {
    "han": ("chinese", "mandarin", "cantonese", "中文", "汉语", "漢語", "普通话", "粤语"),
    "kana": ("japanese", "日本語"),
    "hangul": ("korean", "한국어"),
    "cyrillic": ("russian", "ukrainian", "bulgarian", "serbian", "belarusian", "kazakh", "kyrgyz", "macedonian",
                 "mongolian", "tajik", "русский", "українська"),
    "greek": ("greek", "ελληνικά"),
    "armenian": ("armenian", "հայերեն"),
    "georgian": ("georgian", "ქართული"),
    "hebrew": ("hebrew", "yiddish", "עברית"),
    "arabic": ("arabic", "persian", "farsi", "dari", "urdu", "pashto", "kurdish", "uyghur", "العربية", "فارسی",
               "اردو"),
    "thaana": ("dhivehi",),
    "ethiopic": ("amharic", "tigrinya", "አማርኛ"),
    "devanagari": ("hindi", "marathi", "nepali", "sanskrit", "हिन्दी", "मराठी"),
    "bengali": ("bengali", "bangla", "assamese", "বাংলা"),
    "gurmukhi": ("punjabi", "ਪੰਜਾਬੀ"),
    "gujarati": ("gujarati", "ગુજરાતી"),
    "oriya": ("odia", "oriya", "ଓଡ଼ିଆ"),
    "tamil": ("tamil", "தமிழ்"),
    "telugu": ("telugu", "తెలుగు"),
    "kannada": ("kannada", "ಕನ್ನಡ"),
    "malayalam": ("malayalam", "മലയാളം"),
    "sinhala": ("sinhala", "sinhalese", "සිංහල"),
    "thai": ("thai", "ไทย"),
    "lao": ("lao", "ລາວ"),
    "khmer": ("khmer", "cambodian", "ខ្មែរ"),
    "myanmar": ("burmese", "myanmar", "မြန်မာ"),
    "tibetan": ("tibetan", "བོད་ཡིག"),
}
LANGUAGE_SCRIPTS = {language: script for script, languages in SCRIPTS.items() for language in languages}
MIXED = 0.2  # a text with at least this share of letters in other scripts is translated (people mix languages)

class Miscounted(ValueError):
    """The chat model answered a batch of notes with the wrong number of glosses (or with no list at all)."""


class Unify:
    name = "unify"
    GLOSS_BATCH = 16  # notes per gloss request
    STRIKE_GAP_S = 600.0  # a note's failures alone count this far apart when nothing else succeeds meanwhile

    def __init__(self, complete: Complete | None, language: str = "English", *, cache: int = 256,
                 prompts: Mapping[str, str] = PROMPTS):
        self.complete, self.language, self.size, self.prompts = complete, language, cache, prompts
        self.script = LANGUAGE_SCRIPTS.get(language.strip().lower(), "latin")
        self.rest = Rest()
        self.calls = 0
        self.answered = 0  # requests that came back right: a note's failures count only while others succeed
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._caps: dict[int, int] = {}  # note id → the largest batch it is asked in, after a batch failed
        self._strikes: dict[int, tuple[int, int, float]] = {}  # note id → (failures alone, `answered`, when)

    def ready(self, complete: Complete | None = None) -> bool:
        """Whether this tier can be asked now: there is a chat model (given at start or for this call), and it is
        not resting. Without a model it is simply not asked; that is no failure."""
        return (complete or self.complete) is not None and self.rest.up()

    def needs_translation(self, text: str) -> bool:
        """Whether at least a fifth of the text's letters are in another script than the unifying language's (so a
        query mixing two languages is translated too)."""
        shares = texts.scripts(text)
        return bool(shares) and 1 - shares.get(self.script, 0.0) >= MIXED

    async def _ask(self, system: str, user: str, complete: Complete | None) -> str:
        self.calls += 1
        return (await ask(complete or self.complete, system, user)).strip()

    async def gloss(self, notes: Sequence[str], *, complete: Complete | None = None) -> list[str]:
        """Each note in the unifying language, in one request (a note already in it is kept as it is)."""
        glosses = [note if not self.needs_translation(note) else "" for note in notes]
        todo = [index for index, gloss in enumerate(glosses) if not gloss]
        if todo:
            listing = "\n".join(f"{number}. {notes[index]}" for number, index in enumerate(todo, 1))
            system = fill(self.prompts["gloss"], language=self.language)
            items = json_in(await self._ask(system, listing, complete), "[")
            if not isinstance(items, list) or len(items) != len(todo):
                raise Miscounted(f"expected {len(todo)} glosses, got {len(items) if isinstance(items, list) else 0}")
            for index, item in zip(todo, items):  # an empty or missing gloss keeps the note itself
                gloss = texts.clip(item, 500) if isinstance(item, str) else ""
                glosses[index] = gloss or notes[index]
        return glosses

    async def glosses(self, notes, *, complete: Complete | None = None, calls: int = 2) -> dict[int, str]:
        """Glosses for the notes that have none, by note id: the most important and newest first, in at most
        `calls` requests, so a recall never waits on more (later recalls write the rest). A batch that fails (the
        wrong number of glosses, a reply that is no list, an error) is split in half, and its notes are asked in
        the smaller batches from then on, so a note the model won't gloss is soon asked alone; alone, a wrong
        answer, or a third error, leaves it its own text; errors count while the tier answers other requests, or
        ten minutes apart (a short outage is not the note's fault). An error also rests this tier."""
        missing = sorted((note for note in notes if not note.gloss), key=lambda note: (-note.importance,
                                                                                       -note.created_at))

        def cap(note) -> int:
            return self._caps.get(note.id, self.GLOSS_BATCH)
        queue: list[list] = []
        for note in missing:  # no batch larger than one of its notes allows
            if queue and len(queue[-1]) < min(cap(item) for item in queue[-1] + [note]):
                queue[-1].append(note)
            else:
                queue.append([note])
        written: dict[int, str] = {}
        while queue and calls > 0 and self.ready(complete):
            batch, calls = queue.pop(0), calls - 1
            try:
                found = await self.gloss([note.text for note in batch], complete=complete)
                self.answered += 1
            except Exception as error:
                if not isinstance(error, Miscounted):
                    self.rest.failed(error)
                if len(batch) > 1:
                    for note in batch:
                        self._caps[note.id] = len(batch) // 2
                    queue[:0] = [batch[:len(batch) // 2], batch[len(batch) // 2:]]
                    continue
                if not isinstance(error, Miscounted) and self._strike(batch[0].id) < 3:
                    continue
                found = [batch[0].text]  # a note it can't gloss keeps its own text, and isn't asked again
            for note, gloss in zip(batch, found):
                written[note.id] = gloss
                self._caps.pop(note.id, None)
                self._strikes.pop(note.id, None)
        return written

    def forget_failures(self, ids) -> None:
        """Ask these notes again from scratch (`Mneme.aregloss`): their batch limits and failures are dropped."""
        for id in ids:
            self._caps.pop(id, None)
            self._strikes.pop(id, None)

    def _strike(self, id: int) -> int:
        """One more failure of this note asked alone: counted when the tier answered something since the last one,
        or when the last one was long enough ago."""
        count, seen, at = self._strikes.get(id, (0, -1, 0.0))
        now = time.monotonic()
        if seen != self.answered or now - at >= self.STRIKE_GAP_S:
            count, seen, at = count + 1, self.answered, now
        self._strikes[id] = (count, seen, at)
        return count

    async def translate(self, query: str, *, complete: Complete | None = None) -> str:
        key = query.strip()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        system = fill(self.prompts["translate"], language=self.language)
        translated = texts.clip(await self._ask(system, key, complete), 1000)
        self._cache[key] = translated
        while len(self._cache) > self.size:
            self._cache.popitem(last=False)
        return translated

    def report(self) -> dict:
        return {"language": self.language, "calls": self.calls}
