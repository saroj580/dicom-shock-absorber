; ==============================================================================
; ProRadCS Enterprise DICOM Gateway & Edge Node - Enterprise NSIS Installer
; Version: 1.0.0-PROD | IEC 62304 Class B Medical Device Software Appliance
; ==============================================================================

Unicode true
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "nsDialogs.nsh"

; --- Application & Publisher Definitions ---
!define COMPANYNAME "ProRadCS"
!define APPNAME "ProRadCS Enterprise DICOM Gateway"
!define DESCRIPTION "Zero-Trust On-Premise Medical Imaging Gateway & Shock Absorber"
!define VERSIONMAJOR 1
!define VERSIONMINOR 0
!define VERSIONPATCH 0
!define VERSIONBUILD 0
!define PRODUCT_VERSION "1.0.0-PROD"
!define REG_UNINSTALL "Software\Microsoft\Windows\CurrentVersion\Uninstall\ProRadCS Gateway"

Name "${APPNAME} ${PRODUCT_VERSION}"
OutFile "..\deployment\dist\ProRadCS_Gateway_Setup_v1.0.0.exe"
InstallDir "$PROGRAMFILES64\ProRadCS"
RequestExecutionLevel admin

; --- Global Runtime Variables ---
Var PowerShellPath
Var ArchiveDir
Var AeTitle
Var DicomPort
Var WebPort
Var CloudEndpoint
Var NodeToken

; Controls for Custom Configuration Page
Var Dialog
Var HwndArchiveDir
Var HwndAeTitle
Var HwndDicomPort
Var HwndWebPort
Var HwndCloudEndpoint
Var HwndNodeToken

; --- Modern UI 2 Settings ---
!define MUI_ABORTWARNING
!define MUI_COMPONENTSPAGE_NODESC

; Wizard Pages Sequence
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE" ; Will fallback to embedded text if file not present
!insertmacro MUI_PAGE_DIRECTORY
Page custom CustomConfigPageShow CustomConfigPageLeave
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstaller Pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

; Language Configuration
!insertmacro MUI_LANGUAGE "English"

; ------------------------------------------------------------------------------
; Initialization & Pre-Install Prerequisite Verification
; ------------------------------------------------------------------------------
Function .onInit
    ; 1. Enforce 64-bit Architecture
    ${IfNot} ${RunningX64}
        MessageBox MB_ICONSTOP "Error: ${APPNAME} requires a 64-bit Windows operating system (Windows 10/11 or Server 2019+)."
        Abort
    ${EndIf}

    ; 2. Resolve Native 64-bit PowerShell Executable
    ${If} ${RunningX64}
        StrCpy $PowerShellPath "$WINDIR\SysNative\WindowsPowerShell\v1.0\powershell.exe"
    ${Else}
        StrCpy $PowerShellPath "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    ${EndIf}

    ; Set Default Parameter Values
    StrCpy $ArchiveDir "D:\DICOM_Archive"
    StrCpy $AeTitle "PRCS_EDGE_01"
    StrCpy $DicomPort "104"
    StrCpy $WebPort "8080"
    StrCpy $CloudEndpoint "https://vna.hospital.org/stow"
    StrCpy $NodeToken ""

    ; 3. Extract checkPrereqs.ps1 to temp directory for pre-installation check
    InitPluginsDir
    File /oname=$PLUGINSDIR\checkPrereqs.ps1 "..\scripts\checkPrereqs.ps1"

    ; Run pre-install verification
    DetailPrint "Executing host prerequisite verification..."
    ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\checkPrereqs.ps1" -TargetDrive "D" -MinDiskSpaceGB 20 -DicomPort 104 -WebPort 8080' $0

    ${If} $0 == 10
        MessageBox MB_YESNO|MB_ICONEXCLAMATION "Warning: One or more host prerequisites were not met (OS version, VC++ Redistributable, or Disk Space < 20GB).$\n$\nDo you want to continue the installation anyway?" IDYES ContinuePrereq
        Abort
        ContinuePrereq:
    ${ElseIf} $0 == 20
        MessageBox MB_ICONSTOP "Port Conflict Detected: Port 104 or 8080 is currently in use by another service.$\n$\nPlease terminate conflicting applications before proceeding."
        Abort
    ${EndIf}
FunctionEnd

; ------------------------------------------------------------------------------
; Custom Configuration Dialog (nsDialogs)
; ------------------------------------------------------------------------------
Function CustomConfigPageShow
    nsDialogs::Create 1018
    Pop $Dialog
    ${If} $Dialog == error
        Abort
    ${EndIf}

    !insertmacro MUI_HEADER_TEXT "ProRadCS Gateway Configuration" "Specify clinical imaging archive and network endpoints"

    ; Archive Storage Directory
    ${NSD_CreateLabel} 0 0 100% 12u "Archive Storage Directory (D:\DICOM_Archive):"
    Pop $0
    ${NSD_CreateText} 0 14u 90% 12u "$ArchiveDir"
    Pop $HwndArchiveDir

    ; Modality Ingestion Settings
    ${NSD_CreateLabel} 0 32u 45% 12u "Local AE Title (Port 104 SCP):"
    Pop $0
    ${NSD_CreateText} 0 46u 45% 12u "$AeTitle"
    Pop $HwndAeTitle

    ${NSD_CreateLabel} 50% 32u 22% 12u "DICOM Port:"
    Pop $0
    ${NSD_CreateText} 50% 46u 22% 12u "$DicomPort"
    Pop $HwndDicomPort

    ${NSD_CreateLabel} 75% 32u 25% 12u "Web Port:"
    Pop $0
    ${NSD_CreateText} 75% 46u 25% 12u "$WebPort"
    Pop $HwndWebPort

    ; Cloud VNA Relay Settings
    ${NSD_CreateLabel} 0 64u 100% 12u "Upstream Cloud VNA STOW-RS URL:"
    Pop $0
    ${NSD_CreateText} 0 78u 100% 12u "$CloudEndpoint"
    Pop $HwndCloudEndpoint

    ${NSD_CreateLabel} 0 96u 100% 12u "Node Authentication Token / API Key (Optional):"
    Pop $0
    ${NSD_CreatePassword} 0 110u 100% 12u "$NodeToken"
    Pop $HwndNodeToken

    nsDialogs::Show
FunctionEnd

Function CustomConfigPageLeave
    ${NSD_GetText} $HwndArchiveDir $ArchiveDir
    ${NSD_GetText} $HwndAeTitle $AeTitle
    ${NSD_GetText} $HwndDicomPort $DicomPort
    ${NSD_GetText} $HwndWebPort $WebPort
    ${NSD_GetText} $HwndCloudEndpoint $CloudEndpoint
    ${NSD_GetText} $HwndNodeToken $NodeToken

    ${If} $ArchiveDir == ""
        MessageBox MB_ICONEXCLAMATION "Please specify a valid archive directory."
        Abort
    ${EndIf}
    ${If} $AeTitle == ""
        MessageBox MB_ICONEXCLAMATION "Please specify a valid DICOM Application Entity Title."
        Abort
    ${EndIf}
FunctionEnd

; ------------------------------------------------------------------------------
; Main Installation Section
; ------------------------------------------------------------------------------
Section "MainSection" SEC01
    SetOutPath "$INSTDIR"

    ; 1. Create Target Directory Tree
    CreateDirectory "$INSTDIR\bin"
    CreateDirectory "$INSTDIR\scripts"
    CreateDirectory "$INSTDIR\frontend\dist"
    CreateDirectory "$INSTDIR\logs"

    ; 2. Extract PowerShell Automation Scripts
    DetailPrint "Extracting host security automation scripts..."
    SetOutPath "$INSTDIR\scripts"
    File "..\scripts\checkPrereqs.ps1"
    File "..\scripts\createUserAccounts.ps1"
    File "..\scripts\configureStorageAcls.ps1"
    File "..\scripts\setupFirewall.ps1"
    File "..\scripts\setEnvironmentVars.ps1"
    File "..\scripts\installServices.ps1"
    File "..\scripts\backupScheduler.ps1"
    File "..\scripts\healthCheck.ps1"
    File "..\scripts\uninstallAll.ps1"

    ; 3. Extract Binaries and Frontend Assets (staged)
    SetOutPath "$INSTDIR\bin"
    File /nonfatal "..\deployment\dist\proradcs-receiver.exe"
    File /nonfatal "..\deployment\dist\proradcs-worker.exe"
    File /nonfatal "..\deployment\dist\proradcs-web.exe"

    SetOutPath "$INSTDIR\frontend\dist"
    File /nonfatal /r "..\frontend\dist\*.*"

    ; --------------------------------------------------------------------------
    ; 4. Execute OS Hardening & Provisioning Pipeline
    ; --------------------------------------------------------------------------
    DetailPrint "Step 1/6: Provisioning PacsServiceWorker service account..."
    ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\createUserAccounts.ps1" -AccountName "PacsServiceWorker"' $0
    ${If} $0 != 0
        DetailPrint "createUserAccounts.ps1 returned code: $0"
    ${EndIf}

    DetailPrint "Step 2/6: Configuring NTFS DACLs on $ArchiveDir..."
    ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\configureStorageAcls.ps1" -ArchiveRoot "$ArchiveDir" -InstallRoot "$INSTDIR" -ServiceAccount "PacsServiceWorker"' $0
    ${If} $0 != 0
        DetailPrint "configureStorageAcls.ps1 returned code: $0"
    ${EndIf}

    DetailPrint "Step 3/6: Configuring Windows Defender Firewall rules..."
    ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\setupFirewall.ps1" -DicomPort $DicomPort -WebPort $WebPort' $0
    ${If} $0 != 0
        DetailPrint "setupFirewall.ps1 returned code: $0"
    ${EndIf}

    DetailPrint "Step 4/6: Configuring system environment variables..."
    ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\setEnvironmentVars.ps1" -AeTitle "$AeTitle" -DicomPort $DicomPort -WebPort $WebPort -ArchiveDir "$ArchiveDir" -CloudEndpoint "$CloudEndpoint" -NodeToken "$NodeToken"' $0
    ${If} $0 != 0
        DetailPrint "setEnvironmentVars.ps1 returned code: $0"
    ${EndIf}

    DetailPrint "Step 5/6: Registering Windows background services..."
    ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\installServices.ps1" -BinDir "$INSTDIR\bin" -ServiceAccount "PacsServiceWorker" -StartImmediately' $0
    ${If} $0 != 0
        DetailPrint "installServices.ps1 returned code: $0"
    ${EndIf}

    DetailPrint "Step 6/6: Registering daily midnight WAL checkpoint and maintenance task..."
    ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\backupScheduler.ps1" -DailyTime "00:00"' $0
    ${If} $0 != 0
        DetailPrint "backupScheduler.ps1 returned code: $0"
    ${EndIf}

    ; --------------------------------------------------------------------------
    ; 5. Shortcuts & Start Menu
    ; --------------------------------------------------------------------------
    SetOutPath "$INSTDIR"
    CreateDirectory "$SMPROGRAMS\ProRadCS"
    CreateShortcut "$SMPROGRAMS\ProRadCS\Web Dashboard.lnk" "http://localhost:$WebPort"
    CreateShortcut "$SMPROGRAMS\ProRadCS\Diagnostic Health Check.lnk" "$PowerShellPath" '-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\healthCheck.ps1"'
    CreateShortcut "$SMPROGRAMS\ProRadCS\Uninstall ProRadCS.lnk" "$INSTDIR\uninstall.exe"

    ; --------------------------------------------------------------------------
    ; 6. Windows Add/Remove Programs Registry Entries
    ; --------------------------------------------------------------------------
    DetailPrint "Writing Windows uninstaller registry records..."
    WriteRegStr HKLM "${REG_UNINSTALL}" "DisplayName" "${APPNAME} (${PRODUCT_VERSION})"
    WriteRegStr HKLM "${REG_UNINSTALL}" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKLM "${REG_UNINSTALL}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
    WriteRegStr HKLM "${REG_UNINSTALL}" "InstallLocation" '"$INSTDIR"'
    WriteRegStr HKLM "${REG_UNINSTALL}" "Publisher" "${COMPANYNAME}"
    WriteRegStr HKLM "${REG_UNINSTALL}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegDWORD HKLM "${REG_UNINSTALL}" "VersionMajor" ${VERSIONMAJOR}
    WriteRegDWORD HKLM "${REG_UNINSTALL}" "VersionMinor" ${VERSIONMINOR}
    WriteRegDWORD HKLM "${REG_UNINSTALL}" "NoModify" 1
    WriteRegDWORD HKLM "${REG_UNINSTALL}" "NoRepair" 1

    ; Write Uninstaller executable
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Run operational post-install health verification
    DetailPrint "Executing operational health check verification..."
    ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\healthCheck.ps1"' $0
SectionEnd

; ------------------------------------------------------------------------------
; Uninstaller Implementation
; ------------------------------------------------------------------------------
Function un.onInit
    ${If} ${RunningX64}
        StrCpy $PowerShellPath "$WINDIR\SysNative\WindowsPowerShell\v1.0\powershell.exe"
    ${Else}
        StrCpy $PowerShellPath "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    ${EndIf}
FunctionEnd

Section "Uninstall"
    DetailPrint "Executing appliance de-provisioning suite (scripts\uninstallAll.ps1)..."
    DetailPrint "Preserving clinical DICOM images in archive by default..."

    ; 1. Run graceful teardown script
    ${If} ${FileExists} "$INSTDIR\scripts\uninstallAll.ps1"
        ExecWait '"$PowerShellPath" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\scripts\uninstallAll.ps1"' $0
    ${EndIf}

    ; 2. Remove Start Menu Shortcuts
    Delete "$SMPROGRAMS\ProRadCS\Web Dashboard.lnk"
    Delete "$SMPROGRAMS\ProRadCS\Diagnostic Health Check.lnk"
    Delete "$SMPROGRAMS\ProRadCS\Uninstall ProRadCS.lnk"
    RMDir "$SMPROGRAMS\ProRadCS"

    ; 3. Remove Installation Files
    RMDir /r "$INSTDIR\bin"
    RMDir /r "$INSTDIR\scripts"
    RMDir /r "$INSTDIR\frontend"
    Delete "$INSTDIR\uninstall.exe"
    RMDir "$INSTDIR"

    ; 4. Clean Registry
    DeleteRegKey HKLM "${REG_UNINSTALL}"

    DetailPrint "ProRadCS Enterprise Gateway successfully uninstalled."
SectionEnd
