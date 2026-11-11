; CleanYourMail 0.6.1 - per-user installer (no administrator required).
;
; The app and its frozen CLI sidecar are installed under
; %LOCALAPPDATA%\Programs\CleanYourMail. Build it with:
;   scripts/build-app.ps1
; or directly:
;   ISCC.exe packaging\installer.iss
;
; 0.6.1 is not code-signed. Windows SmartScreen may warn on first launch; the
; SHA-256 published with the release lets users verify the download. Feedback
; is opt-in: nothing is sent unless the person presses Send in the app dialog.

#define MyAppName "CleanYourMail"
#define MyAppVersion "0.6.1"
#define MyAppPublisher "CleanYourMail contributors"
#define MyAppURL "https://github.com/jparedesDS/cleanyourmail-app"
#define MyAppExeName "CleanYourMail.exe"

[Setup]
AppId={{3B9F2C64-7D18-4A0E-9C5B-6E2A81F4D7C3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion=0.6.1.0
DefaultDirName={localappdata}\Programs\CleanYourMail
DefaultGroupName=CleanYourMail
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=CleanYourMail-Setup-0.6.1
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

; Use the CleanYourMail brand icon for the installer when packaging/app.ico
; exists (it is committed). If SVG conversion failed and the file was removed,
; fall back to Inno Setup's default icon instead of failing the build.
#if FileExists(AddBackslash(SourcePath) + "..\packaging\app.ico")
SetupIconFile=..\packaging\app.ico
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\dist\CleanYourMail\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\CleanYourMail"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Clean up your inbox with a reversible, reviewed plan"
Name: "{autodesktop}\CleanYourMail"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,CleanYourMail}"; Flags: nowait postinstall skipifsilent

; Intentionally no [UninstallDelete] section.
;
; Inno removes only the files it installed and the shortcuts it created. The
; user's config and preferences live in %APPDATA%\cleanyourmail-app, the app
; password lives in %USERPROFILE%\.secrets\cleanyourmail.txt, the Outlook
; refresh token lives in %USERPROFILE%\.secrets\cleanyourmail-oauth.json and
; the CLI state lives under %LOCALAPPDATA%. Uninstalling keeps all of them so a
; reinstall, an upgrade or the CLI does not lose the account or the undo
; journal. Never add an [UninstallDelete] entry for those paths.
