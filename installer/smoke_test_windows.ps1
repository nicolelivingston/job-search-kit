# Installs a freshly built installer on a clean Windows machine and checks it
# the way a new user would meet it: the checksum matches, files and Start menu
# items are in place, setup's folder step works, the agent finishes a dry run
# against a made-up test person, an error report saves, and uninstalling
# keeps the user's Job Search folder.
#
# Used by two workflows so they can't drift apart:
#   checks.yml   on every pull request, before anything reaches main
#   release.yml  on every release tag, before anything is published
#
#   ./installer/smoke_test_windows.ps1 -Dist dist
param([string]$Dist = "dist")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

$exe = Get-ChildItem $Dist -Filter "JobSearchKit-Setup-*.exe" | Select-Object -First 1
if (-not $exe) { throw "no installer in $Dist" }
$want = (Get-Content (Join-Path $Dist "SHA256SUMS.txt") | Where-Object { $_ -like "*$($exe.Name)" }).Split(" ")[0]
if ((Get-FileHash $exe.FullName -Algorithm SHA256).Hash.ToLower() -ne $want) { throw "checksum mismatch" }

Write-Host "Installing $($exe.Name) silently"
Start-Process $exe.FullName -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait
$app = "$env:LOCALAPPDATA\JobSearchKit"
foreach ($f in "python\python.exe","app\wizard.py","app\first_run.py","app\VERSION","plugin\.claude-plugin\plugin.json","templates\settings\criteria.json") {
  if (-not (Test-Path "$app\$f")) { throw "missing $f" } }
$menu = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Job Search Kit"
foreach ($l in "Open my job tracker","Change my settings","Send an error report","Check for updates") {
  if (-not (Test-Path "$menu\$l.lnk")) { throw "missing Start menu item $l" } }
Write-Host "Installed version $(Get-Content "$app\app\VERSION")"

# First run: choose a local-only folder (as the wizard's first step does)
$env:KIT_CONFIG_DIR = "$env:TEMP\kitcfg"
& "$app\python\python.exe" -c "import sys; sys.path.insert(0, r'$app\app'); import first_run; print(first_run.choose('local'))"
if ($LASTEXITCODE -ne 0) { throw "first-run folder step failed" }

# A dry agent run with the blank template settings a new user starts from
$env:KIT_SETTINGS_DIR = "$env:USERPROFILE\Job Search\settings"
New-Item -ItemType Directory -Force $env:KIT_SETTINGS_DIR | Out-Null
Copy-Item "$app\templates\settings\*" $env:KIT_SETTINGS_DIR -Force
$env:AGENT_DRY_RUN = "1"
& "$app\python\python.exe" "$app\app\agent\job_search_agent.py" --quick
if ($LASTEXITCODE -ne 0) { throw "agent dry run failed with the template settings" }

# The same dry run as the made-up test person (filled-in settings, no real data)
$priya = Join-Path $root "examples\priya-healthtech-pm\settings"
if (Test-Path $priya) {
  $env:KIT_SETTINGS_DIR = $priya
  & "$app\python\python.exe" "$app\app\agent\job_search_agent.py" --quick
  if ($LASTEXITCODE -ne 0) { throw "agent dry run failed with the test person's settings" }
  $env:KIT_SETTINGS_DIR = "$env:USERPROFILE\Job Search\settings"
}

& "$app\python\python.exe" "$app\app\error_report.py" --save-only
if ($LASTEXITCODE -ne 0) { throw "saving an error report failed" }

Write-Host "Uninstalling"
Start-Process "$app\unins000.exe" -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait
if (-not (Test-Path "$env:USERPROFILE\Job Search\settings\criteria.json")) { throw "uninstall removed the user's folder" }
Write-Host "Windows install check passed"
