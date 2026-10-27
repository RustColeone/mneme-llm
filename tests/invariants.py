"""What must hold in any mneme-llm file, whatever was done to it: the rules of docs/FORMAT.md, checked row by row.

`check(store)` returns a list of the broken rules (empty when the file is sound), so a stress test can say what
broke instead of only that something did.
"""

import json
from collections import Counter, defaultdict

from mneme_llm import text as texts
from mneme_llm.meaning import unpack
from mneme_llm.config import ORIGINS, check as check_setting
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
        if row["folded"] is not None and row["folded"] != texts.fold(text):
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

    # The term index holds exactly the cached terms of each note, and nothing for a note without them.
    indexed = defaultdict(set)
    for row in store.rows("select * from note_terms"):
        indexed[row["memory_id"]].add(row["term"])
    by_id = {row["id"]: row for row in rows}
    for id, terms in indexed.items():
        row = by_id.get(id)
        if row is None:
            problems.append(f"the term index names missing note #{id}")
        elif row["terms"] is None or set(row["terms"].split()) != terms:
            problems.append(f"note #{id} is indexed by other terms than its own")
    problems += [f"note #{row['id']} has terms but no index rows" for row in rows
                 if row["terms"] and row["id"] not in indexed]

    vectors = store.rows("select * from vectors")
    problems += [f"a vector of missing note #{row['memory_id']}" for row in vectors if row["memory_id"] not in ids]

    # The word centroids: every count and mean is exactly what the taught vectors add up to.
    for embedder in {row["embedder"] for row in vectors} | {row["embedder"] for row in
                                                            store.rows("select distinct embedder from meaning_terms")}:
        taught = [row for row in vectors if row["embedder"] == embedder and row["taught"] is not None]
        learned = int(store.meta(f"meaning_texts:{embedder}") or 0)
        if learned != len(taught):
            problems.append(f"{embedder}: meaning_texts {learned} but {len(taught)} vectors taught")
        expected = defaultdict(list)
        for row in taught:
            for term in row["taught"].split():
                expected[term].append(unpack(row["vector"]))
        stored = {row["term"]: row for row in store.rows("select * from meaning_terms where embedder = ?",
                                                         (embedder,))}
        if set(stored) != set(expected):
            problems.append(f"{embedder}: terms differ, only stored {sorted(set(stored) - set(expected))[:5]}, "
                            f"only taught {sorted(set(expected) - set(stored))[:5]}")
        for term in set(stored) & set(expected):
            vectors_of = expected[term]
            if stored[term]["count"] != len(vectors_of):
                problems.append(f"{embedder}: {term!r} counted {stored[term]['count']}, taught {len(vectors_of)}")
                continue
            mean = [sum(values) / len(vectors_of) for values in zip(*vectors_of)]
            if any(abs(a - b) > 1e-3 for a, b in zip(unpack(stored[term]["vector"]), mean)):
                problems.append(f"{embedder}: the mean of {term!r} drifted")

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
