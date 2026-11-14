# User guide

## Opening the brief

- **Windows:** double-click the desktop icon or press **Ctrl + Alt + B**. This fetches fresh news and opens the report, which takes about 10–20 seconds. The scheduled run builds one every morning anyway; to see it without refreshing, open **Start → Daily Brief → Reports folder → index.html**.
- **iPhone:** tap the Daily Brief icon on your Home Screen.
- **Any browser:** go to `https://<you>.github.io/daily-brief/`.

## Reading it

**Summary findings** (top box) give the day at a glance:
- How many items were scanned, how many sources worked, and how many distinct issues were found
- The rating mix of the top list, and how many items are threats versus watch items
- The balance between Social, Cultural and Technical perspectives
- **Rising topics**: keywords mentioned noticeably more than their 7-day average. This is the most forward-looking signal; a topic that keeps rising across several days is worth watching. It needs 3 days of history before it switches on.
- The most widely reported issue

**Each issue card** shows:

| Part | Meaning |
|---|---|
| **#rank, rating and score** | High ≥ 7, Elevated ≥ 5, Moderate ≥ 3, Low < 3. The coloured bar shows the score. |
| **Threat / Watch** | *Threat* = strong severity wording (attack, breach, crisis...). *Watch* = notable, but less severe language. |
| **Perspective tags** | Which of Social, Cultural and Technical it touches |
| **Finding** | The outlet's own summary of the story |
| **Rationale** | Exactly why it scored as it did: sources, matched keywords, severity words, rising topics |
| **Also reported by** | The other outlets covering the same event. Compare them to see different angles. |

Use the **filter buttons** (Cultural, Social, Technical, Threats only) to narrow the list. **Previous briefs** at the bottom link to past days, which are kept for 30 days.

### Reading it well
- The score measures **attention and alarm in reporting**, not real-world likelihood. A High score means many outlets are covering it with severe language. It doesn't mean it will happen, or that it affects you.
- One source with dramatic wording can outscore a quieter but more important story. Use the corroboration count in the rationale.
- Check **Source status** at the bottom. If several feeds failed, the brief has less to go on that day.

## Customising

Open **Start → Daily Brief → Settings**, which opens `user_config.json` in Notepad. Anything you put here overrides the defaults and **is never touched by updates**. See `user_config.example.json` in the program folder for the format.

```json
{
  "settings": { "top_n": 15, "max_age_hours": 24 },
  "feeds": {
    "Sky News World": "https://feeds.skynews.com/feeds/rss/world.xml",
    "Fox News World": null
  },
  "severity": { "drought": 2, "boil notice": 3 }
}
```

- **Add a feed:** give it a name and an RSS/Atom address. **Remove one:** set it to `null`.
- **Keywords:** a `themes` list in your file *replaces* that whole perspective list, so copy the full list from `config.json` and edit it. Matching is whole-word and also catches simple plurals (`protest` matches *protests*). End a word with `*` to match anything starting with it (`cyber*` matches *cyberattack*).
- **Severity weights:** use 1 to 4. A higher number pushes stories with that word up the list.
- Settings in `settings`: `top_n`, `max_age_hours` (ignore older stories), `cluster_similarity` (0–1, higher means less grouping of similar headlines), `keep_reports_days`, `check_for_updates`.
- After editing, run `--check-feeds` to confirm your new sources work.

For the **GitHub/iPhone** version, edit `config.json` in the repo directly (click it, then the pencil icon). The next run picks up the change.

## Updating

Updates come from your GitHub repo, so the repo is the single place where changes are made.

**On Windows:**
- The brief shows an **"Update available"** banner when your repo has a newer `VERSION`.
- To update, use **Start → Daily Brief → Update**. It downloads the latest version, reinstalls it in place and keeps your schedule, settings and reports.
- `update.ps1 -Force` reinstalls even if the version is the same.

**GitHub/iPhone:** there's nothing to do. The workflow always runs the latest code in the repo.

**Releasing a change** (e.g. new code from Claude):
1. Replace the changed files in the repo (upload, or `git push`).
2. Increase the number in **`VERSION`** (e.g. `2.0.0` to `2.0.1`), **and** `__version__` near the top of `daily_brief.py`, to match. A test checks that they agree.
3. The GitHub workflow runs the tests on every code change, so a red ✗ in Actions means don't update Windows yet.
4. Windows PCs see the banner on their next run and update with one click.

## Uninstalling

Use **Start → Daily Brief → Uninstall**. Your reports and settings in `%USERPROFILE%\DailyBrief` are kept. To remove those too, run `uninstall.ps1 -All`.
