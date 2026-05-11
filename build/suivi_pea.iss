; ════════════════════════════════════════════════════════════════════════════
; Suivi PEA — Script Inno Setup
; Genere un Setup.exe propre avec raccourci bureau, menu Demarrer, desinstall.
; ════════════════════════════════════════════════════════════════════════════

#define MyAppName        "Suivi PEA"
#define MyAppVersion     "3.0.4"
#define MyAppPublisher   "Arthur"
#define MyAppExeName     "Suivi_PEA.exe"
#define MyAppId          "{{A7C5D4E2-PEA-4B1A-9F3D-Suivi2026PEA}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes
LicenseFile=
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Suivi_PEA_Setup
SetupIconFile=..\assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
ShowLanguageDialog=no
WizardImageStretch=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le &Bureau"; GroupDescription: "Raccourcis :"; Flags: checkedonce

[Files]
; L'executable principal
Source: "..\dist\Suivi_PEA.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";    Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName} maintenant"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; A la desinstallation, on NE supprime PAS le dossier Donnees pour preserver les
; donnees utilisateur. L'utilisateur doit le supprimer manuellement s'il veut.
Type: dirifempty; Name: "{app}"
