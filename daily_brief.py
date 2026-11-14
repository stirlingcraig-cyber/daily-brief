#!/usr/bin/env python3
"""Daily Brief - a public-source early-warning digest built from news RSS/Atom feeds.

Ranks today's top social, cultural and technical issues using transparent,
rule-based signals:

    * theme breadth      - how many of the three perspectives an issue touches
    * severity wording   - words such as "attack", "breach", "crisis"
    * corroboration      - how many independent outlets report the same issue
    * momentum           - whether the issue's topics are rising versus recent days

Scores are heuristic indicators of attention and concern. They are NOT
forecasts or probabilities. Always read the underlying sources before acting.

Usage:
    python daily_brief.py                # run, print brief, write HTML + JSON
    python daily_brief.py --open         # ...and open the HTML report
    python daily_brief.py --check-feeds  # test every feed and exit
    python daily_brief.py --help
"""

from __future__ import annotations

__version__ = "2.0.0"

import argparse
import html
import json
import logging
import os
import re
import shutil
import sys
import time
import webbrowser
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_DIR = Path(__file__).resolve().parent
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MAX_FEED_BYTES = 5 * 1024 * 1024
RATING_BANDS = ((7.0, "High"), (5.0, "Elevated"), (3.0, "Moderate"), (0.0, "Low"))
MIN_BASELINE_DAYS = 3

STOP_WORDS = {
    "about", "after", "again", "against", "among", "amid", "because", "before",
    "being", "between", "could", "first", "from", "have", "into", "just",
    "more", "most", "other", "over", "said", "says", "that", "their", "there",
    "these", "they", "this", "those", "under", "were", "what", "when", "where",
    "which", "while", "with", "would", "will", "than", "then", "them", "also",
    "been", "only", "some", "such", "your", "news", "live", "latest", "today",
    "year", "years", "week", "people", "new", "how", "why", "who", "the", "and",
}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]+")

log = logging.getLogger("daily_brief")


# --------------------------------------------------------------------------- config

def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Lists and scalars replace."""
    merged = dict(base)
    for key, value in override.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(*paths: Path) -> dict:
    config: dict = {}
    for path in paths:
        if path and path.is_file():
            try:
                config = deep_merge(config, json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Config error in {path}: {exc}") from exc
    if not config.get("feeds") or not config.get("themes"):
        raise SystemExit("Config must define 'feeds' and 'themes'.")
    config["feeds"] = {k: v for k, v in config["feeds"].items() if v}
    config.setdefault("severity", {})
    config.setdefault("settings", {})
    return config


# --------------------------------------------------------------------------- matching

def compile_term(term: str) -> re.Pattern:
    """Whole-word match with simple plurals; a trailing * means 'starts with'."""
    term = term.strip().lower()
    if term.endswith("*"):
        return re.compile(r"\b" + re.escape(term[:-1]))
    return re.compile(r"\b" + re.escape(term) + r"(?:s|es|ed|d|ing)?\b")


class Matcher:
    def __init__(self, config: dict):
        self.themes = {
            name: [(term, compile_term(term)) for term in terms]
            for name, terms in config["themes"].items()
        }
        self.severity = [
            (term, int(weight), compile_term(term))
            for term, weight in config["severity"].items()
        ]

    def classify(self, text: str) -> tuple[dict[str, set[str]], dict[str, int]]:
        text = text.lower()
        themes = {}
        for name, terms in self.themes.items():
            hits = {term for term, pattern in terms if pattern.search(text)}
            if hits:
                themes[name] = hits
        severity = {term: weight for term, weight, pattern in self.severity if pattern.search(text)}
        return themes, severity


# --------------------------------------------------------------------------- data

@dataclass
class Story:
    title: str
    summary: str
    link: str
    source: str
    published: datetime | None
    themes: dict[str, set[str]] = field(default_factory=dict)
    severity: dict[str, int] = field(default_factory=dict)
    tokens: set[str] = field(default_factory=set)


@dataclass
class Issue:
    stories: list[Story]
    score: float = 0.0
    rising: list[str] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return sorted({s.source for s in self.stories})

    @property
    def themes(self) -> dict[str, set[str]]:
        merged: dict[str, set[str]] = {}
        for story in self.stories:
            for name, terms in story.themes.items():
                merged.setdefault(name, set()).update(terms)
        return merged

    @property
    def severity(self) -> dict[str, int]:
        merged: dict[str, int] = {}
        for story in self.stories:
            merged.update(story.severity)
        return merged

    @property
    def published(self) -> datetime | None:
        dates = [s.published for s in self.stories if s.published]
        return max(dates) if dates else None

    @property
    def lead(self) -> Story:
        return max(self.stories, key=lambda s: (bool(s.summary), s.published or EPOCH))

    @property
    def kind(self) -> str:
        return "Threat" if sum(self.severity.values()) >= 3 else "Watch"

    @property
    def rating(self) -> str:
        return next(label for floor, label in RATING_BANDS if self.score >= floor)


@dataclass
class Brief:
    generated: datetime
    issues: list[Issue]
    items_scanned: int
    items_matched: int
    issue_count: int
    rising_terms: list[str]
    baseline_days: int
    feed_status: dict[str, str]
    update_notice: str | None = None


# --------------------------------------------------------------------------- feeds

def clean_text(value: str | None) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def safe_link(url: str) -> str:
    url = (url or "").strip()
    return url if re.match(r"^https?://", url, re.I) else ""


def parse_date(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    result = None
    try:
        result = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def tokenize(text: str) -> set[str]:
    return {w for w in TOKEN_RE.findall(text.lower()) if len(w) > 3 and w not in STOP_WORDS}


def parse_feed(source: str, data: bytes) -> list[Story]:
    """Parse RSS 2.0, RSS 1.0 (RDF) or Atom into Story objects."""
    if re.search(rb"<!ENTITY", data, re.I):
        raise ValueError("feed declares XML entities; refused for safety")
    root = ET.fromstring(data)
    stories = []
    for element in root.iter():
        if _local(element.tag) not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        link = ""
        for child in element:
            name = _local(child.tag)
            if name == "link":
                href = child.get("href")
                if href and child.get("rel", "alternate") == "alternate":
                    link = link or href
                elif not href and child.text:
                    link = link or child.text
            elif name not in fields:
                fields[name] = "".join(child.itertext())
        title = clean_text(fields.get("title"))
        if not title:
            continue
        summary = clean_text(fields.get("description") or fields.get("summary") or fields.get("content"))
        date = fields.get("pubdate") or fields.get("published") or fields.get("updated") or fields.get("date")
        stories.append(Story(
            title=title,
            summary=summary if summary.lower() != title.lower() else "",
            link=safe_link(link),
            source=source,
            published=parse_date(date),
            tokens=tokenize(title),
        ))
    return stories


def http_get(url: str, timeout: float, limit: int = MAX_FEED_BYTES) -> bytes:
    request = Request(url, headers={
        "User-Agent": f"DailyBrief/{__version__} (personal news digest)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    })
    with urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("response too large")
    return data


def fetch_feed(source: str, url: str, timeout: float, attempts: int = 2) -> tuple[list[Story], str]:
    error = "unknown error"
    for attempt in range(attempts):
        try:
            stories = parse_feed(source, http_get(url, timeout))
            return stories, f"ok ({len(stories)} items)"
        except HTTPError as exc:
            error = f"HTTP {exc.code}"
            if 400 <= exc.code < 500 and exc.code != 429:
                break
        except ET.ParseError as exc:
            error = f"invalid XML: {exc}"
            break
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            error = str(getattr(exc, "reason", exc))
        if attempt < attempts - 1:
            time.sleep(1.5)
    return [], f"FAILED - {error}"


def collect(feeds: dict[str, str], timeout: float, workers: int) -> tuple[list[Story], dict[str, str]]:
    stories: list[Story] = []
    status: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {name: pool.submit(fetch_feed, name, url, timeout) for name, url in feeds.items()}
        for name, future in futures.items():
            items, status[name] = future.result()
            stories.extend(items)
            if items:
                log.info("%s: %s", name, status[name])
            else:
                log.warning("%s: %s", name, status[name])
    return stories, status


# --------------------------------------------------------------------------- analysis

def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def generic_words(config: dict) -> tuple[set[str], tuple[str, ...]]:
    """Keyword-list words are too common to prove two headlines share an event."""
    terms = [t.lower() for terms in config["themes"].values() for t in terms] + [t.lower() for t in config["severity"]]
    exact = {w for t in terms if not t.endswith("*") for w in TOKEN_RE.findall(t)}
    prefixes = tuple(t[:-1] for t in terms if t.endswith("*"))
    return exact, prefixes


def similarity(a: set[str], b: set[str], generic=(frozenset(), ())) -> float:
    exact, prefixes = generic
    specific = {w for w in a & b if w.rstrip("s") not in exact and w not in exact and not w.startswith(prefixes)}
    return jaccard(a, b) if specific else 0.0


def cluster(stories: list[Story], threshold: float, generic=(frozenset(), ())) -> list[Issue]:
    """Group headlines about the same event so one story can't fill the list."""
    issues: list[Issue] = []
    for story in sorted(stories, key=lambda s: s.published or EPOCH, reverse=True):
        best, best_sim = None, 0.0
        for issue in issues:
            sim = max(similarity(story.tokens, other.tokens, generic) for other in issue.stories)
            if sim > best_sim:
                best, best_sim = issue, sim
        if best is not None and best_sim >= threshold:
            best.stories.append(story)
        else:
            issues.append(Issue(stories=[story]))
    return issues


def term_counts(issues: list[Issue]) -> Counter:
    counts: Counter = Counter()
    for issue in issues:
        for terms in issue.themes.values():
            counts.update(terms)
    return counts


def rising_terms(today: Counter, history: dict, today_key: str, window: int = 7) -> tuple[list[str], int]:
    previous = sorted(k for k in history if k < today_key)[-window:]
    if len(previous) < MIN_BASELINE_DAYS:
        return [], len(previous)
    rising = []
    for term, count in today.items():
        average = sum(history[d].get(term, 0) for d in previous) / len(previous)
        if count >= 2 and count >= 1.5 * average + 1:
            rising.append((count - average, term))
    return [t for _, t in sorted(rising, reverse=True)], len(previous)


def score_issue(issue: Issue, rising: set[str]) -> None:
    themes = issue.themes
    issue.rising = sorted({t for terms in themes.values() for t in terms} & rising)
    breadth = min(3.0, 1.5 * len(themes))
    severity = min(4, sum(issue.severity.values()))
    corroboration = min(2, len(issue.sources) - 1)
    momentum = 1 if issue.rising else 0
    issue.score = round(min(10.0, breadth + severity + corroboration + momentum), 1)


def select_top(issues: list[Issue], n: int, theme_names: list[str]) -> list[Issue]:
    def key(i: Issue):
        return (i.score, len(i.sources), i.published or EPOCH)

    ranked = sorted(issues, key=key, reverse=True)
    top, rest = ranked[:n], ranked[n:]
    # Make sure every perspective is represented when material exists for it.
    for theme in theme_names:
        if any(theme in i.themes for i in top):
            continue
        candidate = next((i for i in rest if theme in i.themes), None)
        if not candidate:
            continue
        for idx in range(len(top) - 1, -1, -1):
            others = top[:idx] + top[idx + 1:]
            if all(any(t in o.themes for o in others) for t in top[idx].themes):
                rest.remove(candidate)
                top[idx] = candidate
                break
    return sorted(top, key=key, reverse=True)


def analyse(stories: list[Story], config: dict, history: dict, now: datetime,
            feed_status: dict[str, str]) -> tuple[Brief, dict]:
    settings = config["settings"]
    matcher = Matcher(config)
    cutoff = now - timedelta(hours=float(settings.get("max_age_hours", 48)))

    matched, seen = [], set()
    for story in stories:
        if story.published and story.published < cutoff:
            continue
        key = (story.source, " ".join(sorted(story.tokens)) or story.title.lower())
        if key in seen:
            continue
        seen.add(key)
        story.themes, story.severity = matcher.classify(f"{story.title} {story.summary}")
        if story.themes:
            matched.append(story)

    issues = cluster(matched, float(settings.get("cluster_similarity", 0.4)), generic_words(config))
    today_key = now.strftime("%Y-%m-%d")
    counts = term_counts(issues)
    rising, baseline_days = rising_terms(counts, history, today_key)
    for issue in issues:
        score_issue(issue, set(rising))

    top = select_top(issues, int(settings.get("top_n", 10)), list(config["themes"]))

    history = dict(history)
    history[today_key] = dict(counts)
    keep = int(settings.get("history_days", 30))
    for day in sorted(history)[:-keep]:
        del history[day]

    brief = Brief(
        generated=now, issues=top, items_scanned=len(stories), items_matched=len(matched),
        issue_count=len(issues), rising_terms=rising[:8], baseline_days=baseline_days,
        feed_status=feed_status,
    )
    return brief, history


# --------------------------------------------------------------------------- text helpers

def trim(text: str, limit: int = 320) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:-") + "..."


def rationale(issue: Issue) -> str:
    n = len(issue.sources)
    parts = [f"Reported by {n} source{'s' if n != 1 else ''} ({', '.join(issue.sources)})"]
    parts.append("perspectives: " + "; ".join(
        f"{name} ({', '.join(sorted(t.rstrip('*') for t in terms)[:3])})" for name, terms in sorted(issue.themes.items())))
    severity = sorted(issue.severity, key=lambda t: -issue.severity[t])
    parts.append("severity wording: " + ", ".join(severity[:4]) if severity else "no severity wording")
    if issue.rising:
        parts.append("rising versus recent days: " + ", ".join(issue.rising[:4]))
    return "; ".join(parts) + "."


def finding(issue: Issue) -> str:
    lead = issue.lead
    return trim(lead.summary) if lead.summary else "Headline only - open the source for detail."


def summary_lines(brief: Brief) -> list[str]:
    ok = sum(1 for s in brief.feed_status.values() if s.startswith("ok"))
    ratings = Counter(i.rating for i in brief.issues)
    kinds = Counter(i.kind for i in brief.issues)
    themes = Counter(t for i in brief.issues for t in i.themes)
    lines = [
        f"Scanned {brief.items_scanned} items from {ok} of {len(brief.feed_status)} sources; "
        f"{brief.items_matched} matched a perspective and were grouped into {brief.issue_count} distinct issues.",
        "Top list ratings: " + ", ".join(f"{label} {ratings[label]}" for _, label in RATING_BANDS if ratings[label])
        + f" ({kinds['Threat']} threats, {kinds['Watch']} watch items).",
        "Perspective mix: " + ", ".join(f"{t} {c}" for t, c in themes.most_common()) + ".",
    ]
    if brief.rising_terms:
        lines.append("Rising topics versus recent days: " + ", ".join(brief.rising_terms) + ".")
    else:
        lines.append(
            "No topics rising sharply versus recent days." if brief.baseline_days >= MIN_BASELINE_DAYS
            else f"Momentum baseline still building ({brief.baseline_days} of {MIN_BASELINE_DAYS} days collected).")
    if brief.issues:
        most = max(brief.issues, key=lambda i: len(i.sources))
        if len(most.sources) > 1:
            lines.append(f"Most widely reported: \"{most.lead.title}\" ({len(most.sources)} sources).")
    return lines


METHOD_NOTE = ("Scores (0-10) combine perspective breadth, severity wording, cross-source corroboration "
               "and momentum. They measure attention and concern in public reporting - not probability, "
               "not a forecast. Read the sources before acting.")


# --------------------------------------------------------------------------- output

def render_text(brief: Brief) -> str:
    out = [f"DAILY BRIEF - {brief.generated:%A %d %B %Y, %H:%M} UTC", METHOD_NOTE, ""]
    if brief.update_notice:
        out += [f"UPDATE: {brief.update_notice}", ""]
    out.append("SUMMARY FINDINGS")
    out += [f"  - {line}" for line in summary_lines(brief)]
    out.append("")
    if not brief.issues:
        out.append("No matching stories were retrieved. Run with --check-feeds to test your sources.")
    for rank, issue in enumerate(brief.issues, 1):
        date = f"{issue.published:%d %b %H:%M} UTC" if issue.published else "date unavailable"
        out.append(f"{rank:>2}. [{issue.rating} | {issue.score}/10 | {issue.kind}] {issue.lead.title}")
        out.append(f"    Perspectives: {', '.join(sorted(issue.themes))} | Latest: {date}")
        out.append(f"    Rationale: {rationale(issue)}")
        out.append(f"    Finding: {finding(issue)}")
        if issue.lead.link:
            out.append(f"    Link: {issue.lead.link}")
        out.append("")
    return "\n".join(out)


def to_json(brief: Brief) -> dict:
    return {
        "version": __version__,
        "generated_utc": brief.generated.isoformat(),
        "method": METHOD_NOTE,
        "summary": summary_lines(brief),
        "rising_terms": brief.rising_terms,
        "feed_status": brief.feed_status,
        "issues": [{
            "rank": rank,
            "title": issue.lead.title,
            "score": issue.score,
            "rating": issue.rating,
            "type": issue.kind,
            "perspectives": sorted(issue.themes),
            "sources": issue.sources,
            "latest_utc": issue.published.isoformat() if issue.published else None,
            "rationale": rationale(issue),
            "finding": finding(issue),
            "links": [{"source": s.source, "title": s.title, "url": s.link} for s in issue.stories if s.link],
        } for rank, issue in enumerate(brief.issues, 1)],
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Daily Brief">
<meta name="theme-color" content="#0b1f33">
<link rel="icon" href="assets/icon-192.png">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<title>Daily Brief - {date}</title>
<style>
:root{{--bg:#f4f6f9;--card:#fff;--ink:#14202b;--muted:#5b6876;--line:#dde3ea;--accent:#1f6feb;
--high:#c62828;--elev:#e2711d;--mod:#b38600;--low:#3d7a52}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d141b;--card:#16202a;--ink:#e6edf3;--muted:#93a1b0;--line:#26323e;--accent:#58a6ff}}}}
*{{box-sizing:border-box}}body{{margin:0;font:16px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink)}}
header{{background:#0b1f33;color:#fff;padding:calc(18px + env(safe-area-inset-top)) 20px 18px;display:flex;gap:14px;align-items:center}}
header img{{width:44px;height:44px;border-radius:10px}}header h1{{margin:0;font-size:1.3rem}}header p{{margin:2px 0 0;opacity:.8;font-size:.9rem}}
main{{max-width:880px;margin:0 auto;padding:16px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin-bottom:14px}}
.box h2{{font-size:1rem;margin:0 0 6px}}.box ul{{margin:0;padding-left:20px}}.note{{color:var(--muted);font-size:.85rem}}
.update{{border-color:var(--accent)}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 14px}}
.chips button{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 14px;font:inherit;font-size:.9rem;cursor:pointer}}
.chips button.on{{background:var(--accent);border-color:var(--accent);color:#fff}}
.card{{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c);border-radius:12px;padding:14px 18px;margin-bottom:12px}}
.card h3{{margin:4px 0 8px;font-size:1.05rem}}.card a{{color:var(--ink)}}
.tags{{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:.8rem}}
.pill{{border-radius:999px;padding:2px 10px;font-weight:600;color:#fff;background:var(--c)}}
.tag{{border:1px solid var(--line);border-radius:999px;padding:1px 9px;color:var(--muted)}}
.bar{{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin:8px 0}}.bar i{{display:block;height:100%;background:var(--c)}}
.card p{{margin:6px 0;font-size:.93rem}}.card b{{font-weight:600}}.more{{font-size:.85rem;color:var(--muted)}}
details{{margin-top:6px}}footer{{text-align:center;color:var(--muted);font-size:.8rem;padding:10px 16px 40px}}
.archive a{{color:var(--accent);margin-right:10px}}
</style></head><body>
<header><img src="assets/icon-192.png" alt=""><div><h1>Daily Brief</h1><p>{date_long} &middot; generated {time} UTC</p></div></header>
<main>
{update}
<section class="box"><h2>Summary findings</h2><ul>{summary}</ul><p class="note">{method}</p></section>
<div class="chips" id="chips"><button class="on" data-f="all">All</button>{chips}<button data-f="Threat">Threats only</button></div>
{cards}
<section class="box"><details><summary>Source status</summary><ul>{status}</ul></details></section>
{archive}
</main>
<footer>Daily Brief v{version} &middot; public RSS sources &middot; heuristic ranking, not a forecast</footer>
<script>
document.getElementById('chips').addEventListener('click',function(e){{
 var f=e.target.getAttribute('data-f'); if(!f)return;
 document.querySelectorAll('#chips button').forEach(function(b){{b.classList.toggle('on',b===e.target)}});
 document.querySelectorAll('.card').forEach(function(c){{
  c.style.display=(f==='all'||c.dataset.themes.split(',').indexOf(f)>-1||c.dataset.kind===f)?'':'none';}});
}});
</script></body></html>"""

RATING_COLOURS = {"High": "var(--high)", "Elevated": "var(--elev)", "Moderate": "var(--mod)", "Low": "var(--low)"}


def render_html(brief: Brief, archive: list[str]) -> str:
    e = html.escape
    cards = []
    for rank, issue in enumerate(brief.issues, 1):
        lead = issue.lead
        title = f'<a href="{e(lead.link)}" target="_blank" rel="noopener">{e(lead.title)}</a>' if lead.link else e(lead.title)
        date = f"{issue.published:%d %b %H:%M} UTC" if issue.published else "date unavailable"
        others = [s for s in issue.stories if s is not lead and s.link]
        more = ""
        if others:
            more = "<details class='more'><summary>Also reported by</summary><ul>" + "".join(
                f'<li><a href="{e(s.link)}" target="_blank" rel="noopener">{e(s.source)}: {e(s.title)}</a></li>'
                for s in others[:8]) + "</ul></details>"
        tags = "".join(f'<span class="tag">{e(t)}</span>' for t in sorted(issue.themes))
        cards.append(
            f'<article class="card" style="--c:{RATING_COLOURS[issue.rating]}" '
            f'data-themes="{e(",".join(sorted(issue.themes)))}" data-kind="{issue.kind}">'
            f'<div class="tags"><b>#{rank}</b><span class="pill">{issue.rating} &middot; {issue.score}/10</span>'
            f'<span class="tag">{issue.kind}</span>{tags}</div>'
            f'<h3>{title}</h3><div class="bar"><i style="width:{issue.score * 10:.0f}%"></i></div>'
            f'<p><b>Finding:</b> {e(finding(issue))}</p><p><b>Rationale:</b> {e(rationale(issue))}</p>'
            f'<p class="note">{e(lead.source)} &middot; latest {date}</p>{more}</article>')
    if not cards:
        cards.append('<section class="box">No matching stories were retrieved today. '
                     'Check the source status below.</section>')
    archive_html = ""
    if archive:
        archive_html = ('<section class="box archive"><h2>Previous briefs</h2>' + "".join(
            f'<a href="{e(name)}">{e(name[6:16])}</a>' for name in archive) + "</section>")
    update = f'<section class="box update"><b>Update available:</b> {e(brief.update_notice)}</section>' \
        if brief.update_notice else ""
    return HTML_TEMPLATE.format(
        date=f"{brief.generated:%Y-%m-%d}", date_long=f"{brief.generated:%A %d %B %Y}",
        time=f"{brief.generated:%H:%M}", version=__version__, update=update,
        summary="".join(f"<li>{e(line)}</li>" for line in summary_lines(brief)),
        method=e(METHOD_NOTE),
        chips="".join(f'<button data-f="{e(t)}">{e(t)}</button>' for t in sorted({t for i in brief.issues for t in i.themes})),
        cards="\n".join(cards),
        status="".join(f"<li>{e(k)}: {e(v)}</li>" for k, v in sorted(brief.feed_status.items())),
        archive=archive_html,
    )


MANIFEST = {
    "name": "Daily Brief", "short_name": "Daily Brief", "start_url": "./index.html",
    "display": "standalone", "background_color": "#0b1f33", "theme_color": "#0b1f33",
    "icons": [{"src": "assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "assets/icon-512.png", "sizes": "512x512", "type": "image/png"}],
}


def write_outputs(brief: Brief, out_dir: Path, keep_days: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = out_dir / "assets"
    assets.mkdir(exist_ok=True)
    for name in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        src = APP_DIR / "assets" / name
        if src.is_file() and not (assets / name).is_file():
            shutil.copy2(src, assets / name)
    (out_dir / "manifest.webmanifest").write_text(json.dumps(MANIFEST, indent=2), encoding="utf-8")

    cutoff = (brief.generated - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for old in out_dir.glob("brief-*.*"):
        if old.stem[6:16] < cutoff:
            old.unlink(missing_ok=True)

    day = f"{brief.generated:%Y-%m-%d}"
    archive = sorted((p.name for p in out_dir.glob("brief-*.html") if p.stem[6:] != day), reverse=True)[:14]
    page = render_html(brief, archive)
    data = json.dumps(to_json(brief), indent=2, ensure_ascii=False)
    for name, content in ((f"brief-{day}.html", page), ("index.html", page),
                          (f"brief-{day}.json", data), ("latest.json", data)):
        (out_dir / name).write_text(content, encoding="utf-8")
    return out_dir / "index.html"


# --------------------------------------------------------------------------- update check

def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3])


def check_for_update(timeout: float = 5) -> str | None:
    repo_file = APP_DIR / "repo.txt"
    if not repo_file.is_file():
        return None
    repo = repo_file.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or repo.upper().startswith("YOUR-"):
        return None
    try:
        remote = http_get(f"https://raw.githubusercontent.com/{repo}/main/VERSION", timeout, 64).decode().strip()
    except (URLError, OSError, ValueError, UnicodeDecodeError):
        return None
    if version_tuple(remote) > version_tuple(__version__):
        return (f"version {remote} is available (you have {__version__}). "
                "Run 'Daily Brief - Update' from the Start menu.")
    return None


# --------------------------------------------------------------------------- CLI

def default_home() -> Path:
    return Path(os.environ.get("DAILY_BRIEF_HOME") or Path.home() / "DailyBrief")


def load_history(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily early-warning brief from public news feeds.")
    parser.add_argument("--home", type=Path, default=default_home(), help="Folder for reports, history, user config.")
    parser.add_argument("--output-dir", type=Path, help="Where to write HTML/JSON (default: HOME/reports).")
    parser.add_argument("--history", type=Path, help="History file for momentum (default: HOME/history.json).")
    parser.add_argument("--config", type=Path, help="Extra config file merged over the defaults.")
    parser.add_argument("--top", type=int, help="Number of issues to show (default 10).")
    parser.add_argument("--open", action="store_true", help="Open the HTML report when done.")
    parser.add_argument("--quiet", action="store_true", help="Don't print the brief to the console.")
    parser.add_argument("--check-feeds", action="store_true", help="Test every feed and exit.")
    parser.add_argument("--no-update-check", action="store_true", help="Skip the GitHub version check.")
    parser.add_argument("--version", action="version", version=f"Daily Brief {__version__}")
    args = parser.parse_args(argv)

    if sys.stdout is None:  # pythonw.exe (desktop shortcut / scheduled task) has no console
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    home = args.home
    home.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(home / "daily_brief.log", mode="w", encoding="utf-8")])
    config = load_config(APP_DIR / "config.json", home / "user_config.json", args.config)
    settings = config["settings"]
    if args.top:
        settings["top_n"] = max(1, args.top)
    timeout = float(settings.get("timeout_seconds", 15))

    if args.check_feeds:
        _, status = collect(config["feeds"], timeout, int(settings.get("max_workers", 8)))
        width = max(map(len, status))
        for name, result in sorted(status.items()):
            print(f"{name:<{width}}  {result}")
        return 0 if any(v.startswith("ok") for v in status.values()) else 1

    stories, status = collect(config["feeds"], timeout, int(settings.get("max_workers", 8)))
    history_path = args.history or home / "history.json"
    brief, history = analyse(stories, config, load_history(history_path), datetime.now(timezone.utc), status)
    if settings.get("check_for_updates", True) and not args.no_update_check:
        brief.update_notice = check_for_update()

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=1, sort_keys=True), encoding="utf-8")
    report = write_outputs(brief, args.output_dir or home / "reports", int(settings.get("keep_reports_days", 30)))
    log.info("Report written to %s", report)

    if not args.quiet:
        print(render_text(brief))
        print(f"Report: {report}")
    if args.open:
        webbrowser.open(report.resolve().as_uri())
    return 0 if stories else 2


if __name__ == "__main__":
    sys.exit(main())
