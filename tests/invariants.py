"""What must hold in any mneme-llm file, whatever was done to it: the rules of docs/FORMAT.md, checked row by row.

`check(store)` returns a list of the broken rules (empty when the file is sound), so a stress test can say what
broke instead of only that something did.
"""

import json
from collections import Counter, defaultdict

from mneme_llm import text as texts
from mneme_llm.config import ORIGINS, check as check_setting
from mneme_llm.episodes import cost
from mneme_llm.relations import ROLES


def check(store) -> list[str]:
    problems = []
    rows = store.rows("select * from memories")
    ids = {row["id"] for row in rows}
    live = [row for row in rows if row["superseded_by"] is None and row["deleted_at"] is None]

    keys = Counter((row["space"], row["subject"], row["key"]) for row in live if row["key"] is not None)
    problems += [f"{count} live notes for key {key}" for key, count in keys.items() if count > 1]

    texts_seen = defaultdict(list)
    for row in live:
        texts_seen[(row["space"], row["subject"], texts.fold(row["text"]))].append(row["key"])
    for where, found in texts_seen.items():
        if len(found) > 1 and (None in found or len(set(found)) < len(found)):
            problems.append(f"the same live text twice: {where} with keys {found}")

    for row in rows:
        text = row["text"]
        if "\n" in text or texts.CONTROL.search(text) or texts.SURROGATE.search(text) or len(text) > 500:
            problems.append(f"note #{row['id']} is not one clean line of at most 500 characters")
        if texts.blank(text):
            problems.append(f"note #{row['id']} has no text")
        if row["folded"] != texts.fold(text):
            problems.append(f"note #{row['id']} has a folded text that is not its own")
        if row["superseded_by"] is not None and row["superseded_by"] not in ids and row["superseded_by"] != -1:
            problems.append(f"note #{row['id']} points to a missing note")
        if not 1 <= row["importance"] <= 5 or not -1 <= row["feeling"] <= 1:
            problems.append(f"note #{row['id']} has values out of range")
        if not 0 <= row["happened_at"] < 32503680000:
            problems.append(f"note #{row['id']} has an impossible time")

    # A note hidden as a duplicate (on import) has its twin: another note of the subject with the same words.
    for row in rows:
        if row["deleted_at"] is not None and (row["source"] or "").endswith(" duplicate"):
            twins = [other for other in rows if other["id"] != row["id"] and other["space"] == row["space"] and
                     other["subject"] == row["subject"] and texts.fold(other["text"]) == texts.fold(row["text"])]
            if not twins:
                problems.append(f"note #{row['id']} was hidden as a duplicate of nothing")

    # The term index holds exactly the terms of every live note, and names no note that is gone.
    indexed = defaultdict(set)
    for row in store.rows("select * from note_terms"):
        indexed[row["memory_id"]].add(row["term"])
    problems += [f"the term index names missing note #{id}" for id in indexed if id not in ids]
    for row in live:
        terms = texts.terms(" ".join([row["text"], (row["key"] or "").replace(".", " "), row["gloss"] or ""]))
        if indexed.get(row["id"], set()) != set(terms):
            problems.append(f"note #{row['id']} is indexed by other terms than its own")

    vectors = store.rows("select * from vectors")
    problems += [f"a vector of missing note #{row['memory_id']}" for row in vectors if row["memory_id"] not in ids]

    for row in store.rows("select * from moods"):
        if not 0 <= row["value"] <= 100:
            problems.append(f"mood of {row['subject']} out of range: {row['value']}")

    # Relationships: closeness within the role's band, and one creator per space at most.
    bands = {role.key: (role.floor, role.ceiling) for role in ROLES}
    relationships = store.rows("select * from relationships")
    for row in relationships:
        low, high = bands.get(row["role"], (0, 100))
        if not low <= row["closeness"] <= high or not row["role"].strip():
            problems.append(f"{row['subject']}: closeness {row['closeness']} off the band of {row['role']!r}")
    creators = Counter(row["space"] for row in relationships if row["role"] == "creator")
    problems += [f"{count} creators in space {space}" for space, count in creators.items() if count > 1]

    # Aliases: a name on one line, 40 characters at most, never blank.
    for row in store.rows("select * from aliases"):
        alias = row["alias"]
        if not alias.strip() or len(alias) > 40 or "\n" in alias:
            problems.append(f"{row['subject']}: alias {alias!r} is not one short line")

    # Links: one step deep (a person is never linked on), never to itself, and nothing kept under a linked subject.
    links = {(row["space"], row["subject"]): row["person"] for row in store.rows("select * from people")}
    for (space, subject), person in links.items():
        if person == subject or (space, person) in links:
            problems.append(f"{subject} is linked to {person}, which is not a person's own subject")
        for table in ("memories", "profiles", "moods", "mood_events", "relationships", "aliases", "note_terms",
                      "recalls", "episodes", "episode_terms", "surfaces", "first_prompts"):
            if store.row(f"select 1 from {table} where space = ? and subject = ?", (space, subject)) is not None:
                problems.append(f"{table} keeps rows under {subject}, which is linked to {person}")

    # Exchanges: their day is the talking day of when they were said, their tokens what they cost; a surface starts at
    # an exchange that was kept.
    top = store.row("select coalesce(max(id), 0) as id from episodes")["id"]
    for row in store.rows("select id, day, tokens, lines from episodes"):
        if not isinstance(row["day"], int) or row["tokens"] < cost(json.loads(row["lines"])) - 1e-6:
            problems.append(f"exchange #{row['id']} has the wrong day or tokens")
    for row in store.rows("select * from surfaces"):
        if not 0 <= row["start_id"] <= top:
            problems.append(f"the surface of {row['subject']} starts at #{row['start_id']}, past every exchange")

    # The config: every known key's value passes its rule, from a known origin.
    for row in store.rows("select * from config"):
        if row["origin"] not in ORIGINS:
            problems.append(f"config {row['key']} has origin {row['origin']!r}")
        try:
            check_setting(row["key"], json.loads(row["value"]))
        except ValueError as error:
            if "no such setting" not in str(error):
                problems.append(f"config {row['key']} does not pass: {error}")

    result = store.row("pragma integrity_check")[0]
    if result != "ok":
        problems.append(f"integrity_check: {result}")
    return problems
