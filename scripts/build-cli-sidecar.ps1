<#
.SYNOPSIS
    Build the pinned CleanYourMail CLI as a frozen onedir sidecar.

.DESCRIPTION
    Clones the CLI at the requested tag into .build/cli-src, writes a tiny
    launcher that imports ``mail`` from the checkout's ``tools`` directory and
    freezes it with PyInstaller, then stages the result for the app build:

        resources/cli/cym-cli.exe   (plus the onedir files)

    The exact executable that ships is smoke-tested from a different working
    directory while the checkout is renamed away, so a successful build proves
    the bundle is self-contained (config, IMAP, planning, journal and undo are
    all frozen inside it). ``--version`` must print ``CleanYourMail 1.2.2`` and
    ``--help`` must exit 0.

    The sidecar is a console-subsystem program. The app launches every call
    with CREATE_NO_WINDOW, so no console window flashes at runtime.

.PARAMETER CliVersion
    Git tag of the CLI to build. The app ships v1.2.2.

.PARAMETER RepoUrl
    Repository to clone the CLI from.

.PARAMETER Python
    Python executable used for PyInstaller. Defaults to "python".

.PARAMETER Force
    Re-clone the source even when the checkout already has the requested tag.
#>
[CmdletBinding()]
param(
    [string]$CliVersion = "v1.2.2",
    [string]$RepoUrl = "https://github.com/jparedesDS/cleanyourmail",
    [string]$Python = "python",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Build = Join-Path $Root ".build"
$Source = Join-Path $Build "cli-src"
$Tools = Join-Path $Source "tools"
$Launcher = Join-Path $Build "cli-launcher.py"
$Dist = Join-Path $Build "cli-dist"
$Work = Join-Path $Build "cli-work"
$SpecDir = Join-Path $Build "cli-spec"
$CliTarget = Join-Path $Root "resources\cli"
$FrozenExe = Join-Path $CliTarget "cym-cli.exe"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Write-Host "==> $Description"
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Remove-IfPresent {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

New-Item -ItemType Directory -Force -Path $Build | Out-Null

# ---------------------------------------------------------------------------
# 1. Clone the pinned tag. A checkout is reused only when it is exactly at the
#    requested tag, clean, and cloned from the expected origin. Anything else
#    (a dirty tree, a moved tag, a fork) is rebuilt from scratch.
# ---------------------------------------------------------------------------
$reuseSource = $false
if (-not $Force -and (Test-Path (Join-Path $Source ".git"))) {
    $describeExit = 1
    $originExit = 1
    $statusExit = 1
    $existingTag = ""
    $origin = ""
    $status = ""
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $existingTag = (& git -C $Source describe --tags --exact-match 2>$null | Out-String).Trim()
        $describeExit = $LASTEXITCODE
        $origin = (& git -C $Source remote get-url origin 2>$null | Out-String).Trim()
        $originExit = $LASTEXITCODE
        $status = (& git -C $Source status --porcelain 2>$null | Out-String).Trim()
        $statusExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }

    $expectedOrigin = $RepoUrl.Trim().TrimEnd("/")
    $actualOrigin = $origin.Trim().TrimEnd("/")
    if ($actualOrigin.ToLowerInvariant().EndsWith(".git")) {
        $actualOrigin = $actualOrigin.Substring(0, $actualOrigin.Length - 4)
    }
    if ($expectedOrigin.ToLowerInvariant().EndsWith(".git")) {
        $expectedOrigin = $expectedOrigin.Substring(0, $expectedOrigin.Length - 4)
    }
    $originMatches = [string]::Equals(
        $actualOrigin,
        $expectedOrigin,
        [System.StringComparison]::OrdinalIgnoreCase
    )

    if (
        $describeExit -eq 0 -and
        $existingTag -eq $CliVersion -and
        $statusExit -eq 0 -and
        [string]::IsNullOrWhiteSpace($status) -and
        $originExit -eq 0 -and
        $originMatches
    ) {
        $reuseSource = $true
    }
    else {
        Write-Host "==> Existing checkout is not a clean $CliVersion checkout of $RepoUrl; re-cloning"
    }
}

if ($reuseSource) {
    Write-Host "==> Reusing the CleanYourMail checkout at $CliVersion"
}
else {
    Remove-IfPresent $Source
    Invoke-Native "Clone CleanYourMail at $CliVersion" "git" @(
        "clone", "--depth", "1", "--branch", $CliVersion, $RepoUrl, $Source
    )
}

if (-not (Test-Path (Join-Path $Tools "mail.py"))) {
    throw "The checkout at $Source does not look like CleanYourMail (tools/mail.py is missing)."
}

# ---------------------------------------------------------------------------
# 2. Freeze the launcher. The launcher only adjusts sys.path when it is not
#    frozen; at runtime the modules come from the PyInstaller bundle.
# ---------------------------------------------------------------------------
$launcherText = @'
"""PyInstaller entry point for the pinned CleanYourMail CLI sidecar."""

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "cli-src" / "tools"))

import mail  # noqa: E402


if __name__ == "__main__":
    sys.exit(mail.main())
'@
[System.IO.File]::WriteAllText($Launcher, $launcherText, [System.Text.UTF8Encoding]::new($false))

Remove-IfPresent $Dist
Remove-IfPresent $Work
Remove-IfPresent $SpecDir
Invoke-Native "Freeze the CleanYourMail sidecar with PyInstaller" $Python @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--name", "cym-cli",
    "--paths", $Tools,
    "--distpath", $Dist,
    "--workpath", $Work,
    "--specpath", $SpecDir,
    $Launcher
)

$builtExe = Join-Path $Dist "cym-cli\cym-cli.exe"
if (-not (Test-Path $builtExe)) {
    throw "PyInstaller completed but did not produce $builtExe."
}

# ---------------------------------------------------------------------------
# 3. Stage resources for the app and installer.
# ---------------------------------------------------------------------------
Remove-IfPresent $CliTarget
New-Item -ItemType Directory -Force -Path $CliTarget | Out-Null
Copy-Item -Path (Join-Path $Dist "cym-cli\*") -Destination $CliTarget -Recurse -Force

if (-not (Test-Path $FrozenExe)) {
    throw "The frozen sidecar was not staged at $FrozenExe."
}

# ---------------------------------------------------------------------------
# 4. Smoke-test the exact executable that ships. The checkout is renamed away
#    and the process runs from %TEMP%: if the bundle needed Python files from
#    the checkout, these commands would fail or leave a traceback.
# ---------------------------------------------------------------------------
$originalLocation = Get-Location
$hiddenSource = $null
try {
    if (Test-Path $Source) {
        $hiddenSource = "$Source.hidden"
        Remove-IfPresent $hiddenSource
        Rename-Item -LiteralPath $Source -NewName (Split-Path $hiddenSource -Leaf)
    }
    Set-Location $env:TEMP

    $version = (& $FrozenExe "--version" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "The frozen sidecar --version failed with exit code $LASTEXITCODE."
    }
    if ($version -ne "CleanYourMail 1.2.2") {
        throw "Expected sidecar version 'CleanYourMail 1.2.2', got '$version'."
    }

    $null = (& $FrozenExe "--help" 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "The frozen sidecar --help failed with exit code $LASTEXITCODE."
    }

    # Validate with an absent config: this exercises the frozen config module
    # and proves the sidecar fails with a clean config error and no traceback.
    # The clean error goes to stderr, which Windows PowerShell would otherwise
    # promote to a terminating error.
    $missingConfig = Join-Path $env:TEMP ("cym-missing-" + [guid]::NewGuid().ToString("N") + ".toml")
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $validation = (& $FrozenExe "validate" "--config" $missingConfig 2>&1 | Out-String).Trim()
        $validationExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($validationExit -eq 0) {
        throw "The frozen sidecar validate unexpectedly succeeded without a config."
    }
    if ($validation -notmatch "Config file not found") {
        throw "Expected a clean 'Config file not found' error, got:`n$validation"
    }
    if ($validation -match "Traceback") {
        throw "The frozen sidecar printed a traceback:`n$validation"
    }
}
finally {
    Set-Location $originalLocation
    if ($null -ne $hiddenSource -and (Test-Path $hiddenSource)) {
        Rename-Item -LiteralPath $hiddenSource -NewName (Split-Path $Source -Leaf)
    }
}

Write-Host ""
Write-Host "Sidecar ready."
Write-Host "  executable: $FrozenExe"
Write-Host "  version:    $version"
Write-Host "  help exit:  0"
Write-Host "  missing config: exit $validationExit (clean error)"
exit 0
