# Install guide

## Fastest: automated setup (about 5 minutes)

On your Windows PC:

1. Right-click the ZIP, choose **Properties**, tick **Unblock**, click **OK**, then extract it.
2. Double-click **`Setup.cmd`**.
3. When asked, approve the GitHub sign-in in your browser (first time only).

It installs Git and the GitHub CLI if needed, creates your public `daily-brief` repo, uploads everything, turns on Pages, sets the workflow permissions, runs the first cloud brief, installs the Windows app and copies your brief link to the clipboard. Then do the [iPhone](#iphone) step.

Options (from PowerShell in the folder): `.\setup-all.ps1 -RepoName my-brief -Time 06:45`, `-SkipWindows`, `-SkipGitHub`, `-NoSchedule`, `-NoWait`.
**Re-run it any time to publish changed files** to your repo; it becomes your release command.

The manual steps below do the same thing by hand.

---

Set up in this order: **GitHub first** (it's your update source and powers the iPhone page), then **Windows**, then **iPhone**. Each part also works on its own.

---

## GitHub

Allow about 10 minutes, once. You need a free GitHub account.

1. **Create the repo.** On github.com, click **+ → New repository**. Name it `daily-brief`, choose **Public**, and click **Create repository**.
   *Public is needed for free GitHub Pages. The page only shows public news headlines, but anyone with the link can see it.*
2. **Set your repo name.** In the project folder on your PC, open `repo.txt` in Notepad and replace the line with your own name, e.g. `jsmith/daily-brief`. Save it.
3. **Upload the files.** On the new repo page, click **uploading an existing file** and drag in *everything inside* the project folder, including the hidden `.github` folder. Click **Commit changes**.
   - If the `.github` folder won't drag in, choose **Add file → Create new file**, type `.github/workflows/daily-brief.yml` as the name, paste in the contents of that file and commit.
   - With Git installed, this is simpler: `git init`, `git add .`, `git commit -m "Daily Brief"`, `git branch -M main`, `git remote add origin https://github.com/<you>/daily-brief.git`, then `git push -u origin main`.
4. **Turn on Pages.** Go to **Settings → Pages → Build and deployment**, set Source to **Deploy from a branch**, Branch to **main**, folder **/docs**, then **Save**.
5. **Allow the workflow to publish.** Go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, then **Save**.
6. **Run it once.** Open the **Actions** tab, choose **Daily Brief**, then **Run workflow**. It takes about a minute.
7. **Open your page** at `https://<you>.github.io/daily-brief/`. Pages can take a couple of minutes to go live the first time.

After that it runs **every day at 06:17 UTC** by itself. To change the time, edit the `cron` line in `.github/workflows/daily-brief.yml`.

---

## Windows

Allow about 3 minutes. You don't need admin rights.

1. Download the project ZIP. From your repo, use **Code → Download ZIP**, or use the ZIP Claude sent you.
2. **Before extracting**, right-click the ZIP, choose **Properties**, tick **Unblock** and click **OK**. This stops Windows SmartScreen warnings.
3. Extract it anywhere, e.g. to Downloads.
4. Double-click **`Install.cmd`**.
   - If SmartScreen still says *"Windows protected your PC"*, click **More info → Run anyway**.
   - If Python isn't installed, the installer installs it for you using winget.
   - When asked for your GitHub repo, type it (e.g. `jsmith/daily-brief`), or press Enter to skip updates for now.
5. The first brief opens in your browser. You can delete the extracted folder afterwards.

**What gets installed**

| Item | Where |
|---|---|
| **Daily Brief** desktop icon (hotkey **Ctrl + Alt + B**) | Desktop |
| Start menu folder **Daily Brief**: run, **Update**, **Reports folder**, **Settings**, **Uninstall** | Start menu |
| Daily run at **07:30** (catches up at next login if the PC was off) | Task Scheduler → `DailyBrief` |
| Program | `%LOCALAPPDATA%\DailyBrief` |
| Your reports, history and settings (kept through updates) | `%USERPROFILE%\DailyBrief` |

**Pin to the taskbar:** open the Start menu, right-click **Daily Brief**, then choose **Pin to taskbar**.

**Options:** run from PowerShell inside the folder.
```
.\install.ps1 -Time 06:45      # different daily time
.\install.ps1 -NoSchedule      # no daily run
```

---

## iPhone

Allow about 1 minute. This needs the GitHub part set up first.

1. Open **Safari** (it must be Safari) and go to `https://<you>.github.io/daily-brief/`.
2. Tap the **Share** button, then **Add to Home Screen**, then **Add**.
3. You now have a **Daily Brief** icon that opens full-screen like an app and shows the latest brief each morning.

**Optional extras**
- **Run it on demand from your phone:** install the **GitHub** app, open your repo, go to **Actions → Daily Brief → Run workflow**, and refresh the page a minute later.
- **Morning reminder:** in the **Shortcuts** app, go to **Automation → + → Time of Day** (e.g. 07:30), add the action **Open URLs** with your Pages link, and set it to **Run Immediately**.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Brief says *"No matching stories"* | Run `python "%LOCALAPPDATA%\DailyBrief\daily_brief.py" --check-feeds` to see which sources fail. A news site may have changed its feed address; update or remove it in your settings. |
| Desktop icon does nothing | Open `%USERPROFILE%\DailyBrief\daily_brief.log` to see the error. Re-running `Install.cmd` repairs the install. |
| GitHub workflow fails at the *push* step | Check step 5 (Read and write permissions). |
| Pages shows *404* | Wait 2–3 minutes after the first run, and check that Settings → Pages is set to `main` / `/docs`. |
| iPhone shows an old brief | Pull down to refresh, or close and reopen the icon. |
| Update says *"No GitHub repo is set"* | Re-run `Install.cmd` and enter `username/daily-brief`. |
