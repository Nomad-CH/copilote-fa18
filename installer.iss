; Installateur Windows du copilote (compile par GitHub Actions avec Inno Setup).
; Installe pour l'utilisateur seul, sans droits administrateur.
#define Version GetEnv("VERSION")

[Setup]
AppId={{8C1B6F0E-2B5D-4C1A-9E7A-F18C0F18C0F1}
AppName=Copilote F/A-18
AppVersion={#Version}
AppVerName=Copilote F/A-18 {#Version}
AppPublisher=Nomad-CH
AppPublisherURL=https://github.com/Nomad-CH/copilote-fa18
DefaultDirName={localappdata}\Programs\CopiloteF18
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=sortie
OutputBaseFilename=CopiloteF18-Setup
SetupIconFile=icone.ico
UninstallDisplayIcon={app}\CopiloteF18.exe
UninstallDisplayName=Copilote F/A-18
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "Créer une icône sur le Bureau"; Flags: checkedonce

[InstallDelete]
; l'ancienne version est remplacee entierement (tes donnees sont ailleurs)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\CopiloteF18\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Copilote FA-18"; Filename: "{app}\CopiloteF18.exe"
Name: "{userdesktop}\Copilote FA-18"; Filename: "{app}\CopiloteF18.exe"; Tasks: bureau

[Run]
Filename: "{app}\CopiloteF18.exe"; Description: "Lancer le copilote"; Flags: nowait postinstall
