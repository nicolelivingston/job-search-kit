; Inno Setup script for the Job Search Kit (Windows).
; Installs the code and bundled Python per user (no admin rights needed)
; and opens the setup wizard at the end. The wizard's first step asks where
; the user's Job Search folder should live (Documents, or a local-only folder
; when Documents is synced to OneDrive) and creates it from the templates
; (app/first_run.py). Updates replace the code and Python, never the user's
; folder or settings.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\build"
#endif

[Setup]
AppId={{6E2B1C8A-4F7D-4B8E-9C1A-2D5E7F9A0B3C}
AppName=Job Search Kit
AppVersion={#AppVersion}
AppPublisher=Job Search Kit
DefaultDirName={localappdata}\JobSearchKit
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=JobSearchKit-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
; shown before installing (skipped on silent installs and updates)
InfoBeforeFile=PRIVACY.txt

[Files]
Source: "{#BuildDir}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\kit\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\kit\plugin\*"; DestDir: "{app}\plugin"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\kit\SETTINGS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\kit\README.md"; DestDir: "{app}"; Flags: ignoreversion
; the templates ship with the app; first_run.py copies them into the folder the user picks
Source: "{#BuildDir}\kit\templates\*"; DestDir: "{app}\templates"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userprograms}\Job Search Kit\Open my job tracker"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\wizard.py"" --tracker"; WorkingDir: "{app}\app"
Name: "{userprograms}\Job Search Kit\Change my settings"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\wizard.py"""; WorkingDir: "{app}\app"
Name: "{userprograms}\Job Search Kit\Send an error report"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\error_report.py"""; WorkingDir: "{app}\app"
Name: "{userprograms}\Job Search Kit\Check for updates"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\updater.py"" --now"; WorkingDir: "{app}\app"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\wizard.py"""; WorkingDir: "{app}\app"; Description: "Set up the Job Search Kit now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: """{app}\app\schedule.py"" remove"; Flags: runhidden; RunOnceId: "RemoveSchedule"
