<#
.SYNOPSIS
    One-command setup for Daily Brief: GitHub repo + Pages + daily workflow + Windows install.

.DESCRIPTION
    1. Installs Git and the GitHub CLI with winget if they're missing
    2. Signs you in to GitHub (one browser approval, first time only)
    3. Creates the repo (or updates it if it already exists) and uploads the files
    4. Sets workflow permissions and turns on GitHub Pages (main branch, /docs)
    5. Runs the first cloud brief and waits for it to finish
    6. Runs the Windows installer (shortcuts, hotkey, daily schedule)

    Re-running it later publishes any changed files to your repo - it doubles as
    the "release an update" command.

.EXAMPLE
    .\setup-all.ps1
    .\setup-all.ps1 -RepoName my-brief -Time 06:45
    .\setup-all.ps1 -SkipWindows        # GitHub/iPhone only
    .\setup-all.ps1 -SkipGitHub         # Windows only (same as Install.cmd)
#>
[CmdletBinding()]
param(
    [string]$RepoName = "daily-brief",
    [string]$Time = "07:30",
    [switch]$NoSchedule,
    [switch]$SkipGitHub,
    [switch]$SkipWindows,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
$Src = $PSScriptRoot

function Step($n, $msg) { Write-Host ""; Write-Host "  [$n] $msg" -ForegroundColor White }
function Say($msg, $colour = "Cyan") { Write-Host "      $msg" -ForegroundColor $colour }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure-Tool($command, $wingetId, $friendly) {
    if (Get-Command $command -ErrorAction SilentlyContinue) { Say "$friendly found."; return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$friendly is missing and winget isn't available. Install $friendly manually, then run this again."
    }
    Say "Installing $friendly..." "Yellow"
    winget install --id $wingetId -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
    Refresh-Path
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$friendly installed but isn't on PATH yet. Close this window and run Setup.cmd again."
    }
}

# Run a native command; throw with its output if it fails.
# Windows PowerShell 5.1 turns any stderr line into a terminating error under "Stop",
# so native tools run with "Continue" and are judged by their exit code instead.
function Run([string]$exe, [string[]]$arguments, [switch]$AllowFail) {
    $ErrorActionPreference = "Continue"
    $output = & $exe @arguments 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0 -and -not $AllowFail) {
        throw "$exe $($arguments -join ' ') failed:`n$($output | Out-String)"
    }
    return $output
}

# True if the command succeeds; all output discarded.
function Test-Native([string]$exe, [string[]]$arguments) {
    $ErrorActionPreference = "Continue"
    & $exe @arguments *> $null
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-Path (Join-Path $Src "daily_brief.py"))) {
    throw "Run setup-all.ps1 from inside the extracted Daily Brief folder."
}

Write-Host ""
Write-Host "  ==== Daily Brief - automated setup ====" -ForegroundColor White

$full = $null
if (-not $SkipGitHub) {
    # ------------------------------------------------------------------ tools
    Step 1 "Checking tools"
    Ensure-Tool "git" "Git.Git" "Git"
    Ensure-Tool "gh" "GitHub.cli" "GitHub CLI"

    # ------------------------------------------------------------------ sign in
    Step 2 "Signing in to GitHub"
    if (-not (Test-Native gh @("auth", "status", "--hostname", "github.com"))) {
        Say "A browser window will open - copy the one-time code shown here and approve." "Yellow"
        $ErrorActionPreference = "Continue"
        & gh auth login --hostname github.com --web --git-protocol https --scopes "repo,workflow"
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -ne 0) { throw "GitHub sign-in was not completed." }
    } else {
        $scopes = (Run gh @("api", "-i", "user") | Select-String -Pattern "^X-Oauth-Scopes:" | Out-String)
        if ($scopes -notmatch "\bworkflow\b") {
            Say "Adding permission to publish workflow files (browser approval)..." "Yellow"
            $ErrorActionPreference = "Continue"
            & gh auth refresh --hostname github.com --scopes "workflow"
            $ErrorActionPreference = "Stop"
            if ($LASTEXITCODE -ne 0) { throw "GitHub permission refresh was not completed." }
        }
    }
    Run gh @("auth", "setup-git") | Out-Null
    $user = (Run gh @("api", "user", "--jq", ".login") | Out-String).Trim()
    $full = "$user/$RepoName"
    Say "Signed in as $user"

    # ------------------------------------------------------------------ repo
    Step 3 "Preparing repository github.com/$full"
    $isNew = -not (Test-Native gh @("repo", "view", $full))
    if ($isNew) {
        Run gh @("repo", "create", $full, "--public", "--description", "Daily early-warning brief (social, cultural, technical)") | Out-Null
        Say "Created new public repo."
    } else {
        Say "Repo already exists - your changes will be published to it."
    }

    # Workflow must be allowed to push BEFORE the first push triggers it.
    Run gh @("api", "-X", "PUT", "repos/$full/actions/permissions/workflow",
             "-f", "default_workflow_permissions=write", "-F", "can_approve_pull_request_reviews=false") | Out-Null
    Say "Workflow permissions: read and write."

    # ------------------------------------------------------------------ upload
    Step 4 "Uploading files"
    $work = Join-Path $env:TEMP ("daily-brief-publish-" + [guid]::NewGuid().ToString("N"))
    try {
        Run git @("clone", "--quiet", "https://github.com/$full.git", $work) -AllowFail | Out-Null
        if (-not (Test-Path (Join-Path $work ".git"))) {
            New-Item -ItemType Directory -Force -Path $work | Out-Null
            Run git @("-C", $work, "init", "--quiet") | Out-Null
            Run git @("-C", $work, "remote", "add", "origin", "https://github.com/$full.git") | Out-Null
        }
        $repoHasDocs = Test-Path (Join-Path $work "docs\index.html")

        # Copy the project; keep the published briefs (docs/) that already live in the repo.
        $skipDirs = @(".git", "__pycache__")
        if ($repoHasDocs) { $skipDirs += "docs" }
        & robocopy $Src $work /E /XD @skipDirs /XF "*.pyc" /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "Copying files failed (robocopy code $LASTEXITCODE)." }
        Set-Content -Path (Join-Path $work "repo.txt") -Value $full -Encoding ascii
        Set-Content -Path (Join-Path $Src "repo.txt") -Value $full -Encoding ascii

        if (-not (Run git @("-C", $work, "config", "user.email") -AllowFail)) {
            Run git @("-C", $work, "config", "user.email", "$user@users.noreply.github.com") | Out-Null
            Run git @("-C", $work, "config", "user.name", $user) | Out-Null
        }
        Run git @("-C", $work, "add", "-A") | Out-Null
        $changed = -not (Test-Native git @("-C", $work, "diff", "--cached", "--quiet"))
        if ($changed) {
            $version = (Get-Content (Join-Path $Src "VERSION") -Raw).Trim()
            Run git @("-C", $work, "commit", "--quiet", "-m", "Daily Brief $version") | Out-Null
            Run git @("-C", $work, "branch", "-M", "main") | Out-Null
            Run git @("-C", $work, "push", "--quiet", "-u", "origin", "main") | Out-Null
            Say "Files uploaded (version $version)."
        } else {
            Say "Repo already matches this folder - nothing to upload."
        }
    } finally {
        Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
    }

    # ------------------------------------------------------------------ pages
    Step 5 "Turning on GitHub Pages"
    if (-not (Test-Native gh @("api", "repos/$full/pages"))) {
        Run gh @("api", "-X", "POST", "repos/$full/pages",
                 "-f", "source[branch]=main", "-f", "source[path]=/docs") | Out-Null
        Say "Pages enabled (main branch, /docs)."
    } else {
        Say "Pages already enabled."
    }
    $pagesUrl = (Run gh @("api", "repos/$full/pages", "--jq", ".html_url") | Out-String).Trim()
    if (-not $pagesUrl) { $pagesUrl = "https://$($user.ToLower()).github.io/$RepoName/" }

    # ------------------------------------------------------------------ first run
    Step 6 "Running the cloud brief"
    if (-not $isNew) {
        # A brand-new repo's first push starts the workflow by itself; otherwise start it here.
        Run gh @("workflow", "run", "daily-brief.yml", "-R", $full) | Out-Null
    }
    $runId = $null
    for ($i = 0; $i -lt 12 -and -not $runId; $i++) {
        Start-Sleep -Seconds 5
        $runId = (Run gh @("run", "list", "-R", $full, "--workflow", "daily-brief.yml", "-L", "1",
                           "--json", "databaseId", "--jq", ".[0].databaseId") -AllowFail | Out-String).Trim()
    }
    if (-not $runId) {
        Say "Couldn't see the run yet - check the Actions tab: https://github.com/$full/actions" "Yellow"
    } elseif ($NoWait) {
        Say "Started. Follow it at https://github.com/$full/actions"
    } else {
        Say "Waiting for it to finish (about a minute)..."
        if (Test-Native gh @("run", "watch", $runId, "-R", $full, "--exit-status", "--interval", "10")) { Say "Cloud brief published." "Green" }
        else { Say "The run failed - open https://github.com/$full/actions/runs/$runId for details." "Red" }
    }
}

# ---------------------------------------------------------------------- windows
if (-not $SkipWindows) {
    Step 7 "Installing on this PC"
    $installArgs = @{ Time = $Time }
    if ($full) { $installArgs.Repo = $full }
    if ($NoSchedule) { $installArgs.NoSchedule = $true }
    & (Join-Path $Src "install.ps1") @installArgs
}

# ---------------------------------------------------------------------- summary
Write-Host ""
Write-Host "  ==== All done ====" -ForegroundColor Green
if ($full) {
    Say "Repo:        https://github.com/$full"
    Say "Your brief:  $pagesUrl   (can take 2-3 minutes to appear the first time)"
    try { Set-Clipboard -Value $pagesUrl; Say "The brief link is on your clipboard." } catch { }
    Write-Host ""
    Say "iPhone: open that link in Safari > Share > Add to Home Screen." "White"
}
Write-Host ""
