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


class Advancements(unittest.TestCase):
    def run_adv(self, stories, history=None):
        return db.analyse_advances(stories, CONFIG, history or {}, NOW, {})

    def test_launch_ranked_and_threats_and_deals_excluded(self):
        stories = [
            make_story("Startup unveils world's first solid-state battery for electric cars", "TechCrunch",
                       "The new battery charges in ten minutes."),
            make_story("First solid-state battery for electric cars unveiled by startup", "The Verge"),
            make_story("Ransomware attack hits chip maker", "The Register"),
            make_story("Best laptop deals this week", "The Verge"),
        ]
        section, counts = self.run_adv(stories)
        self.assertEqual(section.issue_count, 1)
        top = section.issues[0]
        self.assertEqual(top.mode, "advance")
        self.assertEqual(top.kind, "Launch")
        self.assertEqual(len(top.sources), 2)
        self.assertIn(top.rating, ("Major", "Notable"))
        self.assertTrue(all(k.startswith("adv:") for k in counts))

    def test_research_stage_and_field_coverage(self):
        heads = ["Nvidia unveils Blackwell successor chip", "Google releases Gemini model upgrade",
                 "IBM demonstrates 1000-qubit quantum processor", "Samsung launches foldable display",
                 "Tesla debuts humanoid robot factory pilot", "Intel announces 2nm transistor milestone",
                 "OpenAI launches agent platform for developers", "Apple introduces satellite messaging in Europe",
                 "Qualcomm unveils laptop processor", "Meta releases open-source language model",
                 "Microsoft achieves record supercomputer benchmark"]
        stories = [make_story(h, f"S{i}") for i, h in enumerate(heads)]
        stories.append(make_story("Scientists discover new way to grow lunar habitats", "NASA News"))
        section, _ = self.run_adv(stories)
        self.assertEqual(len(section.issues), 10)
        space = [i for i in section.issues if "Space" in i.themes]
        self.assertTrue(space)
        self.assertEqual(space[0].kind, "Research")

    def test_no_signal_no_entry(self):
        section, _ = self.run_adv([make_story("Satellite operators meet in Paris", "X")])
        self.assertEqual(section.items_matched, 0)


class Output(unittest.TestCase):
    def test_html_is_escaped_and_files_written(self):
        story = make_story("<script>alert(1)</script> cyber breach", "Evil")
        brief, _ = db.analyse([story], CONFIG, {}, NOW, {"Evil": "ok"})
        page = db.render_html(brief, [])
        self.assertNotIn("<script>alert", page)
        with tempfile.TemporaryDirectory() as tmp:
            index = db.write_outputs(brief, Path(tmp), 30)
            self.assertTrue(index.is_file())
            self.assertNotIn("pane-advances", index.read_text())
            self.assertTrue((Path(tmp) / "latest.json").is_file())

    def test_two_tabs_with_advancements(self):
        risk, _ = db.analyse([make_story("Election protest grows in capital", "A")], CONFIG, {}, NOW, {"A": "ok"})
        risk.advances, _ = db.analyse_advances(
            [make_story("<b>Robot</b> breakthrough: humanoid learns to cook", "B")], CONFIG, {}, NOW, {"B": "ok"})
        page = db.render_html(risk, [])
        self.assertIn('id="pane-advances"', page)
        self.assertIn("Tech advancements", page)
        self.assertNotIn("<b>Robot</b>", page)
        data = db.to_json(risk)
        self.assertEqual(data["advancements"]["items"][0]["stage"], "Development")
        self.assertIn("TOP TECHNOLOGY ADVANCEMENTS", db.render_text(risk))

    def test_gzip_and_bom_feeds(self):
        import gzip as gz
        from unittest import mock
        body = gz.compress(b"\xef\xbb\xbf" + RSS)
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = body
        with mock.patch.object(db, "urlopen", return_value=fake):
            self.assertEqual(len(db.parse_feed("Z", db.http_get("https://x", 5))), 2)

    def test_version_file_matches(self):
        self.assertEqual((db.APP_DIR / "VERSION").read_text().strip(), db.__version__)


if __name__ == "__main__":
    unittest.main()
