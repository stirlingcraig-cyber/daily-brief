<#
.SYNOPSIS
    Updates Daily Brief to the latest version on GitHub. Your settings and reports are kept.

.EXAMPLE
    .\update.ps1          # update only if a newer version exists
    .\update.ps1 -Force   # reinstall the latest version regardless
#>
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "DailyBrief"
$repoFile   = Join-Path $InstallDir "repo.txt"

function Finish($msg, $colour = "Green") {
    Write-Host "  $msg" -ForegroundColor $colour
    if ($Host.Name -eq "ConsoleHost") { Read-Host "  Press Enter to close" | Out-Null }
    exit
}

if (-not (Test-Path $repoFile)) {
    Finish "No GitHub repo is set. Re-run Install.cmd and enter your repo (e.g. jsmith/daily-brief)." "Yellow"
}
$repo = (Get-Content $repoFile -Raw).Trim()
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$local = if (Test-Path "$InstallDir\VERSION") { (Get-Content "$InstallDir\VERSION" -Raw).Trim() } else { "0.0.0" }
try {
    $remote = (Invoke-RestMethod "https://raw.githubusercontent.com/$repo/main/VERSION" -TimeoutSec 15).ToString().Trim()
} catch {
    Finish "Couldn't reach github.com/$repo - check the repo name and your connection. ($($_.Exception.Message))" "Red"
}
Write-Host "  Installed: $local   Latest: $remote"
if (-not $Force -and [version]$remote -le [version]$local) { Finish "You're up to date." }

$tmp = Join-Path $env:TEMP ("DailyBrief-update-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "  Downloading $remote..."
    $zip = Join-Path $tmp "latest.zip"
    Invoke-WebRequest "https://github.com/$repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $tmp -Force
    $srcDir = Get-ChildItem $tmp -Directory | Where-Object { Test-Path (Join-Path $_.FullName "daily_brief.py") } | Select-Object -First 1
    if (-not $srcDir) { throw "Downloaded archive doesn't contain daily_brief.py" }
    & (Join-Path $srcDir.FullName "install.ps1") -Quiet -Repo $repo
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
Finish "Updated to $remote."
