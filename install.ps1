<#
.SYNOPSIS
    Installs (or updates) Daily Brief for the current Windows user. No admin rights needed.

.DESCRIPTION
    - Finds Python 3.9+ (installs it with winget if missing)
    - Copies the app to %LOCALAPPDATA%\DailyBrief
    - Creates Desktop + Start-menu shortcuts with icon (hotkey Ctrl+Alt+B)
    - Registers a daily scheduled task (default 07:30)
    - Runs the first brief and opens it

.EXAMPLE
    .\install.ps1
    .\install.ps1 -Time 06:45
    .\install.ps1 -NoSchedule
#>
[CmdletBinding()]
param(
    [string]$Time = "07:30",
    [switch]$NoSchedule,
    [switch]$Quiet,          # used by update.ps1: no prompts, keep existing schedule, don't open the report
    [string]$Repo = ""
)

$ErrorActionPreference = "Stop"
$AppName    = "Daily Brief"
$TaskName   = "DailyBrief"
$InstallDir = Join-Path $env:LOCALAPPDATA "DailyBrief"
$HomeDir    = Join-Path $env:USERPROFILE "DailyBrief"
$Src        = $PSScriptRoot

function Say($msg, $colour = "Cyan") { Write-Host "  $msg" -ForegroundColor $colour }

function Find-Python {
    $candidates = @(
        @{ Cmd = "py";     Args = @("-3") },
        @{ Cmd = "python"; Args = @() },
        @{ Cmd = "python3"; Args = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Cmd -ErrorAction SilentlyContinue)) { continue }
        try {
            $exe = & $c.Cmd @($c.Args + @("-c", "import sys; assert sys.version_info >= (3, 9); print(sys.executable)")) 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) { return $exe.Trim() }
        } catch { }
    }
    $local = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
    if ($local) { return $local.FullName }
    return $null
}

Write-Host ""
Write-Host "  ==== $AppName installer ====" -ForegroundColor White

if (-not (Test-Path (Join-Path $Src "daily_brief.py"))) {
    throw "Run install.ps1 from inside the extracted Daily Brief folder."
}

# 1. Python ------------------------------------------------------------------
$python = Find-Python
if (-not $python) {
    Say "Python 3 not found - installing it with winget (one-off, ~2 minutes)..." "Yellow"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is unavailable. Install Python from https://www.python.org/downloads/ (tick 'Add to PATH'), then run Install.cmd again."
    }
    winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $python = Find-Python
    if (-not $python) { throw "Python installed but not found yet. Close this window, then run Install.cmd again." }
}
$pythonw = Join-Path (Split-Path $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }
Say "Python: $python"

# 2. Copy app files ------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $InstallDir, (Join-Path $InstallDir "assets"), $HomeDir | Out-Null
$files = "daily_brief.py", "config.json", "VERSION", "install.ps1", "update.ps1", "uninstall.ps1",
         "Install.cmd", "setup-all.ps1", "Setup.cmd", "user_config.example.json", "README.md"
foreach ($f in $files) {
    $p = Join-Path $Src $f
    if (Test-Path $p) { Copy-Item $p $InstallDir -Force }
}
Copy-Item (Join-Path $Src "assets\*") (Join-Path $InstallDir "assets") -Force
if (Test-Path (Join-Path $Src "guides")) { Copy-Item (Join-Path $Src "guides") $InstallDir -Recurse -Force }
Say "App installed to $InstallDir"

# 3. GitHub repo for updates --------------------------------------------------
$repoFile = Join-Path $InstallDir "repo.txt"
if (-not $Repo) {
    foreach ($candidate in @((Join-Path $Src "repo.txt"), $repoFile)) {
        if (Test-Path $candidate) {
            $value = (Get-Content $candidate -Raw).Trim()
            if ($value -and $value -notlike "YOUR-*") { $Repo = $value; break }
        }
    }
}
if (-not $Repo -and -not $Quiet) {
    $Repo = (Read-Host "  Your GitHub repo for updates, e.g. jsmith/daily-brief (Enter to skip)").Trim()
}
if ($Repo) { Set-Content -Path $repoFile -Value $Repo -Encoding ascii; Say "Updates from github.com/$Repo" }
else { Say "No GitHub repo set - auto-update disabled (see guides/INSTALL.md)." "Yellow" }

# 4. User settings (never overwritten by updates) ----------------------------
$userCfg = Join-Path $HomeDir "user_config.json"
if (-not (Test-Path $userCfg)) {
    Set-Content -Path $userCfg -Value "{`n  `"_help`": `"Your overrides go here. See user_config.example.json in $InstallDir`"`n}" -Encoding utf8
}

# 5. Shortcuts -----------------------------------------------------------------
$shell     = New-Object -ComObject WScript.Shell
$icon      = Join-Path $InstallDir "assets\icon.ico"
$script    = Join-Path $InstallDir "daily_brief.py"
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) $AppName
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null

function New-Shortcut($path, $target, $arguments, $hotkey = "") {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $InstallDir
    $s.IconLocation = "$icon,0"
    $s.Description = $AppName
    if ($hotkey) { $s.Hotkey = $hotkey }
    $s.Save()
}
$runArgs = "`"$script`" --open"
New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk") $pythonw $runArgs "CTRL+ALT+B"
New-Shortcut (Join-Path $startMenu "$AppName.lnk") $pythonw $runArgs
New-Shortcut (Join-Path $startMenu "$AppName - Update.lnk") "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\update.ps1`""
New-Shortcut (Join-Path $startMenu "$AppName - Reports folder.lnk") "explorer.exe" "`"$HomeDir\reports`""
New-Shortcut (Join-Path $startMenu "$AppName - Settings.lnk") "notepad.exe" "`"$userCfg`""
New-Shortcut (Join-Path $startMenu "$AppName - Uninstall.lnk") "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\uninstall.ps1`""
Say "Shortcuts: Desktop + Start menu (hotkey Ctrl+Alt+B)"

# 6. Daily schedule ------------------------------------------------------------
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($NoSchedule) {
    Say "Daily schedule skipped (-NoSchedule)."
} elseif ($Quiet -and $existing) {
    # Update: keep the user's time, just refresh the program path
    $existing.Actions[0].Execute = $pythonw
    $existing.Actions[0].Arguments = "`"$script`" --quiet"
    Set-ScheduledTask -TaskName $TaskName -Action $existing.Actions[0] | Out-Null
    Say "Daily schedule kept."
} else {
    $action   = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`" --quiet" -WorkingDirectory $InstallDir
    $trigger  = New-ScheduledTaskTrigger -Daily -At $Time
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "Builds the Daily Brief report each morning." -Force | Out-Null
    Say "Daily brief scheduled for $Time (runs at next login if the PC was off)."
}

# 7. First run -----------------------------------------------------------------
Say "Building today's brief..."
$runArgs = @($script, "--quiet")
if (-not $Quiet) { $runArgs += "--open" }
$ErrorActionPreference = "Continue"
& $python @runArgs
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -eq 2) { Say "No feeds could be reached - check your internet connection, then use the desktop icon." "Yellow" }

Write-Host ""
Say "Done. Reports are saved in $HomeDir\reports" "Green"
Write-Host ""
