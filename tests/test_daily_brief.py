"""Unit tests - run with:  python -m unittest discover -s tests"""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_brief as db  # noqa: E402

NOW = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)
CONFIG = db.load_config(db.APP_DIR / "config.json")

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Ransomware attack hits hospital network</title>
<description><![CDATA[<p>A cyber attack disrupted &amp; delayed care.</p>]]></description>
<link>https://example.com/a</link><pubDate>Sat, 14 Nov 2026 06:00:00 GMT</pubDate></item>
<item><title>Local bakery wins award</title><link>https://example.com/b</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Hospital network hit by ransomware attack</title>
<link rel="alternate" href="https://example.org/x"/><summary type="html">&lt;b&gt;Systems offline&lt;/b&gt;</summary>
<updated>2026-11-14T05:00:00Z</updated></entry></feed>"""


def make_story(title, source, summary="", hours_ago=1):
    return db.Story(title=title, summary=summary, link="https://example.com/" + source,
                    source=source, published=NOW - timedelta(hours=hours_ago), tokens=db.tokenize(title))


class TermMatching(unittest.TestCase):
    def test_whole_words_and_plurals(self):
        self.assertTrue(db.compile_term("protest").search("protests spread"))
        self.assertTrue(db.compile_term("attack").search("attacked overnight"))
        self.assertFalse(db.compile_term("ban").search("urban banking"))
        self.assertFalse(db.compile_term("ai").search("said again"))
        self.assertTrue(db.compile_term("cyber*").search("a cyberattack"))
        self.assertTrue(db.compile_term("artificial intelligence").search("new artificial intelligence law"))


class Parsing(unittest.TestCase):
    def test_rss(self):
        stories = db.parse_feed("RSS", RSS)
        self.assertEqual(len(stories), 2)
        self.assertEqual(stories[0].summary, "A cyber attack disrupted & delayed care.")
        self.assertEqual(stories[0].published, datetime(2026, 11, 14, 6, tzinfo=timezone.utc))

    def test_atom(self):
        (story,) = db.parse_feed("Atom", ATOM)
        self.assertEqual(story.link, "https://example.org/x")
        self.assertEqual(story.summary, "Systems offline")
        self.assertIsNotNone(story.published)

    def test_entities_refused(self):
        with self.assertRaises(ValueError):
            db.parse_feed("Bad", b'<!DOCTYPE x [<!ENTITY a "aaaa">]><rss/>')

    def test_unsafe_link_dropped(self):
        self.assertEqual(db.safe_link("javascript:alert(1)"), "")


class Analysis(unittest.TestCase):
    def run_analysis(self, stories, history=None):
        return db.analyse(stories, CONFIG, history or {}, NOW, {"A": "ok (1 items)"})

    def test_clusters_same_event_across_sources(self):
        stories = db.parse_feed("RSS", RSS) + db.parse_feed("Atom", ATOM)
        brief, _ = self.run_analysis(stories)
        self.assertEqual(brief.issue_count, 1)  # bakery filtered, two ransomware reports merged
        issue = brief.issues[0]
        self.assertEqual(issue.sources, ["Atom", "RSS"])
        self.assertEqual(issue.kind, "Threat")
        self.assertLessEqual(issue.score, 10)

    def test_old_stories_excluded(self):
        brief, _ = self.run_analysis([make_story("Election protest grows", "X", hours_ago=100)])
        self.assertEqual(brief.items_matched, 0)

    def test_every_perspective_represented(self):
        places = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel",
                  "India", "Juliet", "Kilo", "Lima"]
        stories = [make_story(f"{p} conflict: deadly attack", f"S{i}") for i, p in enumerate(places)]
        stories.append(make_story("Debate over religious heritage", "Culture desk"))
        brief, _ = self.run_analysis(stories)
        self.assertEqual(len(brief.issues), 10)
        self.assertIn("Cultural", {t for i in brief.issues for t in i.themes})

    def test_momentum_and_history(self):
        history = {f"2026-11-{d:02d}": {"ransomware": 0} for d in range(8, 14)}
        stories = [make_story("Ransomware hits council", "A"), make_story("Ransomware gang leaks files", "B"),
                   make_story("Port ransomware outage", "C")]
        brief, new_history = self.run_analysis(stories, history)
        self.assertIn("ransomware", brief.rising_terms)
        self.assertIn("2026-11-14", new_history)


class Output(unittest.TestCase):
    def test_html_is_escaped_and_files_written(self):
        story = make_story("<script>alert(1)</script> cyber breach", "Evil")
        brief, _ = db.analyse([story], CONFIG, {}, NOW, {"Evil": "ok"})
        page = db.render_html(brief, [])
        self.assertNotIn("<script>alert", page)
        with tempfile.TemporaryDirectory() as tmp:
            index = db.write_outputs(brief, Path(tmp), 30)
            self.assertTrue(index.is_file())
            self.assertTrue((Path(tmp) / "latest.json").is_file())

    def test_version_file_matches(self):
        self.assertEqual((db.APP_DIR / "VERSION").read_text().strip(), db.__version__)


if __name__ == "__main__":
    unittest.main()
