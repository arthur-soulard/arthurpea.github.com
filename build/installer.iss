; ============================================================
;  Suivi PEA - Inno Setup script
;  Compile avec Inno Setup 6+ (https://jrsoftware.org/isdl.php)
;  Produit : dist\Suivi_PEA_Setup.exe
; ============================================================

#define AppName       "Suivi PEA"
#define AppVersion    "3.2.0"
#define AppPublisher  "Arthur"
#define AppExeName    "Suivi_PEA.exe"

[Setup]
AppId={{E1B6F4D2-7C8E-4B5A-9D3F-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Suivi_PEA_Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
LanguageDetectionMethod=uilanguage

[Languages]
Name: "french";  MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Suivi_PEA.exe";   DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\icon.ico";      DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}";          Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#AppName}";           Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: quicklaunchicon

[Run]
; Lancement normal apres installation manuelle (case a cocher)
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
