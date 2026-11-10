<#
.SYNOPSIS
    Build the CleanYourMail app, its frozen CLI sidecar and the per-user installer.

.DESCRIPTION
    1. scripts/build-cli-sidecar.ps1 stages resources/cli/cym-cli.exe.
    2. packaging/app.ico is generated from the SVG when missing.
    3. PyInstaller builds dist/CleanYourMail from cleanyourmail-app.spec.
    4. The shipped tree and both executables are smoke-tested.
    5. Inno Setup builds dist/CleanYourMail-Setup-0.3.0.exe.

    Inno Setup 6 is required for the installer. If ISCC.exe is not installed the
    script fails with an explicit message after the app itself has been built;
    it never creates a placeholder installer. The app and installer are per-user:
    no administrator rights are needed.

.PARAMETER Python
    Python executable used for the sidecar and app builds. Defaults to "python".

.PARAMETER SkipSidecar
    Reuse resources/ from a previous sidecar build. CI uses this to keep the
    build steps separate.

.PARAMETER SkipInstaller
    Build and smoke-test the app but do not run Inno Setup. CI uses this before
    installing the compiler; the exact build-app.ps1 command builds everything.
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipSidecar,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SidecarScript = Join-Path $PSScriptRoot "build-cli-sidecar.ps1"
$IconScript = Join-Path $PSScriptRoot "make-icon.py"
$Icon = Join-Path $Root "packaging\app.ico"
$IconSource = Join-Path $Root "src\cleanyourmail_app\ui\resources\app-icon.svg"
$Spec = Join-Path $Root "cleanyourmail-app.spec"
$InstallerScript = Join-Path $Root "packaging\installer.iss"
$Dist = Join-Path $Root "dist"
$AppDist = Join-Path $Dist "CleanYourMail"
$AppExe = Join-Path $AppDist "CleanYourMail.exe"
$SidecarExe = Join-Path $AppDist "resources\cli\cym-cli.exe"
$SetupExe = Join-Path $Dist "CleanYourMail-Setup-0.3.0.exe"

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

function Find-InnoCompiler {
    $candidates = New-Object System.Collections.Generic.List[string]

    $onPath = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($null -ne $onPath) {
        $candidates.Add($onPath.Source)
    }

    if (-not [string]::IsNullOrWhiteSpace($env:INNO_SETUP_ISCC)) {
        $candidates.Add($env:INNO_SETUP_ISCC)
    }
    if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
        $candidates.Add((Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"))
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidates.Add((Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"))
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"))
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

# ---------------------------------------------------------------------------
# 1. Sidecar.
# ---------------------------------------------------------------------------
if ($SkipSidecar) {
    Write-Host "==> Reusing the staged sidecar"
    if (-not (Test-Path (Join-Path $Root "resources\cli\cym-cli.exe"))) {
        throw "-SkipSidecar was set but resources\cli\cym-cli.exe is missing. Run scripts/build-cli-sidecar.ps1 first."
    }
}
else {
    & $SidecarScript -Python $Python
}

# ---------------------------------------------------------------------------
# 2. Icon. The brand SVG is mirrored in the package; conversion is optional
#    because the design allows the default Inno/PyInstaller icon.
# ---------------------------------------------------------------------------
if (-not (Test-Path $Icon)) {
    Write-Host "==> Generating packaging\app.ico from app-icon.svg"
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Python $IconScript "--source" $IconSource "--output" $Icon
        $iconExit = $LASTEXITCODE
    }
    catch {
        $iconExit = 1
        Write-Host $_.Exception.Message
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }

    if ($iconExit -ne 0 -or -not (Test-Path $Icon)) {
        Write-Warning "Could not generate packaging\app.ico; building with the default icon."
        if (Test-Path $Icon) {
            Remove-Item -LiteralPath $Icon -Force
        }
    }
}

# ---------------------------------------------------------------------------
# 3. Freeze the Qt app (onedir, windowed).
# ---------------------------------------------------------------------------
Remove-IfPresent $AppDist
$appWork = Join-Path $Root "build\pyinstaller-app"
Remove-IfPresent $appWork

Invoke-Native "Freeze the app with PyInstaller" $Python @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--distpath", $Dist,
    "--workpath", $appWork,
    $Spec
)

if (-not (Test-Path $AppExe)) {
    throw "PyInstaller completed but did not produce $AppExe."
}

# The spec decides what goes in; verify the built tree independently so a
# datas/Tree regression fails here and not during the first wizard launch.
$requiredFiles = @(
    (Join-Path $AppDist "resources\cli\cym-cli.exe"),
    (Join-Path $AppDist "cleanyourmail_app\ui\theme.qss"),
    (Join-Path $AppDist "cleanyourmail_app\ui\resources\app-icon.svg"),
    (Join-Path $AppDist "cleanyourmail_app\i18n\en.json"),
    (Join-Path $AppDist "cleanyourmail_app\i18n\es.json")
)
foreach ($required in $requiredFiles) {
    if (-not (Test-Path $required)) {
        throw "The built app is missing a required file: $required"
    }
}

# ---------------------------------------------------------------------------
# 4. Smoke-test the shipped executables from a different working directory.
# ---------------------------------------------------------------------------
$originalLocation = Get-Location
try {
    Set-Location $env:TEMP

    $sidecarVersion = (& $SidecarExe "--version" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $sidecarVersion -ne "CleanYourMail 1.2.2") {
        throw "Sidecar smoke test failed: expected 'CleanYourMail 1.2.2', got '$sidecarVersion' (exit $LASTEXITCODE)."
    }

    $appVersionFile = Join-Path $Root "build\app-version.txt"
    $appErrorFile = Join-Path $Root "build\app-version.err.txt"
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "build") | Out-Null
    Remove-IfPresent $appVersionFile
    Remove-IfPresent $appErrorFile
    $appProcess = Start-Process -FilePath $AppExe `
        -ArgumentList "--version" `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $appVersionFile `
        -RedirectStandardError $appErrorFile
    $appVersion = (Get-Content -LiteralPath $appVersionFile -Raw).Trim()
    if ($appProcess.ExitCode -ne 0 -or $appVersion -ne "CleanYourMail app 0.3.0") {
        $appError = ""
        if (Test-Path $appErrorFile) {
            $appError = (Get-Content -LiteralPath $appErrorFile -Raw).Trim()
        }
        throw "App smoke test failed: expected 'CleanYourMail app 0.3.0', got '$appVersion' (exit $($appProcess.ExitCode)).`n$appError"
    }
}
finally {
    Set-Location $originalLocation
}

Write-Host "Smoke tests passed: $sidecarVersion / $appVersion"

# ---------------------------------------------------------------------------
# 5. Per-user installer.
# ---------------------------------------------------------------------------
if ($SkipInstaller) {
    Write-Host ""
    Write-Host "Installer skipped (-SkipInstaller). App ready at $AppExe."
    exit 0
}

$iscc = Find-InnoCompiler
if ($null -eq $iscc) {
    throw @"
Inno Setup 6 compiler (ISCC.exe) was not found.
Install it and rerun this script:
    choco install innosetup -y
or download it from https://jrsoftware.org/isdl.php
The app itself was built successfully at:
    $AppExe
The installer script is ready at:
    $InstallerScript
No installer was created.
"@
}

Remove-IfPresent $SetupExe
Invoke-Native "Build the per-user installer" $iscc @("/Qp", $InstallerScript)

if (-not (Test-Path $SetupExe)) {
    throw "Inno Setup completed but did not produce $SetupExe."
}

$setupSizeMb = [math]::Round((Get-Item $SetupExe).Length / 1MB, 1)
Write-Host ""
Write-Host "Packaging complete."
Write-Host "  app:       $AppExe"
Write-Host "  sidecar:   $SidecarExe"
Write-Host "  installer: $SetupExe ($setupSizeMb MB)"
exit 0
