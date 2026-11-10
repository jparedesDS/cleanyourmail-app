<#
.SYNOPSIS
    Silent per-user install/uninstall smoke test for the built CleanYourMail installer.

.DESCRIPTION
    Installs dist\CleanYourMail-Setup-0.3.0.exe with /CURRENTUSER, runs the
    installed --version, uninstalls it, and asserts that the app directory and
    Start Menu shortcut are gone while the user-data sentinels survive:

        %APPDATA%\cleanyourmail-app\settings.json
        %USERPROFILE%\.secrets\cleanyourmail.txt
        %LOCALAPPDATA%\CleanYourMail

    Existing user data is never read. The script records Test-Path, file length
    and LastWriteTimeUtc only; it never hashes or prints the contents of a
    secret. Anything the script creates is removed in finally.

    This is separate from build-app.ps1 on purpose: building an installer must
    not install it, and CI does not want to run an interactive per-user install
    on the runner.

.PARAMETER SetupPath
    Installer to smoke. Defaults to dist\CleanYourMail-Setup-0.3.0.exe.
#>
[CmdletBinding()]
param(
    [string]$SetupPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($SetupPath)) {
    $SetupPath = Join-Path $Root "dist\CleanYourMail-Setup-0.3.0.exe"
}
$SetupPath = (Resolve-Path -LiteralPath $SetupPath).Path

$AppDir = Join-Path $env:LOCALAPPDATA "Programs\CleanYourMail"
$AppExe = Join-Path $AppDir "CleanYourMail.exe"
$Uninstaller = Join-Path $AppDir "unins000.exe"
$StartMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "CleanYourMail.lnk"

$SettingsDir = Join-Path $env:APPDATA "cleanyourmail-app"
$SettingsFile = Join-Path $SettingsDir "settings.json"
$SecretDir = Join-Path $env:USERPROFILE ".secrets"
$SecretFile = Join-Path $SecretDir "cleanyourmail.txt"
$StateDir = Join-Path $env:LOCALAPPDATA "CleanYourMail"
$StateFile = Join-Path $StateDir ("task-12-state-sentinel-" + [guid]::NewGuid().ToString("N") + ".txt")

$CreatedSettingsDir = $false
$CreatedSettingsFile = $false
$CreatedSecretDir = $false
$CreatedSecretFile = $false
$CreatedStateDir = $false
$CreatedStateFile = $false
$Installed = $false
$Uninstalled = $false

function Get-PathState {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{
            Exists = $false
            IsDirectory = $false
            Length = $null
            ModifiedUtc = $null
        }
    }

    # Get-Item reads metadata only; it never opens or hashes file content.
    $item = Get-Item -LiteralPath $Path -Force
    $length = $null
    if (-not $item.PSIsContainer) {
        $length = $item.Length
    }
    return [pscustomobject]@{
        Exists = $true
        IsDirectory = $item.PSIsContainer
        Length = $length
        ModifiedUtc = $item.LastWriteTimeUtc.ToString("o")
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Unchanged {
    param(
        [Parameter(Mandatory = $true)]$Before,
        [Parameter(Mandatory = $true)]$After,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Assert-True $After.Exists "$Label disappeared"
    Assert-True ($After.IsDirectory -eq $Before.IsDirectory) "$Label changed type"
    Assert-True ($After.Length -eq $Before.Length) "$Label length changed"
    Assert-True ($After.ModifiedUtc -eq $Before.ModifiedUtc) "$Label timestamp changed"
}

try {
    Assert-True (Test-Path -LiteralPath $SetupPath) "installer missing: $SetupPath"
    Assert-True (-not (Test-Path -LiteralPath $AppDir)) "a CleanYourMail install already exists: $AppDir"

    # App settings sentinel: create only what is absent and remember exactly
    # what this script owns so finally can remove it without touching real data.
    if (-not (Test-Path -LiteralPath $SettingsDir)) {
        New-Item -ItemType Directory -Force -Path $SettingsDir | Out-Null
        $CreatedSettingsDir = $true
    }
    if (-not (Test-Path -LiteralPath $SettingsFile)) {
        Set-Content -LiteralPath $SettingsFile -Encoding UTF8 -Value '{"sentinel":"task-12-installer-smoke","language":"en"}'
        $CreatedSettingsFile = $true
    }

    # Secret sentinel: an existing file is metadata-only. Never hash or print it.
    if (-not (Test-Path -LiteralPath $SecretDir)) {
        New-Item -ItemType Directory -Force -Path $SecretDir | Out-Null
        $CreatedSecretDir = $true
    }
    if (-not (Test-Path -LiteralPath $SecretFile)) {
        Set-Content -LiteralPath $SecretFile -Encoding UTF8 -Value "task-12-installer-smoke-not-a-secret"
        $CreatedSecretFile = $true
    }

    # CLI state sentinel. The pinned CLI (v1.2.2) stores state under
    # %LOCALAPPDATA%\CleanYourMail\<account-key> (tools/config.py); CYM_STATE_DIR
    # would override it, but the app never sets it. Use a unique file in the
    # state root so real account state files are never modified or removed.
    if (-not (Test-Path -LiteralPath $StateDir)) {
        New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
        $CreatedStateDir = $true
    }
    Set-Content -LiteralPath $StateFile -Encoding UTF8 -Value "task-12-state-sentinel"
    $CreatedStateFile = $true

    $settingsDirBefore = Get-PathState $SettingsDir
    $settingsFileBefore = Get-PathState $SettingsFile
    $secretDirBefore = Get-PathState $SecretDir
    $secretFileBefore = Get-PathState $SecretFile
    $stateDirBefore = Get-PathState $StateDir
    $stateFileBefore = Get-PathState $StateFile

    Write-Host "==> Installing per-user (silent)"
    $installLog = Join-Path $env:TEMP "clean-your-mail-install.log"
    Remove-Item -LiteralPath $installLog -ErrorAction SilentlyContinue
    $install = Start-Process -FilePath $SetupPath `
        -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/LOG=`"$installLog`"") `
        -Wait -PassThru
    $Installed = $true
    Write-Host "installer exit: $($install.ExitCode)"
    Write-Host "install log: $installLog"
    Assert-True ($install.ExitCode -eq 0) "installer exited $($install.ExitCode)"
    Assert-True (Test-Path -LiteralPath $AppExe) "installed app missing: $AppExe"
    Assert-True (Test-Path -LiteralPath $StartMenu) "Start Menu shortcut missing: $StartMenu"
    Write-Host "installed exe: $AppExe"
    Write-Host "installed size: $((Get-Item $AppExe).Length) bytes"
    Write-Host "start menu: $StartMenu"

    Write-Host "==> Running the installed app --version"
    $versionOut = Join-Path $env:TEMP "clean-your-mail-installed-version.txt"
    $versionErr = Join-Path $env:TEMP "clean-your-mail-installed-version.err.txt"
    Remove-Item -LiteralPath $versionOut, $versionErr -ErrorAction SilentlyContinue
    $appProcess = Start-Process -FilePath $AppExe `
        -ArgumentList "--version" `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $versionOut `
        -RedirectStandardError $versionErr
    $versionText = ""
    if (Test-Path -LiteralPath $versionOut) {
        $versionText = Get-Content -LiteralPath $versionOut -Raw
    }
    $versionErrorText = ""
    if (Test-Path -LiteralPath $versionErr) {
        $versionErrorText = Get-Content -LiteralPath $versionErr -Raw
    }
    Write-Host "installed app exit: $($appProcess.ExitCode)"
    Assert-True ($appProcess.ExitCode -eq 0) "installed app exited $($appProcess.ExitCode); stderr:`n$versionErrorText"
    if ([string]::IsNullOrWhiteSpace($versionText)) {
        Write-Host "installed app --version produced no output."
        throw "installed app --version produced no output (exit 0); stderr:`n$versionErrorText"
    }
    $version = $versionText.Trim()
    Write-Host "installed app version: $version"
    Assert-True ($version -eq "CleanYourMail app 0.3.0") "unexpected installed version: '$version'"

    Write-Host "==> Uninstalling per-user (silent)"
    Assert-True (Test-Path -LiteralPath $Uninstaller) "uninstaller missing: $Uninstaller"
    $uninstallLog = Join-Path $env:TEMP "clean-your-mail-uninstall.log"
    Remove-Item -LiteralPath $uninstallLog -ErrorAction SilentlyContinue
    $uninstall = Start-Process -FilePath $Uninstaller `
        -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$uninstallLog`"") `
        -Wait -PassThru
    $Uninstalled = $true
    Write-Host "uninstaller exit: $($uninstall.ExitCode)"
    Write-Host "uninstall log: $uninstallLog"
    Assert-True ($uninstall.ExitCode -eq 0) "uninstaller exited $($uninstall.ExitCode)"
    Assert-True (-not (Test-Path -LiteralPath $AppExe)) "app executable survived uninstall: $AppExe"
    Assert-True (-not (Test-Path -LiteralPath $AppDir)) "app directory survived uninstall: $AppDir"
    Assert-True (-not (Test-Path -LiteralPath $StartMenu)) "Start Menu shortcut survived uninstall: $StartMenu"

    Assert-Unchanged $settingsDirBefore (Get-PathState $SettingsDir) "settings directory"
    Assert-Unchanged $settingsFileBefore (Get-PathState $SettingsFile) "settings sentinel"
    Assert-Unchanged $secretDirBefore (Get-PathState $SecretDir) "secrets directory"
    Assert-Unchanged $secretFileBefore (Get-PathState $SecretFile) "secret sentinel"
    Assert-Unchanged $stateDirBefore (Get-PathState $StateDir) "CLI state directory"
    Assert-Unchanged $stateFileBefore (Get-PathState $StateFile) "CLI state sentinel"

    Write-Host "settings sentinel: survived (metadata unchanged)"
    Write-Host "secret sentinel:   survived (metadata unchanged; content never read)"
    Write-Host "CLI state sentinel: survived (metadata unchanged)"
    Write-Host "SMOKE OK"
}
finally {
    if ($Installed -and -not $Uninstalled -and (Test-Path -LiteralPath $Uninstaller)) {
        Write-Warning "Attempting cleanup uninstall after an earlier failure."
        try {
            $cleanup = Start-Process -FilePath $Uninstaller `
                -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
                -Wait -PassThru
            Write-Warning "cleanup uninstall exit: $($cleanup.ExitCode)"
        }
        catch {
            Write-Warning "cleanup uninstall failed: $($_.Exception.Message)"
        }
    }

    if ($CreatedStateFile -and (Test-Path -LiteralPath $StateFile)) {
        Remove-Item -LiteralPath $StateFile -Force
    }
    if ($CreatedStateDir -and (Test-Path -LiteralPath $StateDir)) {
        $remaining = @(Get-ChildItem -LiteralPath $StateDir -Force)
        if ($remaining.Count -eq 0) { Remove-Item -LiteralPath $StateDir -Force }
    }
    if ($CreatedSettingsFile -and (Test-Path -LiteralPath $SettingsFile)) {
        Remove-Item -LiteralPath $SettingsFile -Force
    }
    if ($CreatedSettingsDir -and (Test-Path -LiteralPath $SettingsDir)) {
        $remaining = @(Get-ChildItem -LiteralPath $SettingsDir -Force)
        if ($remaining.Count -eq 0) { Remove-Item -LiteralPath $SettingsDir -Force }
    }
    if ($CreatedSecretFile -and (Test-Path -LiteralPath $SecretFile)) {
        Remove-Item -LiteralPath $SecretFile -Force
    }
    if ($CreatedSecretDir -and (Test-Path -LiteralPath $SecretDir)) {
        $remaining = @(Get-ChildItem -LiteralPath $SecretDir -Force)
        if ($remaining.Count -eq 0) { Remove-Item -LiteralPath $SecretDir -Force }
    }
}
