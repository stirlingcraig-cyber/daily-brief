<#
.SYNOPSIS
    Removes Daily Brief. Reports and settings in %USERPROFILE%\DailyBrief are kept unless -All is used.
#>
[CmdletBinding()]
param([switch]$All)

$AppName    = "Daily Brief"
$InstallDir = Join-Path $env:LOCALAPPDATA "DailyBrief"
$HomeDir    = Join-Path $env:USERPROFILE "DailyBrief"

Unregister-ScheduledTask -TaskName "DailyBrief" -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) $AppName) -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
if ($All) { Remove-Item $HomeDir -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host "  $AppName removed." -ForegroundColor Green
if (-not $All) { Write-Host "  Your reports and settings are still in $HomeDir" }
if ($Host.Name -eq "ConsoleHost") { Read-Host "  Press Enter to close" | Out-Null }
