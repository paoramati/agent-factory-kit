# backup-bundle.ps1: Windows version of backup-bundle.sh.
# Usage: powershell -File backup-bundle.ps1 -Repo C:\code\myrepo -Dest "$env:OneDrive\backups\myrepo" -Keep 24
# Schedule every 2 hours:
#   schtasks /Create /SC HOURLY /MO 2 /TN "repo-bundle-backup" `
#     /TR "powershell -NoProfile -File C:\tools\agent-factory-kit\bin\backup-bundle.ps1 -Repo C:\code\myrepo -Dest %OneDrive%\backups\myrepo"
param(
  [Parameter(Mandatory = $true)][string]$Repo,
  [Parameter(Mandatory = $true)][string]$Dest,
  [int]$Keep = 14
)
$ErrorActionPreference = 'Stop'
Set-Location $Repo
$top  = (git rev-parse --show-toplevel).Trim()
$name = Split-Path $top -Leaf
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

if ((Get-Command bd -ErrorAction SilentlyContinue) -and (Test-Path '.beads')) {
  try { bd export -o .beads/backup-export.jsonl | Out-Null
        Copy-Item .beads/backup-export.jsonl (Join-Path $Dest "$name-issues-latest.jsonl") -Force } catch {}
}

git diff --quiet HEAD
if ($LASTEXITCODE -ne 0) { git diff HEAD | Out-File -Encoding utf8 (Join-Path $Dest "$name-$stamp-uncommitted.patch") }

$tmp   = Join-Path $Dest ".$name-$stamp.bundle.tmp"
$final = Join-Path $Dest "$name-$stamp.bundle"
git bundle create $tmp --all 2>$null
git bundle verify $tmp 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { throw "bundle verify failed" }
Move-Item $tmp $final
Write-Output "wrote $final"

Get-ChildItem $Dest -Filter "$name-*.bundle" | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep | Remove-Item -Force
Get-ChildItem $Dest -Filter "$name-*-uncommitted.patch" | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep | Remove-Item -Force
