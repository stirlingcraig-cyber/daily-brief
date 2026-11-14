# Daily Brief

A daily early-warning digest of the **top 10 social, cultural and technical issues**, built from public news feeds. Each issue gets a **risk rating, a score out of 10, a rationale and a summary finding**, and the brief opens with summary findings for the day.

It runs on **Windows** (desktop icon, Start menu, Ctrl+Alt+B hotkey and a daily scheduled run), on **GitHub** (a free daily run that publishes a web page) and on **iPhone** (that page saved to your Home Screen as an app icon).

> **What it is not:** Daily Brief doesn't predict the future. It measures what public reporting is paying attention to and how serious the language is. The *momentum* signal shows topics that are rising compared with recent days. That's an early-warning indicator, not a forecast or a probability. Always read the sources before acting.

## How an issue is scored (0–10)

| Signal | Points | Meaning |
|---|---|---|
| Perspective breadth | 1.5 per perspective, max 3 | Touches Social / Cultural / Technical keywords |
| Severity wording | sum of word weights, max 4 | e.g. *attack* 3, *breach* 3, *warning* 2, *ban* 1 |
| Corroboration | +1 per extra outlet, max 2 | The same event reported by several independent sources |
| Momentum | +1 | Its topics are mentioned noticeably more than the 7-day average |

**Ratings:** High ≥ 7 · Elevated ≥ 5 · Moderate ≥ 3 · Low < 3.  **Type:** *Threat* if the severity wording totals 3 or more, otherwise *Watch*.

How it reduces bias:
- **Sources from different countries and editorial leanings:** UK (BBC, Guardian), US (NPR, Fox News, WSJ, CISA), Qatar (Al Jazeera), Germany (DW), France (France 24), the UN, and specialist tech outlets.
- **Fixed, published rules:** the same keyword lists and weights apply to every story. Nothing is generated or editorialised, and the findings are the outlets' own summaries.
- **Duplicate grouping:** headlines about the same event are grouped together, so one story can't fill the list.
- **Guaranteed mix:** at least one item from each perspective appears in the top 10 when there is material for it.

Keyword lists and feeds are not neutral in themselves. Review `config.json` and adjust it to suit you.

## Quick start

**One command:** extract the ZIP and double-click **`Setup.cmd`**. It sets up GitHub (repo, Pages, daily run) and Windows in one go; then add the page to your iPhone. Details: [guides/INSTALL.md](guides/INSTALL.md).

Or step by step:

| Platform | Steps |
|---|---|
| **Windows** | Download the ZIP, extract it and double-click **`Install.cmd`**. Details: [guides/INSTALL.md](guides/INSTALL.md#windows) |
| **GitHub** | Upload this folder to a new public repo, turn on Pages (`main` branch, `/docs` folder) and run the workflow once. Details: [guides/INSTALL.md](guides/INSTALL.md#github) |
| **iPhone** | Open your Pages link in Safari, tap **Share** and choose **Add to Home Screen**. Details: [guides/INSTALL.md](guides/INSTALL.md#iphone) |

How to read the brief, customise it and keep it up to date: **[guides/USER_GUIDE.md](guides/USER_GUIDE.md)**.

## Command line

```
python daily_brief.py                 # print the brief and write HTML + JSON reports
python daily_brief.py --open          # ...and open the report in your browser
python daily_brief.py --top 15        # show 15 issues
python daily_brief.py --check-feeds   # test every news source
python -m unittest discover -s tests  # run the tests
```

The script uses only the Python standard library (Python 3.9 or later), so there's nothing to `pip install`.

## Files

| File | Purpose |
|---|---|
| `daily_brief.py` | The program |
| `config.json` | Feeds, keyword lists and severity weights (replaced by updates) |
| `user_config.example.json` | Example of your own overrides, which are kept through updates |
| `VERSION` | Version number checked by the updater; increase it when you release changes |
| `repo.txt` | Your GitHub `username/repo`, used for updates |
| `Setup.cmd`, `setup-all.ps1` | Automated setup: GitHub repo + Pages + workflow + Windows install. Re-run it to publish changes. |
| `Install.cmd`, `install.ps1`, `update.ps1`, `uninstall.ps1` | Windows-only install, update and removal |
| `.github/workflows/daily-brief.yml` | Daily cloud run that publishes to `docs/` |
| `docs/` | The published web page (written by the workflow) |
| `assets/` | App icons |
