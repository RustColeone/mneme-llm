import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mneme_llm import Mneme, links as links_module
from mneme_llm.links import FLOOR, MOST, retention
from tests.test_episodes import DAY, Clock, companion, embedder, talk


def ids(found) -> list[int]:
    return sorted(episode.id for episode in found)


def pairs(m, subject="u") -> set[tuple[int, int]]:
    return {(link.a, link.b) for link in m.episodes.links.all(subject)}


class BornTests(unittest.TestCase):
    """A link is born only from what already happens: an exchange reminding her of one, two coming to mind together, or
    an exchange said while another was on her mind."""

    def setUp(self):
        self.m, self.clock = companion(embed=embedder())
        self.e = self.m.episodes

    def keep(self, said, subject="u"):
        self.clock.now += 60
        return asyncio.run(self.e.akeep(subject, [("Leo", said)]))

    def test_an_exchange_is_linked_to_the_earlier_one_it_reminds_her_of(self):
        for number in range(16):  # enough pairs for the person's spread (`SPREAD_PAIRS`)
            self.keep(f"topic{number} and topic{number + 3}")
        cat = self.keep("my cat Mochi")
        kitten = self.keep("a kitten")
        self.assertIn((cat.id, kitten.id), pairs(self.m))
        link = next(link for link in self.e.links.all("u") if (link.a, link.b) == (cat.id, kitten.id))
        self.assertGreater(link.closeness, 0.9)
        self.assertEqual(link.uses, 0)

    def test_what_comes_to_mind_together_is_linked_and_to_what_is_said_next(self):
        cat = self.keep("my cat Mochi")
        kitten = self.keep("Mochi the kitten")
        self.clock.now += 60
        self.assertEqual(ids(asyncio.run(self.e.alook("u", "my cat", use=True))), [cat.id, kitten.id])
        self.assertIn((cat.id, kitten.id), pairs(self.m))
        said = self.keep("she sleeps all day")  # said while those were on her mind
        self.assertTrue({(cat.id, said.id), (kitten.id, said.id)} <= pairs(self.m))

    def test_a_look_that_is_not_hers_links_nothing(self):
        self.keep("my cat Mochi")
        self.keep("Mochi the kitten")
        self.e.look("u", "my cat")
        self.keep("she sleeps all day")
        self.assertEqual(pairs(self.m), set())

    def test_what_was_on_her_mind_long_ago_is_not_linked_to_what_is_said_now(self):
        cat = self.keep("my cat Mochi")
        self.e.look("u", "my cat", use=True)
        self.clock.now += 3600
        said = self.keep("the weather")
        self.assertNotIn((cat.id, said.id), pairs(self.m))

    def test_a_link_never_joins_two_people(self):
        cat = self.keep("my cat Mochi", "u")
        self.e.look("u", "my cat", use=True)
        other = self.keep("hello", "someone else")
        self.assertNotIn((cat.id, other.id), pairs(self.m, "u") | pairs(self.m, "someone else"))
        self.assertEqual(self.e.links.count("someone else"), 0)

    def test_an_exchange_keeps_its_heaviest_links(self):
        hub = self.keep("my cat Mochi")
        others = [self.keep(f"topic{number}") for number in range(MOST + 4)]
        self.e.links.born("u", [(hub.id, other.id, 0.0) for other in others[:4]], self.clock())
        self.e.links.used("u", followed=[(hub.id, other.id) for other in others[:4]], at=self.clock() + 2 * DAY)
        self.e.links.born("u", [(hub.id, other.id, 0.0) for other in others[4:]], self.clock())
        mine = [link for link in self.e.links.all("u") if hub.id in (link.a, link.b)]
        self.assertEqual(len(mine), MOST)
        self.assertTrue(all((hub.id, other.id) in pairs(self.m) for other in others[:4]))  # (used: heavier)


class FadingTests(unittest.TestCase):
    def setUp(self):
        self.m, self.clock = companion()
        self.e = self.m.episodes
        self.one = self.e.keep("u", [("Leo", "one")])
        self.two = self.e.keep("u", [("Leo", "two")])
        self.e.links.born("u", [(self.one.id, self.two.id, 0.5)], self.clock())

    def link(self):
        return self.e.links.all("u")[0]

    def test_a_link_fades_over_the_days_the_person_talks_and_a_use_renews_it(self):
        self.assertEqual(self.link().strength, 1.0)
        talk(self.m, self.clock, 10)
        faded = self.link().strength
        self.assertAlmostEqual(faded, retention(0, 30.0, 10, list(range(11))))  # (ten talking days since)
        self.assertLess(faded, 1.0)
        self.assertEqual(self.e.links.used("u", together=[self.one.id, self.two.id]), 1)
        link = self.link()
        self.assertEqual((link.strength, link.uses), (1.0, 1))
        self.assertGreater(link.stability, 30.0)
        self.assertEqual(self.e.links.used("u", together=[self.one.id, self.two.id]), 0)  # (once a talking day)

    def test_time_without_talking_fades_it_as_one_day_does(self):
        one_day = self.e.links.all("u", at=self.clock() + DAY)[0].strength
        self.clock.now += 400 * DAY  # (today counts: they are talking now)
        self.assertEqual(self.link().strength, one_day)
        self.assertLess(one_day, 1.0)

    def test_she_lets_go_of_a_faded_link_when_she_sleeps(self):
        talk(self.m, self.clock, 80)  # (the first exchange of each talking day: she has slept)
        self.assertGreater(self.link().strength, FLOOR)
        talk(self.m, self.clock, 10)
        self.assertEqual(self.e.links.count("u"), 0)  # (R e^(−90/30) is under the floor)

    def test_sleep_lets_go_of_a_link_to_an_exchange_gone(self):
        self.m.store.execute("delete from episodes where id = ?", (self.two.id,))  # (as a program without links would)
        self.assertEqual(self.e.links.sleep("u"), 1)


class LookTests(unittest.TestCase):
    def setUp(self):
        self.m, self.clock = companion(embed=embedder())
        self.e = self.m.episodes
        self.cat = asyncio.run(self.e.akeep("u", [("Leo", "my cat Mochi")]))
        self.exam = asyncio.run(self.e.akeep("u", [("Leo", "the physics exam")]))
        self.e.links.born("u", [(self.cat.id, self.exam.id, 0.0)], self.clock())

    def look(self, **options):
        brought = {}
        found = asyncio.run(self.e.alook("u", "a kitten", brought=brought, **options))
        return ids(found), brought

    def test_a_look_follows_no_link_unless_asked(self):
        self.assertEqual(self.look(), ([self.cat.id], {}))
        self.assertEqual(self.look(follow=1), ([self.cat.id], {}))  # (the exam is far under the bar)

    def test_a_look_follows_a_link_to_one_within_reach_of_its_bar(self):
        self.assertEqual(self.look(follow=1, lift=1.0), ([self.cat.id, self.exam.id], {self.exam.id: self.cat.id}))

    def test_what_a_link_brings_takes_the_place_of_the_weakest_within_the_budget(self):
        budget = max(len(self.e.shown(self.cat)), len(self.e.shown(self.exam))) + 2  # (room for one)
        found, brought = self.look(follow=1, lift=1.0, budget=budget)
        self.assertEqual((found, brought), ([self.exam.id], {self.exam.id: self.cat.id}))

    def test_following_a_link_uses_it(self):
        self.clock.now += DAY
        self.look(follow=1, lift=1.0, use=True)
        self.assertEqual(self.e.links.all("u")[0].uses, 1)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.m, self.clock = companion()
        self.e = self.m.episodes
        self.a = self.e.keep("u", [("Leo", "one")])
        self.b = self.e.keep("u", [("Leo", "two")])
        self.c = self.e.keep("u", [("Leo", "three")])
        self.e.links.born("u", [(self.a.id, self.b.id, 0.0), (self.b.id, self.c.id, 0.0)], self.clock())

    def test_forgetting_an_exchange_takes_its_links(self):
        self.e.forget("u", self.b.id)
        self.assertEqual(self.e.links.count("u"), 0)

    def test_erasing_a_person_takes_their_links(self):
        self.e.erase("u")
        self.assertEqual(self.e.links.count(), 0)

    def test_two_subjects_joined_keep_their_links(self):
        self.m.link("u", "leo")
        self.assertEqual(self.e.links.count("leo"), 2)
        self.assertEqual(self.e.links.count("u"), 0)


class SettingTests(unittest.TestCase):
    def test_her_own_look_grows_links_and_follows_none_as_it_ships(self):
        m, clock = companion(embed=embedder())
        self.assertEqual(m.said_follow, 0)
        asyncio.run(m.episodes.akeep("u", [("Leo", "my cat Mochi")]))
        asyncio.run(m.episodes.akeep("u", [("Leo", "Mochi the kitten")]))
        asyncio.run(m.alook("u", "my cat"))
        self.assertEqual(m.episodes.links.count("u"), 1)
        m.change({"memory.said_follow": 2})
        self.assertEqual(m.said_follow, 2)
        with self.assertRaises(ValueError):
            m.change({"memory.said_follow": 21})


class FileTests(unittest.TestCase):
    def test_a_file_of_this_schema_made_before_links_gets_their_table(self):
        path = Path(tempfile.mkdtemp()) / "her.db"
        Mneme(str(path), "t", memory_language=None).close()
        db = sqlite3.connect(path)
        db.execute("drop table links")
        db.commit()
        db.close()
        m = Mneme(str(path), "t", memory_language=None, clock=Clock())
        one, two = m.episodes.keep("u", [("Leo", "one")]), m.episodes.keep("u", [("Leo", "two")])
        self.assertEqual(m.episodes.links.born("u", [(one.id, two.id, 0.0)], m.episodes.clock()), 1)
        m.close()

    def test_the_constants_are_where_the_docs_say(self):
        self.assertEqual((links_module.DAYS, links_module.MOST, links_module.TOP, links_module.FOLLOW),
                         (30.0, 8, 3, 0))


if __name__ == "__main__":
    unittest.main()
