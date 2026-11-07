# Builds dist/JobSearchKit-Setup-<version>.exe on a Windows machine, plus
# dist/job-search-kit.plugin and dist/SHA256SUMS.txt.
#
# Every download is pinned: the Python build by exact version and SHA-256
# (python-build-standalone's published checksum, verified independently on
# Oct 31, 2026), and every pip package by exact version and wheel hash
# (installer/requirements-windows.txt, pip --require-hashes). A changed byte
# anywhere fails the build instead of shipping.
param([string]$Version = "v0.0.0-dev")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root "build"
$dist = Join-Path $root "dist"
Remove-Item $build -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $build | Out-Null
New-Item -ItemType Directory -Force $dist | Out-Null

function Assert-Sha256($path, $expected) {
  $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
  if ($actual -ne $expected.ToLower()) { throw "Checksum mismatch for $path`n expected $expected`n got      $actual" }
}

# 1. Python (python-build-standalone, install_only_stripped: a normal layout with pip, no admin rights)
$PyRelease = "20261026"
$PyFile = "cpython-3.12.16+$PyRelease-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$PySha = "1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149"
$tar = Join-Path $build "python.tar.gz"
Invoke-WebRequest ("https://github.com/astral-sh/python-build-standalone/releases/download/$PyRelease/" + [uri]::EscapeDataString($PyFile)) -OutFile $tar
Assert-Sha256 $tar $PySha
tar -xzf $tar -C $build          # creates build\python
$py = Join-Path $build "python\python.exe"
& $py -m pip install --no-warn-script-location --require-hashes --only-binary=:all: -r (Join-Path $PSScriptRoot "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 2. The kit itself (code, templates, plugin, docs; never dev-settings, dev, or examples)
$stage = Join-Path $build "kit"
New-Item -ItemType Directory $stage | Out-Null
Copy-Item (Join-Path $root "app") $stage -Recurse
Copy-Item (Join-Path $root "templates") $stage -Recurse
Copy-Item (Join-Path $root "plugin") $stage -Recurse
Copy-Item (Join-Path $root "SETTINGS.md"), (Join-Path $root "README.md"), (Join-Path $root "SUPPORT.md"), (Join-Path $root "LICENSE"), (Join-Path $root "THIRD_PARTY_NOTICES.md") $stage
Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem $stage -Recurse -Directory -Filter "agent_tests" | Remove-Item -Recurse -Force
$Version.TrimStart("v") | Set-Content (Join-Path $stage "app\VERSION")

# 2b. The Claude plugin, packaged for the release page too
$pluginZip = Join-Path $dist "job-search-kit.plugin.zip"
Compress-Archive -Path (Join-Path $stage "plugin\*") -DestinationPath $pluginZip -Force
Move-Item $pluginZip (Join-Path $dist "job-search-kit.plugin") -Force

# 3. Inno Setup (preinstalled on GitHub's Windows runners; choco elsewhere)
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 is not installed at $iscc (GitHub's windows runners have it; install it by hand elsewhere). No unpinned downloads here." }
& $iscc "/DAppVersion=$($Version.TrimStart('v'))" "/DBuildDir=$build" (Join-Path $PSScriptRoot "kit.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

# 4. Checksums the updater verifies before it runs anything
$sums = Join-Path $dist "SHA256SUMS.txt"
Get-ChildItem $dist -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
  "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
} | Set-Content $sums -Encoding ascii
Get-Content $sums
